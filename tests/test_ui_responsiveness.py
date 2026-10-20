import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
from app.main import MainWindow, QueueItem
from app.transcriber import TranscribeStopped


class UiResponsivenessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait_for(self, predicate):
        deadline = time.monotonic() + 4
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertTrue(predicate())

    def test_alignment_stage_contributes_to_batch_progress(self):
        with TemporaryDirectory() as tmp:
            window = MainWindow(QSettings(str(Path(tmp) / "prefs.ini"), QSettings.IniFormat))
            with patch("app.main.probe_duration_seconds", return_value=1):
                window._add_row(Path(tmp) / "source.wav")
                self.wait_for(lambda: not window._duration_jobs)
            window.active_rows = {0}
            window._on_item_progress(0, {"status": "aligning", "progress": 42})
            self.assertEqual(window.main_progress.value(), 42)
            window.active_rows.clear()
            window.close()
            self.wait_for(lambda: window._closing)

    def test_failed_settings_write_retains_changes_and_cancel_close_can_retry(self):
        with TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "prefs.ini")
            window = MainWindow(QSettings(path, QSettings.IniFormat))
            window.show()
            with patch.object(QSettings, "sync", side_effect=OSError("fixture disk failure")):
                window.model_combo.setCurrentText("通用快速")
                self.wait_for(lambda: window.settings.save_failed and not window.settings.busy)
                self.app.processEvents()
                self.assertIn("保存失败", window.status_label.text())
                with patch.object(QMessageBox, "warning", return_value=QMessageBox.Cancel) as warning:
                    window.close()
                    self.wait_for(lambda: warning.called and not window._close_requested)
                self.assertTrue(window.isVisible())
                self.assertFalse(window._closing)
                self.assertEqual(window.settings.value("transcription/model"), "通用快速")
            window.settings.sync()
            self.wait_for(lambda: not window.settings.busy)
            self.assertFalse(window.settings.save_failed)
            self.assertEqual(QSettings(path, QSettings.IniFormat).value("transcription/model"), "通用快速")
            window.close()
            self.wait_for(lambda: window._closing)

    def test_slow_settings_disk_does_not_block_option_change(self):
        with TemporaryDirectory() as tmp:
            window = MainWindow(QSettings(str(Path(tmp)/"prefs.ini"), QSettings.IniFormat))
            original = QSettings.sync
            writes = []
            def slow(settings):
                writes.append(threading.get_ident())
                time.sleep(.25)
                return original(settings)
            try:
                with patch.object(QSettings, "sync", slow):
                    started = time.monotonic()
                    window.model_combo.setCurrentText("通用快速")
                    elapsed = time.monotonic() - started
                    self.assertLess(elapsed, .1, "changing an option waits for settings disk I/O")
                    self.wait_for(lambda: bool(writes))
                    self.assertNotIn(threading.get_ident(), writes)
                    self.wait_for(lambda: not window.settings.busy)
            finally:
                window.close()
                writer = getattr(window.settings, "wait_for_idle", None)
                if writer:
                    writer(2)

    def test_close_cancels_running_transcription_without_destroying_thread(self):
        with TemporaryDirectory() as tmp:
            window = MainWindow(QSettings(str(Path(tmp)/"prefs.ini"), QSettings.IniFormat))
            window.completion_dialog_enabled = False
            window.completion_sound_enabled = False
            entered, release, cancelled = threading.Event(), threading.Event(), threading.Event()
            def controlled(source, options, progress, cancel, session=None):
                entered.set()
                while not release.wait(.01):
                    if cancel():
                        cancelled.set()
                raise TranscribeStopped("controlled stop")
            with patch("app.main.probe_duration_seconds", return_value=1):
                window._add_row(Path(tmp)/"source.wav")
            try:
                with patch("app.main.transcribe_file", side_effect=controlled):
                    window.show()
                    window._start_worker([QueueItem(Path(tmp)/"source.wav", 0, "通用快速", "中文")], window._build_options())
                    self.assertTrue(entered.wait(1))
                    started = time.monotonic()
                    window.close()
                    self.assertLess(time.monotonic()-started, .15)
                    self.assertTrue(cancelled.wait(.3), "window close did not request cancellation")
                    self.assertTrue(window.isVisible(), "window disappeared before its worker had stopped")
                    pulses = []
                    QTimer.singleShot(0, lambda: pulses.append(True))
                    self.app.processEvents()
                    self.assertEqual(pulses, [True])
                    release.set()
                    self.wait_for(lambda: window.worker_thread is None and not window.isVisible())
            finally:
                release.set()
                self.wait_for(lambda: window.worker_thread is None)
                window.close()
                writer = getattr(window.settings, "wait_for_idle", None)
                if writer:
                    writer(2)
