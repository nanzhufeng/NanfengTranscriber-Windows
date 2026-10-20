"""Persistent isolated local inference process; no audio leaves this machine."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading

from .model_modes import QWEN_MODEL, ALIGNER_MODEL


def runtime_python() -> Path:
    override = os.environ.get("NANFENG_QWEN_PYTHON")
    if override:
        return Path(override)
    root = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
    runtime = (Path(os.environ["LOCALAPPDATA"]) / "NanfengTranscriber" / "runtimes" / "qwen") if getattr(sys, "frozen", False) else root / ".runtime" / "qwen"
    portable = runtime / "python.exe"
    if portable.is_file():
        return portable
    return runtime / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def runtime_ready() -> bool:
    python = runtime_python()
    if not python.is_file():
        return False
    if getattr(sys, "frozen", False) and not os.environ.get("NANFENG_QWEN_PYTHON"):
        return (python.parent / "runtime.ready").is_file()
    return True


class QwenWorker:
    def __init__(self):
        self.process = None
        self.messages = queue.Queue()
        self.reader = None
        self.writer = None

    def _start(self):
        self.messages = queue.Queue()
        python = runtime_python()
        if not runtime_ready():
            raise RuntimeError("中文精确运行环境尚未安装。请运行“安装中文精确运行环境_Windows.bat”，完成后重新启动软件。")
        worker = Path(__file__).with_name("qwen_worker.py")
        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "utf-8"
        # Cloud credentials are unnecessary for this local worker.
        for key in ("OPENAI_API_KEY", "NANZHU_TEXT_API_KEY", "HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
            environment.pop(key, None)
        self.process = subprocess.Popen(
            [str(python), "-u", str(worker)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", env=environment,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        process = self.process
        messages = self.messages
        def read():
            try:
                for line in process.stdout:
                    try:
                        message = json.loads(line)
                        if isinstance(message, dict):
                            messages.put(message)
                    except json.JSONDecodeError:
                        continue
            finally:
                messages.put({"error": "中文精确运行进程已退出，请检查独立运行环境。"})
        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()

    def transcribe(self, audio_path, options, progress, cancelled=None):
        return self._request(audio_path, options, progress, cancelled)

    def align(self, audio_path, segments, options, progress, cancelled=None):
        return self._request(audio_path, options, progress, cancelled, segments)

    def _request(self, audio_path, options, progress, cancelled=None, segments=None):
        from .transcriber import default_model_cache_dir, TranscribeStopped
        if self.process is None:
            self._start()
        request = {"audio": str(audio_path), "language": options.language,
                   "device": "cpu" if options.compute_mode == "CPU 稳定" else "cuda",
                   "align": options.export_srt, "model": QWEN_MODEL, "aligner": ALIGNER_MODEL,
                   "cache": str(default_model_cache_dir())}
        if segments is not None:
            request["segments"] = segments
        process, messages = self.process, self.messages
        # Full-file alignment text may exceed pipe capacity. Keep cancellation
        # reachable even when a loading/stuck child has stopped reading stdin.
        def write():
            try:
                process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
                process.stdin.flush()
            except (OSError, ValueError):
                messages.put({"error": "中文精确运行进程通信失败，请重试。"})
        self.writer = threading.Thread(target=write, name="qwen-request", daemon=True)
        self.writer.start()
        while True:
            if cancelled and cancelled():
                self.close()
                raise TranscribeStopped("转写已停止。")
            try:
                message = self.messages.get(timeout=0.2)
            except queue.Empty:
                continue
            if "error" in message:
                self.close()
                raise RuntimeError(message["error"])
            if "result" in message:
                return message["result"]
            progress(message)

    def close(self):
        if self.process is not None:
            process = self.process
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            for thread in (self.writer, self.reader):
                if thread is not None:
                    thread.join(timeout=1)
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass
            self.process = None
            self.reader = self.writer = None
