"""Shared product metadata for the UI, build tools and release contracts."""
import json
from pathlib import Path

_metadata = json.loads((Path(__file__).with_name("assets") / "product.json").read_text(encoding="utf-8"))
APP_NAME = _metadata["name"]
APP_VERSION = _metadata["version"]
APP_DEVELOPED_AT = _metadata["developed_at"]
GITHUB_REPOSITORY = _metadata["repository"]
GITHUB_REPOSITORY_URL = f"https://github.com/{GITHUB_REPOSITORY}"
