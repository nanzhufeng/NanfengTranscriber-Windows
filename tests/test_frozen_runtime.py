from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from app import main
from app import transcriber


class FrozenRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_frozen_runtime_skips_dependency_discovery(self) -> None:
        with patch("app.main._is_frozen_runtime", return_value=True), patch(
            "app.main.importlib.util.find_spec"
        ) as find_spec:
            self.assertEqual(main._missing_runtime_dependencies(export_docx=True), [])
            find_spec.assert_not_called()

    def test_source_runtime_checks_required_dependencies(self) -> None:
        def find_spec(name: str):
            return object() if name == "faster_whisper" else None

        with patch("app.main._is_frozen_runtime", return_value=False), patch(
            "app.main.importlib.util.find_spec", side_effect=find_spec
        ):
            self.assertEqual(
                main._missing_runtime_dependencies(export_docx=True),
                [main.REQUIRED_DEPENDENCIES["docx"]],
            )

    def test_frozen_transcriber_skips_external_nvidia_package_scan(self) -> None:
        with patch("app.transcriber._is_frozen_runtime", return_value=True), patch(
            "app.transcriber.importlib.util.find_spec"
        ) as find_spec, patch.dict("app.transcriber.os.environ", {"PATH": ""}, clear=False):
            self.assertFalse(transcriber._dll_exists_in_path({"cublas64_12.dll"}))
            find_spec.assert_not_called()

    def test_start_reaches_worker_in_frozen_runtime(self) -> None:
        with TemporaryDirectory() as temp_dir:
            window = main.MainWindow()
            window.output_edit.setText(temp_dir)
            with patch("app.main.probe_duration_seconds", return_value=0):
                window._add_row(Path(temp_dir) / "sample.mp4")
            with patch("app.main._is_frozen_runtime", return_value=True), patch.object(
                window, "_start_worker"
            ) as start_worker:
                window._start()

            start_worker.assert_called_once()
            items, options = start_worker.call_args.args
            self.assertEqual(len(items), 1)
            self.assertIn(options.compute_mode, {"GPU 优先", "CPU 稳定"})
            window.close()


if __name__ == "__main__":
    unittest.main()
