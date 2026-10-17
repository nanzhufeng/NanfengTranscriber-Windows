import io
import json
import os
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.cloud_asr import CloudAsrError, DashScopeClient, parse_transcript, transcribe_cloud, trusted_resource
from app.model_modes import CLOUD_MODELS
from app.transcriber import TranscribeOptions, TranscriptionSession


class FakeClient:
    def __init__(self):
        self.submits = 0
        self.fail_submit = False
        self.fail_query = False

    def check_cancel(self):
        pass

    def upload(self, audio, model):
        return "oss://temporary/audio.wav"

    def submit(self, model, url, language):
        self.submits += 1
        if self.fail_submit:
            raise CloudAsrError("模拟提交响应丢失")
        return "task-123"

    def exchange(self, path):
        if self.fail_query:
            raise CloudAsrError("模拟轮询断网")
        return {"output": {"task_id": "task-123", "task_status": "SUCCEEDED", "results": [
            {"subtask_status": "SUCCEEDED", "transcription_url": "https://result.oss-cn-beijing.aliyuncs.com/result.json"}]}}

    def result(self, url):
        return [{"start": 1.0, "end": 2.0, "text": "受控字幕"}]


class CloudAsrTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.audio = self.root / "audio.wav"
        self.audio.write_bytes(b"controlled-audio-fixture")
        self.options = TranscribeOptions(self.root, "高精度 Qwen", "zh", "CPU 稳定", True, True, True, False, False, None,
                                        cloud_api_key="fixture-api-key", cloud_state_dir=self.root / "tasks")

    def test_both_models_return_timed_segments_and_reuse_completed_task(self):
        for mode in CLOUD_MODELS:
            client = FakeClient()
            options = replace(self.options, model_size=mode)
            segments = transcribe_cloud(self.audio, options, lambda _: None, None, client)
            self.assertEqual(segments, [{"start": 1.0, "end": 2.0, "text": "受控字幕"}])
            self.assertEqual(transcribe_cloud(self.audio, options, lambda _: None, None, client), segments)
            self.assertEqual(client.submits, 1)
        for path in (self.root / "tasks").glob("*.json"):
            self.assertNotIn("fixture-api-key", path.read_text(encoding="utf-8"))
        self.assertNotIn("fixture-api-key", repr(self.options))

    def test_uncertain_submit_is_not_silently_repeated(self):
        client = FakeClient()
        client.fail_submit = True
        with self.assertRaises(CloudAsrError):
            transcribe_cloud(self.audio, self.options, lambda _: None, None, client)
        client.fail_submit = False
        with self.assertRaisesRegex(CloudAsrError, "避免重复计费"):
            transcribe_cloud(self.audio, self.options, lambda _: None, None, client)
        self.assertEqual(client.submits, 1)

    def test_query_failure_resumes_existing_task(self):
        client = FakeClient()
        client.fail_query = True
        with self.assertRaises(CloudAsrError):
            transcribe_cloud(self.audio, self.options, lambda _: None, None, client)
        client.fail_query = False
        transcribe_cloud(self.audio, self.options, lambda _: None, None, client)
        self.assertEqual(client.submits, 1)

    def test_upload_streams_multipart_without_exposing_api_key_to_storage(self):
        calls = []
        policy = {"data": {"upload_host": "https://upload.oss-cn-beijing.aliyuncs.com", "upload_dir": "temporary",
            "oss_access_key_id": "fixture-id", "signature": "fixture-signature", "policy": "fixture-policy",
            "x_oss_object_acl": "private", "x_oss_forbid_overwrite": "true"}}
        def opened(req, **kwargs):
            calls.append(req)
            if len(calls) == 1:
                return io.BytesIO(json.dumps(policy).encode())
            body = b"".join(req.data)
            self.assertEqual(len(body), int(req.get_header("Content-length")))
            self.assertIn(self.audio.read_bytes(), body)
            self.assertNotIn(b"fixture-api-key", body)
            self.assertIsNone(req.get_header("Authorization"))
            return io.BytesIO(b"")
        client = DashScopeClient("fixture-api-key")
        with patch.object(client.opener, "open", side_effect=opened):
            self.assertTrue(client.upload(self.audio, "paraformer-v2").startswith("oss://temporary/"))

    def test_sentence_milliseconds_and_invalid_ranges(self):
        data = {"transcripts": [{"channel_id": 0, "sentences": [{"begin_time": 1200, "end_time": 2500, "text": "示例"}]}]}
        self.assertEqual(parse_transcript(data), [{"start": 1.2, "end": 2.5, "text": "示例"}])
        data["transcripts"][0]["sentences"][0]["end_time"] = -1
        with self.assertRaises(ValueError):
            parse_transcript(data)

    def test_api_auth_is_not_sent_to_oss_and_models_match_mobile(self):
        for mode, expected in (("高精度 Qwen", "qwen-audio-3.1-asr-flash-filetrans"), ("低成本 Paraformer", "paraformer-v2")):
            calls = []
            def opened(req, **kwargs):
                calls.append(req)
                return io.BytesIO(json.dumps({"output": {"task_id": "task-123", "task_status": "PENDING"}}).encode())
            client = DashScopeClient("fixture-api-key")
            with patch.object(client.opener, "open", side_effect=opened):
                self.assertEqual(client.submit(CLOUD_MODELS[mode], "oss://temp/audio.wav", "zh"), "task-123")
            self.assertEqual(json.loads(calls[0].data)["model"], expected)
            self.assertEqual(calls[0].get_header("Authorization"), "Bearer fixture-api-key")
            calls.clear()
            def result(req, **kwargs):
                calls.append(req)
                return io.BytesIO(b'{"transcripts":[{"channel_id":0,"sentences":[{"begin_time":0,"end_time":1000,"text":"ok"}]}]}')
            with patch.object(client.opener, "open", side_effect=result):
                client.result("https://result.oss-cn-beijing.aliyuncs.com/result.json")
            self.assertIsNone(calls[0].get_header("Authorization"))
        for url in ("http://result.oss-cn-beijing.aliyuncs.com/a", "https://evil.example/a", "https://key@result.oss-cn-beijing.aliyuncs.com/a"):
            self.assertFalse(trusted_resource(url))

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI")
    def test_credentials_are_user_encrypted_and_environment_can_override(self):
        from PySide6.QtCore import QSettings
        from app.cloud_credentials import save_api_key, read_api_key
        settings = QSettings(str(self.root / "prefs.ini"), QSettings.IniFormat)
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": ""}):
            save_api_key(settings, "fixture-protected-key")
            self.assertEqual(read_api_key(settings), "fixture-protected-key")
            self.assertNotIn("fixture-protected-key", (self.root / "prefs.ini").read_text())
            with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "fixture-environment-key"}):
                self.assertEqual(read_api_key(settings), "fixture-environment-key")
            save_api_key(settings, "")
            self.assertEqual(read_api_key(settings), "")

    def test_cloud_dispatch_does_not_load_local_runtime(self):
        session = TranscriptionSession()
        with patch("app.cloud_asr.transcribe_cloud", return_value=[{"start": 0, "end": 1, "text": "ok"}]) as cloud, \
             patch.object(session, "get_runtime", side_effect=AssertionError("local runtime invoked")):
            for mode in CLOUD_MODELS:
                session.transcribe_audio(self.audio, 1, replace(self.options, model_size=mode), lambda _: None)
            self.assertEqual(cloud.call_count, 2)
        session.close()


class CloudUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_cloud_start_requires_explicit_upload_confirmation_and_keeps_model_metadata(self):
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QMessageBox
        from app.main import MainWindow
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"DASHSCOPE_API_KEY": "fixture-api-key"}):
            root = Path(tmp)
            window = MainWindow(QSettings(str(root / "prefs.ini"), QSettings.IniFormat))
            window.output_edit.setText(str(root / "exports"))
            window.model_combo.setCurrentText("高精度 Qwen")
            self.assertEqual(window.model_combo.currentData(), "qwen-audio-3.1-asr-flash-filetrans")
            with patch("app.main.probe_duration_seconds", return_value=1):
                window._add_row(root / "sample.wav")
            with patch.object(window, "_start_worker") as start, patch.object(QMessageBox, "question", return_value=QMessageBox.No):
                window._start()
                start.assert_not_called()
            with patch.object(window, "_start_worker") as start, patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
                window._start()
                start.assert_called_once()
                options = start.call_args.args[1]
                self.assertEqual(options.cloud_api_key, "fixture-api-key")
                self.assertNotIn("fixture-api-key", repr(options))
            window.close()
