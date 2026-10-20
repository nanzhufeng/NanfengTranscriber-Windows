"""Offline drift checks; this is not an installer or media acceptance test."""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.model_modes import MODE_OPTIONS, MODE_MODEL_LABELS, LOCAL_MODE_OPTIONS, CLOUD_MODELS, model_for_mode

REGISTRY = "docs/contract-registry.json"


def active_documents(root: Path) -> tuple[str, ...]:
    try:
        registry = json.loads((root / REGISTRY).read_text(encoding="utf-8"))
        return tuple(item["path"] for item in registry["documents"] if item["role"] != "historical")
    except (OSError, ValueError, KeyError, TypeError):
        return ()


ACTIVE_DOCS = active_documents(ROOT)


def local_file(root: Path, relative: str) -> Path:
    file = (root / relative).resolve()
    if not file.is_relative_to(root.resolve()) or not file.is_file():
        raise ValueError(relative)
    return file


def audit_registry(root: Path, check) -> None:
    try:
        registry = json.loads((root / REGISTRY).read_text(encoding="utf-8"))
        documents, contracts = registry["documents"], registry["contracts"]
        assert registry["schema_version"] == 1
        assert isinstance(documents, list) and isinstance(contracts, list)
        assert all(isinstance(item, dict) and isinstance(item.get("path"), str)
                   and isinstance(item.get("role"), str) for item in documents)
        assert all(isinstance(item, dict) and isinstance(item.get("id"), str)
                   and all(isinstance(item.get(key), list) and all(isinstance(value, str) for value in item[key])
                           for key in ("owners", "tests")) for item in contracts)
        assert all(isinstance(item, dict) and isinstance(item.get("path"), str) for item in registry.get("local_drafts", []))
        assert all(isinstance(value, str) for value in registry.get("legacy_entrypoints", []))
        paths = [item["path"] for item in documents]
        assert len(paths) == len(set(paths)) and registry["authority"] == "docs/CONTRACTS.md"
        check("contract registry", True)
    except (OSError, ValueError, KeyError, TypeError, AssertionError) as exc:
        check("contract registry", False, type(exc).__name__)
        return
    roles = {"policy", "guide", "authority", "architecture", "status", "handoff", "history-index", "audit", "planned", "route", "historical"}
    role_errors = []
    for item in documents:
        try:
            text = local_file(root, item["path"]).read_text(encoding="utf-8-sig")
            assert item["role"] in roles
            if item["role"] == "historical":
                assert "历史" in text.splitlines()[0]
            if item["role"] == "planned":
                assert "未实施" in text.splitlines()[0]
        except (OSError, ValueError, AssertionError, IndexError):
            role_errors.append(item["path"])
    check("document roles", not role_errors, ", ".join(role_errors))
    authorities = [item["path"] for item in documents if item["role"] == "authority"]
    check("single contract authority", authorities == [registry["authority"]])
    observed = {p.relative_to(root).as_posix() for folder in (root / "docs", root / "tests/ui_baselines") for p in folder.rglob("*.md")}
    observed.update(name for name in ("README.md", "AGENTS.md") if (root / name).is_file())
    drafts = {item["path"] for item in registry.get("local_drafts", [])}
    check("document inventory", observed - drafts == set(paths), ", ".join(sorted((observed - drafts) ^ set(paths))))
    try:
        text = local_file(root, registry["authority"]).read_text(encoding="utf-8")
    except (OSError, ValueError):
        check("contract coverage", False, "authority missing or unreadable")
        return
    headings = re.findall(r"^## (C\d+) ", text, re.M)
    identifiers = [item["id"] for item in contracts]
    check("contract coverage", len(identifiers) == len(set(identifiers)) and len(headings) == len(set(headings)) and set(identifiers) == set(headings))
    trees = {}
    reference_errors = []
    for item in contracts:
        if not item.get("owners") or not item.get("tests"):
            reference_errors.append(item["id"])
        for reference in item.get("owners", []) + item.get("tests", []):
            try:
                name, _, symbol = reference.partition(":")
                file = local_file(root, name)
                if symbol:
                    if name not in trees:
                        trees[name] = ast.parse(file.read_text(encoding="utf-8-sig"))
                    node = trees[name]
                    for part in symbol.split("."):
                        node = next(child for child in node.body if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == part)
            except (OSError, ValueError, SyntaxError, StopIteration):
                reference_errors.append(reference)
    for name in registry.get("legacy_entrypoints", []):
        try:
            local_file(root, name)
        except ValueError:
            reference_errors.append(name)
    check("contract references", not reference_errors, ", ".join(reference_errors))
    rows = {match[0].strip(): match[1].strip() for match in re.findall(r"^\| ([^|]+) \| ([^|]+) \|", text, re.M)}
    check("documented models", all(MODE_MODEL_LABELS[mode] in rows.get(mode, "") for mode in MODE_OPTIONS))


def audit_status(root: Path, version: str, check) -> None:
    try:
        status = (root / "docs/PROJECT_STATUS.md").read_text(encoding="utf-8")
        def field(name):
            match = re.search(rf"^- {re.escape(name)}: (.+)$", status, re.M)
            return match[1].strip() if match else ""
        check("source status version", field("Product version") == version)
        published = field("Published version")
        assert re.fullmatch(r"\d+\.\d+\.\d+", published)
        receipt = json.loads((root / f"docs/release-v{published}.json").read_text(encoding="utf-8"))
        check("published status", receipt["version"] == published and field("Release source") == receipt["sourceCommit"] and field("Release signature") == receipt["authenticode"])
    except (OSError, ValueError, KeyError, AssertionError) as exc:
        check("published status", False, type(exc).__name__)


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
    audit_registry(root, check)
    audit_status(root, version, check)
    try:
        readme = (root / "README.md").read_text(encoding="utf-8")
        versions = re.findall(r"NanfengTranscriber-Windows-v(\d+\.\d+\.\d+)-Setup\.exe", readme)
        check("README installer version", bool(versions) and set(versions) == {version}, str(versions))
        for kind in ("preview", "settings", "history", "player"):
            expected = f"docs/{kind}-v{version}.png"
            check(f"README {kind}", expected in readme and (root / expected).is_file(), expected)
    except OSError:
        check("README", False, "missing")
    check("model catalogue", set(MODE_OPTIONS) == set(MODE_MODEL_LABELS)
          and len(LOCAL_MODE_OPTIONS) == 2 and len(CLOUD_MODELS) == 2
          and len({model_for_mode(name) for name in MODE_OPTIONS}) == len(MODE_OPTIONS))
    for name in active_documents(root):
        file = root / name
        if not file.is_file():
            check(f"document {name}", False, "missing")
            continue
        broken = []
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", file.read_text(encoding="utf-8")):
            if re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith("#"):
                continue
            relative = unquote(target.split("#", 1)[0].split("?", 1)[0])
            if relative:
                try:
                    local_file(root, str(file.parent.relative_to(root) / relative))
                except ValueError:
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
                  and receipt["authenticode"] in {"NotSigned", "Valid"}
                  and re.fullmatch(r"[a-f0-9]{40}", receipt["sourceCommit"])
                  and receipt["remoteAssetCount"] == 1
                  and receipt["remoteDigestVerified"] == "sha256:" + receipt["sha256"].lower())
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
