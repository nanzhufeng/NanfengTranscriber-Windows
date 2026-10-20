"""Background dependency installation, owned by one application worker."""
from __future__ import annotations

import importlib
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

from PySide6.QtCore import QObject, Signal, Slot


INSTALL_TIMEOUT_SECONDS = 1800


def _windows_job(process):
    """Keep pip and any build children in a private, kill-on-close Windows job."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes
    class BasicLimits(ctypes.Structure):
        _fields_ = [("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
                    ("flags", wintypes.DWORD), ("min_working_set", ctypes.c_size_t),
                    ("max_working_set", ctypes.c_size_t), ("active_processes", wintypes.DWORD),
                    ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                    ("scheduling", wintypes.DWORD)]
    class ExtendedLimits(ctypes.Structure):
        _fields_ = [("basic", BasicLimits), ("io_counters", ctypes.c_ulonglong * 6),
                    ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                    ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateJobObjectW(None, None)
    if not handle:
        return None
    limits = ExtendedLimits()
    limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if (not kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits))
            or not kernel.AssignProcessToJobObject(handle, int(process._handle))):
        kernel.CloseHandle(handle)
        return None
    return lambda: kernel.CloseHandle(handle)


def _failure_message(return_code, tail):
    detail = bytes(tail).decode("utf-8", errors="replace").lower()
    if any(text in detail for text in ("no space left", "not enough space", "disk full")):
        reason = "磁盘空间不足，请释放空间后重试。"
    elif any(text in detail for text in ("permission denied", "access is denied")):
        reason = "无法写入运行环境，请检查目录权限及文件占用。"
    elif any(text in detail for text in ("no matching distribution", "could not find a version")):
        reason = "当前 Python 环境找不到兼容依赖，请核对运行环境版本。"
    else:
        reason = "请检查网络、依赖源和运行环境后重试。"
    return f"依赖安装失败（退出码 {return_code}）。{reason}"


class DependencyInstallWorker(QObject):
    finished = Signal(bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    @Slot()
    def run(self) -> None:
        if self._cancelled.is_set():
            self.finished.emit(False, "依赖安装已停止。")
            return
        requirements = Path(__file__).resolve().parents[1] / "requirements.txt"
        command = [sys.executable, "-m", "pip", "install", "--no-input", "--disable-pip-version-check",
                   "-r", str(requirements)]
        process = None
        reader = None
        close_job = None
        tail = bytearray()
        ok, message = False, "依赖安装启动失败，请检查 Python 运行环境和目录权限。"
        try:
            process = subprocess.Popen(
                command, cwd=str(requirements.parent), stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                start_new_session=os.name != "nt")
            close_job = _windows_job(process)
            def drain():
                try:
                    while data := process.stdout.read(8192):
                        tail.extend(data)
                        del tail[:-65536]
                except (OSError, ValueError):
                    pass
            reader = threading.Thread(target=drain, name="dependency-install-output", daemon=True)
            reader.start()
            deadline = time.monotonic() + INSTALL_TIMEOUT_SECONDS
            while process.poll() is None:
                if self._cancelled.is_set():
                    message = "依赖安装已停止。"
                    break
                if time.monotonic() >= deadline:
                    message = "依赖安装等待超时，已停止安装进程。请检查网络后重试。"
                    break
                self._cancelled.wait(.05)
            else:
                reader.join(timeout=.5)
                if self._cancelled.is_set():
                    message = "依赖安装已停止。"
                elif process.returncode == 0:
                    ok, message = True, "依赖安装完成。"
                else:
                    message = _failure_message(process.returncode, tail)
        except Exception:
            # pip may echo credentials from private index URLs; never propagate
            # raw output or exception messages into UI/runtime logs.
            ok = False
        finally:
            try:
                if close_job is not None:
                    close_job()
                if process is not None:
                    if process.poll() is None:
                        if os.name == "nt" and close_job is None:
                            try:
                                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                               timeout=3, creationflags=subprocess.CREATE_NO_WINDOW)
                            except (OSError, subprocess.TimeoutExpired):
                                pass
                        elif os.name != "nt":
                            import signal
                            try:
                                os.killpg(process.pid, signal.SIGTERM)
                            except ProcessLookupError:
                                pass
                        try:
                            process.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=2)
                    if reader is not None:
                        reader.join(timeout=1)
                    if reader is None or not reader.is_alive():
                        process.stdout.close()
            except (OSError, subprocess.TimeoutExpired):
                ok, message = False, "依赖安装进程未能正常退出，请关闭软件后重试。"
        if ok:
            importlib.invalidate_caches()
        self.finished.emit(ok, message)
