import io
import json
import os
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import time
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

    def test_cancel_during_final_result_keeps_resume_cache_without_success_fact(self):
        from app.invocations import InvocationStore
        from app.transcriber import TranscribeStopped
        client = FakeClient()
        stopped = False
        def check_cancel():
            if stopped:
                raise TranscribeStopped("stopped")
        def result(_url):
            nonlocal stopped
            client.request_attempted = True
            stopped = True
            return [{"start": 0, "end": 1, "text": "cached result"}]
        client.check_cancel = check_cancel
        client.result = result
        with self.assertRaises(TranscribeStopped):
            transcribe_cloud(self.audio, self.options, lambda _: None, None, client)
        self.assertEqual(InvocationStore(self.root).groups(), [])
        stopped = False
        self.assertEqual(transcribe_cloud(self.audio, self.options, lambda _: None, None, client),
                         [{"start": 0, "end": 1, "text": "cached result"}])
        self.assertEqual(client.submits, 1)

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

    def test_real_transport_seam_records_metadata_once_and_cache_adds_no_fact(self):
        from app.invocations import InvocationStore
        options = replace(self.options, invocation_task_id="file-a", source_display_name="原文件.wav")
        client = DashScopeClient("fixture-api-key")
        def opened(req, **kwargs):
            if "getPolicy" in req.full_url:
                payload = {"data": {"upload_host": "https://upload.oss-cn-beijing.aliyuncs.com", "upload_dir": "temporary",
                    "oss_access_key_id": "fixture-id", "signature": "fixture-signature", "policy": "fixture-policy",
                    "x_oss_object_acl": "private", "x_oss_forbid_overwrite": "true"}}
            elif "upload.oss-" in req.full_url:
                b"".join(req.data)
                return io.BytesIO(b"")
            elif "/services/" in req.full_url:
                payload = {"output": {"task_id": "task-123", "task_status": "PENDING"}}
            elif "/tasks/" in req.full_url:
                payload = {"output": {"task_id": "task-123", "task_status": "SUCCEEDED", "results": [
                    {"subtask_status": "SUCCEEDED", "transcription_url": "https://result.oss-cn-beijing.aliyuncs.com/result.json"}]},
                    "usage": {"input_tokens": 1_000_000, "output_tokens": 1_000_000, "duration": 60}}
            else:
                payload = {"transcripts": [{"channel_id": 0, "sentences": [{"begin_time": 0, "end_time": 1000, "text": "private transcript"}]}]}
            return io.BytesIO(json.dumps(payload).encode())
        with patch.object(client.opener, "open", side_effect=opened) as network:
            transcribe_cloud(self.audio, options, lambda _: None, None, client)
            count = network.call_count
            transcribe_cloud(self.audio, options, lambda _: None, None, client)
            self.assertEqual(network.call_count, count)
        rows = InvocationStore(self.root).groups()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["request_count"], 1)
        self.assertEqual(rows[0]["source_display_name"], "原文件.wav")
        self.assertEqual(rows[0]["estimated_cost_micros"], 3_500_000)
        self.assertEqual(rows[0]["total_tokens"], 2_000_000)
        content = (self.root / "asr_invocations.sqlite3").read_bytes()
        self.assertNotIn(b"private transcript", content)
        self.assertNotIn(b"fixture-api-key", content)

    def test_http_failure_preflight_and_cancel_match_mobile_ledger_boundary(self):
        from urllib.error import HTTPError
        from app.invocations import InvocationStore
        from app.transcriber import TranscribeStopped
        options = replace(self.options, invocation_task_id="file-a")
        client = DashScopeClient("fixture-api-key")
        with patch.object(client.opener, "open", side_effect=HTTPError("https://example", 401, "private response", {}, None)):
            with self.assertRaises(CloudAsrError):
                transcribe_cloud(self.audio, options, lambda _: None, None, client)
        self.assertEqual(InvocationStore(self.root).groups()[0]["error_code"], "FILETRANS_HTTP_401")
        with self.assertRaises(CloudAsrError):
            transcribe_cloud(self.audio, replace(options, cloud_api_key=""), lambda _: None, None)
        client = DashScopeClient("fixture-api-key")
        def cancel_after_request(*args, **kwargs):
            client.cancel = lambda: True
            client.check_cancel()
        with patch.object(client.opener, "open", side_effect=cancel_after_request):
            with self.assertRaises(TranscribeStopped):
                transcribe_cloud(self.audio, options, lambda _: None, None, client)
        rows = InvocationStore(self.root).groups()
        self.assertEqual(rows[0]["request_count"], 1)
        self.assertIsNone(rows[0]["estimated_cost_micros"])

    def test_recording_failure_does_not_discard_successful_transcription(self):
        from app.invocations import InvocationStore
        client = FakeClient()
        original = client.upload
        def attempted(*args):
            client.request_attempted = True
            return original(*args)
        client.upload = attempted
        with patch.object(InvocationStore, "record", side_effect=OSError("private failure")), self.assertLogs("app.cloud_asr", level="WARNING") as logged:
            self.assertTrue(transcribe_cloud(self.audio, self.options, lambda _: None, None, client))
        self.assertNotIn("private failure", str(logged.output))

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

    def test_mixed_batch_keeps_cloud_authorization_when_gpu_switches_to_cpu(self):
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QMessageBox
        from app.main import MainWindow, COL_MODEL
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {
            "DASHSCOPE_API_KEY": "fixture-api-key", "NANZHU_TEXT_API_KEY": "", "OPENAI_API_KEY": "",
        }):
            root = Path(tmp)
            window = MainWindow(QSettings(str(root / "prefs.ini"), QSettings.IniFormat))
            window.output_edit.setText(str(root / "exports"))
            with patch("app.main.probe_duration_seconds", return_value=1):
                window._add_row(root / "cloud.wav")
                window._add_row(root / "local.wav")
            window.table.cellWidget(0, COL_MODEL).setCurrentText("高精度 Qwen")
            window.table.cellWidget(1, COL_MODEL).setCurrentText("通用快速")
            def switch_to_cpu():
                window.compute_mode_combo.setCurrentText("CPU 稳定")
                return True
            with patch.object(window, "_start_worker") as start, \
                 patch.object(QMessageBox, "question", return_value=QMessageBox.Yes), \
                 patch.object(window, "_missing_dependencies", return_value=[]), \
                 patch.object(window, "_warn_gpu_runtime_if_needed", side_effect=switch_to_cpu), \
                 patch.object(window, "_handle_existing_outputs", side_effect=lambda items, options, existing=None: items):
                window._start()
                from PySide6.QtTest import QTest
                deadline = time.monotonic() + 5
                while not start.called and time.monotonic() < deadline:
                    QTest.qWait(10)
                    time.sleep(.001)
                items, options = start.call_args.args
                self.assertEqual([item.model_size for item in items], ["高精度 Qwen", "通用快速"])
                self.assertEqual(options.compute_mode, "CPU 稳定")
                self.assertEqual(options.cloud_api_key, "fixture-api-key")
                self.assertEqual(options.cloud_state_dir, window.history_store.root / "cloud-tasks")
            window.close()

    def test_cloud_start_runs_without_confirmation_and_keeps_model_metadata(self):
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QMessageBox
        from app.main import MainWindow, COL_MODEL
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"DASHSCOPE_API_KEY": "fixture-api-key"}):
            root = Path(tmp)
            window = MainWindow(QSettings(str(root / "prefs.ini"), QSettings.IniFormat))
            window.output_edit.setText(str(root / "exports"))
            window.model_combo.setCurrentText("高精度 Qwen")
            self.assertEqual(window.model_combo.currentData(), "qwen-audio-3.1-asr-flash-filetrans")
            with patch("app.main.probe_duration_seconds", return_value=1):
                window._add_row(root / "sample.wav")
            for mode in CLOUD_MODELS:
                window.table.cellWidget(0, COL_MODEL).setCurrentText(mode)
                with self.subTest(mode=mode), patch.object(window, "_start_worker") as start, patch.object(QMessageBox, "question", return_value=QMessageBox.No) as question:
                    window._start()
                    from PySide6.QtTest import QTest
                    deadline = time.monotonic() + 5
                    while not start.called and time.monotonic() < deadline:
                        QTest.qWait(10)
                        time.sleep(.001)
                    question.assert_not_called()
                    start.assert_called_once()
                    items, options = start.call_args.args
                    self.assertEqual(items[0].model_size, mode)
                    self.assertEqual(options.cloud_api_key, "fixture-api-key")
                    self.assertNotIn("fixture-api-key", repr(options))
            window.close()
