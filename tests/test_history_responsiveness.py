"""Public history interactions must not execute storage/media startup on the GUI thread."""
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch
from unittest.mock import Mock

from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from app.history import HistoryStore
from app.history_ui import HistoryPage
from tests.test_history import result


class HistoryResponsivenessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = HistoryStore(Path(self.temp.name))
        self.record = result(Path(self.temp.name) / "sample.wav")
        self.store.save(self.record)
        self.page = None

    def tearDown(self):
        if self.page:
            self.page.shutdown()
            self.wait(lambda: not self.page.pending_actions and self.page._read_job is None)
            self.page.close()
            self.page.deleteLater()
            self.app.processEvents()

    def wait(self, predicate):
        for _ in range(500):
            self.app.processEvents()
            if predicate():
                return
            QTest.qWait(5)
        self.fail("background action did not complete")

    def test_history_navigation_does_not_initialize_native_media_backend(self):
        from app.media_player import MediaPlayer
        created = []
        original = MediaPlayer.__init__
        def track(player, *args, **kwargs):
            created.append(True)
            original(player, *args, **kwargs)
        with patch.object(MediaPlayer, "__init__", track):
            self.page = HistoryPage(self.store, lambda _: None)
            self.page.reload()
            self.wait(lambda: self.page.count.text() == "1 条记录")
            self.page.request_back()
        self.assertEqual(created, [], "opening/returning from history eagerly started media drivers")

    def test_slow_detail_read_returns_before_io_and_keeps_timer_responsive(self):
        self.page = HistoryPage(self.store, lambda _: None)
        original = self.store.get
        entered, release = threading.Event(), threading.Event()
        def slow_get(*args):
            entered.set()
            release.wait(1)
            return original(*args)
        try:
            with patch.object(self.store, "get", slow_get):
                started = time.monotonic()
                self.page.open_record(self.record.history_id)
                self.assertLess(time.monotonic() - started, .25)
                self.assertTrue(entered.wait(.5))
                pulses = []
                QTimer.singleShot(0, lambda: pulses.append(True))
                self.app.processEvents()
                self.assertEqual(pulses, [True])
                release.set()
                self.wait(lambda: self.page.current_record is not None)
            self.assertEqual(self.page.editor.toPlainText(), self.record.text)
        finally:
            release.set()

    def test_save_export_selection_and_delete_keep_ui_responsive_during_storage(self):
        self.page = HistoryPage(self.store, lambda _: None)
        self.page.open_record(self.record.history_id)
        self.wait(lambda: not self.page.pending_actions)
        self.page.editor.setPlainText("保留完整编辑")
        def delayed(method, action, verify):
            entered, release = threading.Event(), threading.Event()
            original = getattr(self.store, method)
            def slow(*args):
                entered.set()
                release.wait(1)
                return original(*args)
            try:
                with patch.object(self.store, method, slow):
                    start = time.monotonic()
                    action()
                    self.assertLess(time.monotonic() - start, .25, method)
                    self.assertTrue(entered.wait(.5), method)
                    pulse = []
                    QTimer.singleShot(0, lambda: pulse.append(True))
                    self.app.processEvents()
                    self.assertEqual(pulse, [True], method)
                    release.set()
                    self.wait(lambda: not self.page.pending_actions)
                verify()
            finally:
                release.set()
        delayed("edit", self.page.save_edit,
                lambda: self.assertEqual(self.store.get(self.record.history_id)["edited"], "保留完整编辑"))
        self.page.toggle_selection()
        delayed("all_matching_ids", self.page.select_all,
                lambda: self.assertEqual(self.page.selected, {self.record.history_id}))
        target = Path(self.temp.name) / "export.txt"
        with patch("app.history_ui.QFileDialog.getSaveFileName", return_value=(str(target), "")):
            delayed("add_export", self.page.export,
                    lambda: self.assertEqual(target.read_text(encoding="utf-8"), "保留完整编辑\n"))
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            delayed("delete", lambda: self.page.delete_records({self.record.history_id}),
                    lambda: self.assertEqual(self.store.query()[1], 0))

    def test_list_summaries_are_bounded_but_full_text_still_searchable_and_readable(self):
        text = "正文" * 500000 + "完整末尾关键词"
        self.store.edit(self.record.history_id, text)
        cards, count = self.store.query_cards("完整末尾关键词")
        self.assertEqual(count, 1)
        self.assertLessEqual(len(cards[0]["final"]), 240)
        self.assertEqual(cards[0]["segments"], [])
        self.assertEqual(self.store.get(self.record.history_id)["edited"], text)

    def test_long_document_load_yields_and_preserves_complete_text(self):
        self.page = HistoryPage(self.store, lambda _: None)
        text = ("长文稿要完整保留。\n" * 50000) + "最后一行"
        self.store.edit(self.record.history_id, text)
        self.page.open_record(self.record.history_id)
        pulse = []
        timer = QTimer()
        timer.setInterval(1)
        timer.timeout.connect(lambda: pulse.append(self.page.editor.loading))
        timer.start()
        try:
            self.wait(lambda: not self.page.pending_actions)
        finally:
            timer.stop()
        self.assertIn(True, pulse, "the UI must keep dispatching events while laying out the transcript")
        self.assertEqual(self.page.editor.toPlainText(), text)
        self.assertFalse(self.page.editor.document().isUndoAvailable())

    def test_long_subtitle_timeline_can_follow_playback_without_linear_scans(self):
        self.page = HistoryPage(self.store, lambda _: None)
        self.page.media_view = Mock()
        self.page.cues = Mock()
        self.page.cues.currentRow.return_value = -1
        self.page.media_record = {"segments": [
            {"start": i * 2., "end": i * 2. + 1., "text": str(i)} for i in range(50000)]}
        start = time.monotonic()
        for _ in range(500):
            self.page.position_changed(99998500)
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, .5)
        self.page.media_view.set_caption.assert_called_with("49999")

    def test_navigating_back_drops_late_detail_result_without_reopening_document(self):
        self.page = HistoryPage(self.store, lambda _: None)
        entered, release = threading.Event(), threading.Event()
        original = self.store.get
        def slow_get(*args):
            entered.set()
            release.wait(1)
            return original(*args)
        try:
            with patch.object(self.store, "get", slow_get):
                self.page.open_record(self.record.history_id)
                self.assertTrue(entered.wait(.5))
                self.page.show_list()
                release.set()
                self.wait(lambda: not self.page.pending_actions)
            self.assertEqual(self.page.stack.currentIndex(), 0)
            self.assertIsNone(self.page.current_record)
        finally:
            release.set()

    def test_pending_navigation_protects_old_editor_and_restores_it_after_read_failure(self):
        self.page = HistoryPage(self.store, lambda _: None)
        self.page.open_record(self.record.history_id)
        self.wait(lambda: not self.page.pending_actions)
        original_text = "切换失败后仍须完整显示。\n" * 5000 + "完整末尾"
        self.page.saved_text = original_text
        self.page.editor.load_text(original_text)
        entered, release = threading.Event(), threading.Event()
        def fail_read(*_):
            entered.set()
            release.wait(1)
            raise OSError("受控读取失败")
        try:
            with patch.object(self.store, "get", fail_read):
                self.page.open_record("another-record")
                self.assertTrue(entered.wait(.5))
                self.assertFalse(self.page.editor.isEnabled(),
                                 "the previous document must not accept edits that the read will replace")
                release.set()
                self.wait(lambda: not self.page.pending_actions)
            self.assertTrue(self.page.editor.isEnabled())
            self.assertEqual(self.page.editor.toPlainText(), original_text)
            self.assertEqual(self.page.saved_text, original_text)
            self.assertEqual(self.page.current_record["id"], self.record.history_id)
        finally:
            release.set()

    def test_rapid_navigation_reads_only_current_and_latest_destination(self):
        self.page = HistoryPage(self.store, lambda _: None)
        latest = result(Path(self.temp.name) / "latest.wav", text="最后选择的文稿")
        self.store.save(latest)
        entered, release = threading.Event(), threading.Event()
        original = self.store.get
        calls = []
        def slow_get(record_id):
            calls.append(record_id)
            if len(calls) == 1:
                entered.set()
                release.wait(1)
            return original(record_id)
        try:
            with patch.object(self.store, "get", slow_get):
                self.page.open_record(self.record.history_id)
                self.assertTrue(entered.wait(.5))
                for _ in range(10):
                    self.page.open_record(self.record.history_id)
                self.page.open_record(latest.history_id)
                release.set()
                self.wait(lambda: not self.page.pending_actions)
            self.assertEqual(calls, [self.record.history_id, latest.history_id],
                             "superseded navigation reads must not queue behind slow storage")
            self.assertEqual(self.page.editor.toPlainText(), latest.text)
        finally:
            release.set()

    def test_shutdown_drops_pending_navigation_reads_and_can_be_cancelled(self):
        self.page = HistoryPage(self.store, lambda _: None)
        entered, release = threading.Event(), threading.Event()
        original = self.store.get
        calls = []
        def slow_get(record_id):
            calls.append(record_id)
            entered.set()
            release.wait(1)
            return original(record_id)
        try:
            with patch.object(self.store, "get", slow_get):
                self.page.open_record(self.record.history_id)
                self.assertTrue(entered.wait(.5))
                for _ in range(11):
                    self.page.open_record(self.record.history_id)
                self.page.begin_shutdown()
                release.set()
                self.wait(lambda: not self.page.pending_actions)
            self.assertEqual(len(calls), 1)
            self.page.cancel_shutdown()
            self.page.open_record(self.record.history_id)
            self.wait(lambda: not self.page.pending_actions)
            self.assertEqual(self.page.editor.toPlainText(), self.record.text)
        finally:
            release.set()

    def test_cancel_shutdown_restores_complete_interrupted_document(self):
        self.page = HistoryPage(self.store, lambda _: None)
        self.page.open_record(self.record.history_id)
        self.wait(lambda: not self.page.pending_actions)
        text = "长文稿完整保留。\n" * 10000 + "最后一行"
        self.page.saved_text = text
        self.page.editor.load_text(text)
        self.assertTrue(self.page.editor.loading)
        self.page.begin_shutdown()
        self.page.cancel_shutdown()
        self.wait(lambda: not self.page.pending_actions)
        self.assertEqual(self.page.saved_text, text)
        self.assertEqual(self.page.editor.toPlainText(), text)
        self.assertTrue(self.page.editor.isEnabled())
        self.assertFalse(self.page.dirty())

    def test_save_finishing_during_shutdown_remains_saved_after_cancelling_close(self):
        self.page = HistoryPage(self.store, lambda _: None)
        self.page.open_record(self.record.history_id)
        self.wait(lambda: not self.page.pending_actions)
        self.page.editor.setPlainText("关闭期间必须保存的修改")
        entered, release = threading.Event(), threading.Event()
        original = self.store.edit
        def slow_edit(*args):
            entered.set()
            release.wait(1)
            return original(*args)
        resume = Mock()
        try:
            with patch.object(self.store, "edit", slow_edit):
                self.page.save_edit(resume)
                self.assertTrue(entered.wait(.5))
                self.page.begin_shutdown()
                release.set()
                self.wait(lambda: not self.page.pending_actions)
            self.page.cancel_shutdown()
            self.assertFalse(self.page._save_pending)
            self.assertFalse(self.page.dirty())
            self.assertEqual(self.store.get(self.record.history_id)["edited"], "关闭期间必须保存的修改")
            resume.assert_not_called()
        finally:
            release.set()

    def test_relink_finishing_after_leaving_media_does_not_reopen_old_destination(self):
        self.page = HistoryPage(self.store, lambda _: None)
        entered, release = threading.Event(), threading.Event()
        original = self.store.relink
        def slow_relink(*args):
            entered.set()
            release.wait(1)
            return original(*args)
        target = Path(self.temp.name) / "relocated.wav"
        target.write_bytes(b"")
        try:
            with patch.object(self.store, "relink", slow_relink), \
                 patch.object(QMessageBox, "question", return_value=QMessageBox.Yes), \
                 patch("app.history_ui.QFileDialog.getOpenFileName", return_value=(str(target), "")):
                self.page.open_media(self.record.history_id)
                self.wait(entered.is_set)
                self.page.show_list()
                with patch.object(self.page, "open_media") as reopen:
                    release.set()
                    self.wait(lambda: not self.page.pending_actions)
                    reopen.assert_not_called()
            self.assertEqual(self.page.stack.currentIndex(), 0)
            self.assertEqual(Path(self.store.get(self.record.history_id)["source"]), target.resolve())
        finally:
            release.set()

    def test_cancel_close_restores_media_position_state_and_complete_subtitles(self):
        from PySide6.QtMultimedia import QMediaPlayer
        self.record.source_path.write_bytes(b"")
        media = result(self.record.source_path, segments=[
            {"start": float(i), "end": float(i + 1), "text": f"字幕 {i}"} for i in range(350)])
        self.store.save(media)
        self.page = HistoryPage(self.store, lambda _: None)
        self.page._build_media()
        view = self.page.media_view
        def stop():
            view.ready = False
            view.source_key = None
        for was_playing in (False, True):
            with self.subTest(was_playing=was_playing):
                self.page.media_record = self.store.get(media.history_id)
                self.page.stack.setCurrentIndex(2)
                self.page.cues.clear()
                self.page.cues.addItem("仅完成第一批")
                view.source_key = "fixture-position"
                state = QMediaPlayer.PlayingState if was_playing else QMediaPlayer.PausedState
                with patch.object(view, "stop", side_effect=stop), \
                     patch.object(view, "open") as reopen, \
                     patch.object(self.page.player, "position", return_value=123000), \
                     patch.object(self.page.player, "playbackState", return_value=state), \
                     patch.object(self.page.player, "setPosition") as seek, \
                     patch.object(self.page.player, "pause") as pause:
                    self.assertTrue(self.page.leave())  # MainWindow asks to leave before shutdown.
                    self.page.begin_shutdown()
                    self.page.cancel_shutdown()
                    self.wait(lambda: not self.page.pending_actions)
                    reopen.assert_called_once()
                    self.wait(lambda: self.page.cues.count() == len(media.segments))
                    seek.assert_called_with(123000)
                    self.assertEqual(view.resume_position, 123000)
                    self.assertEqual(pause.call_count, 0 if was_playing else 1)

    def test_cancel_close_retries_a_cancelled_thumbnail_after_its_worker_returns(self):
        from app.history_ui import ThumbnailJob
        self.store.save(result(Path(self.temp.name) / "video.mp4"))
        entered, release = threading.Event(), threading.Event()
        calls = []
        def thumbnail(job):
            calls.append(job.record["id"])
            if len(calls) == 1:
                entered.set()
                release.wait(2)
            job.signals.done.emit(job.record["id"], "")
        try:
            with patch.object(ThumbnailJob, "run", thumbnail):
                self.page = HistoryPage(self.store, lambda _: None)
                self.page.reload()
                self.wait(entered.is_set)
                self.page.begin_shutdown()
                self.page.cancel_shutdown()
                self.wait(lambda: self.page._read_job is None)
                release.set()
                self.wait(lambda: len(calls) >= 2)
                self.wait(lambda: not self.page.pending_actions)
            self.assertEqual(len(calls), 2)
        finally:
            release.set()
