from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMessageBox

from app.history import HistoryStore
from app.transcriber import TranscribeResult, export_history_document


def result(source, **changes):
    return replace(TranscribeResult(
        files=[source.with_suffix(".txt")], text="处理后的文稿" + "内容" * 200 + "全文搜索末尾",
        original_text="原始口语", source_path=source, mode="中文精确", model="Qwen3-ASR-1.7B",
        language="中文", duration=10,
        segments=[{"start": 1.0, "end": 2.0, "text": "第一条"}, {"start": 4.0, "end": 5.0, "text": "第二条"}]), **changes)


class HistoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = HistoryStore(self.root / "history")
        self.result = result(self.root / "视频.mp4")
        self.store.save(self.result)

    def test_restart_and_full_text_search_beyond_card_preview(self):
        records, total = HistoryStore(self.store.root).query("全文搜索末尾")
        self.assertEqual(total, 1)
        self.assertEqual(records[0]["segments"], self.result.segments)
        self.assertEqual(self.store.query("不存在的内容")[1], 0)

    def test_duplicate_event_does_not_duplicate_or_reset_edit(self):
        self.store.edit(self.result.history_id, "编辑稿")
        self.store.save(self.result)
        self.assertEqual(self.store.query()[1], 1)
        self.assertEqual(self.store.get(self.result.history_id)["edited"], "编辑稿")
        self.store.save(result(self.result.source_path))
        self.assertEqual(self.store.query()[1], 2)

    def test_history_read_does_not_wait_for_an_existing_write_transaction(self):
        import sqlite3
        writer = sqlite3.connect(self.store.database)
        try:
            writer.execute("BEGIN IMMEDIATE")
            records, total = self.store.query()
            self.assertEqual(total, 1)
            self.assertEqual(records[0]["id"], self.result.history_id)
        finally:
            writer.rollback()
            writer.close()

    def test_edit_preserves_original_segments_and_is_searchable(self):
        before = self.store.get(self.result.history_id)
        self.store.edit(self.result.history_id, "编辑后独有关键词")
        after = self.store.query("独有关键词")[0][0]
        for key in ("original", "final", "segments", "completed"):
            self.assertEqual(before[key], after[key])

    def test_time_filter_and_pagination(self):
        with self.store.connection() as connection:
            connection.execute("UPDATE records SET completed='2000-01-01T12:00:00+08:00'")
        self.store.save(result(self.result.source_path))
        self.assertEqual(self.store.query(period="今天")[1], 1)
        records, total = self.store.query(limit=1)
        self.assertEqual((len(records), total), (1, 2))
        self.assertEqual(len(self.store.all_matching_ids()), 2)

    def test_delete_never_touches_media_exports_or_model_cache(self):
        self.result.source_path.write_bytes(b"source")
        self.result.files[0].write_text("export", encoding="utf-8")
        model = self.root / "models/model.bin"
        model.parent.mkdir()
        model.write_bytes(b"model")
        self.store.delete({self.result.history_id})
        self.assertEqual(self.result.source_path.read_bytes(), b"source")
        self.assertEqual(self.result.files[0].read_text(encoding="utf-8"), "export")
        self.assertEqual(model.read_bytes(), b"model")
        self.assertEqual(self.store.query()[1], 0)

    def test_missing_external_files_do_not_invalidate_snapshot(self):
        self.assertFalse(self.store.get(self.result.history_id)["invalid"])
        self.assertEqual(self.store.invalid_ids(), set())

    def test_corrupt_document_is_explicit_and_cleanable(self):
        with self.store.connection() as connection:
            connection.execute("UPDATE records SET original='', final=''")
        self.assertEqual(self.store.invalid_ids(), {self.result.history_id})
        self.store.delete(self.store.invalid_ids())
        self.assertEqual(self.store.query()[1], 0)

    def test_corrupt_timing_does_not_make_readable_text_cleanable(self):
        with self.store.connection() as connection:
            connection.execute("UPDATE records SET segments='invalid json'")
        record = self.store.get(self.result.history_id)
        self.assertFalse(record["invalid"])
        self.assertTrue(record["warnings"])
        self.assertEqual(record["segments"], [])
        self.assertEqual(self.store.invalid_ids(), set())

    def test_relink_and_export_location_do_not_change_document(self):
        source = self.root / "new.wav"
        source.write_bytes(b"source")
        self.store.relink(self.result.history_id, source)
        export = self.root / "new.md"
        self.store.add_export(self.result.history_id, export)
        self.assertEqual(self.store.get(self.result.history_id)["source"], str(source.resolve()))
        self.assertIn(str(export.resolve()), self.store.get(self.result.history_id)["outputs"])

    def test_four_export_formats_keep_original_srt_timeline(self):
        for extension in (".txt", ".md", ".srt", ".docx"):
            target = self.root / ("edited" + extension)
            export_history_document(target, self.result.source_path, "编辑稿", self.result.segments)
            self.assertGreater(target.stat().st_size, 0)
        srt = (self.root / "edited.srt").read_text(encoding="utf-8")
        self.assertIn("00:00:01,000 --> 00:00:02,000", srt)
        self.assertIn("第二条", srt)
        self.assertNotIn("编辑稿", srt)
        self.assertEqual((self.root / "edited.txt").read_text(encoding="utf-8"), "编辑稿\n")
        with self.assertRaises(ValueError):
            export_history_document(self.root / "bad.srt", self.result.source_path, "没有时间的文字", [])

    def test_failed_export_keeps_existing_file_and_cleans_staging(self):
        target = self.root / "existing.docx"
        target.write_bytes(b"original file")
        def fail(path, *args):
            path.write_bytes(b"partial")
            raise OSError("disk unavailable")
        with patch("app.transcriber._write_docx", side_effect=fail), self.assertRaises(OSError):
            export_history_document(target, self.result.source_path, "new", self.result.segments)
        self.assertEqual(target.read_bytes(), b"original file")
        self.assertEqual(list(self.root.glob(".nf-history-*")), [])

    def test_transcription_completion_contains_a_reexportable_snapshot(self):
        from app.transcriber import TranscribeOptions, transcribe_file
        from unittest.mock import Mock
        session = Mock()
        session.transcribe_audio.return_value = self.result.segments
        options = TranscribeOptions(self.root / "output", "中文精确", "中文", "CPU 稳定", True, False, True, False, False, None)
        with patch("app.transcriber._extract_audio"), patch("app.transcriber.probe_duration_seconds", return_value=10):
            completed = transcribe_file(self.result.source_path, options, lambda info: None, session=session)
        self.assertEqual(completed.segments, self.result.segments)
        self.assertEqual(completed.source_path, self.result.source_path.resolve())
        self.assertEqual((completed.mode, completed.model, completed.language, completed.duration), ("中文精确", "Qwen3-ASR-1.7B", "中文", 10))
        self.store.save(completed)
        self.assertEqual(self.store.get(completed.history_id)["original"], completed.original_text)


class HistoryUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from app.main import MainWindow
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = QSettings(str(self.root / "settings.ini"), QSettings.IniFormat)
        self.window = MainWindow(self.settings)
        self.addCleanup(self.close_and_drain)
        self.window.show()
        with patch("app.main.probe_duration_seconds", return_value=0):
            self.window._add_row(self.root / "音频.wav")
        self.result = result(self.root / "音频.wav")
        self.window.active_rows = {0}
        self.window._on_item_finished(0, self.result)
        self.wait_for_history_save()
        self.app.processEvents()

    def wait_for_history_save(self):
        from PySide6.QtTest import QTest
        for _ in range(600):
            self.app.processEvents()
            if not self.window._history_save_jobs:
                return
            QTest.qWait(5)
        self.fail("history save did not complete")

    def close_and_drain(self):
        from PySide6.QtTest import QTest
        self.window.close()
        for _ in range(600):
            self.app.processEvents()
            page = self.window.history_page
            if not self.window._history_save_jobs and (page is None or page._read_job is None):
                return
            QTest.qWait(5)
        self.fail("background history work did not stop")

    def test_navigation_keeps_queue_worker_and_progress(self):
        worker = object()
        self.window.worker = worker
        self.window.history_button.click()
        self.app.processEvents()
        self.assertIs(self.window.right_stack.currentWidget(), self.window.history_page)
        self.assertEqual(self.window.table.rowCount(), 1)
        self.assertIs(self.window.worker, worker)
        self.assertEqual(self.window.history_page.count.text(), "1 条记录")
        self.window.history_page.request_back()
        self.assertIs(self.window.right_stack.currentWidget(), self.window.workbench_page)
        self.assertIs(self.window.worker, worker)
        self.window.worker = None

    def test_completed_queue_row_disappears_only_after_history_saved(self):
        self.assertTrue(self.window.table.isRowHidden(0))
        self.assertEqual(self.window.history_store.query()[1], 1)
        with patch("app.main.probe_duration_seconds", return_value=0):
            self.window._add_row(self.root / "next.wav")
        self.window.active_rows = {0, 1}
        self.window._on_item_failed(1, "受控失败")
        self.assertFalse(self.window.table.isRowHidden(1))
        self.window._on_all_done()
        self.assertEqual(self.window.pending_completion_summary["success"], 1)
        self.assertEqual(self.window.pending_completion_summary["failed"], 1)
        self.window.pending_completion_summary = None
        self.window._cleanup_worker()
        self.assertEqual(self.window.table.rowCount(), 1)
        self.assertEqual(self.window.table.item(0, 3).text(), "next.wav")
        self.assertEqual(self.window.table.item(0, 2).text(), "失败")
        self.assertEqual(self.window.table.item(0, 0).text(), "1")
        from PySide6.QtWidgets import QPushButton
        with patch.object(self.window, "_locate_row_file") as locate:
            self.window.table.cellWidget(0, 11).findChild(QPushButton).click()
            locate.assert_called_once_with(0)

    def test_editor_save_unsaved_cancel_and_original_protection(self):
        self.window._show_history()
        page = self.window.history_page
        page.open_record(self.result.history_id)
        page.editor.setPlainText("新的编辑稿")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Cancel):
            self.assertFalse(page.leave())
        page.save_edit()
        stored = self.window.history_store.get(self.result.history_id)
        self.assertEqual(stored["edited"], "新的编辑稿")
        self.assertEqual(stored["original"], "原始口语")
        self.assertTrue(page.leave())

    def test_subtitles_only_show_inside_their_time_ranges(self):
        self.window._show_history()
        page = self.window.history_page
        page.media_record = self.window.history_store.get(self.result.history_id)
        page.cues.addItems(["第一条", "第二条"])
        for position, expected in ((0, ""), (1500, "第一条"), (2500, ""), (4500, "第二条"), (6000, "")):
            page.position_changed(position)
            self.assertEqual(page.subtitle.text(), expected)

    def test_document_reading_layout_preserves_text_and_wraps_after_resize(self):
        from PySide6.QtTest import QTest
        from app.history_ui import DocumentEditor
        editor = DocumentEditor()
        self.addCleanup(editor.close)
        text = ("字间距，不应被强行拉伸。较长的转写文字需要清楚的行距和留白。English 2026 M100 " * 60 + "\n") * 4 + "测" * 3000 + "\n" + "M100" * 500
        editor.setPlainText(text)
        editor.show()
        for width in (1450, 750, 751, 752, 1450):
            editor.resize(width, 700)
            QTest.qWait(50)
            self.assertEqual(editor.toPlainText(), text)
            self.assertFalse(editor.document().isModified())
            self.assertFalse(editor.document().isUndoAvailable())
            self.assertEqual(editor.lineWrapColumnOrWidth(), editor.viewport().width())
            block = editor.document().begin()
            while block.isValid():
                lines = block.layout()
                for index in range(lines.lineCount()):
                    line = lines.lineAt(index)
                    edge = lines.position().x() + line.x() + line.naturalTextWidth()
                    self.assertLessEqual(edge, editor.viewport().width() - 10)
                block = block.next()
        editor.insertPlainText("编辑")
        editor.undo()
        self.assertEqual(editor.toPlainText(), text)

    def test_single_click_subtitle_seeks_video_and_updates_progress(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        self.window._show_history()
        page = self.window.history_page
        page.media_record = self.window.history_store.get(self.result.history_id)
        page.stack.setCurrentIndex(2)
        page.seek.setRange(0, 10000)
        for cue in page.media_record["segments"]:
            page.cues.addItem(cue["text"])
            page.cues.item(page.cues.count() - 1).setData(Qt.UserRole, cue["start"])
        self.app.processEvents()
        second = page.cues.item(1)
        with patch.object(page.player, "setPosition") as seek, patch.object(page.player, "play") as play:
            QTest.mouseClick(page.cues.viewport(), Qt.LeftButton, pos=page.cues.visualItemRect(second).center())
            seek.assert_called_once_with(4000)
            self.assertEqual(page.seek.value(), 4000)
            self.assertEqual(page.subtitle.text(), "第二条")
            self.assertTrue(page.media_view.controls.isVisible())
            play.assert_not_called()

    def test_reexport_updates_locations_and_does_not_overwrite_original(self):
        self.window._show_history()
        page = self.window.history_page
        page.open_record(self.result.history_id)
        page.editor.setPlainText("用于导出的编辑稿")
        target = self.root / "exported.txt"
        with patch("app.history_ui.QFileDialog.getSaveFileName", return_value=(str(target), "")):
            page.export()
        self.assertEqual(target.read_text(encoding="utf-8"), "用于导出的编辑稿\n")
        self.assertIn(str(target.resolve()), self.window.history_store.get(self.result.history_id)["outputs"])
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Discard):
            page.leave()
        page.editor.setPlainText(page.saved_text)

    def test_filter_change_clears_hidden_selection(self):
        self.window._show_history()
        page = self.window.history_page
        page.toggle_selection()
        page.select_all()
        self.assertEqual(page.selected, {self.result.history_id})
        page.search.setText("没有匹配")
        page.filter_changed()
        self.assertEqual(page.selected, set())
        self.assertFalse(page.delete_button.isEnabled())

    def test_history_save_failure_keeps_completion_and_can_retry(self):
        second = result(self.root / "another.wav")
        with patch.object(self.window.history_store, "save", side_effect=PermissionError("read only")):
            self.window._on_item_finished(0, second)
            self.wait_for_history_save()
        self.assertEqual(self.window.table.item(0, 2).text(), "完成")
        self.assertFalse(self.window.table.isRowHidden(0))
        self.assertIn(second.history_id, self.window.pending_history_results)
        self.window.active_rows.clear()
        self.window._show_history()
        self.wait_for_history_save()
        self.assertEqual(self.window.pending_history_results, {})
        self.assertEqual(self.window.table.rowCount(), 0)
        self.assertEqual(self.window.history_store.get(second.history_id)["final"], second.text)

    def test_history_more_is_a_transparent_circle_with_colored_icon(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QColor
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QPushButton
        self.window._show_history()
        page = self.window.history_page
        self.app.processEvents()
        QTest.mouseMove(page, QPoint(1, 1))
        self.app.processEvents()
        more = page.cards.findChildren(QPushButton, "HistoryMore")[0]
        self.assertEqual((more.width(), more.height()), (36, 36))
        self.assertTrue(more.icon().isNull() is False)
        self.assertEqual(more.text(), "")
        card = more.parentWidget()
        surface = card.grab().toImage()
        self.assertEqual(surface.pixelColor(more.x()+18, more.y()+4), QColor("#ffffff"))
        QTest.mouseMove(more, QPoint(18, 18))
        self.app.processEvents()
        surface = card.grab().toImage()
        self.assertEqual(surface.pixelColor(more.x()+2, more.y()+2), QColor("#ffffff"))
        self.assertEqual(surface.pixelColor(more.x()+18, more.y()+4), QColor("#e5e7eb"))
        self.assertEqual(page.select_button.palette().buttonText().color(), QColor("#b34646"))

    def test_batch_delete_reuses_timeline_circle_without_extra_checkbox(self):
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QPushButton, QCheckBox
        self.window._show_history()
        page = self.window.history_page
        self.app.processEvents()
        page.toggle_selection()
        QTest.qWait(20)
        self.assertFalse(page.cards.findChildren(QCheckBox))
        circle = page.cards.findChild(QPushButton, "HistorySelection")
        self.assertIsNotNone(circle)
        self.assertFalse(circle.isChecked())
        circle.click()
        self.assertEqual(page.selected, {self.result.history_id})
        self.assertTrue(page.delete_button.isEnabled())
        circle.click()
        self.assertFalse(page.selected)
        self.assertFalse(page.delete_button.isEnabled())
        with patch.object(page, "open_media") as play:
            page.cards.findChild(QPushButton, "HistoryThumb").click()
            self.assertTrue(circle.isChecked())
            play.assert_not_called()
        page.select_all()
        QTest.qWait(20)
        self.assertTrue(page.cards.findChild(QPushButton, "HistorySelection").isChecked())
        page.toggle_selection()
        self.assertFalse(page.selected)

    def test_document_header_keeps_one_title_and_paths_in_details(self):
        self.window._show_history()
        page = self.window.history_page
        name = "长文件名测试" * 30 + ".mp4"
        with self.window.history_store.connection() as connection:
            connection.execute("UPDATE records SET name=? WHERE id=?", (name, self.result.history_id))
        page.open_record(self.result.history_id)
        self.window.resize(1100, 750)
        self.app.processEvents()
        self.assertEqual(page.detail_title.toolTip(), name)
        self.assertNotEqual(page.detail_title.text(), name)
        self.assertNotIn("\n", page.detail_title.text())
        self.assertNotIn(name, page.detail_meta.full_text)
        self.assertNotIn(str(self.root), page.detail_meta.full_text)
        self.assertNotIn(page.current_record["model"], page.detail_meta.full_text)
        self.assertIn("完成", page.detail_meta.full_text)
        self.assertIn(page.current_record["source"], page.metadata(page.current_record))
        self.assertFalse(page.detail_feedback.isVisible())
        page.editor.setPlainText("保存后的文稿")
        page.save_edit()
        self.assertEqual(page.detail_feedback.text(), "编辑已保存")
        self.assertNotIn(str(self.root), page.detail_meta.full_text)

    def test_selected_subtitle_surface_is_orange(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QColor
        self.window._show_history()
        page = self.window.history_page
        page.stack.setCurrentIndex(2)
        page.cues.addItems(["选中字幕", "普通字幕"])
        page.cues.setCurrentRow(0)
        page.cues.setFocus()
        self.app.processEvents()
        image = page.cues.grab().toImage()
        offset = page.cues.viewport().mapTo(page.cues, QPoint(0, 0))
        selected = page.cues.visualItemRect(page.cues.item(0)).translated(offset)
        ordinary = page.cues.visualItemRect(page.cues.item(1)).translated(offset)
        self.assertEqual(image.pixelColor(selected.right()-10, selected.center().y()), QColor("#fff0df"))
        self.assertEqual(image.pixelColor(ordinary.right()-10, ordinary.center().y()), QColor("#ffffff"))

    def test_active_subtitle_centers_and_manual_scroll_temporarily_holds_position(self):
        from PySide6.QtWidgets import QAbstractSlider
        from app.history_ui import SubtitleList
        cues = SubtitleList()
        self.addCleanup(cues.close)
        cues.resize(500, 400)
        cues.addItems([f"Subtitle {i}" for i in range(100)])
        cues.show()
        self.app.processEvents()
        cues.setCurrentRow(50)
        self.app.processEvents()
        self.assertLess(abs(cues.visualItemRect(cues.currentItem()).center().y() - cues.viewport().rect().center().y()), 3)
        bar = cues.verticalScrollBar()
        bar.triggerAction(QAbstractSlider.SliderPageStepSub)
        self.app.processEvents()
        position = bar.value()
        cues.setCurrentRow(55)
        self.app.processEvents()
        self.assertEqual(bar.value(), position)
        cues.resume_follow.timeout.emit()
        self.app.processEvents()
        self.assertLess(abs(cues.visualItemRect(cues.currentItem()).center().y() - cues.viewport().rect().center().y()), 3)

    def test_slow_history_query_leaves_navigation_and_ui_timer_responsive(self):
        import threading
        from PySide6.QtCore import QTimer
        from PySide6.QtTest import QTest
        entered, release = threading.Event(), threading.Event()
        original = self.window.history_store.query
        def slow_query(*args, **kwargs):
            entered.set()
            release.wait(3)
            return original(*args, **kwargs)
        try:
            with patch.object(self.window.history_store, "query", side_effect=slow_query):
                self.window._show_history()
                self.assertTrue(entered.wait(1))
                pulses = []
                QTimer.singleShot(0, lambda: pulses.append(True))
                self.app.processEvents()
                self.assertEqual(pulses, [True])
                self.window._show_workbench()
                self.assertIs(self.window.right_stack.currentWidget(), self.window.workbench_page)
                release.set()
                for _ in range(200):
                    self.app.processEvents()
                    if self.window.history_page._read_job is None:
                        break
                    QTest.qWait(5)
                self.assertEqual(self.window.history_page.count.text(), "1 条记录")
        finally:
            release.set()
