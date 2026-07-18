from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_DIR = PROJECT_ROOT / "tests" / "ui_baselines" / "windows"
SCALES = (1.0, 1.25, 1.5, 2.0)
LOGICAL_SIZE = (1820, 1130)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _capture(scale: float, output: Path, info_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ["QT_SCALE_FACTOR"] = str(scale)
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"

    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication

    from app import main

    app = QApplication.instance() or QApplication([])
    for font_path in (
        Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "msyh.ttc",
        Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "msyhbd.ttc",
    ):
        if font_path.exists():
            QFontDatabase.addApplicationFont(str(font_path))
    window = main.MainWindow()
    window.resize(*LOGICAL_SIZE)
    window.output_edit.setText(r"D:\南枫转写\输出示例")

    rows = [
        ("等待", "0%", "-", "-"),
        ("提取音频", "2%", "1秒", "正在提取音频"),
        ("下载模型", "3%", "3秒", "首次下载 medium 模型"),
        ("加载模型", "3%", "8秒", "正在加载 GPU 模型"),
        ("转写中", "48%", "1分12秒", "1分18秒"),
        ("润色中", "98%", "2分06秒", "正在翻译润色 1/2"),
        ("完成", "100%", "2分18秒", "0秒"),
        ("已存在", "100%", "-", "0秒"),
        ("无文字", "100%", "18秒", "0秒"),
        ("失败", "0%", "-", "请检查文件或运行环境"),
        ("已停止", "36%", "42秒", "-"),
    ]

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        with patch("app.main.probe_duration_seconds", return_value=604.0):
            for index, (status, progress, elapsed, eta) in enumerate(rows, start=1):
                source = temp_root / f"{index:02d}_多DPI界面基线示例_完整文件名_{status}.mp4"
                source.touch()
                window._add_row(source)
                row = window.table.rowCount() - 1
                window._set_status_cell(row, status)
                window._set_cell(row, main.COL_PROGRESS, progress)
                window._set_cell(row, main.COL_ELAPSED, elapsed)
                window._set_cell(row, main.COL_ETA, eta)
                window._set_cell(row, main.COL_OUTPUT, rf"D:\南枫转写\{status}\完整输出路径示例")

        window.status_label.setText("FFmpeg 已就绪｜队列: 11 项｜多 DPI 截图基线")
        window.total_eta_label.setText("总剩余：3分24秒")
        window.main_progress.setValue(54)
        window.show()
        app.processEvents()
        pixmap = window.grab()
        if pixmap.isNull() or not pixmap.save(str(output), "PNG"):
            raise RuntimeError(f"无法保存 UI 基线截图：{output}")
        info = {
            "scale": scale,
            "logical_width": LOGICAL_SIZE[0],
            "logical_height": LOGICAL_SIZE[1],
            "pixel_width": pixmap.width(),
            "pixel_height": pixmap.height(),
            "device_pixel_ratio": pixmap.devicePixelRatio(),
        }
        info_path.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
        window.close()


def _generate_all() -> None:
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, object]] = []
    for scale in SCALES:
        scale_label = str(scale).replace(".", "_")
        output = BASELINE_DIR / f"main-window-scale-{scale_label}.png"
        info_path = BASELINE_DIR / f"main-window-scale-{scale_label}.json"
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PROJECT_ROOT)
        subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--scale", str(scale), "--output", str(output), "--info", str(info_path)],
            cwd=PROJECT_ROOT,
            env=env,
            check=True,
        )
        info = json.loads(info_path.read_text(encoding="utf-8"))
        info_path.unlink()
        info["file"] = output.name
        info["sha256"] = _sha256(output)
        info["bytes"] = output.stat().st_size
        entries.append(info)

    manifest = {
        "schema_version": 1,
        "platform": "Windows",
        "window": "南枫转写 - 转写工作台",
        "capture_mode": "PySide6 offscreen fixed-state baseline",
        "entries": entries,
    }
    (BASELINE_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="生成南枫转写多 DPI UI 截图基线")
    parser.add_argument("--scale", type=float)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--info", type=Path)
    args = parser.parse_args()
    if args.scale is not None:
        if not args.output or not args.info:
            parser.error("--scale 模式必须同时提供 --output 和 --info")
        _capture(args.scale, args.output, args.info)
        return 0
    _generate_all()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
