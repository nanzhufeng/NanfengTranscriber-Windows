import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from app.main import MainWindow, COL_DURATION


class AsyncUiIoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait_for(self, predicate):
        until = time.monotonic() + 3
        while not predicate() and time.monotonic() < until:
            self.app.processEvents()
            QTest.qWait(5)
        self.assertTrue(predicate())

    def test_slow_directory_discovery_does_not_block_ui(self):
        with TemporaryDirectory() as tmp:
            window = MainWindow(QSettings(str(Path(tmp) / "prefs.ini"), QSettings.IniFormat))
            entered, release, timed_out = threading.Event(), threading.Event(), threading.Event()
            def slow(paths):
                entered.set()
                if not release.wait(3):
                    timed_out.set()
                return []
            try:
                with patch.object(window, "_expand_media_paths", side_effect=slow):
                    window._add_paths([Path(tmp)])
                    self.assertTrue(entered.wait(1))
                    self.assertFalse(timed_out.is_set())
                    pulses = []
                    QTimer.singleShot(0, lambda: pulses.append(True))
                    self.app.processEvents()
                    self.assertEqual(pulses, [True])
                    release.set()
                    self.wait_for(lambda: window._import_job is None)
            finally:
                release.set()
                window.close()

    def test_late_metadata_cannot_overwrite_a_row_reused_after_clear(self):
        with TemporaryDirectory() as tmp:
            window = MainWindow(QSettings(str(Path(tmp) / "prefs.ini"), QSettings.IniFormat))
            entered, release = threading.Event(), threading.Event()
            def probe(path, options):
                if path.name == "slow.wav":
                    entered.set()
                    release.wait(3)
                    return 99
                return 1
            try:
                with patch("app.main.probe_duration_seconds", side_effect=probe):
                    window._add_row(Path(tmp) / "slow.wav")
                    self.assertTrue(entered.wait(1))
                    self.assertEqual(window.table.item(0, COL_DURATION).text(), "-")
                    window._clear()
                    window._add_row(Path(tmp) / "new.wav")
                    release.set()
                    self.wait_for(lambda: not window._duration_jobs)
                    self.assertEqual(window.table.item(0, COL_DURATION).text(), "0:01")
            finally:
                release.set()
                window.close()

    def test_slow_history_save_does_not_block_or_hide_unsaved_completion(self):
        from app.transcriber import TranscribeResult
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            window = MainWindow(QSettings(str(root / "prefs.ini"), QSettings.IniFormat))
            entered, release = threading.Event(), threading.Event()
            original = window.history_store.save
            def slow(result):
                entered.set()
                release.wait(3)
                original(result)
            try:
                with patch("app.main.probe_duration_seconds", return_value=1):
                    window._add_row(root / "sample.wav")
                with patch.object(window.history_store, "save", side_effect=slow):
                    window._on_item_finished(0, TranscribeResult([], "受控文稿", source_path=root / "sample.wav"))
                    self.assertTrue(entered.wait(1))
                    self.assertFalse(window.table.isRowHidden(0))
                    pulses = []
                    QTimer.singleShot(0, lambda: pulses.append(True))
                    self.app.processEvents()
                    self.assertEqual(pulses, [True])
                    release.set()
                    self.wait_for(lambda: not window._history_save_jobs)
                    self.assertEqual(window.table.rowCount(), 0)
                    self.assertEqual(window.history_store.query()[1], 1)
            finally:
                release.set()
                window.close()
