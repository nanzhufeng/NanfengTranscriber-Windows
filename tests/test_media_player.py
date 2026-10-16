from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt, QPoint, QSettings
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout

from app.media_player import MediaPlayer


class MediaPlayerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.host = QWidget()
        layout = QVBoxLayout(self.host)
        self.view = MediaPlayer(Path(self.temp.name) / "playback.ini", self.host)
        layout.addWidget(self.view)
        self.host.resize(900, 600)
        self.host.show()
        self.app.processEvents()
        self.addCleanup(lambda: self.view.state_writer.future.result(timeout=10) if self.view.state_writer.future else None)
        self.addCleanup(self.host.close)
        self.addCleanup(self.view.stop)

    def test_chrome_and_captions_stay_inside_canvas_after_resize(self):
        for width in (900, 460):
            self.host.resize(width, 600)
            self.app.processEvents()
            self.view.set_caption("当前字幕")
            for item in (self.view.controls, self.view.top, self.view.subtitle):
                self.assertTrue(self.view.rect().contains(item.geometry()))
            self.assertEqual(self.view.video.size().toSize(), self.view.view.viewport().size())
            self.assertEqual(self.view.play_button.width(), 36)
            self.assertTrue(self.view.controls.rect().contains(self.view.fullscreen_button.geometry()))

    def test_caption_position_stays_fixed_when_controls_hide(self):
        self.view.set_caption("当前字幕")
        self.view.show_controls(True)
        visible_geometry = self.view.subtitle.geometry()
        self.view.show_controls(False)
        self.assertEqual(self.view.subtitle.geometry(), visible_geometry)
        self.view.show_controls(True)
        self.assertEqual(self.view.subtitle.geometry(), visible_geometry)

    def test_scrubbing_coalesces_decoder_requests_and_releases_at_exact_target(self):
        self.view.seek.setRange(0, 100000)
        with patch.object(self.view.player, "setPosition") as seek:
            for position in range(0, 90000, 1000):
                self.view.seek.setValue(position)
                self.view.seek.sliderMoved.emit(position)
            seek.assert_not_called()
            self.view.seek.sliderReleased.emit()
            seek.assert_called_once_with(89000)
            self.assertFalse(self.view.scrub_timer.isActive())

    def test_repeated_same_caption_does_not_repeat_layout(self):
        self.view.set_caption("同一句字幕")
        with patch.object(self.view.subtitle, "heightForWidth", wraps=self.view.subtitle.heightForWidth) as measure:
            for _ in range(100):
                self.view.set_caption("同一句字幕")
            measure.assert_not_called()

    def test_slow_bookmark_disk_write_does_not_block_ui_and_keeps_latest_seek(self):
        import threading
        from PySide6.QtCore import QTimer
        entered, release = threading.Event(), threading.Event()
        original_sync = QSettings.sync

        def slow_sync(settings):
            entered.set()
            release.wait(5)
            original_sync(settings)

        self.view.source_key = "positions/slow-disk"
        self.view.ready = True
        try:
            with patch.object(QSettings, "sync", slow_sync), \
                 patch.object(self.view.player, "position", return_value=0), \
                 patch.object(self.view.player, "duration", return_value=100000), \
                 patch.object(self.view.player, "setPosition"):
                self.view.seek_by(10000)
                self.assertTrue(entered.wait(2))
                self.view.seek_by(20000)
                self.view.seek_by(30000)
                pulses = []
                QTimer.singleShot(0, lambda: pulses.append(True))
                self.app.processEvents()
                self.assertEqual(pulses, [True])
                release.set()
                self.view.state_writer.future.result(timeout=5)
            reread = QSettings(self.view.settings.fileName(), QSettings.IniFormat)
            self.assertEqual(int(reread.value("positions/slow-disk")), 30000)
        finally:
            release.set()
            self.view.ready = False

    def test_seek_buttons_bound_positions_to_real_duration(self):
        with patch.object(self.view.player, "position", return_value=3000), \
             patch.object(self.view.player, "duration", return_value=12000), \
             patch.object(self.view.player, "setPosition") as seek:
            self.view.seek_by(-10000)
            seek.assert_called_with(0)
            self.view.seek_by(10000)
            seek.assert_called_with(12000)

    def test_progress_click_and_drag_seek_to_pointer(self):
        self.view.seek.setRange(0, 100000)
        self.app.processEvents()
        slider = self.view.seek
        with patch.object(self.view.player, "setPosition") as seek:
            point = QPoint(slider.width() * 3 // 4, slider.height() // 2)
            QTest.mouseClick(slider, Qt.LeftButton, pos=point)
            self.assertTrue(73000 < seek.call_args.args[0] < 78000)
            QTest.mousePress(slider, Qt.LeftButton, pos=point)
            QTest.mouseMove(slider, QPoint(slider.width() // 4, point.y()))
            QTest.mouseRelease(slider, Qt.LeftButton, pos=QPoint(slider.width() // 4, point.y()))
            self.assertTrue(22000 < seek.call_args.args[0] < 27000)
            self.assertFalse(slider.isSliderDown())

    def test_double_click_seeks_once_and_continued_click_accumulates(self):
        viewport = self.view.view.viewport()
        point = QPoint(viewport.width() - 30, viewport.height() // 2)
        with patch.object(self.view.player, "setPosition") as seek:
            QTest.mouseDClick(viewport, Qt.LeftButton, pos=point)
            QTest.mouseRelease(viewport, Qt.LeftButton, pos=point)
            self.assertEqual(seek.call_count, 1)
            self.assertEqual(self.view.feedback.text(), "快进 10 秒")
            QTest.mouseClick(viewport, Qt.LeftButton, pos=point)
            self.assertEqual(seek.call_count, 2)
            self.assertEqual(self.view.feedback.text(), "快进 20 秒")
            self.assertFalse(self.view.tap_timer.isActive())

    def test_double_click_three_regions_resize_and_center_breaks_seek_chain(self):
        viewport = self.view.view.viewport()
        for width in (900, 460):
            self.host.resize(width, 600)
            self.app.processEvents()
            with patch.object(self.view.player, "setPosition") as seek, \
                 patch.object(self.view.player, "play") as play, \
                 patch.object(self.view.player, "pause") as pause:
                # Near either edge of the wider center, double-click toggles playback.
                for fraction in (0.31, 0.5, 0.69):
                    point = QPoint(round(viewport.width() * fraction), viewport.height() // 2)
                    QTest.mouseDClick(viewport, Qt.LeftButton, pos=point)
                    QTest.mouseRelease(viewport, Qt.LeftButton, pos=point)
                self.assertEqual(play.call_count + pause.call_count, 3)
                seek.assert_not_called()
                for fraction, label in ((0.29, "快退 10 秒"), (0.71, "快进 10 秒")):
                    point = QPoint(round(viewport.width() * fraction), viewport.height() // 2)
                    QTest.mouseDClick(viewport, Qt.LeftButton, pos=point)
                    QTest.mouseRelease(viewport, Qt.LeftButton, pos=point)
                    self.assertEqual(self.view.feedback.text(), label)
                self.assertEqual(seek.call_count, 2)
                center = QPoint(viewport.width() // 2, viewport.height() // 2)
                QTest.mouseDClick(viewport, Qt.LeftButton, pos=center)
                QTest.mouseRelease(viewport, Qt.LeftButton, pos=center)
                # Clicking right after a center double-click starts a fresh gesture.
                QTest.mouseClick(viewport, Qt.LeftButton, pos=point)
                self.assertEqual(seek.call_count, 2)

    def test_center_double_click_pauses_playing_video_once(self):
        viewport = self.view.view.viewport()
        point = QPoint(viewport.width() // 2, viewport.height() // 2)
        with patch.object(self.view.player, "playbackState", return_value=QMediaPlayer.PlayingState), \
             patch.object(self.view.player, "pause") as pause, \
             patch.object(self.view.player, "setPosition") as seek:
            QTest.mouseDClick(viewport, Qt.LeftButton, pos=point)
            QTest.mouseRelease(viewport, Qt.LeftButton, pos=point)
            pause.assert_called_once()
            seek.assert_not_called()
            self.assertEqual(self.view.feedback.text(), "暂停")
            self.assertFalse(self.view.buffer_timer.isActive())
            self.assertIsNone(self.view.feedback.graphicsEffect())

        with patch.object(self.view.player, "playbackState", return_value=QMediaPlayer.PausedState):
            self.view.buffer_timer.timeout.emit()
            self.assertEqual(self.view.feedback.text(), "暂停")

    def test_unready_or_failed_source_cannot_erase_saved_position(self):
        self.view.source_key = "positions/test"
        self.view.settings.setValue(self.view.source_key, 6500)
        self.view.resume_position = 6500
        self.view.position_changed(0)
        self.assertEqual(int(self.view.settings.value(self.view.source_key)), 6500)
        with patch.object(self.view.player, "duration", return_value=12000), \
             patch.object(self.view.player, "setPosition") as seek:
            self.view._media_status(QMediaPlayer.LoadedMedia)
            seek.assert_called_once_with(6500)
        self.view._media_status(QMediaPlayer.EndOfMedia)
        self.view.state_writer.future.result(timeout=5)
        self.assertEqual(int(self.view.settings.value(self.view.source_key)), 0)

    def test_stop_flushes_bookmark_before_player_resets(self):
        self.view.source_key = "positions/test"
        self.view.ready = True
        with patch.object(self.view.player, "position", return_value=7200):
            self.view.stop()
        self.view.state_writer.future.result(timeout=5)
        reread = QSettings(str(Path(self.temp.name) / "playback.ini"), QSettings.IniFormat)
        self.assertEqual(int(reread.value("positions/test")), 7200)
        self.assertIsNone(self.view.source_key)

    def test_fullscreen_restores_same_player_and_parent_without_restart(self):
        player = self.view.player
        with patch.object(player, "stop") as stop:
            self.view.toggle_fullscreen()
            self.app.processEvents()
            self.assertTrue(self.view.isFullScreen())
            self.view.close()  # Window close and Escape both restore embedded playback.
            self.app.processEvents()
            self.assertIs(self.view.parentWidget(), self.host)
            self.assertIs(self.view.player, player)
            self.assertEqual(self.host.layout().indexOf(self.view), 0)
            stop.assert_not_called()

    def test_controls_captions_volume_speed_have_live_effects(self):
        self.view.set_caption("当前字幕")
        self.view.caption_button.click()
        self.assertFalse(self.view.subtitle.isVisible())
        self.view.toggle_captions()
        self.assertTrue(self.view.subtitle.isVisible())
        self.view.volume.setValue(35)
        self.assertAlmostEqual(self.view.audio.volume(), 0.35)
        self.view.mute_button.click()
        self.assertTrue(self.view.audio.isMuted())
        self.view.speed.setCurrentIndex(4)
        self.assertEqual(self.view.player.playbackRate(), 1.5)
        self.view.show_controls(False)
        self.assertFalse(self.view.controls.isVisible())
        self.view._play_state(QMediaPlayer.PausedState)
        self.assertTrue(self.view.controls.isVisible())


if __name__ == "__main__":
    unittest.main()
