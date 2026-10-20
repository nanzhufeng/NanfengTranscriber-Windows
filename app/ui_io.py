"""Bounded filesystem/preflight jobs; results return to the owning GUI slot."""
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

_pool = None


class IoSignals(QObject):
    done = Signal(object, object, str)


class IoJob(QRunnable):
    def __init__(self, operation):
        super().__init__()
        self.operation = operation
        self.cancelled = False
        self.signals = IoSignals()

    def run(self):
        try:
            result = None if self.cancelled else self.operation()
            self.signals.done.emit(self, result, "")
        except Exception:
            self.signals.done.emit(self, None, "读取或保存失败，请检查磁盘连接、目录权限和可用空间后重试。")


def start_io(job):
    global _pool
    if _pool is None:
        _pool = QThreadPool()
        _pool.setMaxThreadCount(2)
    _pool.start(job)
