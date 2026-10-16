"""Desktop media chrome; playback presentation state stays outside history facts."""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

from PySide6.QtCore import Qt, QEvent, QSettings, QTimer, QUrl, QSize, QSizeF, Signal
from PySide6.QtGui import QKeySequence, QShortcut, QPainter
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
from PySide6.QtWidgets import (
    QApplication, QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QSlider,
    QPushButton, QComboBox, QGraphicsScene, QGraphicsView, QSizePolicy, QStyle,
)

from .ui_icons import icon


def clock(milliseconds):
    seconds = max(0, int(milliseconds) // 1000)
    return (f"{seconds // 3600:02}:" if seconds >= 3600 else "") + f"{seconds // 60 % 60:02}:{seconds % 60:02}"


class SeekSlider(QSlider):
    """Click or drag to the pointer, rather than advancing a tiny page step."""

    def _seek_at(self, event):
        value = QStyle.sliderValueFromPosition(self.minimum(), self.maximum(),
                                               round(event.position().x()) - 6, max(1, self.width() - 12))
        self.setValue(value)
        self.sliderMoved.emit(value)
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setSliderDown(True)
            self._seek_at(event)
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.isSliderDown():
            self._seek_at(event)
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.isSliderDown():
            self._seek_at(event)
            self.setSliderDown(False)
        else:
            super().mouseReleaseEvent(event)


class MediaPlayer(QWidget):
    """One black canvas owns picture, captions, title and playback controls."""

    close_requested = Signal()

    def __init__(self, state_path: Path, parent=None):
        super().__init__(parent)
        self.setObjectName("MediaCanvas")
        self.setMinimumSize(420, 260)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setAttribute(Qt.WA_StyledBackground)
        self.setFocusPolicy(Qt.StrongFocus)
        self.settings = QSettings(str(state_path), QSettings.IniFormat)
        self.source_key = None
        self.resume_position = 0
        self.ready = False
        self.last_saved = 0
        self.restore_parent = None
        self.last_seek_side = None
        self.last_seek_time = 0
        self.seek_steps = 0
        self.ignore_release = False
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)

        self.scene = QGraphicsScene(self)
        self.video = QGraphicsVideoItem()
        self.video.setAspectRatioMode(Qt.KeepAspectRatio)
        self.scene.addItem(self.video)
        self.video.nativeSizeChanged.connect(lambda *_: self._fit_video())
        self.view = QGraphicsView(self.scene, self)
        self.view.setFrameShape(QFrame.NoFrame)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setBackgroundBrush(Qt.black)
        self.view.setRenderHint(QPainter.SmoothPixmapTransform)
        self.view.setFocusPolicy(Qt.NoFocus)
        self.view.viewport().setMouseTracking(True)
        self.view.viewport().installEventFilter(self)
        self.player.setVideoOutput(self.video)

        self.audio_placeholder = QLabel(self)
        self.audio_placeholder.setAlignment(Qt.AlignCenter)
        self.audio_placeholder.setPixmap(icon("music-2", "#b5c3f5", 64).pixmap(64, 64))
        self.audio_placeholder.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.audio_placeholder.hide()

        self.top = QFrame(self)
        self.top.setObjectName("PlayerTop")
        title_layout = QHBoxLayout(self.top)
        title_layout.setContentsMargins(16, 8, 8, 8)
        self.title = QLabel()
        self.title.setMinimumWidth(0)
        self.title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        title_layout.addWidget(self.title, 1)
        title_layout.addWidget(self._button("x", "关闭播放，返回历史", self.close_requested.emit))
        self.title_text = ""

        self.controls = QFrame(self)
        self.controls.setObjectName("PlayerControls")
        controls_layout = QVBoxLayout(self.controls)
        controls_layout.setContentsMargins(12, 4, 12, 10)
        controls_layout.setSpacing(2)
        self.seek = SeekSlider(Qt.Horizontal)
        self.seek.setRange(0, 0)
        self.seek.setFocusPolicy(Qt.TabFocus)
        self.seek.setAccessibleName("播放进度")
        self.seek.setToolTip("拖动跳转播放位置")
        controls_layout.addWidget(self.seek)
        row = QHBoxLayout()
        row.setSpacing(4)
        controls_layout.addLayout(row)
        self.play_button = self._button("play", "播放 / 暂停（空格）", self.play_pause)
        row.addWidget(self.play_button)
        self.rewind_button = self._button("skip-back", "快退 10 秒（←）", lambda: self.seek_by(-10000))
        self.forward_button = self._button("skip-forward", "快进 10 秒（→）", lambda: self.seek_by(10000))
        row.addWidget(self.rewind_button)
        row.addWidget(self.forward_button)
        self.play_clock = QLabel("00:00 / 00:00")
        self.play_clock.setObjectName("PlayerClock")
        self.play_clock.setFixedWidth(118)
        row.addWidget(self.play_clock)
        row.addStretch()
        self.mute_button = self._button("volume-2", "静音（M）", self.toggle_mute)
        row.addWidget(self.mute_button)
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setFocusPolicy(Qt.TabFocus)
        self.volume.setFixedWidth(64)
        self.volume.setAccessibleName("音量")
        self.volume.setValue(max(0, min(100, self._setting_int("volume", 80))))
        self.audio.setVolume(self.volume.value() / 100)
        row.addWidget(self.volume)
        self.speed = QComboBox()
        self.speed.setObjectName("PlayerSpeed")
        self.speed.setAccessibleName("播放速度")
        for value in (0.5, 0.75, 1, 1.25, 1.5, 2):
            self.speed.addItem(f"{value:g}×", value)
        self.speed.setCurrentIndex(2)
        self.speed.setFixedWidth(64)
        row.addWidget(self.speed)
        self.caption_button = self._button("captions", "显示 / 隐藏画面字幕（C）", self.toggle_captions)
        self.caption_button.setCheckable(True)
        self.caption_button.setChecked(True)
        row.addWidget(self.caption_button)
        self.fullscreen_button = self._button("maximize", "全屏（F）", self.toggle_fullscreen)
        row.addWidget(self.fullscreen_button)

        self.subtitle = QLabel(self)
        self.subtitle.setObjectName("PlayerCaption")
        self.subtitle.setAlignment(Qt.AlignCenter)
        self.subtitle.setWordWrap(True)
        self.subtitle.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.subtitle.hide()
        self.feedback = QLabel(self)
        self.feedback.setObjectName("PlayerFeedback")
        self.feedback.setAlignment(Qt.AlignCenter)
        self.feedback.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.feedback.hide()
        self.feedback_timer = QTimer(self)
        self.feedback_timer.setSingleShot(True)
        self.feedback_timer.timeout.connect(self.feedback.hide)
        self.buffer_timer = QTimer(self)
        self.buffer_timer.setSingleShot(True)
        self.buffer_timer.timeout.connect(self._show_buffering)
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self._auto_hide)
        self.tap_timer = QTimer(self)
        self.tap_timer.setSingleShot(True)
        self.tap_timer.timeout.connect(lambda: self.show_controls(not self.controls.isVisible()))
        self.seek.sliderMoved.connect(self.player.setPosition)
        self.seek.sliderReleased.connect(lambda: self.player.setPosition(self.seek.value()))
        self.volume.valueChanged.connect(self.set_volume)
        self.audio.mutedChanged.connect(self._volume_icon)
        self.audio.volumeChanged.connect(self._volume_icon)
        self.speed.currentIndexChanged.connect(lambda: self.player.setPlaybackRate(self.speed.currentData()))
        self.player.positionChanged.connect(self.position_changed)
        self.player.durationChanged.connect(self._duration_changed)
        self.player.playbackStateChanged.connect(self._play_state)
        self.player.mediaStatusChanged.connect(self._media_status)
        self.player.errorOccurred.connect(self._error)
        self.shortcuts = []
        for key, action in (("Space", self.play_pause), ("Left", lambda: self.seek_by(-10000)),
                            ("Right", lambda: self.seek_by(10000)), ("M", self.toggle_mute),
                            ("F", self.toggle_fullscreen), ("Escape", self.exit_fullscreen),
                            ("C", self.toggle_captions), ("Up", lambda: self.volume.setValue(self.volume.value() + 5)),
                            ("Down", lambda: self.volume.setValue(self.volume.value() - 5))):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(action)
            self.shortcuts.append(shortcut)
        self.setStyleSheet("""
            QWidget#MediaCanvas { background: #000000; }
            QFrame#PlayerTop, QFrame#PlayerControls { background: rgba(12, 15, 22, 220); border: none; border-radius: 0; }
            QWidget#MediaCanvas QLabel { color: #ffffff; background: transparent; border: none; }
            QWidget#MediaCanvas QPushButton { background: transparent; border: none; outline: none; border-radius: 18px; padding: 0; min-width: 36px; max-width: 36px; min-height: 36px; max-height: 36px; color: white; }
            QWidget#MediaCanvas QPushButton:hover, QWidget#MediaCanvas QPushButton:focus { background: #343b50; }
            QWidget#MediaCanvas QPushButton:pressed { background: #46516b; }
            QWidget#MediaCanvas QPushButton:checked { background: #465782; }
            QLabel#PlayerClock { font-size: 12px; padding: 0 6px; }
            QLabel#PlayerCaption { color: white; background: rgba(0, 0, 0, 165); border-radius: 6px; padding: 6px 12px; font-size: 18px; }
            QLabel#PlayerFeedback { background: rgba(0, 0, 0, 175); border-radius: 16px; padding: 10px; }
            QComboBox#PlayerSpeed { background: #252c3c; color: white; border: none; border-radius: 12px; padding: 4px; min-height: 24px; }
            QComboBox#PlayerSpeed::drop-down { border: none; width: 0; }
            QComboBox#PlayerSpeed::down-arrow { image: none; width: 0; }
            QComboBox#PlayerSpeed QAbstractItemView { background: white; color: #233342; selection-background-color: #edf2ff; selection-color: #5269ac; border: none; }
            QWidget#MediaCanvas QSlider::groove:horizontal { background: #566071; height: 4px; border-radius: 2px; }
            QWidget#MediaCanvas QSlider::sub-page:horizontal { background: #8ca2ff; border-radius: 2px; }
            QWidget#MediaCanvas QSlider::handle:horizontal { background: #ffffff; width: 12px; margin: -4px 0; border: none; border-radius: 6px; }
        """)

    def _button(self, name, title, action):
        button = QPushButton()
        button.setFixedSize(36, 36)
        button.setFocusPolicy(Qt.TabFocus)
        button.setIcon(icon(name, "#ffffff", 20))
        button.setIconSize(QSize(20, 20))
        button.setToolTip(title)
        button.setAccessibleName(title)
        button.clicked.connect(action)
        return button

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.view.setGeometry(self.rect())
        self._fit_video()
        self.audio_placeholder.setGeometry(self.rect())
        self.top.setGeometry(0, 0, self.width(), 48)
        self.title.setText(self.title.fontMetrics().elidedText(self.title_text, Qt.ElideRight, max(0, self.width() - 80)))
        # Compact windows keep the essential controls; volume remains keyboard accessible.
        self.volume.setVisible(self.width() >= 650)
        self.rewind_button.setVisible(self.width() >= 560)
        self.forward_button.setVisible(self.width() >= 560)
        self.speed.setVisible(self.width() >= 490)
        self.play_clock.setFixedWidth(100 if self.width() < 560 else 118)
        self.controls.setGeometry(0, self.height() - 84, self.width(), 84)
        self._caption_geometry()
        self.feedback.setGeometry(max(12, self.width() // 2 - 90), max(48, self.height() // 2 - 24), 180, 48)

    def _fit_video(self):
        size = self.view.viewport().size()
        self.scene.setSceneRect(0, 0, size.width(), size.height())
        self.video.setSize(QSizeF(size))
        self.view.resetTransform()

    def _caption_geometry(self):
        width = max(100, self.width() - 48)
        height = min(120, self.subtitle.heightForWidth(width) + 12)
        bottom = 96 if self.controls.isVisible() else 20
        self.subtitle.setGeometry(24, self.height() - bottom - height, width, height)

    def _setting_int(self, key, default):
        try:
            return int(self.settings.value(key, default))
        except (ValueError, TypeError):
            return default

    def open(self, source: Path, title: str, is_audio=False):
        self.stop()
        self.source_key = "positions/" + hashlib.sha256(str(source.resolve()).casefold().encode()).hexdigest()
        self.resume_position = max(0, self._setting_int(self.source_key, 0))
        self.ready = False
        self.last_saved = self.resume_position
        self.title_text = title
        self.title.setToolTip(title)
        self.title.setText(self.title.fontMetrics().elidedText(title, Qt.ElideRight, max(0, self.width() - 80)))
        self.video.setVisible(not is_audio)
        self.audio_placeholder.setVisible(is_audio)
        self.set_caption("")
        self.feedback.hide()
        self.player.setSource(QUrl.fromLocalFile(str(source.resolve())))
        self.player.play()
        self.show_controls(True)
        self.setFocus(Qt.OtherFocusReason)

    def _duration_changed(self, duration):
        self.seek.setRange(0, max(0, int(duration)))
        self.play_clock.setText(f"{clock(self.player.position())} / {clock(duration)}")

    def _media_status(self, status):
        self.buffer_timer.stop()
        if status in (QMediaPlayer.LoadingMedia, QMediaPlayer.BufferingMedia, QMediaPlayer.StalledMedia):
            self.buffer_timer.start(350)
        elif self.feedback.text() == "正在缓冲…":
            self.feedback.hide()
        if status in (QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia) and not self.ready and self.source_key:
            self.ready = True
            if self.resume_position:
                self.player.setPosition(min(self.resume_position, max(0, self.player.duration() - 1)))
        if status == QMediaPlayer.EndOfMedia:
            self.resume_position = 0
            self._save_position(0, flush=True)
            self.show_controls(True)

    def _save_position(self, position=None, flush=False):
        if not self.source_key or not self.ready:
            return
        value = self.player.position() if position is None else position
        self.settings.setValue(self.source_key, max(0, int(value)))
        self.last_saved = value
        if flush:
            self.settings.sync()

    def position_changed(self, position):
        self.play_clock.setText(f"{clock(position)} / {clock(self.player.duration())}")
        if not self.seek.isSliderDown():
            self.seek.setValue(position)
        if abs(position - self.last_saved) >= 1000:
            self._save_position(position)

    def stop(self):
        self._save_position(0 if self.player.mediaStatus() == QMediaPlayer.EndOfMedia else None, flush=True)
        self.ready = False
        self.source_key = None
        self.hide_timer.stop()
        self.tap_timer.stop()
        self.buffer_timer.stop()
        self.player.stop()
        self.exit_fullscreen()

    def play_pause(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            self._save_position(flush=True)
        else:
            self.player.play()
        self.show_controls(True)

    def _play_state(self, state):
        playing = state == QMediaPlayer.PlayingState
        self.play_button.setIcon(icon("pause" if playing else "play", "#ffffff", 20))
        self.play_button.setAccessibleName("暂停（空格）" if playing else "播放（空格）")
        self.show_controls(True)

    def seek_by(self, offset):
        target = max(0, self.player.position() + offset)
        if self.player.duration() > 0:
            target = min(target, self.player.duration())
        self.player.setPosition(target)
        self._save_position(target, flush=True)
        self.show_controls(True)

    def _seek_tap(self, side):
        now = time.monotonic()
        self.seek_steps = self.seek_steps + 1 if side == self.last_seek_side and now - self.last_seek_time <= 0.6 else 1
        self.last_seek_time, self.last_seek_side = now, side
        self.seek_by(side * 10000)
        self.show_controls(False)
        self.feedback.setText(f"{'快退' if side < 0 else '快进'} {self.seek_steps * 10} 秒")
        self.feedback.show()
        self.feedback.raise_()
        self.feedback_timer.start(800)

    def set_caption(self, text):
        self.subtitle.setText(text)
        self.subtitle.setVisible(bool(text) and self.caption_button.isChecked())
        self._caption_geometry()
        self.subtitle.raise_()

    def toggle_captions(self):
        # QPushButton has already toggled on click; shortcuts toggle explicitly.
        if self.sender() is not self.caption_button:
            self.caption_button.toggle()
        self.set_caption(self.subtitle.text())
        self.show_controls(True)

    def set_volume(self, value):
        self.audio.setVolume(value / 100)
        self.audio.setMuted(False)
        self.settings.setValue("volume", value)

    def toggle_mute(self):
        self.audio.setMuted(not self.audio.isMuted())
        self.show_controls(True)

    def _volume_icon(self, *_):
        muted = self.audio.isMuted() or self.audio.volume() == 0
        self.mute_button.setIcon(icon("volume-x" if muted else "volume-2", "#ffffff", 20))

    def show_controls(self, visible=True):
        self.top.setVisible(visible)
        self.controls.setVisible(visible)
        self.view.viewport().setCursor(Qt.ArrowCursor if visible else Qt.BlankCursor)
        self._caption_geometry()
        self.hide_timer.stop()
        if visible and self.player.playbackState() == QMediaPlayer.PlayingState:
            self.hide_timer.start(2500)

    def _auto_hide(self):
        focused = QApplication.focusWidget()
        if self.controls.underMouse() or (focused is not None and self.controls.isAncestorOf(focused)):
            self.hide_timer.start(2500)
        elif self.player.playbackState() == QMediaPlayer.PlayingState:
            self.show_controls(False)

    def eventFilter(self, watched, event):
        if watched is self.view.viewport():
            if event.type() == QEvent.Resize:
                QTimer.singleShot(0, self._fit_video)
            elif event.type() == QEvent.MouseMove:
                self.show_controls(True)
            elif event.type() == QEvent.MouseButtonDblClick and event.button() == Qt.LeftButton:
                self.tap_timer.stop()
                self.ignore_release = True
                self._seek_tap(-1 if event.position().x() < self.width() / 2 else 1)
                return True
            elif event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                self.setFocus(Qt.MouseFocusReason)
                side = -1 if event.position().x() < self.width() / 2 else 1
                # The release belonging to a double click must not seek twice.
                if self.ignore_release:
                    self.ignore_release = False
                    return True
                if side == self.last_seek_side and time.monotonic() - self.last_seek_time <= 0.6:
                    self._seek_tap(side)
                else:
                    self.tap_timer.start(QApplication.doubleClickInterval())
                return True
        return super().eventFilter(watched, event)

    def toggle_fullscreen(self):
        if self.restore_parent is not None:
            self.exit_fullscreen()
            return
        self.restore_parent = self.parentWidget()
        self.restore_parent.layout().removeWidget(self)
        self.setParent(None)
        self.showFullScreen()
        self.fullscreen_button.setIcon(icon("minimize", "#ffffff", 20))
        self.fullscreen_button.setToolTip("退出全屏（Esc）")
        self.setFocus()
        self.show_controls(True)

    def exit_fullscreen(self):
        if self.restore_parent is None:
            return
        parent, self.restore_parent = self.restore_parent, None
        self.showNormal()
        self.setParent(parent)
        parent.layout().addWidget(self)
        self.show()
        self.fullscreen_button.setIcon(icon("maximize", "#ffffff", 20))
        self.fullscreen_button.setToolTip("全屏（F）")
        self.setFocus()

    def closeEvent(self, event):
        if self.restore_parent is not None:
            self.exit_fullscreen()
            event.ignore()
        else:
            self.stop()
            super().closeEvent(event)

    def _error(self, error, message):
        self.buffer_timer.stop()
        self.show_controls(True)
        self.feedback.setText("无法播放")
        self.feedback.setToolTip(message)
        self.feedback.show()

    def _show_buffering(self):
        self.feedback.setText("正在缓冲…")
        self.feedback.show()
        self.feedback.raise_()
