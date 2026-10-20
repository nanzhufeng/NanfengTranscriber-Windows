from pathlib import Path
from tempfile import TemporaryDirectory
import time
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, QSettings, QThreadPool, QTimer
from PySide6.QtWidgets import QApplication

from app.main import AppSettingsDialog, MainWindow


class DialogLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_repeated_settings_open_close_does_not_retain_hidden_dialogs(self):
        with TemporaryDirectory() as temporary, \
             patch("app.cloud_credentials.read_api_key", return_value=""):
            window = MainWindow(QSettings(str(Path(temporary) / "prefs.ini"), QSettings.IniFormat))
            try:
                for _ in range(3):
                    QTimer.singleShot(0, lambda: QApplication.activeModalWidget().reject())
                    window.settings_button.click()
                    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
                    self.assertEqual(window.findChildren(AppSettingsDialog), [],
                                     "Closed settings retained timers, widgets and background refresh")
            finally:
                window.close()
                deadline = time.monotonic() + 2
                while not window._closing and time.monotonic() < deadline:
                    self.app.processEvents()
                    time.sleep(.005)
                self.assertTrue(window._closing)
                # Dialog destruction disconnects its count callback; the read
                # still owns a short-lived SQLite connection until it returns.
                # Drain test-owned background reads before removing the fixture.
                self.assertTrue(QThreadPool.globalInstance().waitForDone(2000))

    def test_close_cancels_running_installer_without_restarting_transcription(self):
        real_popen = subprocess.Popen
        started = threading.Event()
        children = []
        def launch(_command, **kwargs):
            process = real_popen([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)
            children.append(process)
            started.set()
            return process
        with TemporaryDirectory() as temporary:
            window = MainWindow(QSettings(str(Path(temporary) / "prefs.ini"), QSettings.IniFormat))
            window.show()
            try:
                with patch("app.dependency_install.subprocess.Popen", side_effect=launch), \
                     patch.object(window, "_start") as restart:
                    window._install_dependency_then_start()
                    self.assertTrue(started.wait(2))
                    begin = time.monotonic()
                    window.close()
                    self.assertLess(time.monotonic() - begin, .2)
                    deadline = time.monotonic() + 3
                    while not window._closing and time.monotonic() < deadline:
                        self.app.processEvents()
                        time.sleep(.005)
                    self.assertTrue(window._closing)
                    self.assertIsNone(window.install_thread)
                    self.assertTrue(all(child.poll() is not None for child in children))
                    self.assertFalse(window.start_after_install)
                    restart.assert_not_called()
            finally:
                for child in children:
                    if child.poll() is None:
                        child.kill()
                    child.wait(timeout=3)
                window.close()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
