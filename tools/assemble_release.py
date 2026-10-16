"""Reassemble verified draft-only transport parts; never rebuild an installer."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
import time


def api(path, method="GET"):
    result = subprocess.run(["gh", "api", "--method", method, path], check=True, capture_output=True, text=True)
    return json.loads(result.stdout) if result.stdout.strip() else None


def main():
    repo = os.environ["GITHUB_REPOSITORY"]
    release_id = os.environ["RELEASE_ID"]
    tag = os.environ["RELEASE_TAG"]
    expected_hash = os.environ["EXPECTED_SHA256"].lower()
    expected_size = int(os.environ["EXPECTED_BYTES"])
    commit = os.environ["SOURCE_COMMIT"]
    count = int(os.environ["PART_COUNT"])
    assert release_id.isdecimal() and re.fullmatch(r"v\d+\.\d+\.\d+", tag)
    assert re.fullmatch(r"[a-f0-9]{64}", expected_hash) and re.fullmatch(r"[a-f0-9]{40}", commit)
    assert 0 < count <= 256 and 1_000_000 < expected_size < 2_000_000_000
    endpoint = f"repos/{repo}/releases/{release_id}"
    release = api(endpoint)
    assert release["draft"] and release["tag_name"] == tag and release["target_commitish"] == commit
    name = f"NanfengTranscriber-Windows-{tag}-Setup.exe"
    prefix = f"transport-{tag}.part-"
    part_names = {f"{prefix}{index:03}" for index in range(count)}
    assets = {item["name"]: item for item in api(endpoint + "/assets?per_page=100")}
    assert set(assets) <= part_names | {name}, "Unexpected draft asset; refusing publication"
    digest = "sha256:" + expected_hash
    if name in assets and assets[name]["state"] == "starter":
        api(f"repos/{repo}/releases/assets/{assets[name]['id']}", "DELETE")
        del assets[name]
    if name not in assets:
        assert part_names <= set(assets), "Transport parts are incomplete"
        with TemporaryDirectory(prefix="nanfeng-release-") as directory:
            root = Path(directory)
            subprocess.run(["gh", "release", "download", tag, "--repo", repo, "--pattern", prefix + "*", "--dir", str(root)], check=True)
            target = root / name
            checksum = hashlib.sha256()
            with target.open("wb") as output:
                for part_name in sorted(part_names):
                    data = (root / part_name).read_bytes()
                    part = assets[part_name]
                    assert part["state"] == "uploaded" and len(data) == part["size"]
                    assert part["digest"] == "sha256:" + hashlib.sha256(data).hexdigest()
                    output.write(data)
                    checksum.update(data)
            assert target.stat().st_size == expected_size and checksum.hexdigest() == expected_hash
            subprocess.run(["gh", "release", "upload", tag, str(target), "--repo", repo], check=True)
        for attempt in range(20):
            assets = {item["name"]: item for item in api(endpoint + "/assets?per_page=100")}
            if name in assets and assets[name]["state"] == "uploaded" and assets[name]["digest"]:
                break
            time.sleep(3)
    full = assets[name]
    assert full["state"] == "uploaded" and full["size"] == expected_size and full["digest"] == digest
    for part_name in sorted(part_names & set(assets)):
        api(f"repos/{repo}/releases/assets/{assets[part_name]['id']}", "DELETE")
    final = api(endpoint + "/assets?per_page=100")
    assert len(final) == 1 and final[0]["name"] == name and final[0]["digest"] == digest
    subprocess.run(["gh", "release", "edit", tag, "--repo", repo, "--draft=false", "--latest"], check=True)
    published = api(endpoint)
    assert not published["draft"] and not published["prerelease"]
    print(json.dumps({"url": published["html_url"], "bytes": expected_size, "sha256": expected_hash}))


if __name__ == "__main__":
    main()
