from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import transcriber


SEGMENTS = [
    {"start": 0.0, "end": 1.2, "text": "大家好。"},
    {"start": 1.2, "end": 3.4, "text": "这是转写测试。"},
]


class FakeSession:
    def __init__(self, segments: list[dict] | None = None) -> None:
        self.segments = list(SEGMENTS if segments is None else segments)
        self.calls = 0
        self.close_calls = 0

    def transcribe_audio(self, *_args, **_kwargs) -> list[dict]:
        self.calls += 1
        return list(self.segments)

    def close(self) -> None:
        self.close_calls += 1


class TranscribeFileOutputTests(unittest.TestCase):
    def make_options(self, output_dir: Path) -> transcriber.TranscribeOptions:
        return transcriber.TranscribeOptions(
            output_dir=output_dir,
            model_size="medium",
            language="中文",
            compute_mode="GPU 优先",
            export_txt=True,
            export_md=True,
            export_srt=True,
            export_docx=True,
            postprocess_enabled=False,
            ffmpeg_dir=None,
        )

    @patch("app.transcriber._add_nvidia_dll_directories")
    @patch("app.transcriber._extract_audio")
    @patch("app.transcriber.probe_duration_seconds", return_value=3.4)
    def test_export_files_keep_existing_directory_structure(
        self,
        _probe_duration,
        _extract_audio,
        _add_nvidia_dlls,
    ) -> None:
        source = Path("示例视频.mp4")
        session = FakeSession()
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            result = transcriber.transcribe_file(
                source,
                self.make_options(output_dir),
                lambda _info: None,
                session=session,
            )

            expected_dir = output_dir / transcriber.safe_output_stem(source.stem)
            self.assertEqual({path.suffix for path in result.files}, {".txt", ".md", ".srt", ".docx"})
            self.assertTrue(all(path.parent == expected_dir and path.is_file() for path in result.files))
            self.assertIn("00:00:00,000", (expected_dir / f"{source.stem}.srt").read_text(encoding="utf-8"))
            self.assertEqual(session.calls, 1)
            self.assertEqual(session.close_calls, 0)

    @patch("app.transcriber._add_nvidia_dll_directories")
    @patch("app.transcriber._extract_audio")
    @patch("app.transcriber.probe_duration_seconds", return_value=3.4)
    def test_temporary_session_is_closed_when_caller_does_not_provide_one(
        self,
        _probe_duration,
        _extract_audio,
        _add_nvidia_dlls,
    ) -> None:
        session = FakeSession()
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("app.transcriber.TranscriptionSession", return_value=session):
                transcriber.transcribe_file(
                    Path("示例视频.mp4"),
                    self.make_options(Path(temp_dir)),
                    lambda _info: None,
                )

        self.assertEqual(session.close_calls, 1)

    @patch("app.transcriber._add_nvidia_dll_directories")
    @patch("app.transcriber._extract_audio")
    @patch("app.transcriber.probe_duration_seconds", return_value=3.4)
    def test_empty_segments_keep_existing_error_message(
        self,
        _probe_duration,
        _extract_audio,
        _add_nvidia_dlls,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(RuntimeError, "没有识别到可导出的文字"):
                transcriber.transcribe_file(
                    Path("示例视频.mp4"),
                    self.make_options(Path(temp_dir)),
                    lambda _info: None,
                    session=FakeSession([]),
                )
