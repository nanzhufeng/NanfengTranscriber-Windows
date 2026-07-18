from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


BASELINE_DIR = Path(__file__).resolve().parent / "ui_baselines" / "windows"


class UiBaselineManifestTests(unittest.TestCase):
    def test_windows_multi_dpi_baselines_are_complete_and_unchanged(self) -> None:
        manifest = json.loads((BASELINE_DIR / "manifest.json").read_text(encoding="utf-8"))
        entries = manifest["entries"]
        self.assertEqual([entry["scale"] for entry in entries], [1.0, 1.25, 1.5, 2.0])

        for entry in entries:
            image = BASELINE_DIR / entry["file"]
            self.assertTrue(image.is_file())
            self.assertGreater(entry["pixel_width"], 1000)
            self.assertGreater(entry["pixel_height"], 700)
            self.assertGreater(entry["bytes"], 20_000)
            digest = hashlib.sha256(image.read_bytes()).hexdigest().upper()
            self.assertEqual(digest, entry["sha256"])


if __name__ == "__main__":
    unittest.main()
