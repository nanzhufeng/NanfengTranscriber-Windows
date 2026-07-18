from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QEvent, QObject, QRect, Qt, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon
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
    QProgressBar,
    QProgressDialog,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionButton,
    QTableWidget,
    QTableWidgetItem,
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
    transcribe_file,
)


APP_NAME = "南枫转写"
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
MODEL_OPTIONS = ["base", "small", "medium", "large-v3"]
LANGUAGE_OPTIONS = ["中文", "自动识别", "英文", "日语", "韩语"]
COMPUTE_MODE_OPTIONS = ["GPU 优先", "CPU 稳定"]
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


class CenterComboBox(QComboBox):
    def __init__(self) -> None:
        super().__init__()
        self._popup_open = False
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

    def mousePressEvent(self, event) -> None:
        self._toggle_popup()
        event.accept()

    def showPopup(self) -> None:
        self._popup_open = True
        super().showPopup()

    def hidePopup(self) -> None:
        self._popup_open = False
        super().hidePopup()

    def _toggle_popup(self) -> None:
        if self._popup_open or self.view().isVisible():
            self.hidePopup()
        else:
            self.showPopup()


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
    def __init__(self) -> None:
        super().__init__()
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
        self._apply_style()
        self._lock_add_button_widths()
        self._update_status()
        self._debug_log("app started")

    def _asset_path(self, name: str) -> Path:
        packaged_asset = self.project_root / "app" / "assets" / name
        if packaged_asset.exists():
            return packaged_asset
        return self.project_root.parent / "CleanVideoDownloader" / "app" / "assets" / name

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
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(220)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(20, 20, 20, 20)
        sidebar_layout.setSpacing(16)

        brand_mark = QLabel("南")
        brand_mark.setObjectName("BrandMark")
        brand_title = QLabel(APP_NAME)
        brand_title.setObjectName("BrandTitle")
        brand_subtitle = QLabel("音视频文稿工作台")
        brand_subtitle.setObjectName("BrandSubtitle")
        sidebar_layout.addWidget(brand_mark)
        sidebar_layout.addWidget(brand_title)
        sidebar_layout.addWidget(brand_subtitle)
        sidebar_layout.addSpacing(10)

        module_title = QLabel("输出格式")
        module_title.setObjectName("SideSectionTitle")
        module_text = QLabel("TXT\nMarkdown\nSRT\nDOCX")
        module_text.setObjectName("PlatformBlue")
        sidebar_layout.addWidget(module_title)
        sidebar_layout.addWidget(module_text)
        sidebar_layout.addSpacing(8)

        workflow_title = QLabel("操作流程")
        workflow_title.setObjectName("SideSectionTitle")
        sidebar_layout.addWidget(workflow_title)
        for index, text in enumerate(["添加文件", "选择模型", "开始转写", "检查导出"], start=1):
            step = QLabel(f"{index:02d}  {text}")
            step.setObjectName("WorkflowStep")
            sidebar_layout.addWidget(step)
        sidebar_layout.addStretch(1)

        self.open_folder_button = QPushButton("打开输出目录")
        self.open_folder_button.setObjectName("SideButton")
        self.open_folder_button.clicked.connect(self._open_output_dir)
        sidebar_layout.addWidget(self.open_folder_button)
        shell.addWidget(sidebar)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        shell.addWidget(content, 1)

        title = QLabel("转写工作台")
        title.setObjectName("Title")
        subtitle = QLabel("批量识别音视频内容，导出文稿、Markdown 和字幕。")
        subtitle.setObjectName("Subtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        input_frame = QFrame()
        input_frame.setObjectName("Panel")
        input_layout = QGridLayout(input_frame)
        input_layout.setContentsMargins(20, 18, 20, 18)
        input_layout.setHorizontalSpacing(12)
        input_layout.setVerticalSpacing(12)

        output_label = QLabel("保存位置")
        output_label.setObjectName("FieldLabel")
        self.output_edit = QLineEdit(str(default_output_dir()))
        self.output_button = QPushButton("选择")
        self.output_button.setObjectName("ChooseButton")
        self.output_button.clicked.connect(self._choose_output_dir)

        model_label = QLabel("模型")
        model_label.setObjectName("FieldLabel")
        self.model_combo = CenterComboBox()
        self.model_combo.addItems(MODEL_OPTIONS)
        self.model_combo.setCurrentText("medium")
        self.model_combo.setFixedWidth(150)

        language_label = QLabel("语言")
        language_label.setObjectName("FieldLabel")
        self.language_combo = CenterComboBox()
        self.language_combo.addItems(LANGUAGE_OPTIONS)
        self.language_combo.setCurrentText("中文")
        self.language_combo.setFixedWidth(170)

        mode_label = QLabel("模式")
        mode_label.setObjectName("FieldLabel")
        self.compute_mode_combo = CenterComboBox()
        self.compute_mode_combo.addItems(COMPUTE_MODE_OPTIONS)
        self.compute_mode_combo.setCurrentText("GPU 优先")
        self.compute_mode_combo.setFixedWidth(160)

        format_label = QLabel("导出")
        format_label.setObjectName("FieldLabel")
        self.txt_check = QCheckBox("TXT")
        self.txt_check.setChecked(True)
        self.md_check = QCheckBox("Markdown")
        self.md_check.setChecked(True)
        self.srt_check = QCheckBox("SRT")
        self.srt_check.setChecked(True)
        self.docx_check = QCheckBox("DOCX")
        self.docx_check.setChecked(True)
        self.polish_check = QCheckBox("翻译润色")
        self.polish_check.setChecked(bool(os.environ.get("NANZHU_TEXT_API_KEY") or os.environ.get("OPENAI_API_KEY")))
        self.polish_check.setToolTip("开启后会调用文本 API，把转写稿翻译/整理为现代简体中文。需要配置 NANZHU_TEXT_API_KEY 或 OPENAI_API_KEY。")
        format_row = QHBoxLayout()
        format_row.addWidget(self.txt_check)
        format_row.addWidget(self.md_check)
        format_row.addWidget(self.srt_check)
        format_row.addWidget(self.docx_check)
        format_row.addWidget(self.polish_check)
        format_row.addStretch(1)
        option_row = QHBoxLayout()
        option_row.setContentsMargins(0, 0, 0, 0)
        option_row.setSpacing(10)
        option_row.addWidget(model_label)
        option_row.addWidget(self.model_combo)
        option_row.addWidget(language_label)
        option_row.addWidget(self.language_combo)
        option_row.addWidget(mode_label)
        option_row.addWidget(self.compute_mode_combo)
        option_row.addWidget(format_label)
        option_row.addLayout(format_row)
        option_row.addStretch(1)

        self.add_files_button = QPushButton("添加文件")
        self.add_files_button.setObjectName("AddFileButton")
        self.add_files_button.setFixedWidth(220)
        self.add_files_button.clicked.connect(self._choose_files)
        self.add_folder_button = QPushButton("添加文件夹")
        self.add_folder_button.setObjectName("AddFolderButton")
        self.add_folder_button.setFixedWidth(220)
        self.add_folder_button.clicked.connect(self._choose_folder)
        add_button_row = QHBoxLayout()
        add_button_row.setContentsMargins(0, 0, 0, 0)
        add_button_row.setSpacing(12)
        add_button_row.addWidget(self.add_files_button)
        add_button_row.addWidget(self.add_folder_button)
        add_button_row.addStretch(1)
        self.hint_label = QLabel("也可以把视频或音频文件直接拖到窗口里。首次使用需要安装 faster-whisper 依赖。")
        self.hint_label.setObjectName("Hint")

        input_layout.addWidget(output_label, 0, 0)
        input_layout.addWidget(self.output_edit, 0, 1, 1, 4)
        input_layout.addWidget(self.output_button, 0, 5)
        input_layout.addLayout(option_row, 1, 1, 1, 5)
        input_layout.addLayout(add_button_row, 2, 1, 1, 5)
        input_layout.addWidget(self.hint_label, 3, 1, 1, 5)
        input_layout.setColumnStretch(1, 1)
        input_layout.setColumnStretch(3, 1)
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
        action_layout.addWidget(self.start_button)
        action_layout.addWidget(self.stop_button)
        action_layout.addWidget(self.clear_button)
        action_layout.addSpacing(12)
        action_layout.addWidget(self.select_all_button)
        action_layout.addWidget(self.invert_button)
        action_layout.addStretch(1)
        layout.addWidget(action_frame)

        self.table = QTableWidget(0, 11)
        self.table.setHorizontalHeaderLabels(["序号", "选择", "状态", "文件名", "时长", "语言", "模型", "进度", "耗时", "剩余", "输出路径"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
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
        }.items():
            header.setSectionResizeMode(column, QHeaderView.Fixed)
            self.table.setColumnWidth(column, width)
        header.setSectionResizeMode(COL_FILE, QHeaderView.Stretch)
        header.setSectionResizeMode(COL_OUTPUT, QHeaderView.Stretch)
        layout.addWidget(self.table, 1)

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

    def _apply_style(self) -> None:
        QApplication.instance().setFont(QFont("Microsoft YaHei UI", 10))
        chevron_icon = self._asset_path("chevron-down.svg")
        chevron_url = chevron_icon.as_posix() if chevron_icon.exists() else ""
        stylesheet = (
            """
            QMainWindow { background: #edf6f7; font-family: "Microsoft YaHei UI"; }
            QLabel { color: #1f2933; }
            QLabel#Title { font-size: 25px; font-weight: 800; color: #102027; }
            QLabel#Subtitle, QLabel#Hint, QLabel#Status { color: #667782; }
            QLabel#TotalEta { color: #3f5f66; font-weight: 700; }
            QLabel#CopyToast { background: transparent; color: transparent; border-radius: 8px; padding: 6px 12px; font-weight: 800; }
            QLabel#CopyToast[active="true"] { background: #16a34a; color: #ffffff; }
            QLabel#FieldLabel { color: #29434b; font-weight: 700; }
            QFrame#Sidebar { background: #ffffff; border: 1px solid #d7e7ea; border-radius: 8px; }
            QFrame#Panel, QFrame#ActionPanel { background: #ffffff; border: 1px solid #d7e7ea; border-radius: 8px; }
            QLabel#BrandMark { background: #d9fbf3; color: #087f76; border: 1px solid #7de3d0; border-radius: 8px; min-width: 34px; max-width: 34px; min-height: 34px; max-height: 34px; qproperty-alignment: AlignCenter; font-size: 18px; font-weight: 800; }
            QLabel#BrandTitle { color: #102027; font-size: 16px; font-weight: 800; }
            QLabel#BrandSubtitle { color: #6b7e86; font-size: 12px; font-weight: 700; }
            QLabel#SideSectionTitle { color: #8797a0; font-size: 12px; font-weight: 700; }
            QLabel#PlatformBlue { background: #e8faf7; color: #0f766e; border: 1px solid #b8ead7; border-radius: 8px; padding: 12px; font-weight: 800; }
            QLabel#WorkflowStep { background: #f7fbfc; color: #38545c; border: 1px solid #d7e7ea; border-radius: 8px; padding: 9px 11px; font-weight: 700; }
            QLineEdit, QComboBox { background: #fbfefd; border: 1px solid #cfe3e6; border-radius: 6px; padding: 9px; color: #102027; selection-background-color: #14b8a6; }
            QLineEdit:focus, QComboBox:focus { border: 1px solid #14b8a6; background: #ffffff; }
            QComboBox { padding-right: 34px; }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 30px;
                border-left: 1px solid #d4e5e7;
                border-top-right-radius: 6px;
                border-bottom-right-radius: 6px;
                background: #f1fbfa;
            }
            QComboBox::drop-down:hover { background: #dff8f5; }
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
            }
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
            QPushButton { background: #f8fbfc; color: #31454c; border: 1px solid #d5e7ea; border-radius: 6px; padding: 9px 14px; min-width: 82px; }
            QPushButton:hover { background: #e8faf7; border: 1px solid #9edbd3; }
            QPushButton:disabled { color: #9aa9ad; background: #f1f5f6; border: 1px solid #dde8ea; }
            QPushButton#PrimaryButton { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0f766e, stop:1 #2563eb); border: 1px solid #0f766e; color: #ffffff; font-weight: 800; }
            QPushButton#SideButton { background: #16a394; border: 1px solid #26c6b5; color: #ffffff; font-weight: 800; }
            QPushButton#ChooseButton { background: #eefdf8; border: 1px solid #aee9d7; color: #087f76; font-weight: 800; }
            QPushButton#AddFileButton, QPushButton#AddFolderButton { min-width: 220px; max-width: 220px; background: #fff8e8; border: 1px solid #f6d48b; color: #a45b00; font-weight: 800; }
            QPushButton#AddFolderButton { background: #f3efff; border: 1px solid #ddd2ff; color: #6941c6; }
            QPushButton#StopButton { background: #fff1f2; border: 1px solid #fecdd3; color: #be123c; font-weight: 800; }
            QPushButton#ClearButton { background: #f3f7f9; border: 1px solid #d5e3e7; color: #42545b; font-weight: 800; }
            QPushButton#SelectButton { background: #e9fbf4; border: 1px solid #b8ead7; color: #047857; font-weight: 800; }
            QPushButton#InvertButton { background: #eff6ff; border: 1px solid #bfdbfe; color: #1d4ed8; font-weight: 800; }
            QTableWidget { background: #ffffff; alternate-background-color: #f6fbfc; border: 1px solid #d7e7ea; border-radius: 8px; gridline-color: #e6f0f2; selection-background-color: #e0f2fe; selection-color: #0f172a; }
            QHeaderView::section { background: #e9f4f6; color: #38545c; padding: 10px 8px; border: none; border-right: 1px solid #d7e7ea; font-weight: 800; }
            QProgressBar { background: #e7f1f3; border: 1px solid #cfe3e6; border-radius: 6px; height: 16px; text-align: center; color: #253f46; }
            QProgressBar::chunk { background: #14b8a6; border-radius: 5px; }
            QCheckBox { color: #29434b; font-weight: 700; }
            """
        )
        self.setStyleSheet(stylesheet.replace("__CHEVRON_ICON__", chevron_url))

    def _lock_add_button_widths(self) -> None:
        for button in (self.add_files_button, self.add_folder_button):
            button.setFixedWidth(220)

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

    def _open_output_dir(self) -> None:
        path = Path(self.output_edit.text()).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

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
        existing = {self.table.item(row, COL_OUTPUT).data(Qt.UserRole) for row in range(self.table.rowCount()) if self.table.item(row, COL_OUTPUT)}
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
        output_item.setData(Qt.UserRole, str(path.resolve()))

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
        combo.setFixedWidth(max(86, self.table.columnWidth(column) - 8))
        self.table.setCellWidget(row, column, combo)

    def _status_colors(self, status: str) -> tuple[QColor, QColor]:
        if status == "完成":
            return QColor("#dcfce7"), QColor("#15803d")
        if status == "已存在":
            return QColor("#e0f2fe"), QColor("#0369a1")
        if status in {"转写中", "提取音频", "下载模型", "加载模型", "润色中"}:
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
        )

    def _expected_output_paths(self, item: QueueItem, options: TranscribeOptions) -> list[Path]:
        safe_stem = safe_output_stem(item.path.stem)
        output_base = options.output_dir / safe_stem
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
        self._debug_log(f"existing outputs: selected={len(items)}, skipped={skipped_count}, remaining={len(filtered_items)}")
        for item in items:
            if item.row in item_existing:
                self._set_status_cell(item.row, "已存在")
                self._set_cell(item.row, COL_PROGRESS, "100%")
                self._set_cell(item.row, COL_ELAPSED, "-")
                self._set_cell(item.row, COL_ETA, "0秒")
                self._set_cell(item.row, COL_OUTPUT, str(item_existing[item.row][0].parent))

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
        # 冻结版不通过 find_spec 查找外部 Python 包。该调用在部分 PyInstaller
        # 环境会阻塞主线程；安装包内的 DLL 由 PATH 或系统 CUDA 路径提供。
        if not _is_frozen_runtime():
            for package_name in ("nvidia.cudnn", "nvidia.cublas", "nvidia.cuda_nvrtc"):
                spec = importlib.util.find_spec(package_name)
                if spec and spec.submodule_search_locations:
                    bin_dir = Path(list(spec.submodule_search_locations)[0]) / "bin"
                    for dll_name in dll_names:
                        if (bin_dir / dll_name).exists():
                            return True
        for folder in os.environ.get("PATH", "").split(os.pathsep):
            if not folder:
                continue
            base = Path(folder)
            for dll_name in dll_names:
                if (base / dll_name).exists():
                    return True
        return False

    def _warn_gpu_runtime_if_needed(self) -> bool:
        if self.compute_mode_combo.currentText() != "GPU 优先" or self.gpu_runtime_warning_ack:
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
                        path=Path(output_item.data(Qt.UserRole)),
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
        if self.compute_mode_combo.currentText() == "GPU 优先":
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
        self._set_status_cell(row, "完成")
        self._set_cell(row, COL_PROGRESS, "100%")
        if result.files:
            self._set_cell(row, COL_OUTPUT, str(result.files[0].parent))
        self._update_main_progress()

    @Slot(int, str)
    def _on_item_failed(self, row: int, error: str) -> None:
        self._debug_log(f"item failed: row={row}, error={error[:200]}")
        if "没有识别到可导出的文字" in error:
            message = "未识别到语音文字。可能是静音、纯音乐、画面字幕、音量太低，或语音被降噪过滤。"
            self._set_status_cell(row, "无文字")
            self._set_cell(row, COL_PROGRESS, "100%")
            self._set_cell(row, COL_ETA, "0秒")
            self._set_cell(row, COL_OUTPUT, message)
            self.status_label.setText(message)
            self._update_main_progress()
            return
        if "WinError 206" in error or "文件名或扩展名太长" in error:
            message = "路径过长。已优化为短文件名规则，请重启软件后重新转写这些失败项。"
            self._set_status_cell(row, "失败")
            self._set_cell(row, COL_OUTPUT, message)
            self.status_label.setText(message)
            self._update_main_progress()
            return
        self._set_status_cell(row, "失败")
        self._set_cell(row, COL_OUTPUT, error[:160])
        self._update_main_progress()

    @Slot(int)
    def _on_item_stopped(self, row: int) -> None:
        self._set_status_cell(row, "已停止")
        self._update_main_progress()

    @Slot()
    def _on_all_done(self) -> None:
        self._debug_log("all done")
        self.status_label.setText("转写任务已结束。")
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
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

