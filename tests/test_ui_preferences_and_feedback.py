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
            first.completion_sound_enabled = False
            first.completion_dialog_enabled = False
            first.auto_open_output_enabled = True
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
            self.assertFalse(second.completion_sound_enabled)
            self.assertFalse(second.completion_dialog_enabled)
            self.assertTrue(second.auto_open_output_enabled)
            second.close()

    def test_settings_dialog_returns_completion_preferences(self) -> None:
        with TemporaryDirectory() as temp_dir:
            settings = QSettings(str(Path(temp_dir) / "settings.ini"), QSettings.IniFormat)
            window = main.MainWindow(settings=settings)
            dialog = main.AppSettingsDialog(
                window,
                completion_sound=True,
                completion_dialog=True,
                auto_open_output=False,
            )
            dialog.completion_sound_check.setChecked(False)
            dialog.completion_dialog_check.setChecked(False)
            dialog.auto_open_output_check.setChecked(True)
            self.assertEqual(
                dialog.values(),
                {"completion_sound": False, "completion_dialog": False, "auto_open_output": True},
            )
            dialog.close()
            window.close()

    def test_completion_sound_respects_user_switch(self) -> None:
        with TemporaryDirectory() as temp_dir:
            settings = QSettings(str(Path(temp_dir) / "settings.ini"), QSettings.IniFormat)
            window = main.MainWindow(settings=settings)
            window.completion_sound_enabled = True
            with patch("app.main.sys.platform", "win32"), patch("app.main.winsound") as mocked_winsound:
                mocked_winsound.SND_MEMORY = 4
                window._play_completion_sound({"success": 1, "failed": 0, "no_text": 0})
            mocked_winsound.PlaySound.assert_called_once()
            payload = mocked_winsound.PlaySound.call_args.args[0]
            self.assertTrue(payload.startswith(b"RIFF"))

            window.completion_sound_enabled = False
            with patch("app.main.sys.platform", "win32"), patch("app.main.winsound") as muted_winsound:
                window._play_completion_sound({"success": 1, "failed": 0, "no_text": 0})
            muted_winsound.PlaySound.assert_not_called()
            window.close()

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
            self.assertEqual(window._generated_output_target_for_row(0), output.resolve())
            window.close()

    def test_completion_auto_locate_uses_latest_generated_output(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.mp4"
            first_output = root / "output" / "first.md"
            latest_output = root / "output" / "latest.md"
            source.touch()
            first_output.parent.mkdir()
            first_output.touch()
            latest_output.touch()
            settings = QSettings(str(root / "settings.ini"), QSettings.IniFormat)
            window = main.MainWindow(settings=settings)
            with patch("app.main.probe_duration_seconds", return_value=0.0):
                window._add_row(source)
                window._add_row(source)
            window._set_status_cell(0, "完成")
            window._set_status_cell(1, "完成")
            window._update_output_cell(0, str(first_output.parent), first_output)
            window._update_output_cell(1, str(latest_output.parent), latest_output)
            window.active_rows = {0, 1}

            window._on_all_done()

            self.assertEqual(window.pending_completion_target, latest_output.resolve())
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

    def test_missing_audio_track_is_shown_as_no_text(self) -> None:
        with TemporaryDirectory() as temp_dir:
            settings = QSettings(str(Path(temp_dir) / "settings.ini"), QSettings.IniFormat)
            window = main.MainWindow(settings=settings)
            with patch("app.main.probe_duration_seconds", return_value=0.0):
                window._add_row(Path(temp_dir) / "silent.mp4")

            window._on_item_failed(0, "RuntimeError: 未检测到可转写的音轨。该视频可能没有声音或只有画面。")

            self.assertEqual(window.table.item(0, main.COL_STATUS).text(), "无文字")
            self.assertIn("没有音轨", window.table.item(0, main.COL_OUTPUT).text())
            window.close()


if __name__ == "__main__":
    unittest.main()
