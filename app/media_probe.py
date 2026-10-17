"""Bounded metadata probing away from the GUI event loop."""
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

_pool = None


class ProbeSignals(QObject):
    done = Signal(object, object, float)


class DiscoverySignals(QObject):
    done = Signal(object, object, str)


class PathDiscovery(QRunnable):
    def __init__(self, discover, paths):
        super().__init__()
        self.discover, self.paths = discover, paths
        self.cancelled = False
        self.signals = DiscoverySignals()

    def run(self):
        try:
            paths = [] if self.cancelled else self.discover(self.paths)
            self.signals.done.emit(self, [] if self.cancelled else paths, "")
        except Exception:
            self.signals.done.emit(self, [], "文件读取失败，请检查目录权限后重试。")


class DurationProbe(QRunnable):
    def __init__(self, index, path, options, probe):
        super().__init__()
        self.index, self.path, self.options, self.probe = index, path, options, probe
        self.cancelled = False
        self.signals = ProbeSignals()

    def run(self):
        value = 0.0
        if not self.cancelled:
            try:
                value = self.probe(self.path, self.options)
            except Exception:
                pass
        self.signals.done.emit(id(self), self.index, value)


def start_probe(job):
    global _pool
    if _pool is None:
        _pool = QThreadPool()
        _pool.setMaxThreadCount(2)
    _pool.start(job)
