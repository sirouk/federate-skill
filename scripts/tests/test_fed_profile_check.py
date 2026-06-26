#!/usr/bin/env python3
"""Tests for managed default profile metadata checks."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "fed_profile_check.py"
GOOD_SHA = "621096ac2781d542b94b8412ff76c3149d19a882"
PROFILE_TEXT = "MODE\noperate autonomously.\n"


def sha256_text(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class FedProfileCheckTests(unittest.TestCase):
    def write_profile_tree(self, profile_text: str = PROFILE_TEXT, meta_overrides: dict | None = None):
        td = tempfile.TemporaryDirectory()
        root = Path(td.name)
        profiles = root / "profiles"
        profiles.mkdir()
        profile = profiles / "llm_opa.min.txt"
        profile.write_text(profile_text, encoding="utf-8")
        meta = {
            "schema": "federate.managed_profile.v1",
            "name": "llm-operating-agreement",
            "path": "profiles/llm_opa.min.txt",
            "source": "https://github.com/sirouk/llm-operating-agreement.git",
            "ref": GOOD_SHA,
            "source_path": "LLM_OPA.min.txt",
            "commit": GOOD_SHA,
            "sha256": sha256_text(profile_text),
            "license": "CC BY 4.0",
        }
        if meta_overrides:
            meta.update(meta_overrides)
        meta_path = profiles / "llm_opa.meta.json"
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        return td, root, profile, meta_path

    def run_check(self, meta_path: Path):
        return subprocess.run(
            [str(SCRIPT), "--meta", str(meta_path)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_pinned_profile_is_up_to_date_without_network(self):
        td, _root, _profile, meta_path = self.write_profile_tree()
        with td:
            proc = self.run_check(meta_path)

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("UP_TO_DATE", proc.stdout)
        self.assertIn(f"commit={GOOD_SHA}", proc.stdout)

    def test_local_profile_hash_drift_is_reported(self):
        td, _root, profile, meta_path = self.write_profile_tree()
        with td:
            profile.write_text("changed\n", encoding="utf-8")
            proc = self.run_check(meta_path)

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("LOCAL_CHANGED", proc.stdout)
        self.assertIn("expected_sha=", proc.stdout)
        self.assertIn("actual_sha=", proc.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
