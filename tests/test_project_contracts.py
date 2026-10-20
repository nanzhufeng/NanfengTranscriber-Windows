import json
import re
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest

from app.product_info import APP_VERSION
from tools.check_project_contracts import ACTIVE_DOCS, ROOT, audit_project


class ProjectContractTests(unittest.TestCase):
    def fixture(self, root):
        registry = json.loads((ROOT / "docs/contract-registry.json").read_text(encoding="utf-8"))
        files = set(ACTIVE_DOCS) | {
            "app/assets/product.json", "app/assets/chevron-down.svg", "南枫转写_Windows.spec",
            "requirements.txt", "requirements-qwen.txt", "requirements-build.txt",
            "scripts/build_windows_app.ps1", "scripts/setup_qwen_runtime.ps1", "build_windows_installer_inno.ps1",
            f"docs/preview-v{APP_VERSION}.png", f"docs/settings-v{APP_VERSION}.png",
            f"docs/history-v{APP_VERSION}.png", f"docs/player-v{APP_VERSION}.png",
            f"docs/release-v{APP_VERSION}.json", "docs/contract-registry.json",
        }
        files.update(document["path"] for document in registry["documents"])
        for contract in registry["contracts"]:
            files.update(reference.split(":", 1)[0] for reference in contract["owners"])
            files.update(contract["tests"])
        files.add("build_windows_installer.ps1")
        files.update(registry["legacy_entrypoints"])
        for document in registry["documents"]:
            source = ROOT / document["path"]
            for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", source.read_text(encoding="utf-8")):
                if ":" in target or target.startswith("#"):
                    continue
                dependency = (source.parent / target.split("#", 1)[0]).resolve()
                if dependency.is_relative_to(ROOT) and dependency.is_file():
                    files.add(dependency.relative_to(ROOT).as_posix())
        for name in files:
            source = ROOT / name
            destination = root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)

    def test_missing_contract_group_is_rejected(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            path = root / "docs/contract-registry.json"
            registry = json.loads(path.read_text(encoding="utf-8"))
            registry["contracts"] = [entry for entry in registry["contracts"] if entry["id"] != "C06"]
            path.write_text(json.dumps(registry), encoding="utf-8")
            checks = {name: passed for name, passed, _ in audit_project(root)}
            self.assertIn("contract coverage", checks)
            self.assertFalse(checks["contract coverage"])

    def test_registry_references_roles_and_inventory_reject_drift(self):
        cases = (
            ("contract references", lambda root, registry: registry["contracts"][0]["owners"].append("app/main.py:MainWindow.no_such_entry")),
            ("single contract authority", lambda root, registry: registry["documents"][0].update(role="authority")),
            ("document roles", lambda root, registry: (root / "docs/RELEASE_NOTES_v1.0.8.md").write_text("# 现行合同\n", encoding="utf-8")),
            ("document inventory", lambda root, registry: (root / "docs/unregistered-contract.md").write_text("# Another rule\n", encoding="utf-8")),
        )
        for expected, mutate in cases:
            with self.subTest(expected=expected), TemporaryDirectory() as temp:
                root = Path(temp)
                self.fixture(root)
                self.assertTrue(all(passed for _, passed, _ in audit_project(root, release=True)))
                path = root / "docs/contract-registry.json"
                registry = json.loads(path.read_text(encoding="utf-8"))
                mutate(root, registry)
                path.write_text(json.dumps(registry), encoding="utf-8")
                self.assertFalse(dict((name, passed) for name, passed, _ in audit_project(root))[expected])

    def test_model_status_and_release_digest_reject_drift(self):
        signature = json.loads((ROOT / f"docs/release-v{APP_VERSION}.json").read_text(encoding="utf-8"))["authenticode"]
        alternate_signature = "Valid" if signature == "NotSigned" else "NotSigned"
        cases = (
            ("documented models", "docs/CONTRACTS.md", "paraformer-v2", "paraformer-obsolete"),
            ("source status version", "docs/PROJECT_STATUS.md", f"Product version: {APP_VERSION}", "Product version: 0.0.0"),
            ("published status", "docs/PROJECT_STATUS.md", f"Release signature: {signature}", f"Release signature: {alternate_signature}"),
            ("release receipt", f"docs/release-v{APP_VERSION}.json", "\"remoteAssetCount\": 1", "\"remoteAssetCount\": 2"),
        )
        for expected, name, before, after in cases:
            with self.subTest(expected=expected), TemporaryDirectory() as temp:
                root = Path(temp)
                self.fixture(root)
                path = root / name
                text = path.read_text(encoding="utf-8")
                self.assertIn(before, text)
                path.write_text(text.replace(before, after), encoding="utf-8")
                self.assertFalse(dict((name, passed) for name, passed, _ in audit_project(root, release=True))[expected])

    def test_existing_file_outside_project_is_not_a_valid_local_document_link(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            root.mkdir()
            self.fixture(root)
            (root.parent / "outside.md").write_text("outside", encoding="utf-8")
            (root / "README.md").write_text("[escape](../outside.md)", encoding="utf-8")
            self.assertFalse(dict((name, passed) for name, passed, _ in audit_project(root))["links README.md"])

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
