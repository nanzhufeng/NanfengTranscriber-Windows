from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from app.transcriber import TranscribeOptions, TranscribeStopped, transcribe_file
from app.qwen_bridge import QwenWorker


class RuntimeLifecycleTests(unittest.TestCase):
    def test_local_worker_reuses_process_for_next_file_and_closes_owned_pipes(self):
        real_popen = subprocess.Popen
        children = []
        def responsive_worker(_command, **kwargs):
            process = real_popen([sys.executable, "-u", "-c",
                "import json, sys\n"
                "for line in sys.stdin:\n"
                " json.loads(line)\n"
                " print(json.dumps({'result': [{'start': 0, 'end': 1, 'text': 'ok'}]}), flush=True)\n"
            ], **kwargs)
            children.append(process)
            return process
        options = TranscribeOptions(Path("out"), "中文精确", "中文", "CPU 稳定",
                                   True, False, False, False, False, None)
        worker = QwenWorker()
        with patch("app.qwen_bridge.runtime_ready", return_value=True), \
             patch("app.qwen_bridge.subprocess.Popen", side_effect=responsive_worker):
            try:
                for name in ("first.wav", "second.wav"):
                    deadline = time.monotonic() + 3
                    self.assertEqual(worker.transcribe(Path(name), options, lambda _: None,
                                     lambda: time.monotonic() > deadline),
                                     [{"start": 0, "end": 1, "text": "ok"}])
            finally:
                worker.close()
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].poll())
        self.assertTrue(children[0].stdin.closed)
        self.assertTrue(children[0].stdout.closed)

    def test_stop_during_final_inference_does_not_export_a_completed_file(self):
        cancelled = threading.Event()
        def inference(*_args):
            cancelled.set()
            return [{"start": 0, "end": 1, "text": "不应导出"}]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "sample.mp4"
            options = TranscribeOptions(root / "out", "中文精确", "中文", "CPU 稳定",
                                       True, False, False, False, False, None)
            session = Mock()
            session.transcribe_audio.side_effect = inference
            with patch("app.transcriber._extract_audio"), \
                 patch("app.transcriber.probe_duration_seconds", return_value=1), \
                 patch("app.transcriber.importlib.util.find_spec", return_value=object()):
                with self.assertRaises(TranscribeStopped):
                    transcribe_file(source, options, lambda _: None, cancelled.is_set, session)
            self.assertFalse((root / "out" / "sample.txt").exists())

    def test_stop_during_last_polish_response_is_reported_as_stopped(self):
        from app.postprocess import polish_to_simplified_chinese
        cancelled = threading.Event()
        def response(*_args):
            cancelled.set()
            return "不应导出"
        with patch("app.postprocess._request_chat_completion", side_effect=response):
            with self.assertRaises(TranscribeStopped):
                polish_to_simplified_chinese("测试", "文件", lambda _: None, cancelled.is_set)

    def test_stop_interrupts_large_alignment_request_when_worker_stops_reading(self):
        real_popen = subprocess.Popen
        started = threading.Event()
        cancelled = threading.Event()
        finished = threading.Event()
        errors = []

        def unresponsive_worker(_command, **kwargs):
            process = real_popen(
                [sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)
            started.set()
            return process

        options = TranscribeOptions(Path("out"), "中文精确", "中文", "CPU 稳定",
                                   True, False, False, False, False, None)
        worker = QwenWorker()
        def run_alignment():
            try:
                worker.align(Path("audio.wav"), [
                    {"start": 0, "end": 1, "text": "测试" * 100000}],
                    options, lambda _: None, cancelled.is_set)
            except BaseException as error:
                errors.append(error)
            finally:
                finished.set()

        with patch("app.qwen_bridge.runtime_ready", return_value=True), \
             patch("app.qwen_bridge.subprocess.Popen", side_effect=unresponsive_worker):
            thread = threading.Thread(target=run_alignment, daemon=True)
            thread.start()
            self.assertTrue(started.wait(2))
            cancelled.set()
            try:
                self.assertTrue(finished.wait(1.5), "Stop is blocked behind a full worker stdin pipe")
                self.assertIsInstance(errors[0], TranscribeStopped)
                self.assertIsNone(worker.process)
            finally:
                worker.close()
                thread.join(timeout=3)

    def test_verbose_extractor_completes_without_filling_stderr_pipe(self):
        """A damaged/noisy decoder must still finish, rather than wait for Stop."""
        real_popen = subprocess.Popen
        children = []

        def extractor(command, **kwargs):
            process = real_popen(
                [sys.executable, "-c",
                 "import sys; sys.stderr.write('decoder warning\\n' * 100000); "
                 "sys.stderr.flush(); open(sys.argv[1], 'wb').close()",
                 command[-1]], **kwargs)
            children.append(process)
            return process

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "sample.mp4"
            source.touch()
            options = TranscribeOptions(root / "out", "中文精确", "中文", "CPU 稳定",
                                       True, False, False, False, False, None)
            session = Mock()
            session.transcribe_audio.return_value = [
                {"start": 0, "end": 1, "text": "受控测试"}]
            deadline = time.monotonic() + 3
            try:
                with patch("app.transcriber.subprocess.Popen", side_effect=extractor), \
                     patch("app.transcriber.probe_duration_seconds", return_value=1), \
                     patch("app.transcriber.importlib.util.find_spec", return_value=object()):
                    result = transcribe_file(
                        source, options, lambda _: None,
                        lambda: time.monotonic() > deadline, session)
                self.assertEqual(result.text, "受控测试")
                self.assertTrue(all(child.poll() == 0 for child in children))
            finally:
                for child in children:
                    if child.poll() is None:
                        child.kill()
                    child.wait(timeout=3)


if __name__ == "__main__":
    unittest.main()
