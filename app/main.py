from __future__ import annotations

import importlib.util
import io
import math
import os
import subprocess
import sys
import time
import traceback
import wave
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import winsound
except ImportError:  # macOS 迁移时保留 Qt 的系统提示音回退。
    winsound = None

from PySide6.QtCore import QEvent, QObject, QRect, QRectF, QSize, QSettings, Qt, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap, QRegion
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QCheckBox,
    QComboBox,
    QDialog,
    QRadioButton,
    QScrollArea,
    QGraphicsDropShadowEffect,
    QProgressBar,
    QProgressDialog,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionButton,
    QStyleOptionComboBox,
    QStyleOptionViewItem,
    QStylePainter,
    QTableWidget,
    QTableWidgetItem,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .transcriber import (
    TranscriptionSession,
    TranscribeOptions,
    TranscribeResult,
    TranscribeStopped,
    default_output_dir,
    find_ffmpeg_dir,
    probe_duration_seconds,
    safe_output_stem,
    resolve_output_directory,
    transcribe_file,
    gpu_libraries_available,
)


from .model_modes import MODE_OPTIONS, MODE_MODEL_LABELS, mode_description, model_for_mode
from .product_info import APP_NAME, APP_VERSION, APP_DEVELOPED_AT, GITHUB_REPOSITORY, GITHUB_REPOSITORY_URL
SUPPORTED_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".mkv",
    ".avi",
    ".m4v",
    ".wmv",
    ".flv",
    ".webm",
    ".mp3",
    ".wav",
    ".m4a",
    ".aac",
    ".flac",
    ".ogg",
}
MODEL_OPTIONS = MODE_OPTIONS
LANGUAGE_OPTIONS = ["中文", "自动识别", "英文", "日语", "韩语"]
COMPUTE_MODE_OPTIONS = ["GPU 快速", "CPU 稳定"]
REQUIRED_DEPENDENCIES = {
    "faster_whisper": "faster-whisper",
    "docx": "python-docx",
}


def _is_frozen_runtime() -> bool:
    """PyInstaller 包内的运行时已随包携带依赖，无需再做模块发现扫描。"""
    return bool(getattr(sys, "frozen", False))


def _missing_runtime_dependencies(export_docx: bool) -> list[str]:
    """只在源码环境检测可选依赖，避免冻结版的 find_spec 阻塞界面线程。"""
    if _is_frozen_runtime():
        return []

    missing: list[str] = []
    if importlib.util.find_spec("faster_whisper") is None:
        missing.append(REQUIRED_DEPENDENCIES["faster_whisper"])
    if export_docx and importlib.util.find_spec("docx") is None:
        missing.append(REQUIRED_DEPENDENCIES["docx"])
    return missing

COL_INDEX = 0
COL_SELECT = 1
COL_STATUS = 2
COL_FILE = 3
COL_DURATION = 4
COL_LANGUAGE = 5
COL_MODEL = 6
COL_PROGRESS = 7
COL_ELAPSED = 8
COL_ETA = 9
COL_OUTPUT = 10
COL_LOCATE = 11

SOURCE_PATH_ROLE = Qt.UserRole
OUTPUT_FILE_ROLE = Qt.UserRole + 1


class CenteredCheckBoxDelegate(QStyledItemDelegate):
    @staticmethod
    def _check_state_value(check_state: Any) -> int:
        return int(getattr(check_state, "value", check_state))

    def paint(self, painter, option, index) -> None:
        check_state = index.data(Qt.CheckStateRole)
        if check_state is None:
            super().paint(painter, option, index)
            return

        style = option.widget.style() if option.widget else QApplication.style()
        style.drawPrimitive(QStyle.PE_PanelItemViewItem, option, painter, option.widget)
        indicator_width = style.pixelMetric(QStyle.PM_IndicatorWidth, None, option.widget)
        indicator_height = style.pixelMetric(QStyle.PM_IndicatorHeight, None, option.widget)
        indicator_rect = QRect(
            option.rect.center().x() - indicator_width // 2,
            option.rect.center().y() - indicator_height // 2,
            indicator_width,
            indicator_height,
        )

        checkbox_option = QStyleOptionButton()
        checkbox_option.rect = indicator_rect
        checkbox_option.state = QStyle.State_Enabled
        checkbox_option.state |= (
            QStyle.State_On
            if self._check_state_value(check_state) == Qt.CheckState.Checked.value
            else QStyle.State_Off
        )
        style.drawPrimitive(QStyle.PE_IndicatorItemViewItemCheck, checkbox_option, painter, option.widget)


class CompletionResultDialog(QDialog):
    """批量转写结束后的结果面板，避免把完成信息淹没在底部状态栏中。"""

    def __init__(self, parent: QWidget, summary: dict[str, int]) -> None:
        super().__init__(parent)
        success = summary.get("success", 0)
        failed = summary.get("failed", 0) + summary.get("no_text", 0)
        skipped = summary.get("skipped", 0)
        stopped = summary.get("stopped", 0)
        has_failure = failed > 0
        stopped_only = stopped > 0 and success == 0 and failed == 0

        self.setWindowTitle("转写结果")
        self.setModal(True)
        self.setMinimumWidth(470)
        self.setStyleSheet(
            "QDialog { background: #ffffff; }"
            "QLabel#ResultTitle { font-size: 19px; font-weight: 800; }"
            "QLabel#ResultSubtitle, QLabel#ResultHint { color: #55707a; }"
            "QFrame#ResultStat { border-radius: 8px; }"
            "QLabel#ResultNumber { font-size: 21px; font-weight: 800; }"
            "QLabel#ResultLabel { font-size: 12px; font-weight: 700; }"
            "QPushButton#ResultClose { min-width: 126px; background: #6075c8; color: #ffffff; "
            "border: none; border-radius: 18px; padding: 10px 22px; font-weight: 700; }"
            "QPushButton#ResultClose:hover { background: #5065b5; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 22)
        layout.setSpacing(12)

        if has_failure:
            title_text, title_color = "转写已结束，存在失败", "#dc2626"
            hint = "失败项目保留在队列中，可调整设置后重新勾选转写。"
        elif stopped_only:
            title_text, title_color = "转写已停止", "#475569"
            hint = "未完成项目保留在队列中，可重新勾选后继续转写。"
        else:
            title_text, title_color = "转写全部完成", "#16a34a"
            hint = "可在列表最右侧点击定位，快速查看对应的导出文件。"

        title = QLabel(title_text)
        title.setObjectName("ResultTitle")
        title.setStyleSheet(f"color: {title_color};")
        title.setAlignment(Qt.AlignCenter)
        subtitle = QLabel(f"本次处理 {success + failed + skipped + stopped} 项，请查看成功与失败结果。")
        subtitle.setObjectName("ResultSubtitle")
        subtitle.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        stats = QHBoxLayout()
        stats.setSpacing(10)
        for number, label, background, foreground, border in (
            (success, "成功", "#ecfdf3", "#15803d", "#bbf7d0"),
            (failed, "失败", "#fef2f2", "#dc2626", "#fecaca"),
            (skipped, "跳过", "#eff6ff", "#475569", "#cbd5e1"),
            (stopped, "停止", "#fff7ed", "#c2410c", "#fed7aa"),
        ):
            card = QFrame()
            card.setObjectName("ResultStat")
            # 使用带选择器的样式，避免外层卡片边框继承到内部数字和标签。
            card.setStyleSheet(
                f"QFrame#ResultStat {{ background: {background}; border: none; }}"
                "QFrame#ResultStat QLabel { background: transparent; border: none; }"
            )
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(10, 8, 10, 8)
            card_layout.setSpacing(2)
            number_label = QLabel(str(number))
            number_label.setObjectName("ResultNumber")
            number_label.setStyleSheet(f"color: {foreground};")
            number_label.setAlignment(Qt.AlignCenter)
            label_widget = QLabel(label)
            label_widget.setObjectName("ResultLabel")
            label_widget.setStyleSheet(f"color: {foreground};")
            label_widget.setAlignment(Qt.AlignCenter)
            card_layout.addWidget(number_label)
            card_layout.addWidget(label_widget)
            stats.addWidget(card, 1)
        layout.addLayout(stats)

        hint_label = QLabel(hint)
        hint_label.setObjectName("ResultHint")
        hint_label.setWordWrap(True)
        hint_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(hint_label)

        close_button = QPushButton("关闭")
        close_button.setObjectName("ResultClose")
        close_button.clicked.connect(self.accept)
        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_row.addWidget(close_button)
        close_row.addStretch(1)
        layout.addLayout(close_row)


class AboutDialog(QDialog):
    """展示当前版本可追溯的产品和开发者信息。"""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("关于")
        self.setModal(True)
        self.setMinimumWidth(620)
        self.setStyleSheet(
            "QDialog { background: #fbfbfb; }"
            "QLabel#AboutTitle { color: #102027; font-size: 24px; font-weight: 800; }"
            "QLabel#AboutProduct { color: #102027; font-size: 17px; font-weight: 800; }"
            "QLabel#AboutSectionTitle { color: #102027; font-size: 16px; font-weight: 800; }"
            "QLabel#AboutBody, QLabel#AboutHint { color: #42545b; font-size: 14px; }"
            "QLabel#AboutLink { color: #29434b; font-size: 14px; }"
            "QFrame#AboutCard { background: #ffffff; border: none; border-radius: 18px; }"
            "QFrame#AboutSeparator { background: #e7ecee; border: none; max-height: 1px; }"
            "QPushButton#AboutClose { min-width: 104px; background: #6075c8; color: #ffffff; "
            "border: none; border-radius: 18px; padding: 9px 18px; font-weight: 700; }"
            "QPushButton#AboutClose:hover { background: #5065b5; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(42, 26, 42, 26)
        layout.setSpacing(20)

        title = QLabel("关于")
        title.setObjectName("AboutTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        card = QFrame()
        card.setObjectName("AboutCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(30, 27, 30, 25)
        card_layout.setSpacing(0)

        product = QLabel("南枫转写 Windows")
        product.setObjectName("AboutProduct")
        description = QLabel("本地优先的批量音视频转写工作台。")
        description.setObjectName("AboutHint")
        card_layout.addWidget(product)
        card_layout.addWidget(description)
        card_layout.addSpacing(26)
        card_layout.addWidget(self._separator())
        card_layout.addSpacing(25)

        version_title = QLabel("版本信息")
        version_title.setObjectName("AboutSectionTitle")
        version = QLabel(f"Desktop 版 {APP_VERSION}")
        version.setObjectName("AboutBody")
        developed_at = QLabel(f"开发时间 {APP_DEVELOPED_AT}")
        developed_at.setObjectName("AboutBody")
        card_layout.addWidget(version_title)
        card_layout.addWidget(version)
        card_layout.addWidget(developed_at)
        card_layout.addSpacing(25)
        card_layout.addWidget(self._separator())
        card_layout.addSpacing(25)

        developer_title = QLabel("开发者信息")
        developer_title.setObjectName("AboutSectionTitle")
        developer = QLabel("开发者：席瑞")
        developer.setObjectName("AboutBody")
        email = QLabel("联系邮箱：nanzhufeng.studio@gmail.com")
        email.setObjectName("AboutBody")
        repository = QLabel(
            f'源码与更新：<a href="{GITHUB_REPOSITORY_URL}">GitHub · {GITHUB_REPOSITORY}</a>'
        )
        repository.setObjectName("AboutLink")
        repository.setOpenExternalLinks(True)
        copyright_label = QLabel("版权所有 © 2026 席瑞")
        copyright_label.setObjectName("AboutBody")
        card_layout.addWidget(developer_title)
        card_layout.addWidget(developer)
        card_layout.addWidget(email)
        card_layout.addWidget(repository)
        card_layout.addWidget(copyright_label)
        layout.addWidget(card)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_button = QPushButton("关闭")
        close_button.setObjectName("AboutClose")
        close_button.clicked.connect(self.accept)
        close_row.addWidget(close_button)
        close_row.addStretch(1)
        layout.addLayout(close_row)

    @staticmethod
    def _separator() -> QFrame:
        separator = QFrame()
        separator.setObjectName("AboutSeparator")
        separator.setFrameShape(QFrame.HLine)
        return separator


class AppSettingsDialog(QDialog):
    """集中放置会影响批量结束行为的可持久化偏好。"""

    def __init__(
        self,
        parent: QWidget,
        *,
        completion_sound: bool,
        completion_dialog: bool,
        auto_open_output: bool,
        create_video_subfolder: bool = False,
        save_beside_video: bool = False,
        precision_subtitles: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setModal(True)
        self.setWindowFlag(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumWidth(660)
        self.setStyleSheet(
            "QDialog { background: transparent; }"
            "QFrame#SettingsCard { background: #ffffff; border: none; border-radius: 18px; }"
            "QLabel { color: #182430; font-size: 14px; background: transparent; border: none; }"
            "QLabel#SettingsTitle { font-size: 22px; font-weight: 700; }"
            "QLabel#SectionTitle { font-size: 17px; font-weight: 700; }"
            "QLabel#SettingsHint { color: #687684; font-size: 12px; }"
            "QFrame#SettingsSection { background: #f4f4f4; border: none; border-radius: 12px; }"
            "QScrollArea, QWidget#SettingsContent { background: transparent; border: none; }"
            "QRadioButton { color: #182430; font-size: 14px; spacing: 10px; background: transparent; }"
            "QRadioButton::indicator { width: 18px; height: 18px; border-radius: 10px; border: 1px solid #aeb8c2; background: white; }"
            "QRadioButton::indicator:checked { border: 5px solid #6075c8; width: 10px; height: 10px; }"
            "QRadioButton:focus { color: #182430; }"
            "QPushButton { color: #27313d; font-size: 14px; font-weight: 600; background: #f1f3f5; border: none; border-radius: 20px; padding: 0 18px; }"
            "QPushButton:hover { background: #e7eaee; }"
            "QPushButton:focus { background: #e3e6ea; }"
            "QPushButton#SettingsSave { background: #6075c8; color: white; border: none; }"
            "QPushButton#SettingsSave:hover, QPushButton#SettingsSave:focus { background: #5065b5; }"
            "QPushButton#SettingsClose { border: none; background: transparent; border-radius: 16px; padding: 0; }"
            "QPushButton#SettingsClose:hover { background: #eef0f2; }"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        card = QFrame()
        card.setObjectName("SettingsCard")
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 3)
        shadow.setColor(QColor(20, 40, 55, 32))
        card.setGraphicsEffect(shadow)
        outer.addWidget(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(16)
        heading = QHBoxLayout()
        title = QLabel("设置")
        title.setObjectName("SettingsTitle")
        self._title_widget = title
        title.installEventFilter(self)
        heading.addWidget(title)
        heading.addStretch()
        close = QPushButton()
        close.setObjectName("SettingsClose")
        close.setIcon(parent._configuration_icon("x", "#7b8791"))
        close.setAccessibleName("关闭设置")
        close.setFixedSize(32, 32)
        close.clicked.connect(self.reject)
        heading.addWidget(close)
        layout.addLayout(heading)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("SettingsContent")
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(12)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        def section(name, icon):
            frame = QFrame()
            frame.setObjectName("SettingsSection")
            box = QVBoxLayout(frame)
            box.setContentsMargins(18, 16, 18, 18)
            box.setSpacing(12)
            row = QHBoxLayout()
            badge = QLabel()
            badge.setFixedSize(38, 38)
            badge.setAlignment(Qt.AlignCenter)
            badge.setStyleSheet("background: #eef0f2; border-radius: 19px;")
            badge.setPixmap(parent._configuration_icon(icon, "#374151").pixmap(22, 22))
            row.addWidget(badge)
            label = QLabel(name)
            label.setObjectName("SectionTitle")
            row.addWidget(label)
            row.addStretch()
            box.addLayout(row)
            return frame, box

        def hint(box, text):
            label = QLabel(text)
            label.setObjectName("SettingsHint")
            label.setWordWrap(True)
            box.addWidget(label)
            return label

        def toggle(box, text, checked):
            row = QHBoxLayout()
            label = QLabel(text)
            label.setWordWrap(True)
            row.addWidget(label, 1)
            switch = PolishSwitch()
            switch.setAccessibleName(text)
            switch.setChecked(checked)
            row.addWidget(switch)
            box.addLayout(row)
            label.setBuddy(switch)
            return switch

        output, output_box = section("保存与目录", "folder")
        output_box.addWidget(QLabel("保存位置"))
        self.software_path_radio = QRadioButton("软件指定路径", output)
        self.save_beside_video_check = QRadioButton("视频所在目录", output)
        self.software_path_radio.setChecked(not save_beside_video)
        self.save_beside_video_check.setChecked(save_beside_video)
        output_box.addWidget(self.software_path_radio)
        output_box.addWidget(self.save_beside_video_check)
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet("background: #e5e7eb;")
        output_box.addWidget(line)
        self.create_video_subfolder_check = toggle(output_box, "新建视频同名子文件夹", create_video_subfolder)
        hint(output_box, "关闭时直接保存到目标目录。")
        body.addWidget(output)
        lower = QHBoxLayout()
        lower.setSpacing(12)
        subtitles, subtitles_box = section("字幕处理", "file")
        self.precision_subtitles_check = toggle(subtitles_box, "快速模式精确字幕对齐", precision_subtitles)
        hint(subtitles_box, "中文精确模式自动对齐；开启后快速模式也对齐，耗时增加。")
        subtitles_box.addStretch()
        completion, completion_box = section("完成提醒", "bell")
        self.completion_sound_check = toggle(completion_box, "完成提示音", completion_sound)
        self.completion_dialog_check = toggle(completion_box, "完成提示", completion_dialog)
        self.auto_open_output_check = toggle(completion_box, "完成后定位结果", auto_open_output)
        self.auto_open_output_check.setToolTip("仅在本次没有失败、无文字或主动停止项目时，定位并选中最近完成的导出文件。")
        hint(completion_box, "全部完成后，选中最近导出文件。")
        lower.addWidget(subtitles, 1)
        lower.addWidget(completion, 1)
        body.addLayout(lower)
        buttons = QHBoxLayout()
        about_button = QPushButton("关于南枫转写")
        about_button.setObjectName("SettingsCancel")
        about_button.setIcon(parent._configuration_icon("info", "#405362"))
        about_button.setFixedHeight(40)
        about_button.clicked.connect(self._open_about)
        buttons.addWidget(about_button)
        buttons.addStretch(1)
        cancel_button = QPushButton("取消")
        cancel_button.setObjectName("SettingsCancel")
        cancel_button.setFixedSize(94, 40)
        cancel_button.clicked.connect(self.reject)
        save_button = QPushButton("保存")
        save_button.setObjectName("SettingsSave")
        save_button.setFixedSize(108, 40)
        save_button.clicked.connect(self.accept)
        buttons.addWidget(cancel_button)
        buttons.addWidget(save_button)
        layout.addLayout(buttons)
        self.resize(700, min(670, QApplication.primaryScreen().availableGeometry().height() - 48))

    def eventFilter(self, watched, event):
        if watched is getattr(self, "_title_widget", None) and event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            if self.windowHandle():
                self.windowHandle().startSystemMove()
            return True
        return super().eventFilter(watched, event)

    def _open_about(self) -> None:
        AboutDialog(self).exec()

    def values(self) -> dict[str, bool]:
        return {
            "completion_sound": self.completion_sound_check.isChecked(),
            "completion_dialog": self.completion_dialog_check.isChecked(),
            "auto_open_output": self.auto_open_output_check.isChecked(),
            "create_video_subfolder": self.create_video_subfolder_check.isChecked(),
            "save_beside_video": self.save_beside_video_check.isChecked(),
            "precision_subtitles": self.precision_subtitles_check.isChecked(),
        }


class ComboTriggerFilter(QObject):
    def __init__(self, combo):
        super().__init__(combo)
        self.combo = combo

    def eventFilter(self, watched, event):
        return self.combo.filter_trigger_click(event)


class ToggleComboBox(QComboBox):
    """Consume a second trigger click before Qt dismisses and reopens its popup."""
    def __init__(self):
        super().__init__()
        self._trigger_press_active = False
        self._trigger_filter = ComboTriggerFilter(self)
        QApplication.instance().installEventFilter(self._trigger_filter)

    def filter_trigger_click(self, event):
        if event.type() == QEvent.MouseButtonRelease:
            self._trigger_press_active = False
        if (event.type() == QEvent.MouseButtonPress
                and event.button() == Qt.LeftButton
                and not self._trigger_press_active
                and self.view().isVisible()
                and self.rect().contains(self.mapFromGlobal(event.globalPosition().toPoint()))):
            self.hidePopup()
            self._trigger_press_active = True
            event.accept()
            return True
        return False

    def _toggle_popup(self):
        if self._trigger_press_active:
            return
        self._trigger_press_active = True
        if self.view().isVisible():
            self.hidePopup()
        else:
            self.showPopup()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._toggle_popup()
            event.accept()
        else:
            super().mousePressEvent(event)


class CenterComboBox(ToggleComboBox):
    def __init__(self) -> None:
        super().__init__()
        self.setEditable(True)
        self.lineEdit().setReadOnly(True)
        self.lineEdit().setAlignment(Qt.AlignCenter)
        self.lineEdit().setFocusPolicy(Qt.NoFocus)
        self.lineEdit().installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.lineEdit() and event.type() == QEvent.MouseButtonPress:
            self._toggle_popup()
            return True
        return super().eventFilter(watched, event)

def draw_mode_lines(painter, rect, name, model, selected=False):
    painter.save()
    title_font = QFont(painter.font())
    title_font.setPixelSize(13)
    title_font.setWeight(QFont.DemiBold)
    painter.setFont(title_font)
    painter.setPen(QColor("#1f2937") if selected else QColor("#374151"))
    painter.drawText(QRect(rect.x(), rect.y(), rect.width(), rect.height() // 2), Qt.AlignCenter, name)
    model_font = QFont(title_font)
    model_font.setPixelSize(11)
    model_font.setWeight(QFont.Normal)
    painter.setFont(model_font)
    painter.setPen(QColor("#4b5563") if selected else QColor("#6b7280"))
    painter.drawText(QRect(rect.x(), rect.y() + rect.height() // 2, rect.width(), rect.height() // 2), Qt.AlignCenter, model)
    painter.restore()


class ModeItemDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(210, 52)

    def paint(self, painter, option, index):
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setFont(option.font)
        painter.fillRect(option.rect, QColor("#ffffff"))
        surface = option.rect.adjusted(4, 2, -4, -2)
        painter.setPen(Qt.NoPen)
        focused = bool(option.state & QStyle.State_HasFocus)
        painter.setBrush(QColor("#f4f4f4") if selected or hovered or focused else QColor("#ffffff"))
        painter.drawRoundedRect(surface, 6, 6)
        if selected:
            painter.setBrush(QColor("#c43c3c"))
            painter.drawRoundedRect(surface.left() + 2, surface.center().y() - 10, 2, 20, 1, 1)
        draw_mode_lines(painter, option.rect.adjusted(8, 4, -8, -4), index.data(), index.data(Qt.UserRole), selected)
        painter.restore()


class QueuePanel(QWidget):
    """Own the queue silhouette and the continuous header background."""

    RADIUS = 16

    def __init__(self, table):
        super().__init__()
        self.table = table
        self.header = table.horizontalHeader()
        self.setObjectName("QueuePanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(table)
        table.installEventFilter(self)
        self.header.installEventFilter(self)

    def eventFilter(self, watched, event):
        if watched is self.table and event.type() == QEvent.Resize:
            path = QPainterPath()
            path.addRoundedRect(QRectF(self.table.rect()), self.RADIUS, self.RADIUS)
            self.table.setMask(QRegion(path.toFillPolygon().toPolygon()))
        if watched is self.header and event.type() == QEvent.Resize:
            self.update()
        return super().eventFilter(watched, event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        outline = QPainterPath()
        outline.addRoundedRect(QRectF(self.rect()), self.RADIUS, self.RADIUS)
        painter.setClipPath(outline)
        painter.fillRect(self.rect(), QColor("#ffffff"))
        painter.fillRect(0, 0, self.width(), self.header.height(), QColor("#f4f4f4"))


class FormatChoice(QCheckBox):
    def hitButton(self, position):
        return self.rect().contains(position)


class PolishSwitch(QCheckBox):
    def __init__(self):
        super().__init__()
        self.setFixedSize(52, 30)
        self.setAccessibleName("翻译润色")
        self.setCursor(Qt.PointingHandCursor)
        self._keyboard_focus = False

    def focusInEvent(self, event):
        self._keyboard_focus = event.reason() in (Qt.TabFocusReason, Qt.BacktabFocusReason, Qt.ShortcutFocusReason)
        super().focusInEvent(event)
        self.update()

    def mousePressEvent(self, event):
        self._keyboard_focus = False
        super().mousePressEvent(event)
        self.update()

    def keyPressEvent(self, event):
        self._keyboard_focus = True
        super().keyPressEvent(event)
        self.update()

    def hitButton(self, position):
        return self.rect().contains(position)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        track = QPainterPath()
        track.addRoundedRect(QRectF(1.5, 1.5, self.width() - 3, self.height() - 3), 13.5, 13.5)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#6075c8") if self.isChecked() else QColor("#d7dbe0"))
        painter.drawPath(track)
        if self.hasFocus() and self._keyboard_focus:
            painter.setPen(QPen(QColor("#6b7280"), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(track)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(27 if self.isChecked() else 5, 5, 20, 20)


class TranscriptionModeCombo(ToggleComboBox):
    """Show only the Chinese name when closed; model details live in the menu."""
    def __init__(self):
        super().__init__()
        self.setItemDelegate(ModeItemDelegate(self))
        self.setFixedSize(150, 36)
        self.view().setMinimumWidth(220)
        for name in MODE_OPTIONS:
            self.addItem(name, MODE_MODEL_LABELS[name])
        for index in range(self.count()):
            self.setItemData(index, mode_description(self.itemText(index))[0], Qt.ToolTipRole)
        self.currentTextChanged.connect(lambda name: self.setToolTip(mode_description(name)[0]))
        self.setToolTip(mode_description(self.currentText())[0])

    def paintEvent(self, event):
        painter = QStylePainter(self)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        option.currentText = ""
        painter.drawComplexControl(QStyle.CC_ComboBox, option)
        field = self.style().subControlRect(QStyle.CC_ComboBox, option, QStyle.SC_ComboBoxEditField, self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.drawText(field, Qt.AlignCenter, self.currentText())

@dataclass
class QueueItem:
    path: Path
    row: int
    model_size: str
    language: str


class TranscribeWorker(QObject):
    item_started = Signal(int)
    item_progress = Signal(int, dict)
    item_finished = Signal(int, object)
    item_failed = Signal(int, str)
    item_stopped = Signal(int)
    all_done = Signal()

    def __init__(self, items: list[QueueItem], options: TranscribeOptions) -> None:
        super().__init__()
        self.items = items
        self.options = options
        self._cancel_requested = False

    @Slot()
    def run(self) -> None:
        from dataclasses import replace

        session = TranscriptionSession()
        try:
            for item in self.items:
                if self._cancel_requested:
                    break
                self.item_started.emit(item.row)
                item_options = replace(self.options, model_size=item.model_size, language=item.language)
                try:
                    result = transcribe_file(
                        item.path,
                        item_options,
                        lambda info, row=item.row: self.item_progress.emit(row, info),
                        self.is_cancel_requested,
                        session=session,
                    )
                except TranscribeStopped:
                    self.item_stopped.emit(item.row)
                    break
                except Exception as exc:
                    detail = "".join(traceback.format_exception_only(type(exc), exc)).strip()
                    self.item_failed.emit(item.row, detail)
                else:
                    self.item_finished.emit(item.row, result)
        finally:
            session.close()
            self.all_done.emit()

    def cancel(self) -> None:
        self._cancel_requested = True

    def is_cancel_requested(self) -> bool:
        return self._cancel_requested


class DependencyInstallWorker(QObject):
    finished = Signal(bool, str)

    @Slot()
    def run(self) -> None:
        requirements = Path(__file__).resolve().parents[1] / "requirements.txt"
        command = [sys.executable, "-m", "pip", "install", "-r", str(requirements)]
        startupinfo = None
        creationflags = 0
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            completed = subprocess.run(
                command,
                cwd=str(requirements.parent),
                capture_output=True,
                text=True,
                startupinfo=startupinfo,
                creationflags=creationflags,
            )
        except Exception as exc:
            self.finished.emit(False, f"依赖安装启动失败：{exc}")
            return
        if completed.returncode == 0:
            importlib.invalidate_caches()
            self.finished.emit(True, "依赖安装完成。")
            return
        detail = (completed.stderr or completed.stdout or "未知错误").strip()
        self.finished.emit(False, f"依赖安装失败：{detail[:500]}")


class MainWindow(QMainWindow):
    def __init__(self, settings: QSettings | None = None) -> None:
        super().__init__()
        self.settings = settings if settings is not None else QSettings("Nanzhufeng", "NanfengTranscriber")
        from .history import HistoryStore
        history_root = (Path(self.settings.fileName()).parent / "history") if settings is not None else Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "NanfengTranscriber" / "history"
        self.history_store = HistoryStore(history_root)
        self.history_page = None
        self.pending_history_results = {}
        self.project_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
        self.ffmpeg_dir = find_ffmpeg_dir(self.project_root)
        self.runtime_log_path = self.project_root / "runtime-log.txt"
        self.worker_thread: QThread | None = None
        self.worker: TranscribeWorker | None = None
        self.install_thread: QThread | None = None
        self.install_worker: DependencyInstallWorker | None = None
        self.install_progress: QProgressDialog | None = None
        self.start_after_install = False
        self.active_rows: set[int] = set()
        self.current_run_skipped_count = 0
        self.pending_completion_summary: dict[str, int] | None = None
        self.pending_completion_target: Path | None = None
        self.started_at: float | None = None
        self.check_drag_active = False
        self.check_drag_state = Qt.Unchecked
        self.check_drag_rows: set[int] = set()
        self.gpu_runtime_warning_ack = False

        self.setWindowTitle(APP_NAME)
        icon_path = self._asset_path("nanfeng-transcriber-icon.png")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.resize(1820, 1130)
        self.setAcceptDrops(True)
        self._build_ui()
        self._restore_settings()
        self._connect_settings_signals()
        self._apply_style()
        self._lock_add_button_widths()
        self._update_status()
        self._debug_log("app started")

    @staticmethod
    def _setting_bool(value: Any, default: bool) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def _restore_combo_setting(self, combo: QComboBox, key: str, default: str) -> None:
        value = str(self.settings.value(key, default))
        combo.setCurrentText(value if combo.findText(value) >= 0 else default)

    def _restore_settings(self) -> None:
        self.output_edit.setText(str(self.settings.value("transcription/output_dir", str(default_output_dir()))))
        saved_model = str(self.settings.value("transcription/model", "中文精确"))
        self.model_combo.setCurrentText(saved_model if saved_model in MODEL_OPTIONS else "通用快速")
        self._restore_combo_setting(self.language_combo, "transcription/language", "中文")
        self._restore_combo_setting(self.compute_mode_combo, "transcription/compute_mode", "GPU 快速")
        self.completion_sound_enabled = self._setting_bool(
            self.settings.value("preferences/completion_sound"), True
        )
        self.completion_dialog_enabled = self._setting_bool(
            self.settings.value("preferences/completion_dialog"), True
        )
        self.auto_open_output_enabled = self._setting_bool(
            self.settings.value("preferences/auto_open_output"), False
        )
        self.create_video_subfolder = self._setting_bool(
            self.settings.value("preferences/create_video_subfolder"), False
        )
        self.save_beside_video = self._setting_bool(
            self.settings.value("preferences/save_beside_video"), False
        )
        self.precision_subtitles = self._setting_bool(self.settings.value("preferences/precision_subtitles"), False)
        defaults = {
            "export_txt": True,
            "export_md": True,
            "export_srt": True,
            "export_docx": True,
            "polish": bool(os.environ.get("NANZHU_TEXT_API_KEY") or os.environ.get("OPENAI_API_KEY")),
        }
        for key, checkbox in {
            "export_txt": self.txt_check,
            "export_md": self.md_check,
            "export_srt": self.srt_check,
            "export_docx": self.docx_check,
            "polish": self.polish_check,
        }.items():
            checkbox.setChecked(self._setting_bool(self.settings.value(f"transcription/{key}"), defaults[key]))

    def _connect_settings_signals(self) -> None:
        self.output_edit.editingFinished.connect(self._save_settings)
        for combo in (self.model_combo, self.language_combo, self.compute_mode_combo):
            combo.currentTextChanged.connect(self._save_settings)
        for checkbox in (self.txt_check, self.md_check, self.srt_check, self.docx_check, self.polish_check):
            checkbox.toggled.connect(self._save_settings)

    @Slot()
    def _save_settings(self) -> None:
        values = {
            "output_dir": self.output_edit.text().strip(),
            "model": self.model_combo.currentText(),
            "language": self.language_combo.currentText(),
            "compute_mode": self.compute_mode_combo.currentText(),
            "export_txt": self.txt_check.isChecked(),
            "export_md": self.md_check.isChecked(),
            "export_srt": self.srt_check.isChecked(),
            "export_docx": self.docx_check.isChecked(),
            "polish": self.polish_check.isChecked(),
        }
        for key, value in values.items():
            self.settings.setValue(f"transcription/{key}", value)
        self.settings.setValue("preferences/completion_sound", self.completion_sound_enabled)
        self.settings.setValue("preferences/completion_dialog", self.completion_dialog_enabled)
        self.settings.setValue("preferences/auto_open_output", self.auto_open_output_enabled)
        self.settings.setValue("preferences/create_video_subfolder", self.create_video_subfolder)
        self.settings.setValue("preferences/save_beside_video", self.save_beside_video)
        self.settings.setValue("preferences/precision_subtitles", self.precision_subtitles)
        self.settings.sync()

    def closeEvent(self, event) -> None:
        if self.history_page is not None and not self.history_page.leave():
            event.ignore()
            return
        if self.history_page is not None:
            self.history_page.shutdown()
        self._save_settings()
        super().closeEvent(event)

    def _asset_path(self, name: str) -> Path:
        return self.project_root / "app" / "assets" / name

    def _debug_log(self, message: str) -> None:
        try:
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.runtime_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.runtime_log_path.open("a", encoding="utf-8") as handle:
                handle.write(f"[{stamp}] {message}\n")
        except Exception:
            pass

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        shell = QHBoxLayout(root)
        shell.setContentsMargins(24, 24, 24, 24)
        shell.setSpacing(18)

        sidebar = QFrame()
        self.sidebar = sidebar
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(260)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(18, 22, 18, 18)
        sidebar_layout.setSpacing(14)

        brand_mark = QLabel("南")
        brand_mark.setObjectName("BrandMark")
        brand_title = QLabel(APP_NAME)
        brand_title.setObjectName("BrandTitle")
        brand_subtitle = QLabel("音视频文稿工作台")
        brand_subtitle.setObjectName("BrandSubtitle")
        brand_row = QHBoxLayout()
        brand_row.setSpacing(12)
        brand_row.addWidget(brand_mark)
        brand_text = QVBoxLayout()
        brand_text.setSpacing(4)
        brand_text.addWidget(brand_title)
        brand_text.addWidget(brand_subtitle)
        brand_row.addLayout(brand_text, 1)
        sidebar_layout.addLayout(brand_row)

        def separator():
            line = QFrame()
            line.setObjectName("SidebarSeparator")
            line.setFixedHeight(1)
            sidebar_layout.addSpacing(6)
            sidebar_layout.addWidget(line)
            sidebar_layout.addSpacing(4)

        separator()

        module_title = QLabel("输出格式")
        module_title.setObjectName("SideSectionTitle")
        sidebar_layout.addWidget(module_title)
        formats = QGridLayout()
        formats.setSpacing(8)
        for index, (name, icon) in enumerate((("TXT", "file"), ("Markdown", "file-type"), ("SRT", "file-text"), ("DOCX", "file-type"))):
            tile = QFrame()
            tile.setObjectName("SidebarFormat")
            tile.setFixedHeight(44)
            tile.setToolTip(f"支持导出 {name} 格式；在主界面选择导出格式。")
            row = QHBoxLayout(tile)
            row.setContentsMargins(10, 0, 8, 0)
            row.setSpacing(6)
            symbol = QLabel()
            symbol.setPixmap(self._configuration_icon(icon, "#405362").pixmap(18, 18))
            row.addWidget(symbol)
            text = QLabel(name)
            text.setObjectName("SidebarFormatLabel")
            row.addWidget(text)
            row.addStretch()
            formats.addWidget(tile, index // 2, index % 2)
        formats.setColumnStretch(0, 1)
        formats.setColumnStretch(1, 1)
        sidebar_layout.addLayout(formats)
        separator()

        workflow_title = QLabel("操作流程")
        workflow_title.setObjectName("SideSectionTitle")
        sidebar_layout.addWidget(workflow_title)
        steps = QVBoxLayout()
        steps.setSpacing(0)
        for index, (text, icon) in enumerate((("添加文件", "folder"), ("选择模型", "cpu"), ("开始转写", "play"), ("检查导出", "file-search")), start=1):
            row = QHBoxLayout()
            row.setSpacing(14)
            number = QLabel(f"{index:02d}")
            number.setObjectName("WorkflowNumber")
            number.setFixedSize(30, 30)
            number.setAlignment(Qt.AlignCenter)
            row.addWidget(number)
            symbol = QLabel()
            symbol.setPixmap(self._configuration_icon(icon, "#405362").pixmap(20, 20))
            row.addWidget(symbol)
            label = QLabel(text)
            label.setObjectName("WorkflowLabel")
            row.addWidget(label, 1)
            steps.addLayout(row)
            if index < 4:
                connector = QFrame()
                connector.setObjectName("WorkflowConnector")
                connector.setFixedSize(2, 22)
                connection_row = QHBoxLayout()
                connection_row.setContentsMargins(14, 4, 0, 4)
                connection_row.addWidget(connector)
                connection_row.addStretch()
                steps.addLayout(connection_row)
        sidebar_layout.addLayout(steps)
        sidebar_layout.addStretch(1)
        separator()

        self.open_folder_button = QPushButton("打开输出目录")
        self.open_folder_button.setObjectName("PrimaryButton")
        self.open_folder_button.setIcon(self._configuration_icon("folder", "#ffffff"))
        self.open_folder_button.setFixedHeight(38)
        self.open_folder_button.clicked.connect(self._open_output_dir)
        self.settings_button = QPushButton("设置")
        self.settings_button.setObjectName("SideSettingsButton")
        self.settings_button.setIcon(self._configuration_icon("settings", "#405362"))
        self.settings_button.setFixedHeight(40)
        self.settings_button.clicked.connect(self._open_settings)
        self.history_button = QPushButton("历史")
        self.history_button.setObjectName("SideSettingsButton")
        self.history_button.setCheckable(True)
        self.history_button.setFixedHeight(40)
        self.history_button.setIcon(self._configuration_icon("history", "#5269ac"))
        self.history_button.clicked.connect(self._show_history)
        sidebar_layout.addWidget(self.history_button)
        sidebar_layout.addWidget(self.settings_button)
        shell.addWidget(sidebar)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        self.workbench_page = content
        self.right_stack = QStackedWidget()
        self.right_stack.addWidget(content)
        shell.addWidget(self.right_stack, 1)

        input_frame = QFrame()
        input_frame.setObjectName("ConfigurationPanel")
        input_layout = QHBoxLayout(input_frame)
        input_layout.setContentsMargins(24, 24, 24, 24)
        input_layout.setSpacing(24)

        output_label = QLabel("保存位置")
        output_label.setObjectName("FieldLabel")
        self.output_edit = QLineEdit(str(default_output_dir()))
        self.output_button = QPushButton("选择")
        self.output_button.setObjectName("ChooseButton")
        self.output_button.clicked.connect(self._choose_output_dir)

        model_label = QLabel("转写模式")
        model_label.setObjectName("FieldLabel")
        self.model_combo = TranscriptionModeCombo()
        self.model_combo.setCurrentText("中文精确")

        language_label = QLabel("语言")
        language_label.setObjectName("FieldLabel")
        self.language_combo = CenterComboBox()
        self.language_combo.addItems(LANGUAGE_OPTIONS)
        self.language_combo.setCurrentText("中文")
        self.language_combo.setMinimumWidth(110)

        mode_label = QLabel("运行方式")
        mode_label.setObjectName("FieldLabel")
        self.compute_mode_combo = CenterComboBox()
        self.compute_mode_combo.addItems(COMPUTE_MODE_OPTIONS)
        self.compute_mode_combo.setCurrentText("GPU 快速")
        self.compute_mode_combo.setMinimumWidth(120)

        format_label = QLabel("导出格式")
        format_label.setObjectName("FieldLabel")
        self.txt_check = FormatChoice("TXT")
        self.txt_check.setChecked(True)
        self.md_check = FormatChoice("Markdown")
        self.md_check.setChecked(True)
        self.srt_check = FormatChoice("SRT")
        self.srt_check.setChecked(True)
        self.docx_check = FormatChoice("DOCX")
        self.docx_check.setChecked(True)
        self.polish_check = PolishSwitch()
        self.polish_check.setChecked(bool(os.environ.get("NANZHU_TEXT_API_KEY") or os.environ.get("OPENAI_API_KEY")))
        self.polish_check.setToolTip("开启后会调用文本 API，把转写稿翻译/整理为现代简体中文。需要配置 NANZHU_TEXT_API_KEY 或 OPENAI_API_KEY。")
        format_row = QGridLayout()
        format_row.setContentsMargins(0, 0, 0, 0)
        format_row.setSpacing(12)
        for position, choice in enumerate((self.txt_check, self.md_check, self.srt_check, self.docx_check)):
            choice.setObjectName("FormatChoice")
            choice.setMinimumHeight(44)
            format_row.addWidget(choice, position // 2, position % 2)

        self.add_files_button = QPushButton("添加文件")
        self.add_files_button.setObjectName("AddFileButton")
        self.add_files_button.setIcon(self._configuration_icon("folder", "#a65e28"))
        self.add_files_button.setIconSize(QSize(18, 18))
        self.add_files_button.clicked.connect(self._choose_files)
        self.add_folder_button = QPushButton("添加文件夹")
        self.add_folder_button.setObjectName("AddFolderButton")
        self.add_folder_button.setIcon(self._configuration_icon("folder-plus", "#7653aa"))
        self.add_folder_button.setIconSize(QSize(18, 18))
        self.add_folder_button.clicked.connect(self._choose_folder)
        add_button_row = QHBoxLayout()
        add_button_row.setContentsMargins(0, 0, 0, 0)
        add_button_row.setSpacing(10)
        add_button_row.addWidget(self.add_files_button)
        add_button_row.addWidget(self.add_folder_button)
        def group(title, number):
            widget = QWidget()
            box = QVBoxLayout(widget)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(20)
            heading = QHBoxLayout()
            heading.setSpacing(10)
            mark = QLabel(number)
            mark.setObjectName("ConfigurationStep")
            mark.setAlignment(Qt.AlignCenter)
            mark.setFixedSize(42, 42)
            label = QLabel(title)
            label.setObjectName("ConfigurationHeading")
            heading.addWidget(mark)
            heading.addWidget(label)
            heading.addStretch()
            box.addLayout(heading)
            return widget, box

        def separator():
            line = QFrame()
            line.setObjectName("ConfigurationDivider")
            line.setFixedWidth(1)
            return line

        files_group, files_box = group("导入", "01")
        files_box.addSpacing(4)
        files_box.addLayout(add_button_row)
        path_box = QVBoxLayout()
        path_box.setSpacing(7)
        path_box.addWidget(output_label)
        path_row = QHBoxLayout()
        path_row.setSpacing(8)
        self.output_edit.setFixedHeight(40)
        self.output_button.setFixedHeight(40)
        self.output_button.setMinimumWidth(68)
        path_row.addWidget(self.output_edit, 1)
        path_row.addWidget(self.output_button)
        path_box.addLayout(path_row)
        files_box.addLayout(path_box)
        files_box.addStretch(1)

        transcription_group, transcription_box = group("转写", "02")
        fields = QGridLayout()
        fields.setHorizontalSpacing(16)
        fields.setVerticalSpacing(12)
        self.model_combo.setFixedHeight(40)
        self.model_combo.setMinimumWidth(0)
        self.model_combo.setMaximumWidth(16777215)
        for index, (label, control) in enumerate(((model_label, self.model_combo), (language_label, self.language_combo), (mode_label, self.compute_mode_combo))):
            control.setFixedHeight(40)
            fields.addWidget(label, index, 0)
            fields.addWidget(control, index, 1)
        fields.setColumnStretch(1, 1)
        transcription_box.addLayout(fields)
        transcription_box.addStretch(1)

        export_group, export_box = group("导出", "03")
        formats_box = QVBoxLayout()
        formats_box.setSpacing(15)
        formats_box.addWidget(format_label)
        formats_box.addLayout(format_row)
        polish_box = QHBoxLayout()
        polish_box.setSpacing(10)
        polish_label = QLabel("翻译润色")
        polish_label.setObjectName("FieldLabel")
        polish_box.addWidget(polish_label)
        polish_box.addWidget(self.polish_check)
        polish_box.addStretch(1)
        export_box.addLayout(formats_box)
        export_box.addLayout(polish_box)
        export_box.addStretch(1)

        input_layout.addWidget(files_group, 5)
        input_layout.addWidget(separator())
        input_layout.addWidget(transcription_group, 5)
        input_layout.addWidget(separator())
        input_layout.addWidget(export_group, 5)
        layout.addWidget(input_frame)

        action_frame = QFrame()
        action_frame.setObjectName("ActionPanel")
        action_layout = QHBoxLayout(action_frame)
        action_layout.setContentsMargins(14, 12, 14, 12)
        action_layout.setSpacing(10)
        self.start_button = QPushButton("开始转写")
        self.start_button.setObjectName("PrimaryButton")
        self.start_button.clicked.connect(self._start)
        self.stop_button = QPushButton("停止")
        self.stop_button.setObjectName("StopButton")
        self.stop_button.clicked.connect(self._stop)
        self.stop_button.setEnabled(False)
        self.clear_button = QPushButton("清空队列")
        self.clear_button.setObjectName("ClearButton")
        self.clear_button.clicked.connect(self._clear)
        self.select_all_button = QPushButton("全选")
        self.select_all_button.setObjectName("SelectButton")
        self.select_all_button.clicked.connect(self._select_all)
        self.invert_button = QPushButton("反选")
        self.invert_button.setObjectName("InvertButton")
        self.invert_button.clicked.connect(self._invert)
        for button in (self.start_button, self.stop_button, self.clear_button, self.select_all_button, self.invert_button):
            button.setFixedHeight(38)
        action_layout.addWidget(self.start_button)
        action_layout.addWidget(self.stop_button)
        action_layout.addWidget(self.clear_button)
        action_layout.addSpacing(12)
        action_layout.addWidget(self.select_all_button)
        action_layout.addWidget(self.invert_button)
        action_layout.addStretch(1)
        action_layout.addWidget(self.open_folder_button)
        layout.addWidget(action_frame)

        self.table = QTableWidget(0, 12)
        self.table.setObjectName("QueueTable")
        self.table.viewport().setObjectName("QueueViewport")
        self.table.setHorizontalHeaderLabels(["序号", "选择", "状态", "文件名", "时长", "语言", "转写模式", "进度", "耗时", "剩余", "输出路径", "定位"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideRight)
        self.table.itemClicked.connect(self._on_table_item_clicked)
        self.table.viewport().installEventFilter(self)
        self.table.setItemDelegateForColumn(COL_SELECT, CenteredCheckBoxDelegate(self.table))
        header = self.table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignCenter)
        for column, width in {
            COL_INDEX: 54,
            COL_SELECT: 58,
            COL_STATUS: 86,
            COL_DURATION: 90,
            COL_LANGUAGE: 112,
            COL_MODEL: 108,
            COL_PROGRESS: 72,
            COL_ELAPSED: 78,
            COL_ETA: 150,
            COL_LOCATE: 70,
        }.items():
            header.setSectionResizeMode(column, QHeaderView.Fixed)
            self.table.setColumnWidth(column, width)
        header.setSectionResizeMode(COL_FILE, QHeaderView.Stretch)
        header.setSectionResizeMode(COL_OUTPUT, QHeaderView.Stretch)
        queue_panel = QueuePanel(self.table)
        layout.addWidget(queue_panel, 1)

        bottom = QHBoxLayout()
        self.status_label = QLabel()
        self.status_label.setObjectName("Status")
        self.copy_tip_label = QLabel()
        self.copy_tip_label.setObjectName("CopyToast")
        self.copy_tip_label.setFixedSize(180, 30)
        self.copy_tip_label.setProperty("active", "false")
        self.total_eta_label = QLabel("总剩余：--")
        self.total_eta_label.setObjectName("TotalEta")
        self.total_eta_label.setFixedWidth(110)
        self.total_eta_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.main_progress = QProgressBar()
        self.main_progress.setFixedWidth(260)
        self.main_progress.setRange(0, 100)
        self.main_progress.setValue(0)
        bottom.addWidget(self.status_label)
        bottom.addWidget(self.copy_tip_label)
        bottom.addStretch(1)
        bottom.addWidget(self.total_eta_label)
        bottom.addWidget(self.main_progress)
        layout.addLayout(bottom)

    def _show_history(self) -> None:
        from .history_ui import HistoryPage
        if self.history_page is None:
            self.history_page = HistoryPage(self.history_store, self._reveal_path, self.ffmpeg_dir, self)
            self.history_page.back_requested.connect(self._show_workbench)
            self.right_stack.addWidget(self.history_page)
        for result in list(self.pending_history_results.values()):
            try:
                self.history_store.save(result)
                self.pending_history_results.pop(result.history_id, None)
            except Exception:
                break
        if self.pending_history_results:
            self.history_page.show_error("部分已完成任务的历史保存失败，转写导出文件仍保留。请检查历史目录权限；再次打开历史会重试保存。")
        else:
            self.history_button.setText("历史")
            self.history_page.error_label.hide()
        self.history_page.show_list()
        self.right_stack.setCurrentWidget(self.history_page)
        self.history_page.work_status.setText("后台正在转写，可返回查看进度" if self.worker_thread is not None and self.worker_thread.isRunning() else "")
        self.history_button.setChecked(True)

    def _show_workbench(self) -> None:
        self.right_stack.setCurrentWidget(self.workbench_page)
        self.history_button.setChecked(False)

    def _apply_style(self) -> None:
        QApplication.instance().setFont(QFont("Microsoft YaHei UI", 10))
        chevron_icon = self._asset_path("chevron-down.svg")
        chevron_url = chevron_icon.as_posix() if chevron_icon.exists() else ""
        stylesheet = (
            """
            QMainWindow { background: #eeeeee; font-family: "Microsoft YaHei UI"; }
            QLabel { color: #1f2933; }
            QLabel#Title { font-size: 25px; font-weight: 800; color: #102027; }
            QLabel#Subtitle, QLabel#Hint, QLabel#Status { color: #667782; }
            QLabel#TotalEta { color: #3f5f66; font-weight: 700; }
            QLabel#CopyToast { background: transparent; color: transparent; border-radius: 8px; padding: 6px 12px; font-weight: 800; }
            QLabel#CopyToast[active="true"] { background: #4b5563; color: #ffffff; }
            QLabel#FieldLabel { color: #29434b; font-weight: 700; }
            QFrame#Sidebar { background: #ffffff; border: none; border-radius: 16px; }
            QFrame#SidebarSeparator { background: #e5e5e5; border: none; }
            QFrame#SidebarFormat { background: #f4f4f4; border: none; border-radius: 9px; }
            QLabel#SidebarFormatLabel { font-size: 12px; color: #293c49; }
            QLabel#WorkflowNumber { background: #eeeeee; color: #374151; border-radius: 15px; font-size: 13px; font-weight: 600; }
            QLabel#WorkflowLabel { color: #293c49; font-size: 14px; }
            QFrame#WorkflowConnector { background: #e5e5e5; border: none; }
            QFrame#Panel, QFrame#ActionPanel { background: #ffffff; border: none; border-radius: 12px; }
            QLabel#BrandMark { background: #eeeeee; color: #374151; border: none; border-radius: 12px; min-width: 42px; max-width: 42px; min-height: 42px; max-height: 42px; qproperty-alignment: AlignCenter; font-size: 25px; font-weight: 700; }
            QLabel#BrandTitle { color: #102027; font-size: 20px; font-weight: 700; }
            QLabel#BrandSubtitle { color: #6b7e86; font-size: 12px; }
            QLabel#SideSectionTitle { color: #6b7e86; font-size: 14px; font-weight: 600; }
            QLabel#PlatformBlue { background: #f3f3f3; color: #374151; border: none; border-radius: 8px; padding: 12px; font-weight: 700; }
            QLabel#WorkflowStep { background: #f3f3f3; color: #374151; border: none; border-radius: 8px; padding: 9px 11px; font-weight: 700; }
            QLineEdit, QComboBox { background: #f4f4f4; border: none; border-radius: 8px; padding: 9px; color: #1f2937; selection-background-color: #d1d5db; selection-color: #1f2937; }
            QLineEdit:focus, QComboBox:focus { background: #e8e8e8; }
            QComboBox { padding-right: 34px; }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 30px;
                border: none;
                border-top-right-radius: 6px;
                border-bottom-right-radius: 6px;
                background: transparent;
            }
            QComboBox::drop-down:hover { background: #e5e5e5; }
            QComboBox QAbstractItemView { background: #ffffff; border: none; padding: 4px; selection-background-color: #e5e7eb; selection-color: #1f2937; outline: none; }
            QComboBox::down-arrow {
                image: url(__CHEVRON_ICON__);
                width: 14px;
                height: 14px;
                margin-right: 8px;
            }
            QComboBox QLineEdit {
                border: none;
                background: transparent;
                padding: 0;
                selection-background-color: transparent;
            }
            QComboBox#TableCombo {
                min-width: 0px;
                padding: 4px;
                background: transparent;
            }
            QComboBox#TableCombo:hover, QComboBox#TableCombo:focus, QComboBox#TableCombo:on { background: transparent; }
            QComboBox#TableCombo::drop-down {
                width: 0px;
                border: none;
                background: transparent;
            }
            QComboBox#TableCombo::down-arrow {
                image: none;
                width: 0px;
                height: 0px;
            }
            QComboBox#TableCombo QLineEdit {
                border: none;
                background: transparent;
                padding: 0;
                selection-background-color: transparent;
            }
            QComboBox#TableCombo QLineEdit:focus { background: transparent; }
            QPushButton { background: #f1f1f1; color: #374151; border: none; border-radius: 18px; padding: 9px 14px; min-width: 82px; }
            QPushButton:hover, QPushButton:focus { background: #e5e5e5; }
            QPushButton:pressed { background: #d9d9d9; }
            QPushButton:disabled { color: #9ca3af; background: #f4f4f4; border: none; }
            QPushButton#PrimaryButton { background: #6075c8; border: none; color: #ffffff; font-weight: 700; }
            QPushButton#PrimaryButton:hover, QPushButton#PrimaryButton:focus { background: #5065b5; }
            QPushButton#PrimaryButton:disabled { background: #e5e7eb; color: #9ca3af; }
            QPushButton#SideButton { background: #6075c8; border: none; border-radius: 20px; padding: 0 12px; color: #ffffff; font-size: 14px; font-weight: 600; }
            QPushButton#SideButton:hover, QPushButton#SideButton:focus { background: #5065b5; }
            QPushButton#SideSettingsButton { background: #f1f1f1; border: none; border-radius: 20px; padding: 0 12px; color: #374151; font-size: 14px; font-weight: 600; }
            QPushButton#SideSettingsButton:hover, QPushButton#SideSettingsButton:focus { background: #e5e5e5; }
            QPushButton#ChooseButton { background: #edf2ff; border: none; color: #5267ae; font-weight: 600; }
            QPushButton#ChooseButton:hover, QPushButton#ChooseButton:focus { background: #e0e8ff; }
            QFrame#ConfigurationPanel { background: #ffffff; border: none; border-radius: 16px; }
            QLabel#ConfigurationHeading { font-size: 20px; font-weight: 700; color: #102027; }
            QLabel#ConfigurationStep { background: #eeeeee; border: none; border-radius: 21px; font-size: 19px; font-weight: 700; color: #374151; }
            QFrame#ConfigurationDivider { background: #e5e5e5; border: none; }
            QFrame#ConfigurationPanel QLineEdit, QFrame#ConfigurationPanel QComboBox { background: #f4f4f4; border: none; }
            QFrame#ConfigurationPanel QLineEdit:focus, QFrame#ConfigurationPanel QComboBox:focus { background: #e8e8e8; }
            QFrame#ConfigurationPanel QComboBox::drop-down { background: transparent; border-left: none; }
            QPushButton#AddFileButton, QPushButton#AddFolderButton { min-width: 100px; border: none; font-weight: 600; }
            QPushButton#AddFileButton { background: #fff0e3; color: #a65e28; }
            QPushButton#AddFileButton:hover, QPushButton#AddFileButton:focus { background: #ffe4cc; }
            QPushButton#AddFolderButton { background: #f1ebfc; color: #7653aa; }
            QPushButton#AddFolderButton:hover, QPushButton#AddFolderButton:focus { background: #e7dcf7; }
            QCheckBox#FormatChoice { border: none; border-radius: 8px; background: #f4f4f4; padding: 0 10px; spacing: 8px; font-weight: 600; }
            QCheckBox#FormatChoice:checked { background: #edf2ff; }
            QCheckBox#FormatChoice:hover, QCheckBox#FormatChoice:focus { background: #e0e8ff; }
            QFrame#ConfigurationPanel QCheckBox::indicator { width: 18px; height: 18px; border: none; border-radius: 4px; background: #d1d5db; }
            QFrame#ConfigurationPanel QCheckBox::indicator:checked { background: #6075c8; image: url(__CHECK_ICON__); }
            QPushButton#StopButton { background: #fff1f2; border: none; color: #be123c; font-weight: 700; }
            QPushButton#StopButton:disabled { background: #f4f4f4; color: #9ca3af; }
            QPushButton#ClearButton { background: #eeeeee; border: none; color: #374151; font-weight: 600; }
            QPushButton#ClearButton:hover { background: #e2e2e2; }
            QPushButton#SelectButton { background: #edf2ff; border: none; color: #5267ae; font-weight: 600; }
            QPushButton#SelectButton:hover, QPushButton#SelectButton:focus { background: #e0e8ff; }
            QPushButton#InvertButton { background: #f1ebfc; border: none; color: #7653aa; font-weight: 600; }
            QPushButton#InvertButton:hover, QPushButton#InvertButton:focus { background: #e7dcf7; }
            QPushButton#LocateButton { min-width: 32px; max-width: 32px; min-height: 28px; max-height: 28px; padding: 0; background: transparent; border: none; border-radius: 14px; }
            QPushButton#LocateButton:hover, QPushButton#LocateButton:focus, QPushButton#LocateButton:pressed { background: transparent; }
            QTableWidget { background: #ffffff; alternate-background-color: #fafafa; border: none; border-radius: 12px; gridline-color: #ffffff; selection-background-color: #e5e7eb; selection-color: #1f2937; }
            QTableWidget#QueueTable { background: transparent; border-radius: 0px; }
            QWidget#QueueViewport { background: #ffffff; }
            QHeaderView { background: transparent; }
            QHeaderView::section { background: transparent; color: #374151; padding: 10px 8px; border: none; border-radius: 0px; font-weight: 600; }
            QProgressBar { background: #e3e3e3; border: none; border-radius: 6px; height: 16px; text-align: center; color: #374151; }
            QProgressBar::chunk { background: #6075c8; border-radius: 5px; }
            QCheckBox { color: #29434b; font-weight: 700; }
            """
        )
        self.setStyleSheet(stylesheet.replace("__CHEVRON_ICON__", chevron_url).replace("__CHECK_ICON__", self._asset_path("ui-icons/check.svg").as_posix()))

    def _lock_add_button_widths(self) -> None:
        for button in (self.add_files_button, self.add_folder_button):
            button.setFixedHeight(40)

    def _configuration_icon(self, name: str, color: str) -> QIcon:
        path = self._asset_path(f"ui-icons/{name}.svg")
        if not path.exists():
            return QIcon()
        svg = path.read_bytes().replace(b"currentColor", color.encode("ascii"))
        renderer = QSvgRenderer(svg)
        pixmap = QPixmap(24, 24)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        return QIcon(pixmap)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        self._add_paths(paths)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.table.viewport():
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                row = self._check_column_row_at_event(event)
                if row is not None:
                    item = self.table.item(row, COL_SELECT)
                    if item:
                        self.check_drag_active = True
                        self.check_drag_rows.clear()
                        checked = int(getattr(item.checkState(), "value", item.checkState())) == Qt.CheckState.Checked.value
                        self.check_drag_state = Qt.Unchecked if checked else Qt.Checked
                        self._apply_drag_check(row)
                        return True
            if event.type() == QEvent.MouseMove and self.check_drag_active:
                row = self._check_column_row_at_event(event)
                if row is not None:
                    self._apply_drag_check(row)
                return True
            if event.type() == QEvent.MouseButtonRelease and self.check_drag_active:
                self.check_drag_active = False
                self.check_drag_rows.clear()
                return True
        return super().eventFilter(watched, event)

    def _event_position(self, event: QEvent):
        if hasattr(event, "position"):
            return event.position().toPoint()
        return event.pos()

    def _check_column_row_at_event(self, event: QEvent) -> int | None:
        pos = self._event_position(event)
        row = self.table.rowAt(pos.y())
        column = self.table.columnAt(pos.x())
        if row < 0 or column != COL_SELECT:
            return None
        return row

    def _apply_drag_check(self, row: int) -> None:
        if row in self.check_drag_rows:
            return
        item = self.table.item(row, COL_SELECT)
        if item:
            item.setCheckState(self.check_drag_state)
            self.table.viewport().update(self.table.visualItemRect(item))
            self.check_drag_rows.add(row)

    def _choose_output_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "选择保存位置", self.output_edit.text())
        if directory:
            self.output_edit.setText(directory)
            self._save_settings()

    def _open_output_dir(self) -> None:
        path = Path(self.output_edit.text()).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _open_settings(self) -> None:
        dialog = AppSettingsDialog(
            self,
            completion_sound=self.completion_sound_enabled,
            completion_dialog=self.completion_dialog_enabled,
            auto_open_output=self.auto_open_output_enabled,
            create_video_subfolder=self.create_video_subfolder,
            save_beside_video=self.save_beside_video,
            precision_subtitles=self.precision_subtitles,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        values = dialog.values()
        self.completion_sound_enabled = values["completion_sound"]
        self.completion_dialog_enabled = values["completion_dialog"]
        self.auto_open_output_enabled = values["auto_open_output"]
        self.create_video_subfolder = values["create_video_subfolder"]
        self.save_beside_video = values["save_beside_video"]
        self.precision_subtitles = values["precision_subtitles"]
        self._save_settings()
        self._set_copy_tip("设置已保存", active=True)
        QTimer.singleShot(1800, lambda: self._set_copy_tip("", active=False))

    @staticmethod
    def _completion_sound_bytes(has_failure: bool) -> bytes:
        """生成短促低音量的 PCM WAV，避免依赖系统提示音的不可控音量。"""
        sample_rate = 8_000
        amplitude = 1_100
        silence_samples = int(sample_rate * 0.035)
        notes = ((523.25, 0.11), (392.0, 0.14)) if has_failure else ((783.99, 0.10), (1046.5, 0.14))
        samples: list[int] = []
        for frequency, duration in notes:
            note_samples = int(sample_rate * duration)
            for index in range(note_samples):
                # 两端淡入淡出，避免短提示音产生刺耳的爆音。
                fade = min(1.0, index / 80, (note_samples - index - 1) / 80)
                samples.append(int(amplitude * fade * math.sin(2 * math.pi * frequency * index / sample_rate)))
            samples.extend([0] * silence_samples)
        pcm = b"".join(sample.to_bytes(2, byteorder="little", signed=True) for sample in samples)
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm)
        return buffer.getvalue()

    def _play_completion_sound(self, summary: dict[str, int]) -> None:
        if not self.completion_sound_enabled:
            return
        has_failure = bool(summary.get("failed", 0) or summary.get("no_text", 0))
        try:
            if winsound is not None and sys.platform == "win32":
                winsound.PlaySound(self._completion_sound_bytes(has_failure), winsound.SND_MEMORY)
            else:
                QApplication.beep()
        except RuntimeError as exc:
            self._debug_log(f"completion sound unavailable: {exc}")

    def _choose_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "选择视频或音频文件", "", "媒体文件 (*.mp4 *.mov *.mkv *.avi *.m4v *.wmv *.flv *.webm *.mp3 *.wav *.m4a *.aac *.flac *.ogg);;所有文件 (*.*)")
        self._add_paths([Path(file) for file in files])

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if folder:
            self._add_paths([Path(folder)])

    def _expand_media_paths(self, paths: list[Path]) -> list[Path]:
        media_paths: list[Path] = []
        for path in paths:
            if path.is_dir():
                media_paths.extend(
                    child
                    for child in sorted(path.rglob("*"))
                    if child.is_file() and child.suffix.lower() in SUPPORTED_EXTENSIONS
                )
            elif path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
                media_paths.append(path)
        return media_paths

    def _add_paths(self, paths: list[Path]) -> None:
        media_paths = self._expand_media_paths(paths)
        existing = {
            self.table.item(row, COL_OUTPUT).data(SOURCE_PATH_ROLE)
            for row in range(self.table.rowCount())
            if self.table.item(row, COL_OUTPUT)
        }
        progress = QProgressDialog("正在读取文件信息...", "取消", 0, max(len(media_paths), 1), self)
        progress.setWindowTitle("添加文件")
        progress.setWindowModality(Qt.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(True)
        progress.setAutoReset(True)
        added = 0
        for index, path in enumerate(media_paths, start=1):
            progress.setValue(index - 1)
            progress.setLabelText(f"正在读取文件信息... {index}/{len(media_paths)}")
            QApplication.processEvents()
            if progress.wasCanceled():
                break
            resolved = str(path.resolve())
            if resolved in existing:
                continue
            self._add_row(path)
            existing.add(resolved)
            added += 1
        progress.setValue(max(len(media_paths), 1))
        self._set_copy_tip(f"已添加 {added} 个文件" if added else "没有新增文件", active=bool(added))
        QTimer.singleShot(1800, lambda: self._set_copy_tip("", active=False))
        self._update_status()

    def _add_row(self, path: Path) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self._set_cell(row, COL_INDEX, str(row + 1))
        self._set_select_cell(row, True)
        self._set_status_cell(row, "等待")
        self._set_cell(row, COL_FILE, path.name)
        self._set_cell(row, COL_DURATION, self._format_duration(probe_duration_seconds(path, self._build_preview_options())))
        self._set_combo_cell(row, COL_LANGUAGE, LANGUAGE_OPTIONS, self.language_combo.currentText())
        self._set_combo_cell(row, COL_MODEL, MODEL_OPTIONS, self.model_combo.currentText())
        self._set_cell(row, COL_PROGRESS, "0%")
        self._set_cell(row, COL_ELAPSED, "-")
        self._set_cell(row, COL_ETA, "-")
        output_item = self._set_cell(row, COL_OUTPUT, str(Path(self.output_edit.text()) / safe_output_stem(path.stem)))
        output_item.setData(SOURCE_PATH_ROLE, str(path.resolve()))
        self._set_locate_button(row)

    def _set_locate_button(self, row: int) -> None:
        button = QPushButton()
        button.setObjectName("LocateButton")
        button.setIcon(self.style().standardIcon(QStyle.SP_DirOpenIcon))
        button.setToolTip("在文件管理器中定位当前文件")
        button.setAccessibleName(f"定位第 {row + 1} 个文件")
        button.clicked.connect(lambda _checked=False, row=row: self._locate_row_file(row))
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignCenter)
        layout.addWidget(button)
        self.table.setCellWidget(row, COL_LOCATE, container)
        container.setAutoFillBackground(False)

    def _update_output_cell(self, row: int, text: str, output_file: Path | None = None) -> QTableWidgetItem:
        previous = self.table.item(row, COL_OUTPUT)
        source_path = previous.data(SOURCE_PATH_ROLE) if previous else None
        previous_output = previous.data(OUTPUT_FILE_ROLE) if previous else None
        item = self._set_cell(row, COL_OUTPUT, text)
        if source_path:
            item.setData(SOURCE_PATH_ROLE, source_path)
        if output_file is not None:
            item.setData(OUTPUT_FILE_ROLE, str(output_file.resolve()))
        elif previous_output:
            item.setData(OUTPUT_FILE_ROLE, previous_output)
        return item

    def _locate_target_for_row(self, row: int) -> Path | None:
        output_item = self.table.item(row, COL_OUTPUT)
        if not output_item:
            return None
        output_value = output_item.data(OUTPUT_FILE_ROLE)
        source_value = output_item.data(SOURCE_PATH_ROLE)
        for value in (output_value, source_value):
            if value:
                path = Path(str(value))
                if path.exists():
                    return path
        return None

    def _generated_output_target_for_row(self, row: int) -> Path | None:
        output_item = self.table.item(row, COL_OUTPUT)
        if not output_item:
            return None
        output_value = output_item.data(OUTPUT_FILE_ROLE)
        if not output_value:
            return None
        path = Path(str(output_value))
        return path if path.exists() else None

    def _locate_row_file(self, row: int) -> None:
        target = self._locate_target_for_row(row)
        if target is None:
            QMessageBox.warning(self, "无法定位文件", "源文件和导出文件均不存在，可能已被移动或删除。")
            return
        self._reveal_path(target)

    def _reveal_path(self, target: Path) -> None:
        try:
            if target.is_dir():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
            elif sys.platform == "win32":
                # Explorer 需要把 /select, 与实际路径拆成两个参数；合并后中文或空格路径会被误解析。
                subprocess.Popen(["explorer.exe", "/select,", os.path.normpath(str(target))])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target.parent)])
        except OSError as exc:
            QMessageBox.warning(self, "无法定位文件", f"文件管理器启动失败：{exc}")

    def _build_preview_options(self) -> TranscribeOptions:
        return TranscribeOptions(
            Path(self.output_edit.text()),
            self.model_combo.currentText(),
            self.language_combo.currentText(),
            self.compute_mode_combo.currentText(),
            True,
            True,
            True,
            True,
            False,
            self.ffmpeg_dir,
            create_video_subfolder=self.create_video_subfolder,
            save_beside_video=self.save_beside_video,
            precision_subtitles=self.precision_subtitles,
        )

    def _set_select_cell(self, row: int, checked: bool) -> None:
        item = QTableWidgetItem("")
        item.setFlags((item.flags() & ~Qt.ItemIsEditable) | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        item.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row, COL_SELECT, item)

    def _set_cell(self, row: int, column: int, text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        item.setTextAlignment(Qt.AlignCenter)
        if column in {COL_FILE, COL_ETA, COL_OUTPUT}:
            item.setToolTip(text)
        self.table.setItem(row, column, item)
        return item

    def _set_combo_cell(self, row: int, column: int, items: list[str], current: str) -> None:
        combo = CenterComboBox()
        combo.addItems(items)
        combo.setCurrentText(current if current in items else items[0])
        combo.setObjectName("TableCombo")
        if column == COL_MODEL:
            combo.setToolTip("\n".join(mode_description(combo.currentText())))
            combo.currentTextChanged.connect(lambda text: combo.setToolTip("\n".join(mode_description(text))))
        combo.setFixedWidth(max(86, self.table.columnWidth(column) - 8))
        self.table.setCellWidget(row, column, combo)
        combo.setAutoFillBackground(False)

    def _status_colors(self, status: str) -> tuple[QColor, QColor]:
        if status == "完成":
            return QColor("#dcfce7"), QColor("#15803d")
        if status == "已存在":
            return QColor("#e0f2fe"), QColor("#0369a1")
        if status in {"转写中", "提取音频", "下载模型", "加载模型", "润色中", "字幕对齐"}:
            return QColor("#dbeafe"), QColor("#1d4ed8")
        if status == "等待":
            return QColor("#fef3c7"), QColor("#b45309")
        if status == "无文字":
            return QColor("#e0f2fe"), QColor("#0369a1")
        if status == "失败":
            return QColor("#fee2e2"), QColor("#b91c1c")
        if status == "已停止":
            return QColor("#e5e7eb"), QColor("#4b5563")
        return QColor("#f8fafc"), QColor("#334155")

    def _set_status_cell(self, row: int, status: str) -> None:
        item = QTableWidgetItem(status)
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        item.setTextAlignment(Qt.AlignCenter)
        background, foreground = self._status_colors(status)
        item.setBackground(background)
        item.setForeground(foreground)
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        self.table.setItem(row, COL_STATUS, item)

    def _format_duration(self, seconds: float) -> str:
        if seconds <= 0:
            return "-"
        minutes, sec = divmod(int(seconds), 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{sec:02d}"
        return f"{minutes}:{sec:02d}"

    def _format_eta(self, seconds: float) -> str:
        if seconds <= 0:
            return "--"
        minutes, sec = divmod(int(seconds), 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}时{minutes:02d}分"
        if minutes:
            return f"{minutes}分{sec:02d}秒"
        return f"{sec}秒"

    def _on_table_item_clicked(self, item: QTableWidgetItem) -> None:
        if item.column() in {COL_FILE, COL_OUTPUT}:
            QApplication.clipboard().setText(item.text())
            label = "文件名" if item.column() == COL_FILE else "输出路径"
            self.table.setCurrentCell(item.row(), item.column())
            self._set_copy_tip(f"已复制第 {item.row() + 1} 行{label}", active=True)
            old = item.background()
            item.setBackground(QColor("#dcfce7"))
            QTimer.singleShot(1800, lambda: self._set_copy_tip("", active=False))
            QTimer.singleShot(900, lambda item=item, old=old: item.setBackground(old))

    def _set_copy_tip(self, text: str, active: bool) -> None:
        self.copy_tip_label.setText(text)
        self.copy_tip_label.setProperty("active", "true" if active else "false")
        self.copy_tip_label.style().unpolish(self.copy_tip_label)
        self.copy_tip_label.style().polish(self.copy_tip_label)

    def _build_options(self) -> TranscribeOptions | None:
        if (
            not self.txt_check.isChecked()
            and not self.md_check.isChecked()
            and not self.srt_check.isChecked()
            and not self.docx_check.isChecked()
        ):
            QMessageBox.warning(self, "导出格式为空", "请至少选择 TXT、Markdown 或 SRT。")
            return None
        output_dir = Path(self.output_edit.text()).expanduser()
        if not self.save_beside_video:
            output_dir.mkdir(parents=True, exist_ok=True)
        return TranscribeOptions(
            output_dir,
            self.model_combo.currentText(),
            self.language_combo.currentText(),
            self.compute_mode_combo.currentText(),
            self.txt_check.isChecked(),
            self.md_check.isChecked(),
            self.srt_check.isChecked(),
            self.docx_check.isChecked(),
            self.polish_check.isChecked(),
            self.ffmpeg_dir,
            create_video_subfolder=self.create_video_subfolder,
            save_beside_video=self.save_beside_video,
            precision_subtitles=self.precision_subtitles,
        )

    def _expected_output_paths(self, item: QueueItem, options: TranscribeOptions) -> list[Path]:
        safe_stem = safe_output_stem(item.path.stem)
        output_base = resolve_output_directory(item.path, options)
        paths: list[Path] = []
        if options.export_txt:
            paths.append(output_base / f"{safe_stem}.txt")
        if options.export_md:
            paths.append(output_base / f"{safe_stem}.md")
        if options.export_srt:
            paths.append(output_base / f"{safe_stem}.srt")
        if options.export_docx:
            paths.append(output_base / f"{safe_stem}.docx")
        return paths

    def _handle_existing_outputs(self, items: list[QueueItem], options: TranscribeOptions) -> list[QueueItem] | None:
        item_existing: dict[int, list[Path]] = {}
        for item in items:
            existing_paths = [path for path in self._expected_output_paths(item, options) if path.exists()]
            if existing_paths:
                item_existing[item.row] = existing_paths

        existing = [path for paths in item_existing.values() for path in paths]
        if not existing:
            return items

        preview = "\n".join(str(path) for path in existing[:5])
        extra = f"\n\n另有 {len(existing) - 5} 个文件。" if len(existing) > 5 else ""
        result = QMessageBox.question(
            self,
            "发现已有转写结果",
            "检测到部分导出文件已存在。\n\n"
            "Yes：覆盖已存在文件并继续转写。\n"
            "No：跳过已存在结果的视频，继续处理剩余视频。\n\n"
            f"已存在文件数：{len(existing)}\n\n{preview}{extra}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if result == QMessageBox.Yes:
            return items

        filtered_items = [item for item in items if item.row not in item_existing]
        skipped_count = len(items) - len(filtered_items)
        self.current_run_skipped_count += skipped_count
        self._debug_log(f"existing outputs: selected={len(items)}, skipped={skipped_count}, remaining={len(filtered_items)}")
        for item in items:
            if item.row in item_existing:
                self._set_status_cell(item.row, "已存在")
                self._set_cell(item.row, COL_PROGRESS, "100%")
                self._set_cell(item.row, COL_ELAPSED, "-")
                self._set_cell(item.row, COL_ETA, "0秒")
                self._update_output_cell(
                    item.row,
                    str(item_existing[item.row][0].parent),
                    item_existing[item.row][0],
                )

        self.status_label.setText(f"已跳过 {skipped_count} 个已有结果，继续处理剩余 {len(filtered_items)} 个。")
        if not filtered_items:
            QMessageBox.information(self, "没有需要转写的项目", "已选择的项目都存在导出结果，本次没有需要继续转写的视频。")
            return None
        return filtered_items

    def _prepare_items_for_run(self, items: list[QueueItem]) -> None:
        for item in items:
            self._set_status_cell(item.row, "等待")
            self._set_cell(item.row, COL_PROGRESS, "0%")
            self._set_cell(item.row, COL_ELAPSED, "-")
            self._set_cell(item.row, COL_ETA, "-")

    def _start_worker(self, items: list[QueueItem], options: TranscribeOptions) -> None:
        if not items:
            self.status_label.setText("没有剩余需要转写的项目。")
            self._debug_log("start_worker aborted: empty items")
            return

        self._prepare_items_for_run(items)
        self._debug_log(
            f"start_worker called: count={len(items)}, first_row={items[0].row}, "
            f"mode={options.compute_mode}, model={options.model_size}, language={options.language}"
        )
        self.active_rows = {item.row for item in items}
        self.pending_completion_target = None
        self.started_at = time.monotonic()
        self.main_progress.setValue(0)
        self.total_eta_label.setText("总剩余：--")
        self.worker_thread = QThread(self)
        self.worker = TranscribeWorker(items, options)
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.item_started.connect(self._on_item_started)
        self.worker.item_progress.connect(self._on_item_progress)
        self.worker.item_finished.connect(self._on_item_finished)
        self.worker.item_failed.connect(self._on_item_failed)
        self.worker.item_stopped.connect(self._on_item_stopped)
        self.worker.all_done.connect(self._on_all_done)
        self.worker.all_done.connect(self.worker_thread.quit)
        self.worker_thread.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self._cleanup_worker)
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.clear_button.setEnabled(False)
        self.add_files_button.setEnabled(False)
        self.add_folder_button.setEnabled(False)
        self.status_label.setText(f"正在转写剩余 {len(items)} 个项目。")
        self.worker_thread.start()

    def _dll_exists_in_path(self, dll_names: set[str]) -> bool:
        return gpu_libraries_available(dll_names)

    def _warn_gpu_runtime_if_needed(self) -> bool:
        if all(model_for_mode(item.model_size) == "qwen3-asr" for item in self._selected_items()):
            return True  # The isolated PyTorch runtime performs its own CUDA check.
        if self.compute_mode_combo.currentText() != "GPU 快速" or self.gpu_runtime_warning_ack:
            return True
        has_cublas = self._dll_exists_in_path({"cublas64_12.dll"})
        has_cudnn = self._dll_exists_in_path({"cudnn64_9.dll"})
        if has_cublas and has_cudnn:
            self.gpu_runtime_warning_ack = True
            self._debug_log("gpu runtime detected")
            return True
        self.gpu_runtime_warning_ack = True
        self.compute_mode_combo.setCurrentText("CPU 稳定")
        self.status_label.setText("未检测到完整 GPU 运行库，已自动切换 CPU 并继续转写。")
        self._debug_log("gpu runtime missing: switched to CPU")
        self._set_copy_tip("已自动切换 CPU", active=True)
        QTimer.singleShot(2400, lambda: self._set_copy_tip("", active=False))
        return True

    def _selected_items(self) -> list[QueueItem]:
        items: list[QueueItem] = []
        for row in range(self.table.rowCount()):
            select_item = self.table.item(row, COL_SELECT)
            status_item = self.table.item(row, COL_STATUS)
            output_item = self.table.item(row, COL_OUTPUT)
            if not select_item or not status_item or not output_item:
                continue
            checked = int(getattr(select_item.checkState(), "value", select_item.checkState())) == Qt.CheckState.Checked.value
            if checked and status_item.text() in {"等待", "失败", "已停止", "无文字"}:
                language_widget = self.table.cellWidget(row, COL_LANGUAGE)
                model_widget = self.table.cellWidget(row, COL_MODEL)
                items.append(
                    QueueItem(
                        path=Path(output_item.data(SOURCE_PATH_ROLE)),
                        row=row,
                        model_size=model_widget.currentText() if isinstance(model_widget, QComboBox) else self.model_combo.currentText(),
                        language=language_widget.currentText() if isinstance(language_widget, QComboBox) else self.language_combo.currentText(),
                    )
                )
        return items

    def _missing_dependencies(self) -> list[str]:
        return _missing_runtime_dependencies(self.docx_check.isChecked())

    def _start(self) -> None:
        self._debug_log("start clicked")
        if self.worker_thread:
            self._debug_log("start ignored: worker already running")
            return
        if self.install_thread:
            self._debug_log("start ignored: dependency installer running")
            return
        if self.table.rowCount() == 0:
            self._debug_log("start aborted: empty table")
            QMessageBox.information(self, "队列为空", "请先添加视频或音频文件。")
            return
        self.current_run_skipped_count = 0
        options = self._build_options()
        if not options:
            self._debug_log("start aborted: build options failed")
            return
        items = self._selected_items()
        self._debug_log(f"selected items: count={len(items)}, mode={options.compute_mode}, output={options.output_dir}")
        if not items:
            self._debug_log("start aborted: no selected runnable items")
            QMessageBox.information(self, "没有待转写项目", "请先勾选等待或失败的项目。")
            return
        needs_qwen = any(model_for_mode(item.model_size) == "qwen3-asr" for item in items) or (options.export_srt and options.precision_subtitles)
        if needs_qwen and getattr(sys, "frozen", False):
            from .qwen_bridge import runtime_ready
            if not runtime_ready():
                answer = QMessageBox.question(self, "安装本地转写环境", "首次使用中文精确或精确字幕，需要下载独立运行环境。GPU 依赖占用数 GB，安装后长期复用，音频不会上传。\n\n现在打开安装窗口吗？完成后请重新点击开始转写。", QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
                if answer == QMessageBox.Yes:
                    installer = Path(sys.executable).parent / "安装中文精确运行环境_Windows.bat"
                    subprocess.Popen(["cmd.exe", "/c", str(installer)], cwd=str(installer.parent), creationflags=subprocess.CREATE_NEW_CONSOLE)
                return
        if self.polish_check.isChecked() and not (
            os.environ.get("NANZHU_TEXT_API_KEY") or os.environ.get("OPENAI_API_KEY")
        ):
            QMessageBox.warning(
                self,
                "缺少翻译润色 API",
                "已开启“翻译润色”，但没有检测到 NANZHU_TEXT_API_KEY 或 OPENAI_API_KEY。\n\n"
                "请先配置文本处理 API，或取消勾选“翻译润色”后只导出原始转写结果。",
            )
            self._debug_log("start aborted: polish enabled without API key")
            return
        self._debug_log("dependency scan: begin")
        missing_dependencies = self._missing_dependencies()
        self._debug_log(f"dependency scan: missing={missing_dependencies}")
        if missing_dependencies:
            self._debug_log("dependencies missing: start installer")
            self._install_dependency_then_start()
            return
        self._debug_log("gpu runtime scan: begin")
        if not self._warn_gpu_runtime_if_needed():
            self._debug_log("start aborted: gpu warning rejected")
            return
        self._debug_log("gpu runtime scan: completed")
        if self.compute_mode_combo.currentText() == "GPU 快速" and any(model_for_mode(item.model_size) == "turbo" for item in items):
            has_cublas = self._dll_exists_in_path({"cublas64_12.dll"})
            has_cudnn = self._dll_exists_in_path({"cudnn64_9.dll"})
            if not has_cublas or not has_cudnn:
                self.compute_mode_combo.setCurrentText("CPU 稳定")
                self._debug_log("late gpu check switched to CPU")
        if options.compute_mode != self.compute_mode_combo.currentText():
            options = self._build_options()
            if not options:
                self._debug_log("start aborted: rebuild options failed after mode change")
                return
            self._debug_log(f"options rebuilt: mode={options.compute_mode}")
        items = self._handle_existing_outputs(items, options)
        if not items:
            self._debug_log("start aborted: no items after existing-output scan")
            return

        self._start_worker(items, options)

    def _install_dependency_then_start(self) -> None:
        if self.install_thread:
            return
        self.start_after_install = True
        self.status_label.setText("正在自动安装 faster-whisper 依赖，完成后会继续开始转写。")
        self._set_copy_tip("正在安装依赖", active=True)
        self.install_progress = QProgressDialog("正在安装 faster-whisper 依赖，首次安装可能需要几分钟...", None, 0, 0, self)
        self.install_progress.setWindowTitle("自动安装依赖")
        self.install_progress.setWindowModality(Qt.ApplicationModal)
        self.install_progress.setCancelButton(None)
        self.install_progress.setMinimumDuration(0)
        self.install_progress.show()

        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.clear_button.setEnabled(False)
        self.add_files_button.setEnabled(False)
        self.add_folder_button.setEnabled(False)

        self.install_thread = QThread(self)
        self.install_worker = DependencyInstallWorker()
        self.install_worker.moveToThread(self.install_thread)
        self.install_thread.started.connect(self.install_worker.run)
        self.install_worker.finished.connect(self._on_dependency_install_finished)
        self.install_worker.finished.connect(self.install_thread.quit)
        self.install_thread.finished.connect(self.install_worker.deleteLater)
        self.install_thread.finished.connect(self._cleanup_install_worker)
        self.install_thread.start()

    @Slot(bool, str)
    def _on_dependency_install_finished(self, ok: bool, message: str) -> None:
        if self.install_progress:
            self.install_progress.close()
        if ok:
            self.status_label.setText("依赖安装完成，正在开始转写。")
            self._set_copy_tip("依赖安装完成", active=True)
            QTimer.singleShot(1800, lambda: self._set_copy_tip("", active=False))
            return
        self.start_after_install = False
        self.status_label.setText(message)
        self._set_copy_tip("依赖安装失败", active=True)
        QTimer.singleShot(3000, lambda: self._set_copy_tip("", active=False))

    @Slot()
    def _cleanup_install_worker(self) -> None:
        should_start = self.start_after_install and not self._missing_dependencies()
        self.install_thread = None
        self.install_worker = None
        self.install_progress = None
        self.start_after_install = False
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.clear_button.setEnabled(True)
        self.add_files_button.setEnabled(True)
        self.add_folder_button.setEnabled(True)
        if should_start:
            QTimer.singleShot(0, self._start)

    def _stop(self) -> None:
        if self.worker:
            self.worker.cancel()
            self.stop_button.setEnabled(False)
            self.status_label.setText("正在停止，当前阶段结束后退出。")

    def _clear(self) -> None:
        self.table.setRowCount(0)
        self.main_progress.setValue(0)
        self.total_eta_label.setText("总剩余：--")
        self._update_status()

    def _select_all(self) -> None:
        for row in range(self.table.rowCount()):
            status_item = self.table.item(row, COL_STATUS)
            select_item = self.table.item(row, COL_SELECT)
            if status_item and select_item and status_item.text() in {"等待", "失败", "已停止", "无文字", "已存在"}:
                select_item.setCheckState(Qt.Checked)

    def _invert(self) -> None:
        for row in range(self.table.rowCount()):
            status_item = self.table.item(row, COL_STATUS)
            select_item = self.table.item(row, COL_SELECT)
            if status_item and select_item and status_item.text() in {"等待", "失败", "已停止", "无文字", "已存在"}:
                checked = int(getattr(select_item.checkState(), "value", select_item.checkState())) == Qt.CheckState.Checked.value
                select_item.setCheckState(Qt.Unchecked if checked else Qt.Checked)

    @Slot(int)
    def _on_item_started(self, row: int) -> None:
        self._debug_log(f"item started: row={row}")
        self._set_status_cell(row, "提取音频")
        self._set_cell(row, COL_PROGRESS, "0%")
        self._set_cell(row, COL_ELAPSED, "-")
        self._set_cell(row, COL_ETA, "-")

    @Slot(int, dict)
    def _on_item_progress(self, row: int, info: dict[str, Any]) -> None:
        if self.history_page is not None:
            self.history_page.work_status.setText(f"后台转写 · 第 {row + 1} 项 · {info.get('progress', 0)}%")
        status = info.get("status")
        if status == "extracting":
            self._set_status_cell(row, "提取音频")
        elif status == "downloading_model":
            self._set_status_cell(row, "下载模型")
            eta_text = str(info.get("eta") or "")
            self.status_label.setText(eta_text or "正在下载模型，首次使用需要等待模型文件下载完成。")
        elif status == "loading_model":
            self._set_status_cell(row, "加载模型")
            eta_text = str(info.get("eta") or "")
            self.status_label.setText(eta_text or "正在加载模型，首次使用可能需要下载或解压模型。")
        elif status == "transcribing":
            self._set_status_cell(row, "转写中")
        elif status == "aligning":
            self._set_status_cell(row, "字幕对齐")
            self._set_cell(row, COL_ETA, "字幕时间对齐中")
        elif status == "polishing":
            self._set_status_cell(row, "润色中")
        if info.get("force_cpu"):
            self.compute_mode_combo.setCurrentText("CPU 稳定")
            self._debug_log("worker forced CPU fallback")
        progress = int(info.get("progress") or 0)
        self._set_cell(row, COL_PROGRESS, f"{progress}%")
        self._set_cell(row, COL_ETA, str(info.get("eta") or "-"))
        if info.get("notice"):
            self.status_label.setText(str(info["notice"]))
        if self.started_at:
            self._set_cell(row, COL_ELAPSED, self._format_eta(time.monotonic() - self.started_at))
        self._update_main_progress()

    @Slot(int, object)
    def _on_item_finished(self, row: int, result: TranscribeResult) -> None:
        if result.source_path is not None:
            try:
                self.history_store.save(result)
                if self.history_page is not None and self.history_page.stack.currentIndex() == 0:
                    self.history_page.reload()
            except Exception as exc:
                self.pending_history_results[result.history_id] = result
                self.history_button.setText("历史 · 保存失败")
                self.history_button.setToolTip(f"转写已完成且导出文件保留；历史未保存：{exc}。点击历史重试。")
        self._set_status_cell(row, "完成")
        self._set_cell(row, COL_PROGRESS, "100%")
        if result.files:
            self._update_output_cell(row, str(result.files[0].parent), result.files[0])
        self._update_main_progress()

    @Slot(int, str)
    def _on_item_failed(self, row: int, error: str) -> None:
        self._debug_log(f"item failed: row={row}, error={error[:200]}")
        if "没有识别到可导出的文字" in error or "未检测到可转写的音轨" in error:
            message = "未检测到可转写的语音。该视频可能没有音轨、静音、纯音乐或只有画面。"
            self._set_status_cell(row, "无文字")
            self._set_cell(row, COL_PROGRESS, "100%")
            self._set_cell(row, COL_ETA, "0秒")
            self._update_output_cell(row, message)
            self.status_label.setText(message)
            self._update_main_progress()
            return
        if "WinError 206" in error or "文件名或扩展名太长" in error:
            message = "路径过长。已优化为短文件名规则，请重启软件后重新转写这些失败项。"
            self._set_status_cell(row, "失败")
            self._update_output_cell(row, message)
            self.status_label.setText(message)
            self._update_main_progress()
            return
        self._set_status_cell(row, "失败")
        self._update_output_cell(row, error[:160])
        self._update_main_progress()

    @Slot(int)
    def _on_item_stopped(self, row: int) -> None:
        self._set_status_cell(row, "已停止")
        self._update_main_progress()

    @Slot()
    def _on_all_done(self) -> None:
        if self.history_page is not None:
            self.history_page.work_status.setText("本批任务已结束")
        self._debug_log("all done")
        self.status_label.setText("转写任务已结束。")
        rows = sorted(self.active_rows)
        if rows:
            statuses = [
                self.table.item(row, COL_STATUS).text()
                for row in rows
                if self.table.item(row, COL_STATUS)
            ]
            completed_rows = [
                row
                for row in rows
                if self.table.item(row, COL_STATUS) and self.table.item(row, COL_STATUS).text() == "完成"
            ]
            self.pending_completion_target = next(
                (
                    target
                    for row in reversed(completed_rows)
                    if (target := self._generated_output_target_for_row(row)) is not None
                ),
                None,
            )
            self.pending_completion_summary = {
                "success": statuses.count("完成"),
                "failed": statuses.count("失败"),
                "no_text": statuses.count("无文字"),
                "skipped": self.current_run_skipped_count,
                "stopped": statuses.count("已停止"),
            }
        self.active_rows.clear()
        self.started_at = None
        self.total_eta_label.setText("总剩余：0秒")

    @Slot()
    def _cleanup_worker(self) -> None:
        self.worker_thread = None
        self.worker = None
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.clear_button.setEnabled(True)
        self.add_files_button.setEnabled(True)
        self.add_folder_button.setEnabled(True)
        self._update_status()
        summary = self.pending_completion_summary
        completion_target = self.pending_completion_target
        self.pending_completion_summary = None
        self.pending_completion_target = None
        if summary:
            if summary.get("success", 0) or summary.get("failed", 0) or summary.get("no_text", 0):
                self._play_completion_sound(summary)
            if (
                self.auto_open_output_enabled
                and summary.get("success", 0) > 0
                and not summary.get("failed", 0)
                and not summary.get("no_text", 0)
                and not summary.get("stopped", 0)
                and completion_target is not None
            ):
                QTimer.singleShot(0, lambda target=completion_target: self._reveal_path(target))
            if self.completion_dialog_enabled:
                QTimer.singleShot(0, lambda summary=summary: self._show_completion_dialog(summary))

    def _show_completion_dialog(self, summary: dict[str, int]) -> None:
        CompletionResultDialog(self, summary).exec()

    def _update_main_progress(self) -> None:
        rows = sorted(self.active_rows) if self.active_rows else list(range(self.table.rowCount()))
        if not rows:
            self.main_progress.setValue(0)
            self.total_eta_label.setText("总剩余：--")
            return
        units = 0.0
        for row in rows:
            status = self.table.item(row, COL_STATUS).text() if self.table.item(row, COL_STATUS) else ""
            if status in {"完成", "失败", "已停止", "无文字", "已存在"}:
                units += 1.0
            elif status in {"转写中", "提取音频", "下载模型", "加载模型", "润色中"}:
                units += self._row_progress_ratio(row)
        ratio = units / len(rows)
        self.main_progress.setValue(max(0, min(100, int(ratio * 100))))
        self._update_total_eta(ratio)

    def _row_progress_ratio(self, row: int) -> float:
        item = self.table.item(row, COL_PROGRESS)
        if not item:
            return 0.0
        try:
            return max(0.0, min(1.0, float(item.text().strip().rstrip("%")) / 100))
        except ValueError:
            return 0.0

    def _update_total_eta(self, ratio: float) -> None:
        if not self.started_at or ratio <= 0:
            self.total_eta_label.setText("总剩余：--")
            return
        if ratio >= 1:
            self.total_eta_label.setText("总剩余：0秒")
            return
        elapsed = time.monotonic() - self.started_at
        self.total_eta_label.setText(f"总剩余：{self._format_eta(elapsed * (1 - ratio) / ratio)}")

    def _update_status(self) -> None:
        ffmpeg_text = "FFmpeg 已就绪" if self.ffmpeg_dir else "未找到 FFmpeg，将尝试系统 PATH"
        self.status_label.setText(f"{ffmpeg_text}｜队列: {self.table.rowCount()} 项")


def main() -> int:
    if "--qa-transcribe" in sys.argv:
        import json
        index = sys.argv.index("--qa-transcribe")
        source, mode, target = sys.argv[index + 1:index + 4]
        destination = Path(target).resolve()
        destination.mkdir(parents=True, exist_ok=True)
        options = TranscribeOptions(destination, mode, "中文", "GPU 快速", True, False, True, False, False, find_ffmpeg_dir(Path(__file__).resolve().parents[1]))
        notices = []
        result = transcribe_file(Path(source).resolve(), options, lambda value: notices.append(value.get("notice")) if value.get("notice") else None)
        receipt = {"success": bool(result.text and result.files), "mode": mode, "characters": len(result.text), "exports": [file.name for file in result.files], "notices": notices}
        (destination / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0 if receipt["success"] else 1
    app = QApplication(sys.argv)
    if "--qa-screenshots" in sys.argv:
        target = Path(sys.argv[sys.argv.index("--qa-screenshots") + 1]).resolve()
        target.mkdir(parents=True, exist_ok=True)
        window = MainWindow(QSettings(str(target / "isolated-settings.ini"), QSettings.IniFormat))
        window.resize(1600, 1000)
        window.show()
        def capture():
            window.grab().save(str(target / "workbench.png"))
            dialog = AppSettingsDialog(window, completion_sound=True, completion_dialog=False, auto_open_output=True)
            dialog.show()
            app.processEvents()
            dialog.grab().save(str(target / "settings.png"))
            dialog.close()
            if "--qa-history-source" in sys.argv:
                from .qa_history_preview import capture_history
                source = sys.argv[sys.argv.index("--qa-history-source") + 1]
                capture_history(window, target, source, finish)
                return
            finish()
        def finish():
            window.close()
            app.quit()
        QTimer.singleShot(600, capture)
        return app.exec()
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

