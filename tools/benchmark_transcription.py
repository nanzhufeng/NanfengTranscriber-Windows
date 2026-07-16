from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import transcriber


SAMPLES = [
    Path(
        r"D:\南烛枫视频下载器\Douyin\美静讲故事1\2021-12-24 加油小公主的看过了 ，这几个字最适合女孩取#名字#取名 #家有萌娃 #易学 #豆荚小助手 #上热门.mp4"
    ),
    Path(
        r"D:\南烛枫视频下载器\Douyin\美静讲故事1\2022-01-11 大舍大得小舍小得#修行 #出马 #中华文化 #禅修 #宝宝起名 #好运.mp4"
    ),
    Path(
        r"D:\南烛枫视频下载器\Douyin\美静讲故事1\2022-01-13 离婚到底是因为婚姻有裂痕还是小三真新鲜#出马 #出马 #八字 #出轨 #2022 #内容太过真实.mp4"
    ),
]


def package_version(package_name: str) -> str | None:
    try:
        return version(package_name)
    except PackageNotFoundError:
        return None


def query_current_process_gpu_memory_mb() -> int:
    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-compute-apps=pid,used_memory",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        return 0

    if completed.returncode != 0:
        return 0

    current_pid = str(os.getpid())
    memory_values: list[int] = []
    for line in completed.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 2 or parts[0] != current_pid:
            continue
        try:
            memory_values.append(int(parts[1]))
        except ValueError:
            continue
    if memory_values:
        return max(memory_values)

    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        return 0
    if completed.returncode != 0:
        return 0
    used_values: list[int] = []
    for line in completed.stdout.splitlines():
        try:
            used_values.append(int(line.strip()))
        except ValueError:
            continue
    return sum(used_values)


class GpuMemoryMonitor:
    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._poll, daemon=True)
        self.peak_mb = 0
        self.baseline_mb = 0

    def __enter__(self) -> "GpuMemoryMonitor":
        self.baseline_mb = query_current_process_gpu_memory_mb()
        self.peak_mb = self.baseline_mb
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop_event.set()
        self._thread.join(timeout=2)

    def _poll(self) -> None:
        while not self._stop_event.is_set():
            self.peak_mb = max(self.peak_mb, query_current_process_gpu_memory_mb())
            self._stop_event.wait(0.25)


def make_options(output_dir: Path) -> transcriber.TranscribeOptions:
    return transcriber.TranscribeOptions(
        output_dir=output_dir,
        model_size="medium",
        language="中文",
        compute_mode="GPU 优先",
        export_txt=True,
        export_md=False,
        export_srt=False,
        export_docx=False,
        postprocess_enabled=False,
        ffmpeg_dir=transcriber.find_ffmpeg_dir(PROJECT_ROOT),
    )


def build_record(source: Path, elapsed: float, result: transcriber.TranscribeResult) -> dict[str, Any]:
    normalized_text = result.text.strip()
    return {
        "source": str(source),
        "elapsed_seconds": round(elapsed, 3),
        "text_characters": len(normalized_text),
        "text_sha256": hashlib.sha256(normalized_text.encode("utf-8")).hexdigest(),
        "text_preview": normalized_text[:500],
        "files": [str(path) for path in result.files],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="南烛枫视频转文字性能基准")
    parser.add_argument("--label", required=True, help="本次测量标识，例如 baseline 或 optimized")
    parser.add_argument("--result", required=True, type=Path, help="JSON 结果文件")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    missing_sources = [str(path) for path in SAMPLES if not path.is_file()]
    if missing_sources:
        raise FileNotFoundError("缺少基准媒体：\n" + "\n".join(missing_sources))

    start_time = time.monotonic()
    records: list[dict[str, Any]] = []
    progress_events: list[dict[str, Any]] = []
    error: str | None = None
    session = None

    def on_progress(info: dict[str, Any]) -> None:
        progress_events.append(dict(info))

    try:
        session_class = getattr(transcriber, "TranscriptionSession", None)
        supports_session = "session" in inspect.signature(transcriber.transcribe_file).parameters
        if session_class is not None and supports_session:
            session = session_class()

        with tempfile.TemporaryDirectory(prefix="nanzhufeng_transcriber_benchmark_") as temp_dir:
            options = make_options(Path(temp_dir))
            with GpuMemoryMonitor() as memory_monitor:
                for source in SAMPLES:
                    file_start = time.monotonic()
                    kwargs: dict[str, Any] = {}
                    if session is not None:
                        kwargs["session"] = session
                    result = transcriber.transcribe_file(source, options, on_progress, **kwargs)
                    records.append(build_record(source, time.monotonic() - file_start, result))
            peak_gpu_memory_mb = memory_monitor.peak_mb
            baseline_gpu_memory_mb = memory_monitor.baseline_mb
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        peak_gpu_memory_mb = 0
        baseline_gpu_memory_mb = 0
    finally:
        if session is not None:
            session.close()

    payload = {
        "label": args.label,
        "created_at_epoch": time.time(),
        "total_seconds": round(time.monotonic() - start_time, 3),
        "peak_gpu_memory_mb": peak_gpu_memory_mb,
        "baseline_gpu_memory_mb": baseline_gpu_memory_mb,
        "gpu_memory_delta_mb": max(0, peak_gpu_memory_mb - baseline_gpu_memory_mb),
        "samples": records,
        "last_progress": progress_events[-1] if progress_events else None,
        "error": error,
        "environment": {
            "python": sys.version,
            "faster_whisper": package_version("faster-whisper"),
            "ctranslate2": package_version("ctranslate2"),
            "options": asdict(make_options(Path("benchmark-output"))),
        },
    }
    args.result.parent.mkdir(parents=True, exist_ok=True)
    args.result.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    if error:
        print(error, file=sys.stderr)
        return 1
    print(f"{args.label}: {payload['total_seconds']:.3f}s, GPU peak {peak_gpu_memory_mb} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
