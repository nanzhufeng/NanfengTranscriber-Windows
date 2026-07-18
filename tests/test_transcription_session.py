from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app import transcriber


class FakeModel:
    created: list[tuple[str, str, str, str, bool]] = []

    def __init__(
        self,
        model_size: str,
        *,
        device: str,
        compute_type: str,
        download_root: str,
        local_files_only: bool,
    ) -> None:
        self.created.append((model_size, device, compute_type, download_root, local_files_only))


class FakePipeline:
    batch_calls: list[int] = []
    call_kwargs: list[dict] = []
    failures: dict[int, Exception] = {}

    def __init__(self, model: FakeModel) -> None:
        self.model = model

    def transcribe(self, _audio_path: str, *, batch_size: int, **kwargs):
        self.batch_calls.append(batch_size)
        self.call_kwargs.append(dict(kwargs))
        failure = self.failures.get(batch_size)
        if failure is not None:
            raise failure
        return iter([FakeSegment(0.0, 5.0, "测试文本")]), object()


class FakeSegment:
    def __init__(self, start: float, end: float, text: str) -> None:
        self.start = start
        self.end = end
        self.text = text


class TranscriptionSessionCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cache_dir = TemporaryDirectory()
        self.cache_env = patch.dict(
            "app.transcriber.os.environ",
            {"NANFENG_TRANSCRIBER_MODEL_DIR": self.cache_dir.name},
            clear=False,
        )
        self.cache_env.start()
        FakeModel.created = []
        FakePipeline.batch_calls = []
        FakePipeline.call_kwargs = []
        FakePipeline.failures = {}
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
        self.progress_events: list[dict] = []
        self.audio = Path("audio.wav")

    def tearDown(self) -> None:
        self.cache_env.stop()
        self.cache_dir.cleanup()

    def progress(self, info: dict) -> None:
        self.progress_events.append(info)

    @patch("app.transcriber._has_windows_cuda_runtime", return_value=True)
    def test_same_runtime_is_loaded_once(self, _runtime_available) -> None:
        with TemporaryDirectory() as cache_dir, patch.dict(
            "app.transcriber.os.environ", {"NANFENG_TRANSCRIBER_MODEL_DIR": cache_dir}, clear=False
        ):
            session = transcriber.TranscriptionSession(
                model_class=FakeModel,
                batched_pipeline_class=FakePipeline,
            )

            first = session.get_runtime(self.options, self.progress)
            second = session.get_runtime(self.options, self.progress)

            self.assertIs(first.model, second.model)
            self.assertEqual(len(FakeModel.created), 1)
            self.assertEqual(FakeModel.created[0][:3], ("medium", "cuda", "float16"))
            self.assertEqual(FakeModel.created[0][3], cache_dir)
            self.assertFalse(FakeModel.created[0][4])

    @patch("app.transcriber._has_windows_cuda_runtime", return_value=True)
    def test_different_models_have_separate_cache_entries(self, _runtime_available) -> None:
        with TemporaryDirectory() as cache_dir, patch.dict(
            "app.transcriber.os.environ", {"NANFENG_TRANSCRIBER_MODEL_DIR": cache_dir}, clear=False
        ):
            session = transcriber.TranscriptionSession(
                model_class=FakeModel,
                batched_pipeline_class=FakePipeline,
            )

            session.get_runtime(self.options, self.progress)
            session.get_runtime(replace(self.options, model_size="small"), self.progress)
            session.get_runtime(self.options, self.progress)

        self.assertEqual([entry[:3] for entry in FakeModel.created], [("medium", "cuda", "float16"), ("small", "cuda", "float16")])

    @patch("app.transcriber._has_windows_cuda_runtime", return_value=True)
    def test_second_session_uses_persistent_local_model_cache(self, _runtime_available) -> None:
        with TemporaryDirectory() as cache_dir, patch.dict(
            "app.transcriber.os.environ", {"NANFENG_TRANSCRIBER_MODEL_DIR": cache_dir}, clear=False
        ):
            first_session = transcriber.TranscriptionSession(
                model_class=FakeModel,
                batched_pipeline_class=FakePipeline,
            )
            first_session.get_runtime(self.options, self.progress)

            second_session = transcriber.TranscriptionSession(
                model_class=FakeModel,
                batched_pipeline_class=FakePipeline,
            )
            second_session.get_runtime(self.options, self.progress)

            self.assertEqual([entry[4] for entry in FakeModel.created], [False, True])
            self.assertTrue(list(Path(cache_dir).glob(".ready-*.json")))

    @patch("app.transcriber._has_windows_cuda_runtime", return_value=True)
    def test_incomplete_local_cache_is_repaired_once(self, _runtime_available) -> None:
        class RepairingModel(FakeModel):
            def __init__(self, model_size: str, **kwargs) -> None:
                super().__init__(model_size, **kwargs)
                if kwargs["local_files_only"]:
                    raise FileNotFoundError("cached model is incomplete")

        cache_dir = Path(self.cache_dir.name)
        marker = transcriber._model_cache_marker(cache_dir, self.options.model_size)
        marker.write_text("{}", encoding="utf-8")
        session = transcriber.TranscriptionSession(
            model_class=RepairingModel,
            batched_pipeline_class=FakePipeline,
        )

        session.get_runtime(self.options, self.progress)

        self.assertEqual([entry[4] for entry in FakeModel.created], [True, False])
        self.assertTrue(marker.is_file())
        self.assertTrue(any(event.get("status") == "downloading_model" for event in self.progress_events))

    @patch("app.transcriber._has_windows_cuda_runtime", return_value=True)
    def test_gpu_uses_batch_size_eight_and_beam_size_three(self, _runtime_available) -> None:
        session = transcriber.TranscriptionSession(
            model_class=FakeModel,
            batched_pipeline_class=FakePipeline,
        )

        segments = session.transcribe_audio(self.audio, 30.0, self.options, self.progress)

        self.assertEqual(segments[0]["text"], "测试文本")
        self.assertEqual(FakePipeline.batch_calls, [8])
        self.assertEqual(FakePipeline.call_kwargs[0]["beam_size"], 3)
        self.assertNotIn("initial_prompt", FakePipeline.call_kwargs[0])

    @patch("app.transcriber._has_windows_cuda_runtime", return_value=True)
    def test_gpu_batch_size_falls_back_and_is_remembered(self, _runtime_available) -> None:
        FakePipeline.failures = {8: RuntimeError("CUDA out of memory")}
        session = transcriber.TranscriptionSession(
            model_class=FakeModel,
            batched_pipeline_class=FakePipeline,
        )

        first = session.transcribe_audio(self.audio, 30.0, self.options, self.progress)
        second = session.transcribe_audio(self.audio, 30.0, self.options, self.progress)

        self.assertTrue(first)
        self.assertTrue(second)
        self.assertEqual(FakePipeline.batch_calls, [8, 4, 4])

    @patch("app.transcriber._has_windows_cuda_runtime", return_value=True)
    def test_non_gpu_error_is_not_swallowed(self, _runtime_available) -> None:
        FakePipeline.failures = {8: ValueError("invalid media")}
        session = transcriber.TranscriptionSession(
            model_class=FakeModel,
            batched_pipeline_class=FakePipeline,
        )

        with self.assertRaisesRegex(ValueError, "invalid media"):
            session.transcribe_audio(self.audio, 30.0, self.options, self.progress)
