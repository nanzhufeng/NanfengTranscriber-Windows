"""Opt-in, isolated frozen-app verification with a caller-owned sample file."""
import json
import time
from pathlib import Path

from PySide6.QtCore import QTimer

from .transcriber import TranscribeResult


def capture_history(window, target, source, finish):
    source = Path(source).resolve()
    if not source.is_file():
        raise ValueError("QA sample does not exist")
    text = "这是一段受控演示文稿，用于检查历史记录、编辑排版和视频播放。\n历史文稿独立保存，支持搜索、编辑与重新导出。\n单击右侧字幕可以跳转到对应的播放位置。"
    result = TranscribeResult(files=[], text=text, original_text=text, source_path=source,
        mode="中文精确", model="Qwen3-ASR-1.7B", language="中文", duration=12,
        segments=[{"start": 1, "end": 3, "text": "这是一段受控演示视频"},
                  {"start": 5, "end": 7, "text": "单击字幕即可跳转核对"}], history_id="release-preview")
    window.history_store.save(result)
    window._show_history()
    page = window.history_page

    def wait_for(predicate, action, seconds=15):
        deadline = time.monotonic() + seconds
        def check():
            if predicate():
                action()
            elif time.monotonic() < deadline:
                QTimer.singleShot(25, check)
            else:
                (target / "qa-error.txt").write_text("隔离页面或媒体未在时限内就绪", encoding="utf-8")
                page.show_list()
                finish()
        QTimer.singleShot(0, check)

    def document():
        window.grab().save(str(target / "history.png"))
        page.open_record(result.history_id)
        wait_for(lambda: not page.pending_actions and page.stack.currentIndex() == 1, media)

    def media():
        window.grab().save(str(target / "document.png"))
        page.open_media(result.history_id)
        def ready():
            page.audio.setVolume(0)
            QTimer.singleShot(1600, verify)
        wait_for(lambda: getattr(page, "player", None) is not None and page.player.duration() > 0, ready)

    def verify():
        frame = page.video.videoSink().videoFrame().isValid()
        receipt = {"videoFrameValid": frame, "position": page.player.position(),
                   "duration": page.player.duration(), "error": page.player.errorString(),
                   "subtitle": page.subtitle.text(), "historyCount": window.history_store.query()[1]}
        window.grab().save(str(target / "media.png"))
        (target / "history-media.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
        page.show_list()
        finish()

    wait_for(lambda: page._read_job is None and bool(page.records) and not page.pending_actions, document)
