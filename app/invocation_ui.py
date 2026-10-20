"""Asynchronous views over the Android-compatible invocation ledger."""
from datetime import datetime
from PySide6.QtCore import QAbstractListModel, QModelIndex, QObject, QRunnable, QThreadPool, QTimer, Signal, Qt, Slot, QSize, QRect
from PySide6.QtGui import QColor, QFontMetrics
from PySide6.QtWidgets import QAbstractItemView, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListView, QStyledItemDelegate
from .invocations import InvocationStore, cost_label, usage_label, error_label


class QuerySignals(QObject):
    done = Signal(object)


class LedgerQuery(QRunnable):
    def __init__(self, root, count=False):
        super().__init__()
        self.root, self.count = root, count
        self.signals = QuerySignals()

    def run(self):
        try:
            store = InvocationStore(self.root)
            result = store.count_files() if self.count else store.groups()
        except Exception:
            result = None
        self.signals.done.emit(result)


class InvocationEntry(QPushButton):
    def __init__(self, root, parent=None):
        super().__init__("查看调用记录", parent)
        self.root, self._job = root, None
        self.setAccessibleName("查看调用记录")
        self.clicked.connect(self.open_records)
        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        QTimer.singleShot(0, self.refresh)

    @Slot()
    def refresh(self):
        if self._job is not None or not self.isVisible():
            return
        self._job = LedgerQuery(self.root, count=True)
        self._job.signals.done.connect(self.loaded)
        QThreadPool.globalInstance().start(self._job)

    @Slot(object)
    def loaded(self, count):
        self._job = None
        if not self.isVisible():
            return
        self.setText(f"查看调用记录（{count}）" if count else "查看调用记录")

    @Slot()
    def open_records(self):
        dialog = InvocationHistoryDialog(self.root, self.window())
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self.timer.start()
        self.refresh()


def record_lines(row):
    when = datetime.fromtimestamp(row["completed_at_millis"] / 1000).strftime("%Y-%m-%d %H:%M")
    millis = row["duration_millis"]
    duration = f"{millis} ms" if millis < 1000 else f"{millis/1000:.2f} 秒"
    lines = [
        f'{"成功" if row["status"] == "SUCCEEDED" else "失败"}    {when}',
        row["source_display_name"] or "迁移前调用记录",
        f'百炼官方 · {row["model_id"]}',
        f'完整文件 · 后台分段 {row["request_count"]} 个 · 耗时 {duration} · {usage_label(row)}',
        cost_label(row),
    ]
    if row["error_code"]:
        lines.append("原因：" + error_label(row["error_code"]))
    return lines


class InvocationListModel(QAbstractListModel):
    """Keep metadata in the model; one file never creates a widget subtree."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []
        self._lines = {}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        if role == Qt.UserRole:
            if index.row() not in self._lines:
                self._lines[index.row()] = record_lines(self.rows[index.row()])
            return self._lines[index.row()]
        if role in (Qt.DisplayRole, Qt.AccessibleTextRole):
            return "\n".join(self.data(index, Qt.UserRole))
        return None

    def replace_rows(self, rows):
        self.beginResetModel()
        self.rows = rows
        self._lines.clear()
        self.endResetModel()


class InvocationDelegate(QStyledItemDelegate):
    """Paint visible file rows and cache wrapping for the current viewport."""
    def __init__(self, view):
        super().__init__(view)
        self.view = view
        self._geometry = {}
        self._width = None

    def clear(self):
        self._geometry.clear()
        self._width = None

    def _layout(self, option, index):
        width = max(1, self.view.viewport().width() - 32)
        key = (width, option.font.toString())
        if key != self._width:
            self._width = key
            self._geometry.clear()
        row = index.row()
        if row not in self._geometry:
            metrics = QFontMetrics(option.font)
            lines = index.data(Qt.UserRole) or []
            heights = [max(metrics.height(), metrics.boundingRect(
                QRect(0, 0, width, 100000), Qt.TextWordWrap | Qt.AlignLeft, line
            ).height()) for line in lines]
            self._geometry[row] = (lines, heights, 26 + sum(heights) + 4 * max(0, len(lines) - 1))
        return self._geometry[row]

    def sizeHint(self, option, index):
        return QSize(self.view.viewport().width(), self._layout(option, index)[2])

    def paint(self, painter, option, index):
        lines, heights, _ = self._layout(option, index)
        painter.save()
        painter.setClipRect(option.rect)
        painter.setFont(option.font)
        painter.setPen(QColor("#243746"))
        y = option.rect.top() + 12
        for text, height in zip(lines, heights):
            painter.drawText(
                QRect(option.rect.left() + 16, y, max(1, option.rect.width() - 32), height),
                Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, text,
            )
            y += height + 4
        painter.setPen(QColor("#eeeeee"))
        painter.drawLine(option.rect.left() + 16, option.rect.bottom(),
                         option.rect.right() - 16, option.rect.bottom())
        painter.restore()


class InvocationHistoryDialog(QDialog):
    def __init__(self, root, parent=None):
        super().__init__(parent)
        self.root, self._job, self._rows = root, None, object()
        self.setWindowTitle("调用记录")
        self.resize(760, 560)
        self.setMinimumSize(580, 380)
        self.setSizeGripEnabled(True)
        self.setStyleSheet("QDialog {background:#eeeeee;} QListView {border:0;background:white;border-radius:12px;} QLabel {background:transparent;color:#243746;} QPushButton {background:#e2e4e7;color:#334155;border:0;border-radius:14px;padding:7px 14px;} QPushButton:hover, QPushButton:focus {background:#d5d8dd;}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 20)
        header = QHBoxLayout()
        title = QLabel("调用记录")
        title.setStyleSheet("font-size:18px;font-weight:600;")
        header.addWidget(title)
        header.addStretch()
        close = QPushButton("×")
        close.setAccessibleName("关闭调用记录")
        close.setToolTip("关闭")
        close.clicked.connect(self.accept)
        header.addWidget(close)
        layout.addLayout(header)
        layout.addWidget(QLabel("仅显示本机安全运行元数据。"))
        self.status_label = QLabel("正在读取调用记录…")
        self.status_label.setWordWrap(True)
        self.status_label.setTextFormat(Qt.PlainText)
        layout.addWidget(self.status_label)
        self.scroll = QListView()
        self.scroll.setAccessibleName("云端转写调用记录")
        self.scroll.setSelectionMode(QAbstractItemView.NoSelection)
        self.scroll.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setResizeMode(QListView.Adjust)
        self.scroll.setLayoutMode(QListView.Batched)
        self.scroll.setBatchSize(40)
        self.model = InvocationListModel(self.scroll)
        self.delegate = InvocationDelegate(self.scroll)
        self.scroll.setModel(self.model)
        self.scroll.setItemDelegate(self.delegate)
        self._restore_scroll = None
        self.scroll.verticalScrollBar().rangeChanged.connect(self._restore_scroll_position)
        self.scroll.verticalScrollBar().sliderPressed.connect(self._cancel_scroll_restore)
        layout.addWidget(self.scroll)
        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        QTimer.singleShot(0, self.refresh)

    def _cancel_scroll_restore(self):
        self._restore_scroll = None

    def _restore_scroll_position(self, *_):
        if self._restore_scroll is None:
            return
        bar = self.scroll.verticalScrollBar()
        bar.setValue(min(self._restore_scroll, bar.maximum()))
        if bar.maximum() >= self._restore_scroll:
            self._restore_scroll = None

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self.timer.start()
        self.refresh()

    @Slot()
    def refresh(self):
        if self._job is not None or not self.isVisible():
            return
        self._job = LedgerQuery(self.root)
        self._job.signals.done.connect(self.loaded)
        QThreadPool.globalInstance().start(self._job)

    @Slot(object)
    def loaded(self, rows):
        self._job = None
        if not self.isVisible() or rows == self._rows:
            return
        self._rows = rows
        self._restore_scroll = self.scroll.verticalScrollBar().value()
        self.delegate.clear()
        self.model.replace_rows(rows or [])
        if rows is None:
            self.status_label.setText("调用记录读取失败，请稍后重试。")
        elif not rows:
            self.status_label.setText("尚无本地调用记录\n当前未发出任何真实云端转写请求。")
        else:
            self.status_label.setText("")
        self.status_label.setVisible(not rows)
        QTimer.singleShot(0, self._restore_scroll_position)
