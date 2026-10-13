from pathlib import Path
import os
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


@unittest.skipUnless(os.name == "nt", "Windows PowerShell native argument regression")
class QwenRuntimeSetupTests(unittest.TestCase):
    def test_verification_only_reuses_runtime_and_cleans_probe(self):
        script = Path(__file__).resolve().parents[1] / "scripts/setup_qwen_runtime.ps1"
        for shell in ("powershell.exe", "pwsh.exe"):
            if not shutil.which(shell):
                continue
            with self.subTest(shell=shell), TemporaryDirectory(prefix="qwen runtime ") as temp:
                runtime = Path(temp)
                base = Path(sys.base_prefix)
                shutil.copy2(base / "python.exe", runtime / "python.exe")
                for name in (f"python{sys.version_info.major}{sys.version_info.minor}.dll", "python3.dll"):
                    if (base / name).exists():
                        shutil.copy2(base / name, runtime / name)
                (runtime / f"python{sys.version_info.major}{sys.version_info.minor}._pth").write_text(
                    f"{base / 'Lib'}\n{base / 'DLLs'}\n.\n", encoding="utf-8")
                (runtime / "transformers.py").write_text(
                    "AutoModelForMultimodalLM = object\nAutoModelForTokenClassification = object\n", encoding="utf-8")
                (runtime / "torch.py").write_text(
                    "class cuda:\n    @staticmethod\n    def is_available(): return False\n", encoding="utf-8")
                result = subprocess.run([shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
                                         "-RuntimeDirectory", str(runtime), "-VerifyOnly"], capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
                self.assertIn(b"Qwen runtime ready", result.stdout)
                self.assertTrue((runtime / "runtime.ready").is_file())
                self.assertFalse(list(runtime.glob("verify-*.py")))
                (runtime / "runtime.ready").unlink()
                (runtime / "transformers.py").write_text("raise RuntimeError('broken runtime')\n", encoding="utf-8")
                result = subprocess.run([shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
                                         "-RuntimeDirectory", str(runtime), "-VerifyOnly"], capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((runtime / "runtime.ready").exists())
                self.assertFalse(list(runtime.glob("verify-*.py")))
