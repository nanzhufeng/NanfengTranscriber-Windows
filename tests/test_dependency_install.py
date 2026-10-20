import subprocess
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt

from app.dependency_install import DependencyInstallWorker


class DependencyInstallTests(unittest.TestCase):
    def run_script(self, script, *, timeout=10, cancel=False, before_cancel=None):
        real_popen = subprocess.Popen
        started, finished = threading.Event(), threading.Event()
        children, outcomes = [], []
        worker = DependencyInstallWorker()
        def completed(ok, message):
            outcomes.append((ok, message))
            finished.set()
        worker.finished.connect(completed, Qt.DirectConnection)
        def launch(_command, **kwargs):
            process = real_popen([sys.executable, "-u", "-c", script], **kwargs)
            children.append(process)
            started.set()
            return process
        with patch("app.dependency_install.subprocess.Popen", side_effect=launch), \
             patch("app.dependency_install.INSTALL_TIMEOUT_SECONDS", timeout):
            thread = threading.Thread(target=worker.run, daemon=True)
            thread.start()
            try:
                self.assertTrue(started.wait(2))
                if before_cancel:
                    before_cancel()
                if cancel:
                    worker.cancel()
                self.assertTrue(finished.wait(1.5), "Installer did not honor cancellation/deadline")
                thread.join(timeout=1)
                self.assertFalse(thread.is_alive())
                self.assertTrue(all(child.poll() is not None for child in children))
                self.assertEqual(len(outcomes), 1)
                return outcomes[0]
            finally:
                worker.cancel()
                for child in children:
                    if child.poll() is None:
                        child.kill()
                    child.wait(timeout=3)
                thread.join(timeout=3)

    def test_cancel_reaps_unresponsive_owned_installer(self):
        ok, message = self.run_script("import time; time.sleep(30)", cancel=True)
        self.assertFalse(ok)
        self.assertIn("停止", message)

    def test_overall_deadline_reaps_unresponsive_owned_installer(self):
        ok, message = self.run_script("import time; time.sleep(30)", timeout=.2)
        self.assertFalse(ok)
        self.assertIn("超时", message)

    def test_verbose_installer_drains_output_and_reports_success(self):
        ok, message = self.run_script("import sys; sys.stdout.write('x' * 2000000); "
                                     "sys.stderr.write('y' * 2000000)")
        self.assertTrue(ok, message)

    def test_error_output_does_not_expose_credentials(self):
        ok, message = self.run_script(
            "import sys; sys.stderr.write('https://user:fixture-secret@example.test/private-index'); "
            "sys.exit(7)")
        self.assertFalse(ok)
        self.assertNotIn("fixture-secret", message)
        self.assertNotIn("private-index", message)
        self.assertIn("失败", message)

    @unittest.skipUnless(os.name == "nt", "Windows process job")
    def test_cancel_reaps_installer_build_child_as_well(self):
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        child_handle = None
        with tempfile.TemporaryDirectory() as temporary:
            pid_file = Path(temporary) / "child.pid"
            def capture_child():
                nonlocal child_handle
                deadline = time.monotonic() + 2
                while not pid_file.exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(pid_file.exists())
                child_handle = kernel.OpenProcess(0x100001, False, int(pid_file.read_text()))
                self.assertTrue(child_handle)
            try:
                ok, message = self.run_script(
                    "import subprocess, sys, time\n"
                    "from pathlib import Path\n"
                    "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
                    f"Path({str(pid_file)!r}).write_text(str(child.pid))\n"
                    "time.sleep(30)", cancel=True, before_cancel=capture_child)
                self.assertFalse(ok, message)
                self.assertEqual(kernel.WaitForSingleObject(child_handle, 1000), 0,
                                 "Owned build child remained after installer cancellation")
            finally:
                if child_handle:
                    if kernel.WaitForSingleObject(child_handle, 0) != 0:
                        kernel.TerminateProcess(child_handle, 1)
                        kernel.WaitForSingleObject(child_handle, 3000)
                    kernel.CloseHandle(child_handle)


if __name__ == "__main__":
    unittest.main()
