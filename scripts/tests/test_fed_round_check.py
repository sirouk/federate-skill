#!/usr/bin/env python3
"""test_fed_round_check.py — oracle for Fix D round accountability."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
FED_ROUND_CHECK = SCRIPTS / "fed_round_check.py"

NONCE = {
    "claude": "FED-aaaaaaaa-1111-2222-3333-aaaaaaaaaaaa",
    "codex": "FED-bbbbbbbb-1111-2222-3333-bbbbbbbbbbbb",
    "hermes": "FED-cccccccc-1111-2222-3333-cccccccccccc",
}
HEX = "a" * 64


class FedRoundCheckContract(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.relay = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write_json(self, name, data):
        (self.relay / name).write_text(
            json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def write_receipt(self, agent, nonce=None, receipt_agent=None):
        nonce = nonce or NONCE[agent]
        receipt_agent = receipt_agent or agent
        self.write_json(f"receipt_{agent}.json", {
            "schema": "federate.read_receipt.v1",
            "agent": receipt_agent,
            "nonce": nonce,
            "reply_sha256": HEX,
            "source_path": f"/tmp/{agent}.jsonl",
            "source_kind": "jsonl",
            "window_sha256": HEX,
        })

    def write_round(self, expected_agents):
        expected = {}
        for agent in expected_agents:
            expected[NONCE[agent]] = {
                "agent": agent,
                "session": f"fed-ns-{agent}-0",
                "sent_at": "2026-06-25T14:22:03Z",
            }
        self.write_json("round_manifest.json", {
            "schema": "federate.round_manifest.v1",
            "round": 1,
            "phase": "independent",
            "created_at": "2026-06-25T14:22:01Z",
            "expected": expected,
        })

    def write_cross(self, peers, source_nonces=None, unavailable=None):
        source_nonces = source_nonces or {}
        sources = {}
        for agent in peers:
            nonce = source_nonces.get(agent, NONCE[agent])
            self.write_receipt(agent, nonce)
            sources[agent] = {
                "receipt_path": f"receipt_{agent}.json",
                "nonce": nonce,
                "sha256": HEX,
            }
        cross_files = {}
        for receiver in peers:
            cross_files[receiver] = {
                "receiver": receiver,
                "blocks": [{"source": p} for p in peers if p != receiver],
            }
        self.write_json("cross_manifest.json", {
            "schema": "federate.cross_manifest.v1",
            "peers": peers,
            "sources": sources,
            "cross_files": cross_files,
            "unavailable": unavailable or [],
        })

    def run_check(self):
        return subprocess.run(
            [sys.executable, str(FED_ROUND_CHECK), "--relay", str(self.relay)],
            capture_output=True,
            text=True,
        )

    def run_check_round(self, round_number):
        return subprocess.run(
            [sys.executable, str(FED_ROUND_CHECK), "--relay", str(self.relay),
             "--round", str(round_number)],
            capture_output=True,
            text=True,
        )

    def test_00_fed_round_check_present(self):
        p = self.run_check()
        self.assertNotIn("No such file or directory", p.stderr,
                         "fed_round_check.py absent — EXPECTED pre-impl RED")

    def test_pristine_sources_satisfy_expected(self):
        self.write_round(["claude", "codex"])
        self.write_cross(["claude", "codex"])
        p = self.run_check()
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_round_option_scopes_manifests_under_round_directory(self):
        root = self.relay
        round_dir = root / "round_2"
        round_dir.mkdir()
        self.relay = round_dir
        try:
            self.write_round(["claude", "codex"])
            self.write_cross(["claude", "codex"])
        finally:
            self.relay = root

        p = self.run_check_round(2)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse((root / "round_manifest.json").exists())
        self.assertFalse((root / "cross_manifest.json").exists())

    def test_expected_nonce_missing_fails(self):
        self.write_round(["claude", "codex", "hermes"])
        self.write_cross(["claude", "codex"])
        p = self.run_check()
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("not accounted", p.stderr)

    def test_unavailable_with_evidence_accounts_for_nonce(self):
        self.write_round(["claude", "codex", "hermes"])
        evidence = self.relay / "hermes_timeout.txt"
        evidence.write_text("fed_wait timed out\n", encoding="utf-8")
        self.write_cross(["claude", "codex"], unavailable=[{
            "nonce": NONCE["hermes"],
            "agent": "hermes",
            "reason": "timeout",
            "evidence_path": evidence.name,
        }])
        p = self.run_check()
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_unavailable_without_nonempty_evidence_fails(self):
        self.write_round(["claude", "codex", "hermes"])
        evidence = self.relay / "empty_timeout.txt"
        evidence.write_text("", encoding="utf-8")
        self.write_cross(["claude", "codex"], unavailable=[{
            "nonce": NONCE["hermes"],
            "agent": "hermes",
            "reason": "timeout",
            "evidence_path": evidence.name,
        }])
        p = self.run_check()
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("evidence", p.stderr)

    def test_unknown_source_nonce_fails(self):
        self.write_round(["claude", "codex"])
        self.write_cross(["claude", "codex"], source_nonces={
            "codex": "FED-dddddddd-1111-2222-3333-dddddddddddd",
        })
        p = self.run_check()
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("unknown source nonce", p.stderr)

    def test_receipt_agent_mismatch_fails(self):
        self.write_round(["claude", "codex"])
        self.write_cross(["claude", "codex"])
        self.write_receipt("claude", receipt_agent="codex")
        p = self.run_check()
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("receipt agent", p.stderr)

    def test_self_source_block_fails(self):
        self.write_round(["claude", "codex"])
        self.write_cross(["claude", "codex"])
        man = json.loads((self.relay / "cross_manifest.json").read_text())
        man["cross_files"]["claude"]["blocks"].append({"source": "claude"})
        self.write_json("cross_manifest.json", man)
        p = self.run_check()
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("own source", p.stderr)

    def test_source_omitted_from_peers_fails(self):
        self.write_round(["claude", "codex"])
        self.write_cross(["claude", "codex"])
        man = json.loads((self.relay / "cross_manifest.json").read_text())
        man["peers"] = ["claude"]
        man["cross_files"] = {"claude": {"receiver": "claude", "blocks": []}}
        self.write_json("cross_manifest.json", man)
        p = self.run_check()
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("sources must match peers", p.stderr)

    def test_missing_block_for_source_fails(self):
        self.write_round(["claude", "codex"])
        self.write_cross(["claude", "codex"])
        man = json.loads((self.relay / "cross_manifest.json").read_text())
        man["cross_files"]["claude"]["blocks"] = []
        self.write_json("cross_manifest.json", man)
        p = self.run_check()
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("missing source block", p.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
