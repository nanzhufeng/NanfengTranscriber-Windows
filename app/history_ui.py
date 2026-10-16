from __future__ import annotations

from datetime import datetime
import hashlib
import os
from pathlib import Path
import subprocess
import threading
import time

from PySide6.QtCore import Qt, QTimer, Signal, QObject, QRunnable, QThreadPool, QRectF, QPoint, QSize, QEvent
from PySide6.QtGui import QPixmap, QPainter, QColor, QPainterPath, QFont, QTextCursor, QTextBlockFormat
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QLineEdit, QComboBox, QScrollArea, QFrame,
    QStackedWidget, QTextEdit, QFileDialog, QMessageBox,
    QMenu, QListWidget, QSplitter, QSizePolicy,
)

from .transcriber import export_history_document, history_subtitle_cues, safe_output_stem
from .ui_icons import icon
from .media_player import MediaPlayer


class ThumbnailSignals(QObject):
    done = Signal(str, str)


class ThumbnailJob(QRunnable):
    def __init__(self, record, root, ffmpeg):
        super().__init__()
        self.record, self.root, self.ffmpeg = record, root, ffmpeg
        self.signals = ThumbnailSignals()
        self.cancelled = threading.Event()

    def run(self):
        path = self.root / "thumbnails" / (hashlib.sha256(self.record["id"].encode()).hexdigest() + ".png")
        try:
            if not path.exists() and self.ffmpeg and Path(self.record["source"]).is_file():
                path.parent.mkdir(parents=True, exist_ok=True)
                pending = path.with_suffix(".pending.png")
                try:
                    if self.cancelled.is_set():
                        return
                    with subprocess.Popen([str(self.ffmpeg), "-nostdin", "-loglevel", "error", "-y", "-i",
                                           self.record["source"], "-frames:v", "1", "-vf", "scale=240:-1", str(pending)],
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)) as process:
                        deadline = time.monotonic() + 20
                        while process.poll() is None:
                            if self.cancelled.is_set() or time.monotonic() > deadline:
                                process.terminate()
                                try:
                                    process.wait(timeout=2)
                                except subprocess.TimeoutExpired:
                                    process.kill()
                                break
                            try:
                                process.wait(timeout=0.2)
                            except subprocess.TimeoutExpired:
                                pass
                    if pending.exists() and pending.stat().st_size:
                        os.replace(pending, path)
                finally:
                    pending.unlink(missing_ok=True)
        except (OSError, subprocess.SubprocessError):
            pass  # A thumbnail is optional; the document is still usable.
        self.signals.done.emit(self.record["id"], str(path) if path.exists() else "")


def decorate_button(item, text, primary=False):
    navigation = text.startswith("‹")
    title = text.lstrip("‹ ")
    role = "navigation" if navigation else "danger" if "删除" in title or "清理失效" in title else "utility" if title in {"复制全部", "全选", "定位原文件"} else "media" if title in {"播放", "暂停", "原文件核对"} else "secondary"
    color = {"danger": "#b34646", "utility": "#7959a8", "media": "#327b88"}.get(role, "#5269ac")
    names = {"保存编辑": "save", "复制全部": "copy", "导出": "download", "播放": "play", "暂停": "pause",
             "原文件核对": "file-search", "定位原文件": "folder", "全选": "check-square", "取消选择": "x", "加载更多": "chevron-down"}
    name = "arrow-left" if navigation else "trash-2" if role == "danger" else names.get(title)
    item.setText(title)
    item.setProperty("historyRole", role)
    item.setObjectName("PrimaryButton" if primary else "HistoryAction")
    if name:
        item.setIcon(icon(name, "#ffffff" if primary else color))
        item.setIconSize(QSize(18, 18))
    item.style().unpolish(item)
    item.style().polish(item)


def button(text, action, primary=False):
    item = QPushButton()
    item.setFixedHeight(38)
    decorate_button(item, text, primary)
    item.clicked.connect(action)
    return item


def back_button(title, action):
    item = button("‹ " + title, action)
    item.setText("")
    item.setFixedSize(38, 38)
    item.setStyleSheet("padding: 0; min-width: 38px; max-width: 38px;")
    item.setToolTip(title)
    item.setAccessibleName(title)
    return item


def clock(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}" if seconds >= 3600 else f"{seconds // 60:02}:{seconds % 60:02}"


class DocumentLink(QPushButton):
    def __init__(self, title):
        super().__init__(title)
        self.title = title
        self.setToolTip(title)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.setText(self.fontMetrics().elidedText(self.title, Qt.ElideRight, max(0, self.width() - 4)))


class ElidedLabel(QLabel):
    def __init__(self):
        super().__init__()
        self.full_text = ""
        self.setTextFormat(Qt.PlainText)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    def setText(self, text):
        self.full_text = text
        self.setToolTip(text)
        self._update_text()

    def _update_text(self):
        super().setText(self.fontMetrics().elidedText(self.full_text, Qt.ElideRight, max(0, self.width())))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_text()


class HistoryCard(QFrame):
    clicked = Signal()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class DocumentEditor(QTextEdit):
    """Reading typography is presentation only; plain text remains the saved truth."""

    def __init__(self):
        super().__init__()
        self.setObjectName("HistoryEditor")
        font = QFont("Microsoft YaHei UI")
        font.setPixelSize(15)
        font.setLetterSpacing(QFont.AbsoluteSpacing, 0.35)
        self.setFont(font)
        # Keep glyph ink and the caret clear of the viewport's clipping edge.
        self.document().setDocumentMargin(16)
        self.setAcceptRichText(False)
        self.setLineWrapMode(QTextEdit.FixedPixelWidth)
        self.setStyleSheet("QTextEdit#HistoryEditor { background: #ffffff; color: #283746; border: none; border-radius: 12px; padding: 0; font-family: 'Microsoft YaHei UI'; font-size: 15px; selection-background-color: #dce4fb; selection-color: #1f2937; }")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        inset = max(24, (self.width() - 960) // 2)
        self.setViewportMargins(inset, 24, inset, 24)
        self._sync_reading_width()

    def _sync_reading_width(self):
        width = self.viewport().width()
        if width != self.lineWrapColumnOrWidth():
            self.setLineWrapColumnOrWidth(width)

    def viewportEvent(self, event):
        result = super().viewportEvent(event)
        if event.type() == QEvent.Resize and self.lineWrapMode() == QTextEdit.FixedPixelWidth:
            QTimer.singleShot(0, self._sync_reading_width)
        return result

    def setPlainText(self, text):
        super().setPlainText(text)
        cursor = QTextCursor(self.document())
        cursor.select(QTextCursor.Document)
        block = QTextBlockFormat()
        block.setLineHeight(170, QTextBlockFormat.ProportionalHeight.value)
        block.setBottomMargin(10)
        block.setAlignment(Qt.AlignLeft)
        cursor.mergeBlockFormat(block)
        self.document().clearUndoRedoStacks()
        self.document().setModified(False)


class HistoryPage(QWidget):
    back_requested = Signal()

    def __init__(self, store, reveal, ffmpeg_dir=None, parent=None):
        super().__init__(parent)
        self.store, self.reveal = store, reveal
        self.ffmpeg = Path(ffmpeg_dir) / "ffmpeg.exe" if ffmpeg_dir else None
        self.selected = set()
        self.selection_mode = False
        self.limit = store.PAGE_SIZE
        self.records = []
        self.jobs, self.thumbnails = {}, {}
        self.thumbnail_pool = QThreadPool(self)
        self.thumbnail_pool.setMaxThreadCount(2)
        self.current_record = None
        self.saved_text = ""
        self.columns = 0
        self.setStyleSheet("""
            QFrame#HistoryCard { background: #ffffff; border: none; border-radius: 14px; }
            QLabel#HistoryTitle { font-size: 22px; font-weight: 700; color: #182430; }
            QLabel#HistoryDay { font-size: 16px; font-weight: 600; color: #374151; }
            QLabel#HistoryMeta { color: #697586; font-size: 12px; }
            QLabel#HistoryPreview { color: #596674; font-size: 13px; }
            QLabel#HistoryTag { background: #f1f2f4; border: none; border-radius: 11px; padding: 0 8px; font-size: 12px; color: #5269ac; }
            QLabel#HistoryTag[tone="language"] { color: #7959a8; }
            QLabel#HistoryDuration { color: #327b88; font-size: 12px; }
            QLabel#HistoryModel { color: #5269ac; font-size: 12px; }
            QPushButton#HistorySelection { background: transparent; border: none; border-radius: 14px; padding: 0; min-width: 28px; max-width: 28px; min-height: 28px; max-height: 28px; }
            QPushButton#HistorySelection:hover, QPushButton#HistorySelection:focus { background: #e5e7eb; }
            QPushButton#HistorySelection:pressed { background: #d7dbe2; }
            QFrame#HistoryDetailHeader { background: #ffffff; border: none; border-radius: 14px; }
            QLabel#HistoryDocumentTitle { color: #182430; font-size: 18px; font-weight: 600; background: transparent; }
            QLabel#HistoryDetailFeedback { color: #5269ac; font-size: 12px; padding: 0 4px; }
            QTextEdit, QListWidget { background: #ffffff; border: none; border-radius: 12px; padding: 12px; color: #1f2937; }
            QScrollArea { background: transparent; border: none; }
            QWidget#HistoryCards, QWidget#HistoryViewport { background: #eeeeee; }
            QLineEdit { background: #ffffff; border: none; border-radius: 19px; color: #1f2937; padding: 0 12px; min-height: 38px; }
            QLineEdit:focus { background: #ffffff; }
            QLineEdit QToolButton { background: transparent; border: none; border-radius: 10px; min-width: 20px; max-width: 20px; min-height: 20px; max-height: 20px; padding: 0; }
            QLineEdit QToolButton:hover { background: #e5e7eb; }
            QComboBox { background: #ffffff; border: none; border-radius: 19px; color: #5269ac; font-weight: 600; min-height: 38px; padding: 0 36px 0 14px; }
            QComboBox:focus, QComboBox:on { background: #e4e6ea; }
            QComboBox::drop-down { border: none; background: transparent; width: 30px; }
            QComboBox#HistoryExportFormat { padding: 0 30px; }
            QComboBox#HistoryExportFormat QLineEdit { background: transparent; color: #5269ac; border: none; padding: 0; min-height: 0; font-weight: 600; }
            QPushButton#HistoryAction { background: #e3e5e9; border: none; border-radius: 19px; color: #5269ac; padding: 0 14px; font-weight: 600; }
            QPushButton#HistoryAction[historyRole="danger"] { color: #b34646; }
            QPushButton#HistoryAction[historyRole="utility"] { color: #7959a8; }
            QPushButton#HistoryAction[historyRole="media"] { color: #327b88; }
            QPushButton#HistoryAction:hover, QPushButton#HistoryAction:focus { background: #d7dbe2; }
            QPushButton#HistoryAction:pressed { background: #cbd1db; }
            QPushButton#HistoryAction:disabled { background: #e9eaed; color: #9aa3ad; }
            QPushButton#PrimaryButton { border-radius: 19px; }
            QSlider::groove:horizontal { background: #dce0e7; height: 5px; border: none; border-radius: 2px; }
            QSlider::sub-page:horizontal { background: #6075c8; border-radius: 2px; }
            QSlider::handle:horizontal { background: #6075c8; width: 14px; margin: -5px 0; border: none; border-radius: 7px; }
            QListWidget#HistoryCues { selection-background-color: #fff0df; selection-color: #914714; outline: none; }
            QListWidget#HistoryCues::item { background: transparent; border: none; border-left: 2px solid transparent; border-radius: 6px; padding: 6px 10px; }
            QListWidget#HistoryCues::item:hover { background: #fff8f0; }
            QListWidget#HistoryCues::item:selected { background: #fff0df; color: #914714; border-left: 2px solid #e68a36; }
            QPushButton#HistoryThumb { background: #f1f2f4; border-radius: 10px; min-width: 96px; max-width: 96px; padding: 0; }
            QPushButton#HistoryName { background: transparent; text-align: left; min-width: 0; padding: 0; color: #182430; font-weight: 600; }
            QPushButton#HistoryMore { min-width: 36px; max-width: 36px; min-height: 36px; max-height: 36px; padding: 0; border: none; border-radius: 18px; background: transparent; }
            QPushButton#HistoryMore:hover, QPushButton#HistoryMore:focus { background: #e5e7eb; }
            QPushButton#HistoryMore:pressed { background: #d7dbe2; }
            QMenu { background: #ffffff; color: #405362; border: none; border-radius: 11px; padding: 6px; font-size: 13px; }
            QMenu::item { padding: 7px 14px 7px 8px; border: none; border-radius: 6px; }
            QMenu::item:selected { background: #f1f2f4; }
            QMenu::separator { height: 1px; background: #e1e5e7; margin: 4px 12px; }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        navigation_bar = QWidget()
        navigation_grid = QGridLayout(navigation_bar)
        navigation_grid.setContentsMargins(0, 0, 0, 0)
        navigation = QHBoxLayout()
        navigation.addWidget(back_button("返回转写", self.request_back))
        title = QLabel("历史")
        title.setObjectName("HistoryTitle")
        title.setAttribute(Qt.WA_TransparentForMouseEvents)
        title.setAlignment(Qt.AlignCenter)
        navigation.addStretch()
        self.work_status = QLabel()
        self.work_status.setObjectName("HistoryMeta")
        navigation.addWidget(self.work_status)
        self.count = QLabel()
        navigation.addWidget(self.count)
        navigation_grid.addLayout(navigation, 0, 0)
        navigation_grid.addWidget(title, 0, 0, Qt.AlignCenter)
        layout.addWidget(navigation_bar)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #a33636;")
        self.error_label.hide()
        layout.addWidget(self.error_label)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)
        self._build_list()
        self._build_detail()
        self._build_media()
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(200)
        self.search_timer.timeout.connect(self.filter_changed)
        self.search.textChanged.connect(lambda: self.search_timer.start())
        self.period.currentTextChanged.connect(self.filter_changed)

    def show_error(self, message):
        self.error_label.setText(message)
        self.error_label.show()

    def run_action(self, action):
        try:
            return action()
        except Exception as exc:
            QMessageBox.warning(self, "历史操作未完成", f"{exc}\n\n请检查文件位置或目录权限后重试。")
            return None

    def _build_list(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索文件名或完整转写文字")
        search_action = self.search.addAction(icon("search", "#5269ac"), QLineEdit.LeadingPosition)
        search_action.triggered.connect(lambda: self.search.setFocus())
        self.search.setClearButtonEnabled(True)
        layout.addWidget(self.search)
        actions = QHBoxLayout()
        self.period = QComboBox()
        for period in ["全部时间", "今天", "近 7 天", "近 30 天"]:
            self.period.addItem(icon("calendar-days", "#5269ac"), period)
        actions.addWidget(self.period)
        actions.addStretch()
        self.selection_count = QLabel()
        actions.addWidget(self.selection_count)
        self.select_button = button("批量删除", self.toggle_selection)
        actions.addWidget(self.select_button)
        self.all_button = button("全选", lambda: self.run_action(self.select_all))
        self.delete_button = button("删除所选", lambda: self.delete_records(self.selected))
        actions.addWidget(self.all_button)
        actions.addWidget(self.delete_button)
        self.all_button.hide()
        self.delete_button.hide()
        self.clean_button = button("清理失效", self.clean_invalid)
        actions.addWidget(self.clean_button)
        self.clean_button.hide()
        layout.addLayout(actions)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.viewport().setObjectName("HistoryViewport")
        self.cards = QWidget()
        self.cards.setObjectName("HistoryCards")
        self.grid = QGridLayout(self.cards)
        self.grid.setContentsMargins(0, 4, 0, 4)
        self.grid.setSpacing(14)
        self.grid.setAlignment(Qt.AlignTop)
        self.grid.setColumnStretch(0, 1)
        self.grid.setColumnStretch(1, 1)
        scroll.setWidget(self.cards)
        layout.addWidget(scroll, 1)
        self.more_button = button("加载更多", self.load_more)
        layout.addWidget(self.more_button)
        self.stack.addWidget(page)

    def _build_detail(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)
        header = QFrame()
        header.setObjectName("HistoryDetailHeader")
        top = QHBoxLayout(header)
        top.setContentsMargins(14, 14, 14, 14)
        top.setSpacing(14)
        top.addWidget(back_button("返回历史", self.show_list))
        heading = QVBoxLayout()
        heading.setSpacing(6)
        self.detail_title = ElidedLabel()
        self.detail_title.setObjectName("HistoryDocumentTitle")
        heading.addWidget(self.detail_title)
        self.detail_meta = ElidedLabel()
        self.detail_meta.setObjectName("HistoryMeta")
        heading.addWidget(self.detail_meta)
        top.addLayout(heading, 1)
        top.addWidget(button("原文件核对", lambda: self.open_media(self.current_record["id"])))
        self.detail_more = QPushButton()
        self.detail_more.setObjectName("HistoryMore")
        self.detail_more.setFixedSize(36, 36)
        self.detail_more.setIcon(icon("more-horizontal", "#5269ac", 20))
        self.detail_more.setToolTip("更多：转写信息、文件定位")
        self.detail_more.setAccessibleName("文稿更多操作")
        self.detail_more.clicked.connect(lambda: self.menu(self.current_record, self.detail_more, detail=True))
        top.addWidget(self.detail_more)
        layout.addWidget(header)
        self.detail_feedback = ElidedLabel()
        self.detail_feedback.setObjectName("HistoryDetailFeedback")
        self.detail_feedback.hide()
        layout.addWidget(self.detail_feedback)
        self.editor = DocumentEditor()
        layout.addWidget(self.editor, 1)
        actions = QHBoxLayout()
        actions.addWidget(button("保存编辑", lambda: self.run_action(self.save_edit), True))
        actions.addWidget(button("复制全部", lambda: QApplication.clipboard().setText(self.editor.toPlainText())))
        from .main import CenterComboBox
        self.format = CenterComboBox()
        self.format.setObjectName("HistoryExportFormat")
        self.format.addItems(["TXT", "Markdown", "SRT", "DOCX"])
        for index in range(self.format.count()):
            self.format.setItemData(index, Qt.AlignCenter, Qt.TextAlignmentRole)
        actions.addStretch()
        actions.addWidget(self.format)
        actions.addWidget(button("导出", self.export, True))
        layout.addLayout(actions)
        self.stack.addWidget(page)

    def _build_media(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        actions = QHBoxLayout()
        actions.addWidget(back_button("返回历史", self.show_list))
        actions.addStretch()
        actions.addWidget(button("定位原文件", lambda: self.run_action(lambda: self.reveal(Path(self.media_record["source"])))))
        layout.addLayout(actions)
        split = QSplitter()
        video_side = QWidget()
        video_layout = QVBoxLayout(video_side)
        video_layout.setContentsMargins(0, 0, 0, 0)
        self.media_view = MediaPlayer(self.store.root / "playback.ini", video_side)
        self.media_view.close_requested.connect(self.show_list)
        video_layout.addWidget(self.media_view)
        self.media_title = self.media_view.title
        self.player, self.audio, self.video = self.media_view.player, self.media_view.audio, self.media_view.video
        self.subtitle, self.seek = self.media_view.subtitle, self.media_view.seek
        self.play_button, self.play_clock = self.media_view.play_button, self.media_view.play_clock
        self.audio_placeholder = self.media_view.audio_placeholder
        self.cues = QListWidget()
        self.cues.setObjectName("HistoryCues")
        self.cues.itemClicked.connect(self.seek_to_cue)
        split.addWidget(video_side)
        split.addWidget(self.cues)
        split.setSizes([600, 400])
        layout.addWidget(split, 1)
        self.media_status = QLabel()
        self.media_status.setWordWrap(True)
        self.media_status.hide()
        layout.addWidget(self.media_status)
        self.player.positionChanged.connect(self.position_changed)
        self.player.errorOccurred.connect(self._media_error)
        self.stack.addWidget(page)

    def dirty(self):
        return self.stack.currentIndex() == 1 and self.editor.toPlainText() != self.saved_text

    def leave(self):
        if self.dirty():
            choice = QMessageBox.question(self, "保存文稿编辑？", "当前文稿有未保存的修改。", QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
            if choice == QMessageBox.Cancel:
                return False
            if choice == QMessageBox.Save:
                try:
                    self.save_edit()
                except Exception as exc:
                    QMessageBox.warning(self, "保存失败", str(exc))
                    return False
        self.media_view.stop()
        return True

    def request_back(self):
        if self.leave():
            self.back_requested.emit()

    def shutdown(self):
        self.media_view.stop()
        for job in self.jobs.values():
            job.cancelled.set()
        self.thumbnail_pool.clear()

    def show_list(self):
        if not self.leave():
            return
        self.stack.setCurrentIndex(0)
        self.reload()

    def reload(self):
        try:
            self.records, total = self.store.query(self.search.text(), self.period.currentText(), self.limit)
            self.count.setText(f"{total} 条记录")
            self.more_button.setVisible(len(self.records) < total)
            invalid_count = len(self.store.invalid_ids())
            self.clean_button.setVisible(invalid_count > 0)
            self.clean_button.setText(f"清理失效（{invalid_count}）")
            self.render()
        except Exception as exc:
            self.show_error(f"历史记录暂时无法读取：{exc}。转写工作台仍可使用，请检查历史目录权限。")

    def load_more(self):
        self.limit += self.store.PAGE_SIZE
        self.reload()

    def filter_changed(self):
        self.limit = self.store.PAGE_SIZE
        self.selected.clear()
        self.reload()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if (2 if self.width() >= 1000 else 1) != self.columns:
            QTimer.singleShot(0, self.render)

    def render(self):
        self.columns = 2 if self.width() >= 1000 else 1
        self.grid.setColumnStretch(1, 1 if self.columns == 2 else 0)
        self.thumbnails.clear()
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        row, column, day = 0, 0, None
        if not self.records:
            message = QLabel("暂无匹配记录" if self.search.text() or self.period.currentIndex() else "暂无转写历史，完成转写后会自动保存在这里。")
            message.setAlignment(Qt.AlignCenter)
            self.grid.addWidget(message, 0, 0, 1, self.columns)
        for record in self.records:
            current_day = record["completed"][:10]
            if current_day != day:
                if column:
                    row += 1
                label = QLabel(datetime.fromisoformat(record["completed"]).strftime("%Y 年 %m 月 %d 日"))
                label.setObjectName("HistoryDay")
                self.grid.addWidget(label, row, 0, 1, self.columns)
                row, column, day = row + 1, 0, current_day
            self.grid.addWidget(self.card(record), row, column)
            column += 1
            if column == self.columns:
                row, column = row + 1, 0
        self.selection_count.setText(f"已选 {len(self.selected)} 项" if self.selection_mode else "")
        self.delete_button.setEnabled(bool(self.selected))

    def card(self, record):
        card = HistoryCard()
        card.setObjectName("HistoryCard")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        if not self.selection_mode:
            card.clicked.connect(lambda: self.open_record(record["id"]))
        timeline_group = QWidget()
        timeline_group.setObjectName("HistoryTimeline")
        timeline_group.setFixedHeight(78)
        timeline = QVBoxLayout(timeline_group)
        timeline.setContentsMargins(0, 0, 0, 0)
        timeline.setSpacing(6)
        timeline.setAlignment(Qt.AlignCenter)
        if self.selection_mode:
            completed = QPushButton()
            completed.setObjectName("HistorySelection")
            completed.setCheckable(True)
            completed.setFixedSize(28, 28)
            completed.setIconSize(QSize(20, 20))
            completed.setAccessibleName(f"选择 {record['name']}")
            completed.setToolTip("选择 / 取消选择此记录")
            def select(checked, key=record["id"], control=completed):
                control.setIcon(icon("check-circle" if checked else "circle", "#5269ac" if checked else "#8c96a3", 20))
                self.change_selection(key, checked)
            completed.setChecked(record["id"] in self.selected)
            completed.setIcon(icon("check-circle" if completed.isChecked() else "circle", "#5269ac" if completed.isChecked() else "#8c96a3", 20))
            completed.toggled.connect(select)
            card.clicked.connect(completed.click)
        else:
            completed = QLabel()
            completed.setPixmap(icon("check-circle", "#327b88", 20).pixmap(20, 20))
            completed.setFixedSize(28, 28)
            completed.setAlignment(Qt.AlignCenter)
        timeline.addWidget(completed, 0, Qt.AlignHCenter)
        timestamp = QLabel(record["completed"][11:16])
        timestamp.setFixedHeight(18)
        timestamp.setObjectName("HistoryMeta")
        timestamp.setAlignment(Qt.AlignCenter)
        timeline.addWidget(timestamp)
        layout.addWidget(timeline_group, 0, Qt.AlignVCenter)
        thumb = button("▶", completed.click if self.selection_mode else lambda: self.open_media(record["id"]))
        thumb.setObjectName("HistoryThumb")
        thumb.setFixedHeight(78)
        thumb.setToolTip("选择 / 取消选择此记录" if self.selection_mode else "播放原文件核对")
        layout.addWidget(thumb, 0, Qt.AlignVCenter)
        self.thumbnails[record["id"]] = thumb
        text = QVBoxLayout()
        text.setSpacing(5)
        name = DocumentLink(record["name"])
        name.clicked.connect(completed.click if self.selection_mode else lambda: self.open_record(record["id"]))
        name.setFixedHeight(28)
        name.setObjectName("HistoryName")
        name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        text.addWidget(name)
        preview = ElidedLabel()
        preview.setObjectName("HistoryPreview")
        content = "内部文稿损坏，可清理此记录" if record["invalid"] else (record["edited"] if record["edited"] is not None else record["final"])
        preview.setText(" ".join(content[:240].split()))
        preview.setFixedHeight(22)
        if record["invalid"]:
            preview.setStyleSheet("color: #b34646;")
        text.addWidget(preview)
        meta = QHBoxLayout()
        meta.setSpacing(7)
        for value, tone in ((record["mode"], "mode"), (record["language"], "language")):
            tag = QLabel(value)
            tag.setTextFormat(Qt.PlainText)
            tag.setObjectName("HistoryTag")
            tag.setProperty("tone", tone)
            tag.setFixedHeight(22)
            tag.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
            tag.setToolTip(record["model"] if tone == "mode" else "识别语言")
            meta.addWidget(tag)
        duration = QLabel(clock(record["duration"]))
        duration.setObjectName("HistoryDuration")
        duration.setToolTip("音视频时长")
        meta.addWidget(duration)
        model = ElidedLabel()
        model.setObjectName("HistoryModel")
        model.setText(record["model"])
        model.setFixedHeight(22)
        meta.addWidget(model, 1)
        text.addLayout(meta)
        layout.addLayout(text, 1)
        more = button("", lambda: self.menu(record, more))
        more.setObjectName("HistoryMore")
        more.setFixedSize(36, 36)
        more.setIcon(icon("more-horizontal", "#5269ac", 20))
        more.setIconSize(QSize(20, 20))
        more.setToolTip("更多操作")
        more.setAccessibleName(f"{record['name']}，更多操作")
        layout.addWidget(more)
        name.setEnabled(not record["invalid"])
        suffix = Path(record["source"]).suffix.lower()
        audio = suffix in {".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg", ".opus"}
        if audio:
            thumb.setIcon(icon("music-2", "#327b88", 26))
            thumb.setIconSize(QSize(26, 26))
            thumb.setText("播放")
        else:
            cached = self.store.root / "thumbnails" / (hashlib.sha256(record["id"].encode()).hexdigest() + ".png")
            if cached.exists():
                self._thumbnail_ready(record["id"], str(cached))
            elif record["id"] not in self.jobs:
                job = ThumbnailJob(record, self.store.root, self.ffmpeg)
                self.jobs[record["id"]] = job
                job.signals.done.connect(self._thumbnail_ready)
                self.thumbnail_pool.start(job)
        return card

    def _thumbnail_ready(self, record_id, path):
        self.jobs.pop(record_id, None)
        if not path:
            return
        try:
            self.store.get(record_id)
        except ValueError:
            Path(path).unlink(missing_ok=True)
            return
        except Exception:
            return
        control = self.thumbnails.get(record_id)
        if control:
            from PySide6.QtGui import QIcon
            preview = QPixmap(path)
            if preview.isNull():
                return
            painter = QPainter(preview)
            painter.setRenderHint(QPainter.Antialiasing)
            center = preview.rect().center()
            radius = min(preview.width(), preview.height()) * 0.18
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(255, 255, 255, 235))
            painter.drawEllipse(QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2))
            triangle = QPainterPath()
            triangle.moveTo(center.x() - radius * 0.25, center.y() - radius * 0.5)
            triangle.lineTo(center.x() + radius * 0.55, center.y())
            triangle.lineTo(center.x() - radius * 0.25, center.y() + radius * 0.5)
            triangle.closeSubpath()
            painter.fillPath(triangle, QColor("#405362"))
            painter.end()
            control.setIcon(QIcon(preview))
            from PySide6.QtCore import QSize
            control.setIconSize(QSize(90, 70))
            control.setText("")

    def change_selection(self, record_id, checked):
        if checked:
            self.selected.add(record_id)
        else:
            self.selected.discard(record_id)
        self.selection_count.setText(f"已选 {len(self.selected)} 项")
        self.delete_button.setEnabled(bool(self.selected))

    def toggle_selection(self):
        self.selection_mode = not self.selection_mode
        self.selected.clear()
        decorate_button(self.select_button, "取消选择" if self.selection_mode else "批量删除")
        self.all_button.setVisible(self.selection_mode)
        self.delete_button.setVisible(self.selection_mode)
        self.render()

    def select_all(self):
        self.selected = self.store.all_matching_ids(self.search.text(), self.period.currentText())
        self.render()

    def menu(self, record, anchor, detail=False):
        menu = QMenu(self)
        menu.setAttribute(Qt.WA_TranslucentBackground)
        menu.setWindowFlag(Qt.FramelessWindowHint, True)
        actions = [
            ("转写信息", lambda: QMessageBox.information(self, "转写信息", self.metadata(record))),
            ("打开完整文字", lambda: self.open_record(record["id"])),
            ("复制全部文字", lambda: QApplication.clipboard().setText(record["edited"] if record["edited"] is not None else record["final"])),
            ("播放原文件核对", lambda: self.open_media(record["id"])),
            ("定位原文件", lambda: self.locate(record["source"])),
            ("定位导出文件", lambda: self.locate_export(record)),
            ("删除历史记录", lambda: self.delete_records({record["id"]})),
        ]
        names = ["info", "file-text", "copy", "play", "folder", "folder", "trash-2"]
        for index, (title, action) in enumerate(actions):
            if detail and index not in (0, 4, 5):
                continue
            if index in (4, 6):
                menu.addSeparator()
            color = "#b34646" if index == 6 else "#7959a8" if index == 2 else "#5269ac"
            menu.addAction(icon(names[index], color, 16), title, action)
        menu.exec(anchor.mapToGlobal(QPoint(0, anchor.height() + 6)))
        menu.deleteLater()

    def metadata(self, record):
        return f"{record['name']}\n{record['mode']} · {record['model']} · {record['language']}\n时长 {clock(record['duration'])} · 完成 {record['completed'][:19]}\n源文件：{record['source']}\n导出文件：" + ("\n".join(record["outputs"]) or "无") + ("\n" + "\n".join(record["warnings"]) if record["warnings"] else "")

    def detail_summary(self, record):
        completed = datetime.fromisoformat(record["completed"]).strftime("%Y/%m/%d %H:%M")
        return f"{record['mode']}  ·  {record['language']}  ·  时长 {clock(record['duration'])}  ·  完成 {completed}"

    def detail_message(self, text, tooltip=None):
        self.detail_feedback.setText(text)
        if tooltip:
            self.detail_feedback.setToolTip(tooltip)
        self.detail_feedback.setVisible(bool(text))

    def locate(self, path):
        self.run_action(lambda: self.reveal(Path(path)) if Path(path).exists() else (_ for _ in ()).throw(ValueError("文件已被移动或删除，历史文稿仍然保留")))

    def locate_export(self, record):
        path = next((path for path in reversed(record["outputs"]) if Path(path).exists()), None)
        if path:
            self.locate(path)
        else:
            QMessageBox.information(self, "导出文件不可用", "原导出文件已移动或删除。可打开完整文字重新导出，历史文稿仍然保留。")

    def open_record(self, record_id):
        def load():
            record = self.store.get(record_id)
            if record["invalid"]:
                raise ValueError("内部文稿损坏，请从已有导出文件保留内容后再清理记录")
            if not self.leave():
                return
            self.current_record = record
            self.detail_title.setText(record["name"])
            self.detail_meta.setText(self.detail_summary(record))
            self.detail_meta.setToolTip(f"{record['model']}\n完成时间：{record['completed'][:19].replace('T', ' ')}")
            self.detail_message("；".join(record["warnings"]))
            self.saved_text = record["edited"] if record["edited"] is not None else record["final"]
            self.editor.setPlainText(self.saved_text)
            self.stack.setCurrentIndex(1)
        self.run_action(load)

    def save_edit(self):
        self.store.edit(self.current_record["id"], self.editor.toPlainText())
        self.saved_text = self.editor.toPlainText()
        self.current_record = self.store.get(self.current_record["id"])
        self.detail_message("编辑已保存")

    def export(self):
        record = self.current_record
        suffix = {"TXT": ".txt", "Markdown": ".md", "SRT": ".srt", "DOCX": ".docx"}[self.format.currentText()]
        target, _ = QFileDialog.getSaveFileName(self, "导出历史文稿", str(Path.home() / (safe_output_stem(Path(record["name"]).stem) + suffix)), f"{self.format.currentText()} (*{suffix})")
        if not target:
            return
        if not target.lower().endswith(suffix):
            target += suffix
            if Path(target).exists() and QMessageBox.question(self, "覆盖导出文件？", f"{target}\n已存在，是否覆盖？", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
        def save():
            export_history_document(Path(target), Path(record["source"]), self.editor.toPlainText(), record["segments"])
            try:
                self.store.add_export(record["id"], target)
            except Exception as exc:
                self.detail_message("文件已导出，历史中的路径更新失败", target)
                raise RuntimeError(f"文件已成功导出到 {target}，但历史中的路径更新失败：{exc}") from exc
            self.current_record = self.store.get(record["id"])
            self.detail_message(f"已导出：{Path(target).name}", target)
        self.run_action(save)

    def delete_records(self, record_ids):
        ids = set(record_ids)
        if not ids:
            return
        if QMessageBox.question(self, "删除历史记录？", f"删除 {len(ids)} 条历史及软件内部文稿？\n原音视频、导出文件和模型缓存不会删除。", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        def remove():
            self.store.delete(ids)
            self.selected.difference_update(ids)
            self.reload()
        self.run_action(remove)

    def clean_invalid(self):
        self.run_action(lambda: self.delete_records(self.store.invalid_ids()))

    def open_media(self, record_id):
        def load():
            if not self.leave():
                return
            record = self.store.get(record_id)
            source = Path(record["source"])
            if not source.is_file():
                if QMessageBox.question(self, "原文件不可用", "原音视频已被移动或删除，历史文稿不受影响。是否重新选择原文件？", QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
                    return
                path, _ = QFileDialog.getOpenFileName(self, "重新定位原音视频")
                if not path:
                    return
                self.store.relink(record_id, path)
                record = self.store.get(record_id)
                source = Path(path)
            self.media_record = dict(record, segments=history_subtitle_cues(record["segments"]))
            is_audio = source.suffix.lower() in {".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg", ".opus"}
            self.media_title.setText(record["name"])
            self.cues.clear()
            for cue in self.media_record["segments"]:
                self.cues.addItem(f"{clock(cue['start'])} — {clock(cue['end'])}  {cue['text']}")
                self.cues.item(self.cues.count() - 1).setData(Qt.UserRole, cue["start"])
            self.media_view.set_caption("")
            self.media_status.clear()
            self.media_status.hide()
            self.cues.setToolTip("单击字幕跳转到对应时间")
            self.stack.setCurrentIndex(2)
            self.media_view.open(source, record["name"], is_audio)
        self.run_action(load)

    def _media_error(self, error, message):
        self.media_status.setText(f"无法播放：{message}。可定位原文件，使用系统播放器打开。")
        self.media_status.show()

    def play_pause(self):
        self.media_view.play_pause()

    def seek_to_cue(self, item):
        position = int(item.data(Qt.UserRole) * 1000)
        self.player.setPosition(position)
        self.media_view.position_changed(position)
        self.position_changed(position)
        self.media_view.show_controls(True)

    def position_changed(self, position):
        if not hasattr(self, "media_record"):
            return
        seconds = position / 1000
        index = next((i for i, cue in enumerate(self.media_record["segments"]) if cue["start"] <= seconds < cue["end"]), -1)
        self.media_view.set_caption(self.media_record["segments"][index]["text"] if index >= 0 else "")
        if self.cues.currentRow() != index:
            self.cues.setCurrentRow(index)
