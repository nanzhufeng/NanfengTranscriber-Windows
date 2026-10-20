"""Cached GUI settings with one coalescing disk writer per settings file."""
from concurrent.futures import ThreadPoolExecutor
import threading
import weakref
from PySide6.QtCore import QObject, QSettings, Signal

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="app-settings")
_states = weakref.WeakValueDictionary()
_removed = object()

class SettingsSignals(QObject):
    finished = Signal(bool)


class SettingsState:
    def __init__(self, settings):
        self.signals = SettingsSignals()
        self.path, self.format = settings.fileName(), settings.format()
        self.values = {key: settings.value(key) for key in settings.allKeys()}
        self.pending = {}
        self.lock = threading.Lock()
        self.running = False
        self.future = None
        self.error = False

    def put(self, key, value):
        with self.lock:
            previous = self.values.get(key, _removed)
            if value == previous:
                return
            if value is _removed:
                self.values.pop(key, None)
            else:
                self.values[key] = value
            self.pending[key] = value
        self.start()

    def start(self):
        with self.lock:
            if self.pending and not self.running:
                self.running = True
                self.future = _executor.submit(self.write)

    def write(self):
        batch = {}
        try:
            settings = QSettings(self.path, self.format)
            while True:
                with self.lock:
                    if not self.pending:
                        self.running = False
                        return
                    batch, self.pending = self.pending, {}
                for key, value in batch.items():
                    if value is _removed:
                        settings.remove(key)
                    else:
                        settings.setValue(key, value)
                settings.sync()
                if settings.status() != QSettings.NoError:
                    raise OSError("settings write failed")
                self.error = False
        except Exception:
            with self.lock:
                for key, value in batch.items():
                    self.pending.setdefault(key, value)
                self.running = False
                self.error = True
        finally:
            self.signals.finished.emit(not self.error)


class AsyncSettings:
    def __init__(self, settings):
        key = (settings.fileName(), settings.format())
        state = _states.get(key)
        if state is None:
            state = SettingsState(settings)
            _states[key] = state
        self._state = state

    @property
    def write_finished(self):
        return self._state.signals.finished

    def value(self, key, defaultValue=None):
        with self._state.lock:
            return self._state.values.get(key, defaultValue)

    def setValue(self, key, value):
        self._state.put(key, value)

    def remove(self, key):
        self._state.put(key, _removed)

    def contains(self, key):
        with self._state.lock:
            return key in self._state.values

    def fileName(self):
        return self._state.path

    def sync(self):
        """Queue outstanding writes; GUI callers never wait for the disk."""
        self._state.start()

    @property
    def busy(self):
        with self._state.lock:
            return self._state.running

    @property
    def save_failed(self):
        return self._state.error

    def wait_for_idle(self, timeout=3):
        """Only for isolated tests/command line shutdown, never a GUI handler."""
        future = self._state.future
        if future:
            future.result(timeout=timeout)
