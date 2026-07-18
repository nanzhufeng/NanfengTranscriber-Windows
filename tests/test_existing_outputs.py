from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QMessageBox

from app import main
from app.transcriber import safe_output_stem


class ExistingOutputFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_no_skips_existing_item_and_starts_remaining_items(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_existing = root / "existing.mp4"
            source_pending = root / "pending.mp4"
            source_existing.touch()
            source_pending.touch()

            window = main.MainWindow()
            window.output_edit.setText(str(root / "outputs"))
            window.compute_mode_combo.setCurrentText("CPU 稳定")
            window.txt_check.setChecked(True)
            window.md_check.setChecked(False)
            window.srt_check.setChecked(False)
            window.docx_check.setChecked(False)
            window.polish_check.setChecked(False)

            with patch("app.main.probe_duration_seconds", return_value=0.0):
                window._add_row(source_existing)
                window._add_row(source_pending)

            existing_stem = safe_output_stem(source_existing.stem)
            existing_output = root / "outputs" / existing_stem / f"{existing_stem}.txt"
            existing_output.parent.mkdir(parents=True)
            existing_output.write_text("already transcribed", encoding="utf-8")

            with (
                patch.object(window, "_missing_dependencies", return_value=[]),
                patch.object(window, "_warn_gpu_runtime_if_needed", return_value=True),
                patch.object(window, "_start_worker") as start_worker,
                patch.object(QMessageBox, "question", return_value=QMessageBox.No),
            ):
                window._start()

            start_worker.assert_called_once()
            remaining_items = start_worker.call_args.args[0]
            self.assertEqual([item.row for item in remaining_items], [1])
            self.assertEqual(window.table.item(0, main.COL_STATUS).text(), "已存在")
            self.assertIn("继续处理剩余 1 个", window.status_label.text())
            window.close()


if __name__ == "__main__":
    unittest.main()
