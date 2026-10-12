import unittest
from pathlib import Path
from unittest.mock import patch
from app.model_modes import MODE_OPTIONS, model_for_mode, mode_description


class LocalModeTests(unittest.TestCase):
    def test_frozen_qwen_runtime_uses_user_cache_and_requires_ready_marker(self):
        import os
        from tempfile import TemporaryDirectory
        from app.qwen_bridge import runtime_python, runtime_ready
        with TemporaryDirectory() as temp, patch('sys.frozen', True, create=True), patch.dict(os.environ, {'LOCALAPPDATA': temp}):
            with patch.dict(os.environ):
                os.environ.pop('NANFENG_QWEN_PYTHON', None)
                runtime = Path(temp) / 'NanfengTranscriber/runtimes/qwen'
                runtime.mkdir(parents=True)
                (runtime / 'python.exe').touch()
                self.assertEqual(runtime_python(), runtime / 'python.exe')
                self.assertFalse(runtime_ready())
                (runtime / 'runtime.ready').write_text('verified')
                self.assertTrue(runtime_ready())

    def test_two_chinese_modes_map_to_only_two_asr_models(self):
        self.assertEqual(MODE_OPTIONS, ["中文精确", "通用快速"])
        self.assertEqual(model_for_mode("中文精确"), "qwen3-asr")
        self.assertEqual(model_for_mode("通用快速"), "turbo")
        self.assertIn("Qwen3-ASR-1.7B", mode_description("中文精确")[1])
        self.assertIn("large-v3-turbo", mode_description("通用快速")[1])

    def test_legacy_models_migrate_to_fast_mode(self):
        self.assertEqual(model_for_mode("medium"), "turbo")
        self.assertEqual(model_for_mode("large-v3"), "turbo")

    def test_alignment_keeps_original_english_spaces_and_punctuation(self):
        from app.qwen_worker import aligned_words
        from app.transcriber import _subtitle_cues
        words = aligned_words("Hello, world!", [
            {"text": "Hello", "start_time": 0.2, "end_time": 0.6},
            {"text": "world", "start_time": 0.7, "end_time": 1.1}], 30, 32)
        cues = _subtitle_cues([{"text": "Hello, world!", "start": 30, "end": 32, "words": words}])
        self.assertEqual(cues, [{"text": "Hello, world!", "start": 30.2, "end": 31.1}])
        with self.assertRaises(RuntimeError):
            aligned_words("Hello world", [{"text": "Hello", "start_time": 0, "end_time": 1}], 0, 2)

    def test_qwen_session_dispatches_and_closes_local_worker(self):
        from app.transcriber import TranscriptionSession, TranscribeOptions
        options = TranscribeOptions(Path("out"), "中文精确", "中文", "GPU 优先", True, False, True, False, False, None)
        with patch("app.qwen_bridge.QwenWorker") as worker_factory:
            worker = worker_factory.return_value
            worker.transcribe.return_value = [{"start": 1, "end": 2, "text": "测试。"}]
            session = TranscriptionSession()
            self.assertEqual(session.transcribe_audio(Path("audio.wav"), 3, options, lambda _: None)[0]["text"], "测试。")
            session.close()
            worker.close.assert_called_once()
