import json
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest

from app.product_info import APP_VERSION
from tools.check_project_contracts import ACTIVE_DOCS, ROOT, audit_project


class ProjectContractTests(unittest.TestCase):
    def fixture(self, root):
        files = set(ACTIVE_DOCS) | {
            "app/assets/product.json", "app/assets/chevron-down.svg", "南枫转写_Windows.spec",
            "requirements.txt", "requirements-qwen.txt", "requirements-build.txt",
            "scripts/build_windows_app.ps1", "scripts/setup_qwen_runtime.ps1", "build_windows_installer_inno.ps1",
            f"docs/preview-v{APP_VERSION}.png", f"docs/settings-v{APP_VERSION}.png",
        }
        for name in files:
            source = ROOT / name
            destination = root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)

    def test_current_contracts_and_declared_release_receipt(self):
        failures = [item for item in audit_project(ROOT, release=True) if not item[1]]
        self.assertEqual(failures, [])

    def test_stale_readme_version_is_rejected(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            readme = root / "README.md"
            readme.write_text(readme.read_text(encoding="utf-8").replace(f"v{APP_VERSION}-Setup.exe", "v0.0.0-Setup.exe"), encoding="utf-8")
            self.assertFalse(next(passed for name, passed, _ in audit_project(root) if name == "README installer version"))

    def test_broken_active_document_link_is_rejected(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            (root / "AGENTS.md").write_text("[broken](docs/missing.md)", encoding="utf-8")
            self.assertFalse(next(passed for name, passed, _ in audit_project(root) if name == "links AGENTS.md"))

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required for build contract tests")
    def test_installer_version_comes_from_built_metadata_and_mismatch_stops(self):
        with TemporaryDirectory() as temp:
            app = Path(temp)
            (app / "南枫转写.exe").touch()
            data = app / "_internal/app/assets/product.json"
            data.parent.mkdir(parents=True)
            shutil.copyfile(ROOT / "app/assets/product.json", data)
            command = ["pwsh", "-NoProfile", "-File", str(ROOT / "build_windows_installer_inno.ps1"), "-SourceAppPath", str(app), "-ValidateOnly"]
            valid = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=20)
            self.assertEqual(valid.returncode, 0, valid.stderr)
            self.assertEqual(json.loads(valid.stdout)["Version"], APP_VERSION)
            wrong = subprocess.run(command + ["-Version", "0.0.0"], capture_output=True, text=True, encoding="utf-8", timeout=20)
            self.assertNotEqual(wrong.returncode, 0)
            self.assertIn("differs", wrong.stderr)
            self.assertEqual(sorted(p.name for p in app.iterdir()), ["_internal", "南枫转写.exe"])

    @unittest.skipUnless(shutil.which("cmd"), "Windows launcher contract")
    def test_launcher_check_propagates_import_failure(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            shutil.copyfile(ROOT / "启动最新界面_Windows.bat", root / "launcher.bat")
            (root / "app").mkdir()
            (root / "app/__init__.py").touch()
            (root / "app/main.py").write_text("raise RuntimeError('controlled import failure')", encoding="utf-8")
            result = subprocess.run(["cmd", "/c", str(root / "launcher.bat"), "--check"], capture_output=True, timeout=20)
            self.assertNotEqual(result.returncode, 0, (result.stdout + result.stderr).decode("utf-8", errors="replace")[:1200])
