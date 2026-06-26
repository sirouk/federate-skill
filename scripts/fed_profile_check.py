#!/usr/bin/env python3
"""Check the managed default federation profile against local and upstream metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_META = ROOT / "profiles" / "llm_opa.meta.json"


def die(message: str, code: int = 2) -> None:
    print(f"ERROR {message}", file=sys.stderr)
    raise SystemExit(code)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_meta(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        die(f"missing profile metadata: {path}")
    except json.JSONDecodeError as exc:
        die(f"invalid profile metadata JSON: {path}: {exc}")


def is_full_sha(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]{40}", value or ""))


def raw_url(source: str, commit: str, source_path: str) -> str:
    match = re.fullmatch(r"(?:https://github\.com/|git@github\.com:)([^/]+/[^/.]+)(?:\.git)?", source)
    if not match:
        die(f"unsupported GitHub source URL: {source}")
    return f"https://raw.githubusercontent.com/{match.group(1)}/{commit}/{source_path}"


def remote_commit(source: str, ref: str) -> str:
    if is_full_sha(ref):
        return ref.lower()
    try:
        proc = subprocess.run(
            ["git", "ls-remote", source, ref],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        die("git not found; cannot check managed profile upstream")
    if proc.returncode != 0:
        die(f"could not resolve profile upstream {source} {ref}: {proc.stderr.strip()}")
    first = proc.stdout.splitlines()[0].split()[0] if proc.stdout.splitlines() else ""
    if not is_full_sha(first):
        die(f"profile upstream did not return a full 40-hex SHA for {source} {ref}: {first}")
    return first.lower()


def fetch_to(path: Path, url: str) -> None:
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            data = response.read()
    except Exception as exc:  # noqa: BLE001 - report a concise command-style error.
        die(f"could not fetch managed profile {url}: {exc}")
    path.write_bytes(data)


def write_meta(path: Path, meta: dict) -> None:
    path.write_text(json.dumps(meta, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def check(args: argparse.Namespace) -> int:
    meta_path = Path(args.meta).expanduser().resolve()
    meta = load_meta(meta_path)
    profile_path = (meta_path.parent.parent / meta.get("path", "")).resolve()
    expected_sha = str(meta.get("sha256", "")).lower()
    recorded_commit = str(meta.get("commit", "")).lower()
    source = str(meta.get("source", ""))
    ref = str(meta.get("ref", ""))
    source_path = str(meta.get("source_path", ""))

    if not profile_path.is_file():
        die(f"missing managed profile file: {profile_path}")
    local_sha = sha256(profile_path)
    if local_sha != expected_sha:
        print(
            f"LOCAL_CHANGED path={profile_path} expected_sha={expected_sha} actual_sha={local_sha} meta={meta_path}"
        )
        return 0

    latest_commit = remote_commit(source, ref)
    if latest_commit == recorded_commit:
        print(f"UP_TO_DATE path={profile_path} commit={recorded_commit} sha256={local_sha}")
        return 0

    with tempfile.TemporaryDirectory() as td:
        tmp_profile = Path(td) / "profile"
        fetch_to(tmp_profile, raw_url(source, latest_commit, source_path))
        latest_sha = sha256(tmp_profile)
        if latest_sha == local_sha:
            print(
                "UPSTREAM_COMMIT_CHANGED_FILE_SAME "
                f"path={profile_path} installed_commit={recorded_commit} latest_commit={latest_commit} sha256={local_sha}"
            )
            if args.apply:
                meta["commit"] = latest_commit
                write_meta(meta_path, meta)
                print(f"UPDATED_META commit={latest_commit} sha256={local_sha}")
            return 0

        print(
            "UPDATE_AVAILABLE "
            f"path={profile_path} installed_commit={recorded_commit} latest_commit={latest_commit} "
            f"installed_sha={local_sha} latest_sha={latest_sha}"
        )
        if args.apply:
            profile_path.write_bytes(tmp_profile.read_bytes())
            meta["commit"] = latest_commit
            meta["sha256"] = latest_sha
            write_meta(meta_path, meta)
            print(f"UPDATED_PROFILE commit={latest_commit} sha256={latest_sha}")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--meta", default=str(DEFAULT_META), help="managed profile metadata path")
    parser.add_argument("--apply", action="store_true", help="apply a detected upstream profile update")
    args = parser.parse_args()
    return check(args)


if __name__ == "__main__":
    raise SystemExit(main())
