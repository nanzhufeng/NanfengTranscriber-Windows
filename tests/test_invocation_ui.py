import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from PySide6.QtCore import QTimer, QSettings, Qt
from PySide6.QtWidgets import QApplication, QLabel
from PySide6.QtTest import QTest
from app.invocation_ui import InvocationHistoryDialog, InvocationEntry
from app.invocations import InvocationStore


class InvocationUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait_for(self, predicate):
        until = time.monotonic() + 3
        while not predicate() and time.monotonic() < until:
            QTest.qWait(10)
        self.assertTrue(predicate())

    def test_empty_state_and_read_failure_are_distinct(self):
        with TemporaryDirectory() as tmp:
            dialog = InvocationHistoryDialog(Path(tmp))
            dialog.show()
            self.wait_for(lambda: dialog._rows == [])
            text = " ".join(label.text() for label in dialog.findChildren(QLabel))
            self.assertIn("尚无本地调用记录", text)
            self.assertIn("当前未发出任何真实云端转写请求。", text)
            dialog.close()
            with patch.object(InvocationStore, "groups", side_effect=OSError("private details")):
                failed = InvocationHistoryDialog(Path(tmp))
                failed.show()
                self.wait_for(lambda: failed._rows is None)
                text = " ".join(label.text() for label in failed.findChildren(QLabel))
                self.assertIn("调用记录读取失败", text)
                self.assertNotIn("private details", text)
                failed.close()

    def test_slow_query_keeps_gui_live_and_close_during_query_is_safe(self):
        with TemporaryDirectory() as tmp:
            entered, release = threading.Event(), threading.Event()
            def slow(_):
                entered.set()
                release.wait(3)
                return []
            ticks = []
            timer = QTimer()
            timer.timeout.connect(lambda: ticks.append(1))
            timer.start(10)
            dialog = InvocationHistoryDialog(Path(tmp))
            try:
                with patch.object(InvocationStore, "groups", slow):
                    dialog.show()
                    self.wait_for(entered.is_set)
                    QTest.qWait(90)
                    self.assertGreater(len(ticks), 2)
                    dialog.close()
                    dialog.deleteLater()
                    self.app.processEvents()
                    release.set()
                    QTest.qWait(100)
            finally:
                release.set()
                timer.stop()

    def test_ten_thousand_files_use_visible_row_painting_and_keep_gui_live(self):
        rows = [
            dict(group_key=str(index), source_display_name=f"完整文件-{index}.wav",
                 model_id="paraformer-v2", status="SUCCEEDED", completed_at_millis=1700000000000 + index,
                 duration_millis=100, request_count=1, input_tokens=None, output_tokens=None,
                 total_tokens=None, estimated_cost_micros=None, cost_currency_code=None, error_code=None)
            for index in range(10000)
        ]
        with TemporaryDirectory() as tmp:
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
            dialog = InvocationHistoryDialog(Path(tmp))
            try:
                with patch.object(InvocationStore, "groups", return_value=rows):
                    dialog.show()
                    self.wait_for(lambda: dialog._rows == rows)
                    QTest.qWait(200)
                    self.assertEqual(dialog.model.rowCount(), 10000)
                    self.assertLess(len(dialog.findChildren(QLabel)), 10)
                    self.assertGreater(len(gaps), 3)
                    # The last file remains available without allocating one widget per row.
                    final = dialog.model.index(9999, 0)
                    self.wait_for(lambda: dialog.scroll.visualRect(final).height() > 0)
                    dialog.scroll.scrollTo(final)
                    QTest.qWait(100)
                    self.assertIn("完整文件-9999.wav", dialog.model.data(final, Qt.AccessibleTextRole))
                    self.assertTrue(dialog.scroll.visualRect(final).intersects(dialog.scroll.viewport().rect()))
                    self.assertLess(max(gaps), .15, f"大列表GUI心跳阻塞 {max(gaps):.3f}s")
            finally:
                timer.stop()
                dialog.close()

    def test_virtual_rows_keep_mobile_fields_and_refresh_keeps_scroll_position(self):
        row = dict(group_key="original", source_display_name="完整原文件.wav", model_id="paraformer-v2",
                   status="FAILED", completed_at_millis=1700000000000, duration_millis=2100,
                   request_count=2, input_tokens=None, output_tokens=12, total_tokens=None,
                   estimated_cost_micros=4800, cost_currency_code="CNY", error_code="FILETRANS_HTTP_401")
        rows = [dict(row, group_key=str(index)) for index in range(100)]
        with TemporaryDirectory() as tmp:
            dialog = InvocationHistoryDialog(Path(tmp))
            try:
                with patch.object(InvocationStore, "groups", return_value=rows):
                    dialog.show()
                    self.wait_for(lambda: dialog._rows == rows)
                    QTest.qWait(100)
                    text = dialog.model.data(dialog.model.index(0, 0), Qt.AccessibleTextRole)
                    for expected in ("失败", "完整原文件.wav", "百炼官方 · paraformer-v2",
                                     "后台分段 2 个", "耗时 2.10 秒", "输入 Token：未提供",
                                     "输出 Token：12", "费用估算：≈ ¥0.0048（估算）",
                                     "原因：鉴权、权限或地域不匹配"):
                        self.assertIn(expected, text)
                    bar = dialog.scroll.verticalScrollBar()
                    bar.setValue(500)
                    before = bar.value()
                    dialog.loaded([dict(row, group_key="new")] + rows)
                    QTest.qWait(100)
                    self.assertEqual(bar.value(), before)
            finally:
                dialog.close()

    def test_settings_entry_is_below_key_and_retry_retains_file_identity(self):
        from app.main import MainWindow, AppSettingsDialog, COL_OUTPUT, INVOCATION_TASK_ID_ROLE
        with TemporaryDirectory() as tmp:
            window = MainWindow(QSettings(str(Path(tmp)/"prefs.ini"), QSettings.IniFormat))
            # Open through the real settings action to cover normal wiring.
            captured = []
            def inspect(dialog):
                entry = dialog.findChild(InvocationEntry)
                self.assertIsNotNone(entry)
                captured.append(entry)
                return 0
            with patch.object(AppSettingsDialog, "exec", inspect):
                window._open_settings()
            self.assertEqual(len(captured), 1)
            with patch("app.main.probe_duration_seconds", return_value=1):
                window._add_row(Path(tmp)/"source.wav")
            identity = window.table.item(0, COL_OUTPUT).data(INVOCATION_TASK_ID_ROLE)
            self.assertTrue(identity)
            window._update_output_cell(0, "重试")
            self.assertEqual(window.table.item(0, COL_OUTPUT).data(INVOCATION_TASK_ID_ROLE), identity)
            window.close()
