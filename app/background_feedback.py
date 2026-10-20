"""Bounded, best-effort local diagnostics and completion audio off the GUI."""
from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import queue
import re
import threading


_logs = queue.Queue(maxsize=256)
_log_thread = None
_start_lock = threading.Lock()
_sound_lock = threading.Lock()


def _safe_message(message):
    if ", error=" in message:
        prefix, detail = message.split(", error=", 1)
        kind = re.match(r"([A-Za-z_]\w*(?:Error|Exception|Stopped))(?::|$)", detail)
        message = prefix + ", error=" + (kind.group(1) if kind else "任务失败") + "（详情见任务错误提示）"
    for name in ("DASHSCOPE_API_KEY", "NANZHU_TEXT_API_KEY", "OPENAI_API_KEY",
                 "HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        value = os.environ.get(name)
        if value:
            message = message.replace(value, "[已隐藏]")
    message = re.sub(r"(?i)(bearer\s+)[^\s\"'<>]+", r"\1[已隐藏]", message)
    message = re.sub(r"\bsk-[A-Za-z0-9_-]+", "[已隐藏]", message)
    message = re.sub(r"(?i)(https?://)[^/\s@]+:[^/\s@]+@", r"\1[已隐藏]@", message)
    message = re.sub(r"(?i)((?:api[_-]?key|token|password|secret)[\"']?\s*[:=]\s*[\"']?)[^\s,;\"']+",
                     r"\1[已隐藏]", message)
    return message.replace("\r", "\\r").replace("\n", "\\n")[:2048]


def _write_logs():
    while True:
        path, stamp, message = _logs.get()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as stream:
                stream.write(f"[{stamp}] {_safe_message(message)}\n")
        except Exception:
            pass
        finally:
            _logs.task_done()


def enqueue_log(path: Path, message: str) -> bool:
    """Never wait for a slow/full disk; drop new diagnostics if the queue is full."""
    global _log_thread
    try:
        _logs.put_nowait((path, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), str(message)[:4096]))
    except queue.Full:
        return False
    if _log_thread is None:
        with _start_lock:
            if _log_thread is None:
                _log_thread = threading.Thread(target=_write_logs, name="local-diagnostics", daemon=True)
                _log_thread.start()
    return True


def play_sound(operation) -> bool:
    """One completion sound at a time; a slow audio driver cannot block the GUI."""
    if not _sound_lock.acquire(blocking=False):
        return False
    def run():
        try:
            operation()
        except Exception:
            pass
        finally:
            _sound_lock.release()
    threading.Thread(target=run, name="completion-audio", daemon=True).start()
    return True
