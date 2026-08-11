from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from app import main


class UiPreferencesAndFeedbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_top_level_options_persist_across_restart(self) -> None:
        with TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "settings.ini"
            first_settings = QSettings(str(settings_path), QSettings.IniFormat)
            first = main.MainWindow(settings=first_settings)
            first.output_edit.setText(str(Path(temp_dir) / "outputs"))
            first.model_combo.setCurrentText("large-v3")
            first.language_combo.setCurrentText("英文")
            first.compute_mode_combo.setCurrentText("CPU 稳定")
            first.txt_check.setChecked(False)
            first.md_check.setChecked(True)
            first.srt_check.setChecked(False)
            first.docx_check.setChecked(True)
            first.polish_check.setChecked(True)
            first._save_settings()
            first.close()

            second_settings = QSettings(str(settings_path), QSettings.IniFormat)
            second = main.MainWindow(settings=second_settings)
            self.assertEqual(second.output_edit.text(), str(Path(temp_dir) / "outputs"))
            self.assertEqual(second.model_combo.currentText(), "large-v3")
            self.assertEqual(second.language_combo.currentText(), "英文")
            self.assertEqual(second.compute_mode_combo.currentText(), "CPU 稳定")
            self.assertFalse(second.txt_check.isChecked())
            self.assertTrue(second.md_check.isChecked())
            self.assertFalse(second.srt_check.isChecked())
            self.assertTrue(second.docx_check.isChecked())
            self.assertTrue(second.polish_check.isChecked())
            second.close()

    def test_locate_column_prefers_generated_output_then_source(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.mp4"
            output = root / "output" / "source.md"
            source.touch()
            output.parent.mkdir()
            output.touch()
            settings = QSettings(str(root / "settings.ini"), QSettings.IniFormat)
            window = main.MainWindow(settings=settings)
            with patch("app.main.probe_duration_seconds", return_value=0.0):
                window._add_row(source)

            self.assertIsNotNone(window.table.cellWidget(0, main.COL_LOCATE))
            self.assertEqual(window._locate_target_for_row(0), source.resolve())
            window._update_output_cell(0, str(output.parent), output)
            self.assertEqual(window._locate_target_for_row(0), output.resolve())
            window.close()

    def test_windows_locate_uses_explorer_select_with_a_separate_path_argument(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "含 空格 的源文件.mp4"
            source.touch()
            settings = QSettings(str(root / "settings.ini"), QSettings.IniFormat)
            window = main.MainWindow(settings=settings)
            with patch("app.main.probe_duration_seconds", return_value=0.0):
                window._add_row(source)
            with patch("app.main.sys.platform", "win32"), patch("app.main.subprocess.Popen") as popen:
                window._locate_row_file(0)
            popen.assert_called_once_with(["explorer.exe", "/select,", str(source.resolve())])
            window.close()

    def test_completion_feedback_shows_separate_status_counts(self) -> None:
        with TemporaryDirectory() as temp_dir:
            settings = QSettings(str(Path(temp_dir) / "settings.ini"), QSettings.IniFormat)
            window = main.MainWindow(settings=settings)
            success_dialog = main.CompletionResultDialog(
                window,
                {"success": 3, "failed": 0, "no_text": 0, "skipped": 2, "stopped": 0},
            )
            failed_dialog = main.CompletionResultDialog(
                window,
                {"success": 2, "failed": 1, "no_text": 1, "skipped": 0, "stopped": 0},
            )
            self.assertEqual(success_dialog.windowTitle(), "转写结果")
            self.assertIn("转写全部完成", [label.text() for label in success_dialog.findChildren(main.QLabel)])
            self.assertIn("转写已结束，存在失败", [label.text() for label in failed_dialog.findChildren(main.QLabel)])
            for card in success_dialog.findChildren(main.QFrame, "ResultStat"):
                self.assertIn("QLabel { background: transparent; border: none; }", card.styleSheet())
            success_dialog.close()
            failed_dialog.close()
            window.close()


if __name__ == "__main__":
    unittest.main()
