from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from app import main, transcriber


class FakeSession:
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class TranscribeWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.options = transcriber.TranscribeOptions(
            output_dir=Path("test-output"),
            model_size="medium",
            language="中文",
            compute_mode="GPU 优先",
            export_txt=True,
            export_md=False,
            export_srt=False,
            export_docx=False,
            postprocess_enabled=False,
            ffmpeg_dir=None,
        )
        self.items = [
            main.QueueItem(Path("first.mp4"), 0, "medium", "中文"),
            main.QueueItem(Path("second.mp4"), 1, "medium", "中文"),
        ]

    @patch("app.main.TranscriptionSession")
    @patch("app.main.transcribe_file")
    def test_worker_reuses_one_session_and_stops_before_next_item(
        self,
        transcribe_file_mock,
        session_factory,
    ) -> None:
        session = FakeSession()
        session_factory.return_value = session
        worker = main.TranscribeWorker(self.items, self.options)
        completed: list[bool] = []
        started_rows: list[int] = []
        worker.all_done.connect(lambda: completed.append(True))
        worker.item_started.connect(started_rows.append)

        def transcribe_first_item(source, _options, _progress, _cancel, *, session):
            self.assertEqual(source.name, "first.mp4")
            self.assertIs(session, session_factory.return_value)
            worker.cancel()
            return transcriber.TranscribeResult(files=[], text="已完成")

        transcribe_file_mock.side_effect = transcribe_first_item

        worker.run()

        self.assertEqual(transcribe_file_mock.call_count, 1)
        self.assertEqual(started_rows, [0])
        self.assertEqual(session.close_calls, 1)
        self.assertEqual(completed, [True])
