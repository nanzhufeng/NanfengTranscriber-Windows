from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch

from app.background_feedback import enqueue_log, play_sound


class BackgroundFeedbackTests(unittest.TestCase):
    def test_slow_log_disk_does_not_block_caller_and_redacts_credentials(self):
        entered, release, written = threading.Event(), threading.Event(), threading.Event()
        original = Path.open
        with TemporaryDirectory() as temporary:
            target = Path(temporary) / "runtime-log.txt"
            def slow_open(path, *args, **kwargs):
                if path == target and args and args[0] == "a":
                    entered.set()
                    release.wait(2)
                return original(path, *args, **kwargs)
            try:
                with patch.object(Path, "open", slow_open):
                    start = time.monotonic()
                    self.assertTrue(enqueue_log(target, "Authorization: Bearer fixture-secret "
                                               "https://user:private-password@example.test"))
                    self.assertLess(time.monotonic() - start, .15)
                    self.assertTrue(entered.wait(1))
                    # Saturation must remain bounded even while the disk is stalled.
                    accepted = sum(enqueue_log(target, "bounded diagnostic") for _ in range(1000))
                    self.assertLessEqual(accepted, 256)
                    release.set()
                    deadline = time.monotonic() + 2
                    while time.monotonic() < deadline:
                        if target.exists():
                            content = target.read_text(encoding="utf-8")
                            if content.count("\n") == accepted + 1:
                                written.set()
                                break
                        time.sleep(.005)
                    self.assertTrue(written.is_set())
                self.assertNotIn("fixture-secret", content)
                self.assertNotIn("private-password", content)
                self.assertIn("[已隐藏]", content)
            finally:
                release.set()

    def test_sound_does_not_block_or_build_an_unbounded_backlog(self):
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        thread_ids = []
        def slow_audio():
            thread_ids.append(threading.get_ident())
            entered.set()
            release.wait(2)
            finished.set()
        try:
            start = time.monotonic()
            self.assertTrue(play_sound(slow_audio))
            self.assertLess(time.monotonic() - start, .15)
            self.assertTrue(entered.wait(1))
            self.assertFalse(play_sound(lambda: self.fail("sound backlog should be dropped")))
            self.assertNotEqual(thread_ids, [threading.get_ident()])
        finally:
            release.set()
            self.assertTrue(finished.wait(1))


if __name__ == "__main__":
    unittest.main()
