from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class InnoInstallerContractTests(unittest.TestCase):
    def test_inno_setup_is_per_user_and_platform_explicit(self) -> None:
        content = (PROJECT_ROOT / "installer" / "NanfengTranscriber-Windows.iss").read_text(encoding="utf-8")
        self.assertIn("PrivilegesRequired=lowest", content)
        self.assertIn(r"DefaultDirName={localappdata}\Programs\{#MyAppName}", content)
        self.assertIn('#define MyAppName "南枫转写"', content)
        self.assertIn('#define MyAppExeName "南枫转写.exe"', content)
        self.assertIn("recursesubdirs createallsubdirs", content)
        self.assertIn("{autoprograms}", content)
        self.assertIn("{autodesktop}", content)

    def test_build_script_uses_inno_and_windows_asset_naming(self) -> None:
        content = (PROJECT_ROOT / "build_windows_installer_inno.ps1").read_text(encoding="utf-8")
        self.assertIn("Inno Setup 6", content)
        self.assertIn("ISCC.exe", content)
        self.assertIn("NanfengTranscriber_Windows_v${Version}_Setup_${timestamp}", content)
        self.assertIn("Install-Readme.zh-CN.txt", content)
        self.assertNotIn("iexpress.exe", content.lower())

    def test_install_notes_are_chinese_first_with_english_reference(self) -> None:
        content = (PROJECT_ROOT / "installer" / "Install-Readme.zh-CN.txt").read_text(encoding="utf-8")
        self.assertTrue(content.startswith("南枫转写 Windows v{{VERSION}} 安装说明"))
        self.assertIn("安装步骤：", content)
        self.assertIn("使用说明：", content)
        self.assertIn("卸载方法：", content)
        self.assertIn("English reference:", content)
        self.assertLess(content.index("安装步骤："), content.index("English reference:"))


if __name__ == "__main__":
    unittest.main()
