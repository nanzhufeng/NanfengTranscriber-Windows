from __future__ import annotations

from dataclasses import replace
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


class FailedFfmpegProcess:
    def __init__(self, stderr: bytes) -> None:
        self.stderr = stderr

    def poll(self) -> int:
        return 1

    def communicate(self) -> tuple[bytes, bytes]:
        return b"", self.stderr


class TranscribeFileOutputTests(unittest.TestCase):
    def test_srt_long_segment_is_short_and_sequential(self):
        segments = [{"start": 2, "end": 22, "text": "这是一段很长的字幕。" * 12}]
        cues = transcriber._subtitle_cues(segments)
        self.assertGreater(len(cues), 1)
        self.assertEqual("".join(c["text"] for c in cues), segments[0]["text"])
        self.assertTrue(all(len(c["text"]) <= 24 and c["end"] - c["start"] <= 5.01 for c in cues))
        self.assertEqual(cues[0]["start"], 2)
        self.assertEqual(cues[-1]["end"], 22)
        self.assertTrue(all(a["end"] <= b["start"] for a, b in zip(cues, cues[1:])))

    def test_srt_word_timing_preserves_pause_and_sentence_boundary(self):
        cues = transcriber._subtitle_cues([{"start": 0, "end": 10, "text": "你好。再见。", "words": [
            {"start": 1, "end": 2, "text": "你好。"},
            {"start": 7, "end": 8, "text": "再见。"}]}])
        self.assertEqual([(c["start"], c["end"], c["text"]) for c in cues], [(1, 2, "你好。"), (7, 8, "再见。")])

    def test_srt_overlapping_segments_do_not_stack(self):
        cues = transcriber._subtitle_cues([{"start": 0, "end": 3, "text": "第一句"},
                                            {"start": 2, "end": 4, "text": "第二句"}])
        self.assertEqual(cues[0]["end"], cues[1]["start"])

    @patch("app.transcriber._add_nvidia_dll_directories")
    @patch("app.transcriber._extract_audio")
    @patch("app.transcriber.probe_duration_seconds", return_value=3.4)
    def test_output_location_combinations(self, *_mocks):
        for beside in (False, True):
            for nested in (False, True):
                with self.subTest(beside=beside, nested=nested), tempfile.TemporaryDirectory() as temp:
                    root = Path(temp)
                    source = root / "videos" / "example.mp4"
                    source.parent.mkdir()
                    source.touch()
                    custom = root / "custom"
                    options = replace(self.make_options(custom), save_beside_video=beside,
                                      create_video_subfolder=nested)
                    result = transcriber.transcribe_file(source, options, lambda _: None, session=FakeSession())
                    expected = source.parent if beside else custom
                    if nested:
                        expected = expected / source.stem
                    self.assertTrue(all(p.parent == expected and p.is_file() for p in result.files))
                    if beside:
                        self.assertFalse(custom.exists())

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
        for nested in (False, True):
            with self.subTest(nested=nested), tempfile.TemporaryDirectory() as temp_dir:
                output_dir = Path(temp_dir)
                options = replace(self.make_options(output_dir), create_video_subfolder=nested)
                result = transcriber.transcribe_file(source, options, lambda _info: None, session=FakeSession())
                expected_dir = output_dir / source.stem if nested else output_dir
                self.assertEqual({path.suffix for path in result.files}, {".txt", ".md", ".srt", ".docx"})
                self.assertTrue(all(path.parent == expected_dir and path.is_file() for path in result.files))
                self.assertIn("00:00:00,000", (expected_dir / f"{source.stem}.srt").read_text(encoding="utf-8"))
                if not nested:
                    self.assertFalse(any(path.is_dir() for path in output_dir.iterdir()))

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

    def test_audio_extraction_reports_missing_audio_track(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            options = self.make_options(Path(temp_dir))
            failed_process = FailedFfmpegProcess(b"Output file #0 does not contain any stream\n")
            with patch("app.transcriber.subprocess.Popen", return_value=failed_process) as popen:
                with self.assertRaisesRegex(RuntimeError, "未检测到可转写的音轨"):
                    transcriber._extract_audio(Path("silent.mp4"), Path(temp_dir) / "audio.wav", options, None)

            command = popen.call_args.args[0]
            self.assertIn("-v", command)
            self.assertIn("error", command)
