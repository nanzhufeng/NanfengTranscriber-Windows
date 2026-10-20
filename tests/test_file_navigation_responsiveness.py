import time
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PySide6.QtCore import QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.main import MainWindow


class FileNavigationResponsivenessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait_for(self, predicate):
        deadline = time.monotonic() + 3
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertTrue(predicate())

    def finish(self, window):
        self.wait_for(lambda: not window._io_jobs and not window._duration_jobs)
        window.close()
        window.settings.wait_for_idle(2)

    def test_open_directory_does_not_wait_for_mkdir(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            destination = root / "outputs"
            window = MainWindow(QSettings(str(root / "prefs.ini"), QSettings.IniFormat))
            window.output_edit.setText(str(destination))
            original = Path.mkdir
            def slow_mkdir(path, *args, **kwargs):
                if path == destination:
                    time.sleep(.3)
                return original(path, *args, **kwargs)
            try:
                with (
                    patch.object(Path, "mkdir", slow_mkdir),
                    patch("app.main.subprocess.Popen") as popen,
                    patch("app.main.QDesktopServices.openUrl", return_value=True),
                ):
                    start = time.monotonic()
                    window._open_output_dir()
                    elapsed = time.monotonic() - start
                    self.assertLess(elapsed, .1, f"打开目录阻塞GUI {elapsed:.3f}s")
                    self.wait_for(lambda: popen.called)
                    self.wait_for(lambda: not window._io_jobs)
                    self.assertTrue(destination.is_dir())
            finally:
                self.finish(window)

    def test_locate_file_does_not_wait_for_exists_or_type_probe(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            source = root / "sample.wav"
            source.touch()
            window = MainWindow(QSettings(str(root / "prefs.ini"), QSettings.IniFormat))
            with patch("app.main.probe_duration_seconds", return_value=0):
                window._add_row(source)
                self.wait_for(lambda: not window._duration_jobs)
            original_exists, original_is_dir = Path.exists, Path.is_dir
            def slow_exists(path):
                if path == source:
                    time.sleep(.2)
                return original_exists(path)
            def slow_is_dir(path):
                if path == source:
                    time.sleep(.2)
                return original_is_dir(path)
            try:
                with (
                    patch.object(Path, "exists", slow_exists),
                    patch.object(Path, "is_dir", slow_is_dir),
                    patch("app.main.subprocess.Popen") as popen,
                ):
                    start = time.monotonic()
                    window._locate_row_file(0)
                    elapsed = time.monotonic() - start
                    self.assertLess(elapsed, .1, f"定位文件阻塞GUI {elapsed:.3f}s")
                    self.wait_for(lambda: popen.called)
                    self.wait_for(lambda: not window._io_jobs)
                    popen.assert_called_once_with(["explorer.exe", "/select,", str(source)])
            finally:
                self.finish(window)

    def test_completion_defers_probe_and_keeps_existing_output_fallback(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            source, first, missing = root / "source.wav", root / "first.txt", root / "missing.txt"
            source.touch()
            first.touch()
            window = MainWindow(QSettings(str(root / "prefs.ini"), QSettings.IniFormat))
            window.auto_open_output_enabled = True
            window.completion_sound_enabled = window.completion_dialog_enabled = False
            with patch("app.main.probe_duration_seconds", return_value=0):
                for target in (first, missing):
                    row = window.table.rowCount()
                    window._add_row(source)
                    window._set_status_cell(row, "完成")
                    window._update_output_cell(row, str(root), target)
                self.wait_for(lambda: not window._duration_jobs)
            window.active_rows = {0, 1}
            original = Path.exists
            def slow_exists(path):
                if path in (first, missing):
                    time.sleep(.2)
                return original(path)
            try:
                with patch.object(Path, "exists", slow_exists), patch("app.main.subprocess.Popen") as popen:
                    start = time.monotonic()
                    window._on_all_done()
                    window._cleanup_worker()
                    elapsed = time.monotonic() - start
                    self.assertLess(elapsed, .1, f"批次完成处理阻塞GUI {elapsed:.3f}s")
                    self.wait_for(lambda: popen.called)
                    self.wait_for(lambda: not window._io_jobs)
                    popen.assert_called_once_with(["explorer.exe", "/select,", str(first)])
            finally:
                self.finish(window)

    def test_close_during_locate_does_not_open_a_late_explorer_window(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            source = root / "source.wav"
            source.touch()
            window = MainWindow(QSettings(str(root / "prefs.ini"), QSettings.IniFormat))
            entered, release = threading.Event(), threading.Event()
            original = Path.exists
            def slow_exists(path):
                if path == source:
                    entered.set()
                    release.wait(2)
                return original(path)
            try:
                with patch.object(Path, "exists", slow_exists), patch("app.main.subprocess.Popen") as popen:
                    window._reveal_path(source)
                    self.assertTrue(entered.wait(1))
                    window.close()
                    release.set()
                    self.wait_for(lambda: not window._io_jobs)
                    popen.assert_not_called()
            finally:
                release.set()
                self.finish(window)
