"""Offline drift checks; this is not an installer or media acceptance test."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.model_modes import MODE_OPTIONS, MODE_MODEL_LABELS, LOCAL_MODE_OPTIONS, CLOUD_MODELS, model_for_mode

ACTIVE_DOCS = (
    "AGENTS.md", "README.md", "docs/CONTRACTS.md", "docs/context.md",
    "docs/PROJECT_STATUS.md", "docs/CURRENT_HANDOFF.md",
    "docs/chatgpt-project-context.md", "docs/HISTORY.md",
    "docs/contract-audit.md", "docs/MAC_CODEX_START_PROMPT.md",
)


def audit_project(root: Path, release: bool = False) -> list[tuple[str, bool, str]]:
    checks = []
    def check(name, passed, detail=""):
        checks.append((name, bool(passed), detail))
    try:
        meta = json.loads((root / "app/assets/product.json").read_text(encoding="utf-8"))
        version = meta["version"]
        check("product metadata", re.fullmatch(r"\d+\.\d+\.\d+", version)
              and meta["name"] == "南枫转写" and meta["repository"] == "nanzhufeng/NanfengTranscriber-Windows"
              and re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", meta["developed_at"]))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        check("product metadata", False, type(exc).__name__)
        return checks
    try:
        readme = (root / "README.md").read_text(encoding="utf-8")
        versions = re.findall(r"NanfengTranscriber-Windows-v(\d+\.\d+\.\d+)-Setup\.exe", readme)
        check("README installer version", bool(versions) and set(versions) == {version}, str(versions))
        for kind in ("preview", "settings"):
            expected = f"docs/{kind}-v{version}.png"
            check(f"README {kind}", expected in readme and (root / expected).is_file(), expected)
    except OSError:
        check("README", False, "missing")
    check("model catalogue", set(MODE_OPTIONS) == set(MODE_MODEL_LABELS)
          and len(LOCAL_MODE_OPTIONS) == 2 and len(CLOUD_MODELS) == 2
          and len({model_for_mode(name) for name in MODE_OPTIONS}) == len(MODE_OPTIONS))
    for name in ACTIVE_DOCS:
        file = root / name
        if not file.is_file():
            check(f"document {name}", False, "missing")
            continue
        broken = []
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", file.read_text(encoding="utf-8")):
            if re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith("#"):
                continue
            relative = unquote(target.split("#", 1)[0].split("?", 1)[0])
            if relative and not (file.parent / relative).exists():
                broken.append(target)
        check(f"links {name}", not broken, ", ".join(broken))
    spec = (root / "南枫转写_Windows.spec").read_text(encoding="utf-8-sig")
    check("owned UI assets", "CleanVideoDownloader" not in spec and (root / "app/assets/chevron-down.svg").is_file())
    for name in ("requirements.txt", "requirements-qwen.txt", "requirements-build.txt"):
        requirements = [line.strip() for line in (root / name).read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith(("#", "-r "))]
        check(f"pinned {name}", bool(requirements) and all(re.fullmatch(r"[\w.-]+==[\w.+-]+", line) for line in requirements))
    for name in ("scripts/build_windows_app.ps1", "scripts/setup_qwen_runtime.ps1", "build_windows_installer_inno.ps1"):
        check(f"PowerShell encoding {name}", (root / name).read_bytes().startswith(b"\xef\xbb\xbf"))
    if release:
        try:
            receipt = json.loads((root / f"docs/release-v{version}.json").read_text(encoding="utf-8"))
            check("release receipt", receipt["version"] == version
                  and receipt["installer"] == f"NanfengTranscriber-Windows-v{version}-Setup.exe"
                  and receipt["bytes"] > 1_000_000 and re.fullmatch(r"[a-fA-F0-9]{64}", receipt["sha256"])
                  and receipt["authenticode"] in {"NotSigned", "Valid"})
        except (OSError, ValueError, KeyError, TypeError):
            check("release receipt", False, "missing or invalid")
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description="检查当前项目合同漂移，不执行安装或网络请求")
    parser.add_argument("--release", action="store_true", help="另校验已声明的版本收据；不替代真实产物验收")
    args = parser.parse_args()
    checks = audit_project(ROOT, args.release)
    for name, passed, detail in checks:
        print(f"{'PASS' if passed else 'FAIL'}: {name}" + (f" — {detail}" if not passed else ""))
    failed = sum(not passed for _, passed, _ in checks)
    print(f"SUMMARY: {len(checks) - failed} passed, {failed} failed")
    return int(bool(failed))


if __name__ == "__main__":
    raise SystemExit(main())
