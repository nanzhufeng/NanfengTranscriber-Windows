"""Slow local filesystem seams must not stop the GUI event loop."""
import time
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.main import MainWindow


class PreflightResponsivenessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait_for(self, predicate, timeout=4):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertTrue(predicate(), "后台操作未在隔离测试时限内完成")

    def test_start_returns_while_existing_output_check_is_slow(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "sample.wav"
            source.touch()
            window = MainWindow(QSettings(str(root / "settings.ini"), QSettings.IniFormat))
            try:
                window.output_edit.setText(str(root / "outputs"))
                window.compute_mode_combo.setCurrentText("CPU 稳定")
                window.txt_check.setChecked(True)
                for checkbox in (window.md_check, window.srt_check, window.docx_check, window.polish_check):
                    checkbox.setChecked(False)
                with patch("app.main.probe_duration_seconds", return_value=0):
                    window._add_row(source)
                    self.wait_for(lambda: not window._duration_jobs)
                target = root / "outputs" / "sample.txt"
                original_exists = Path.exists
                def slow_exists(path):
                    if path == target:
                        time.sleep(.35)
                        return False
                    return original_exists(path)
                with (
                    patch.object(Path, "exists", slow_exists),
                    patch.object(window, "_missing_dependencies", return_value=[]),
                    patch.object(window, "_warn_gpu_runtime_if_needed", return_value=True),
                    patch.object(window, "_start_worker") as start_worker,
                ):
                    before = time.monotonic()
                    window._start()
                    returned_after = time.monotonic() - before
                    self.wait_for(lambda: start_worker.called)
                self.assertLess(
                    returned_after, .15,
                    f"点击开始被慢输出检查阻塞了 {returned_after:.3f}s；预检须后台执行",
                )
            finally:
                window.close()

    def test_import_path_resolution_keeps_gui_heartbeat_alive(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            sources = [root / f"sample-{index}.wav" for index in range(4)]
            for source in sources:
                source.touch()
            window = MainWindow(QSettings(str(root / "settings.ini"), QSettings.IniFormat))
            original_resolve = Path.resolve
            source_names = set(sources)
            def slow_resolve(path, *args, **kwargs):
                if path in source_names:
                    time.sleep(.18)
                return original_resolve(path, *args, **kwargs)
            gaps = []
            previous = time.monotonic()
            def heartbeat():
                nonlocal previous
                now = time.monotonic()
                gaps.append(now - previous)
                previous = now
            timer = QTimer()
            timer.setInterval(10)
            timer.timeout.connect(heartbeat)
            timer.start()
            try:
                with (
                    patch.object(Path, "resolve", slow_resolve),
                    patch("app.main.probe_duration_seconds", return_value=0),
                ):
                    window._add_paths(sources)
                    self.wait_for_import(lambda: window._import_job is None and window.table.rowCount() == 4)
                    self.wait_for_import(lambda: not window._duration_jobs)
                    QTest.qWait(30)
                self.assertTrue(gaps)
                self.assertLess(
                    max(gaps), .15,
                    f"添加文件时GUI心跳中断了 {max(gaps):.3f}s；路径规范化须后台执行",
                )
            finally:
                timer.stop()
                window.close()

    def test_import_inserts_in_batches_and_tracks_job_until_cancelled(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            sources = [root / f"sample-{index}.wav" for index in range(60)]
            for source in sources:
                source.touch()
            window = MainWindow(QSettings(str(root / "settings.ini"), QSettings.IniFormat))
            original_add = window._add_row
            jobs_during_insert, gaps = [], []
            previous = time.monotonic()
            def slow_add(path):
                jobs_during_insert.append(window._import_job)
                original_add(path)
                # Controlled per-row layout cost must be bounded to one batch.
                time.sleep(.015)
            def heartbeat():
                nonlocal previous
                now = time.monotonic()
                gaps.append(now - previous)
                previous = now
                if window.table.rowCount() >= 4 and window._import_job:
                    window._import_job.cancelled = True
            timer = QTimer()
            timer.setInterval(5)
            timer.timeout.connect(heartbeat)
            timer.start()
            try:
                with patch.object(window, "_add_row", side_effect=slow_add), \
                        patch("app.main.probe_duration_seconds", return_value=0):
                    window._add_paths(sources)
                    self.wait_for_import(lambda: window._import_job is None)
                    self.wait_for_import(lambda: not window._duration_jobs)
                self.assertTrue(jobs_during_insert)
                self.assertTrue(all(job is not None for job in jobs_during_insert))
                self.assertGreater(window.table.rowCount(), 0)
                self.assertLess(window.table.rowCount(), len(sources))
                self.assertLess(max(gaps), .12)
                self.assertTrue(window.add_files_button.isEnabled())
            finally:
                timer.stop()
                window.close()

    def test_directory_discovery_cancellation_stops_resolving_more_files(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = root / "media"
            directory.mkdir()
            for index in range(30):
                (directory / f"{index:02}.wav").touch()
            window = MainWindow(QSettings(str(root / "settings.ini"), QSettings.IniFormat))
            original_resolve = Path.resolve
            resolved = []
            def cancel_during_resolution(path, *args, **kwargs):
                if path.parent == directory:
                    resolved.append(path)
                    if len(resolved) == 2:
                        window._import_job.cancelled = True
                return original_resolve(path, *args, **kwargs)
            try:
                with patch.object(Path, "resolve", cancel_during_resolution):
                    window._add_paths([directory])
                    self.wait_for_import(lambda: window._import_job is None)
                self.assertEqual(len(resolved), 2)
                self.assertEqual(window.table.rowCount(), 0)
            finally:
                window.close()

    def test_batched_import_finishes_all_files_and_deduplicates_resolved_sources(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            sources = [root / f"{index:02}.wav" for index in range(24)]
            for source in sources:
                source.touch()
            window = MainWindow(QSettings(str(root / "settings.ini"), QSettings.IniFormat))
            try:
                with patch("app.main.probe_duration_seconds", return_value=0):
                    window._add_paths(sources + sources[:4])
                    self.wait_for_import(lambda: window._import_job is None)
                    self.wait_for_import(lambda: not window._duration_jobs)
                self.assertEqual(window.table.rowCount(), 24)
                self.assertTrue(window.start_button.isEnabled())
            finally:
                window.close()

    def test_drop_and_clear_cannot_change_queue_during_start_preflight(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, dropped = root / "a.wav", root / "b.wav"
            source.touch()
            dropped.touch()
            window = MainWindow(QSettings(str(root / "settings.ini"), QSettings.IniFormat))
            entered, release = threading.Event(), threading.Event()
            def slow_scan(*args):
                entered.set()
                release.wait(4)
                return {}
            with patch("app.main.probe_duration_seconds", return_value=0), \
                    patch.object(window, "_scan_existing_outputs", side_effect=slow_scan), \
                    patch.object(window, "_missing_dependencies", return_value=[]), \
                    patch.object(window, "_warn_gpu_runtime_if_needed", return_value=True), \
                    patch.object(window, "_start_worker") as start:
                try:
                    window.compute_mode_combo.setCurrentText("CPU 稳定")
                    window.polish_check.setChecked(False)
                    window.output_edit.setText(str(root / "outputs"))
                    window._add_row(source)
                    self.wait_for_import(lambda: not window._duration_jobs)
                    window._start()
                    self.wait_for_import(entered.is_set)
                    # dropEvent forwards to _add_paths even when toolbar buttons are disabled.
                    window._add_paths([dropped])
                    self.assertIsNone(window._import_job)
                    window._clear()
                    window.invert_button.click()
                    self.assertEqual(window.table.rowCount(), 1)
                    self.assertEqual(len(window._selected_items()), 1)
                    self.assertFalse(window.clear_button.isEnabled())
                    release.set()
                    self.wait_for_import(lambda: start.called)
                    self.assertEqual(start.call_args.args[0][0].path, source)
                finally:
                    release.set()
                    window.close()
                    self.wait_for_import(lambda: window._closing)

    def test_preflight_rejects_late_result_after_row_identity_changes(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "a.wav"
            source.touch()
            window = MainWindow(QSettings(str(root / "settings.ini"), QSettings.IniFormat))
            entered, release = threading.Event(), threading.Event()
            def slow_scan(*args):
                entered.set()
                release.wait(4)
                return {}
            with patch("app.main.probe_duration_seconds", return_value=0), \
                    patch.object(window, "_scan_existing_outputs", side_effect=slow_scan), \
                    patch.object(window, "_missing_dependencies", return_value=[]), \
                    patch.object(window, "_warn_gpu_runtime_if_needed", return_value=True), \
                    patch.object(window, "_start_worker") as start:
                try:
                    window.compute_mode_combo.setCurrentText("CPU 稳定")
                    window.polish_check.setChecked(False)
                    window.output_edit.setText(str(root / "outputs"))
                    window._add_row(source)
                    self.wait_for_import(lambda: not window._duration_jobs)
                    original_id = window._selected_items()[0].task_id
                    window._start()
                    self.wait_for_import(entered.is_set)
                    # Reusing the same row and source is still a different task.
                    window.table.setRowCount(0)
                    window._add_row(source)
                    self.assertNotEqual(window._selected_items()[0].task_id, original_id)
                    release.set()
                    self.wait_for_import(lambda: not window._preflight_pending)
                    start.assert_not_called()
                    self.assertIn("队列已变更", window.status_label.text())
                finally:
                    release.set()
                    window.close()
                    self.wait_for_import(lambda: window._closing)

    def test_start_and_clear_wait_until_import_finishes(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "sample.wav"
            source.touch()
            window = MainWindow(QSettings(str(root / "settings.ini"), QSettings.IniFormat))
            entered, release = threading.Event(), threading.Event()
            def slow_discovery(paths):
                entered.set()
                release.wait(4)
                return paths
            with patch("app.main.probe_duration_seconds", return_value=0), \
                    patch.object(window, "_expand_media_paths", side_effect=slow_discovery), \
                    patch.object(window, "_run_io") as run_io:
                try:
                    window._add_row(source)
                    self.wait_for_import(lambda: not window._duration_jobs)
                    window._add_paths([source])
                    self.wait_for_import(entered.is_set)
                    window._start()
                    window._clear()
                    run_io.assert_not_called()
                    self.assertEqual(window.table.rowCount(), 1)
                    self.assertFalse(window.start_button.isEnabled())
                    release.set()
                    self.wait_for_import(lambda: window._import_job is None)
                    self.assertEqual(window.table.rowCount(), 1)
                    self.assertTrue(window.start_button.isEnabled())
                finally:
                    release.set()
                    window.close()
                    self.wait_for_import(lambda: window._closing)

    def wait_for_import(self, predicate):
        # A Python sleep releases the GIL between GUI turns. A tight qWait loop
        # can starve the Python directory walker on Windows instead of measuring UI.
        deadline = time.monotonic() + 4
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.005)
        self.assertTrue(predicate(), "文件发现或分批插行未完成")
