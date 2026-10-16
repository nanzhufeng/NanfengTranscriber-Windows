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
        self.assertEqual(int(self.view.settings.value(self.view.source_key)), 0)

    def test_stop_flushes_bookmark_before_player_resets(self):
        self.view.source_key = "positions/test"
        self.view.ready = True
        with patch.object(self.view.player, "position", return_value=7200):
            self.view.stop()
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
