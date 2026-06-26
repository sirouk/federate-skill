#!/usr/bin/env python3
"""Implementation-level coverage for fed_read receipt emission."""
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parent.parent
FED_READ = SCRIPTS / "fed_read.py"
FED_CROSS = SCRIPTS / "fed_cross.py"


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


def claude_jsonl(nonce, reply):
    rows = [
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "text", "text": "[[%s]]\n\nbrief body\n\n[[%s]]" % (nonce, nonce)}]}},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": reply}]}},
    ]
    return "".join(json.dumps(row) + "\n" for row in rows)


def codex_jsonl(nonce, reply, close_marker=True):
    body = "[[%s]]\n\nbrief body" % nonce
    if close_marker:
        body += "\n\n[[%s]]" % nonce
    rows = [
        {"type": "response_item", "payload": {"role": "user", "content": [
            {"type": "input_text", "text": body}]}},
        {"type": "response_item", "payload": {"role": "assistant",
            "phase": "final_answer", "content": [
                {"type": "output_text", "text": reply}]}},
    ]
    return "".join(json.dumps(row) + "\n" for row in rows)


def codex_jsonl_with_tool_event(nonce, reply):
    rows = [
        {"type": "response_item", "payload": {"role": "user", "content": [
            {"type": "input_text", "text": "[[%s]]\n\nbrief body\n\n[[%s]]" % (nonce, nonce)}]}},
        {"type": "response_item", "payload": {
            "type": "function_call",
            "name": "shell",
            "arguments": "{\"cmd\":\"echo should-not-run\"}",
        }},
        {"type": "response_item", "payload": {"role": "assistant",
            "phase": "final_answer", "content": [
                {"type": "output_text", "text": reply}]}},
    ]
    return "".join(json.dumps(row) + "\n" for row in rows)


FAKE_SSH = """#!/usr/bin/env python3
import subprocess
import sys

args = sys.argv[1:]
try:
    i = args.index("python3")
except ValueError:
    print("missing python3 argv", file=sys.stderr)
    sys.exit(2)
if i + 3 >= len(args) or args[i + 1] != "-":
    print("unexpected remote python argv", file=sys.stderr)
    sys.exit(2)
key = args[i + 2]
db_path = args[i + 3]
code = sys.stdin.read()
proc = subprocess.run(
    [sys.executable, "-", key, db_path],
    input=code,
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    check=False,
)
sys.stdout.write(proc.stdout)
sys.stderr.write(proc.stderr)
sys.exit(proc.returncode)
"""


class FedReadReceiptImpl(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def make_fake_ssh(self):
        fake = self.root / "fake_ssh.py"
        fake.write_text(FAKE_SSH)
        fake.chmod(0o755)
        return fake

    def remote_env(self, db, host="reviewer@host"):
        fake = self.make_fake_ssh()
        return dict(
            os.environ,
            FED_HERMES_REMOTE_READ="ssh",
            FED_HERMES_SSH_CMD=f"{fake} {host}",
            FED_HERMES_REMOTE_STATE_DB=str(db),
        )

    def make_hermes_db(self, rows):
        db = self.root / "state.db"
        con = sqlite3.connect(db)
        con.execute(
            "CREATE TABLE messages ("
            "id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, active INTEGER)"
        )
        con.executemany(
            "INSERT INTO messages (id, session_id, role, content, active) VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        con.commit()
        con.close()
        return db

    def test_hermes_receipt_dir_from_env_state_db(self):
        db = self.root / "state.db"
        con = sqlite3.connect(db)
        con.execute(
            "CREATE TABLE messages ("
            "id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, active INTEGER)"
        )
        nonce = "FED-cafebabe-1111-2222-3333-cafebabecafe"
        reply = "HERMES_IMPL_REPLY with CRLF\r\nand unicode α"
        con.executemany(
            "INSERT INTO messages (id, session_id, role, content, active) VALUES (?, ?, ?, ?, ?)",
            [
                (1, "s1", "user", "[[%s]]\n\nbrief body\n\n[[%s]]" % (nonce, nonce), 1),
                (2, "s1", "assistant", reply, 1),
            ],
        )
        con.commit()
        con.close()

        relay = self.root / "relay"
        relay.mkdir()
        env = dict(os.environ, FED_HERMES_STATE_DB=str(db))
        p = subprocess.run(
            [sys.executable, str(FED_READ), "hermes", "--nonce", nonce,
             "--receipt-dir", str(relay)],
            capture_output=True, env=env)
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", errors="replace"))
        self.assertEqual(p.stdout.rstrip(b"\n"), reply.encode("utf-8"))

        reply_b = (relay / "reply_hermes.txt").read_bytes()
        receipt = json.loads((relay / "receipt_hermes.json").read_text())
        self.assertEqual(reply_b, reply.encode("utf-8"))
        self.assertEqual(receipt["schema"], "federate.read_receipt.v1")
        self.assertEqual(receipt["agent"], "hermes")
        self.assertEqual(receipt["nonce"], nonce)
        self.assertEqual(receipt["source_path"], str(db))
        self.assertEqual(receipt["source_kind"], "sqlite")
        self.assertEqual(receipt["reply_sha256"], sha256_hex(reply_b))
        self.assertRegex(receipt["window_sha256"], r"^[0-9a-f]{64}$")

    def test_claude_receipt_dir_from_home_project_glob(self):
        home = self.root / "home"
        project = home / ".claude" / "projects" / "tmp-project"
        project.mkdir(parents=True)
        transcript = project / "session.jsonl"
        nonce = "FED-facefeed-1111-2222-3333-facefeedface"
        reply = "CLAUDE_IMPL_REPLY from default glob"
        transcript.write_text(claude_jsonl(nonce, reply))

        relay = self.root / "relay"
        relay.mkdir()
        env = dict(os.environ, HOME=str(home))
        p = subprocess.run(
            [sys.executable, str(FED_READ), "claude", "--nonce", nonce,
             "--receipt-dir", str(relay)],
            capture_output=True, env=env)
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", errors="replace"))
        self.assertEqual(p.stdout.rstrip(b"\n"), reply.encode("utf-8"))

        reply_b = (relay / "reply_claude.txt").read_bytes()
        receipt = json.loads((relay / "receipt_claude.json").read_text())
        self.assertEqual(reply_b, reply.encode("utf-8"))
        self.assertEqual(receipt["agent"], "claude")
        self.assertEqual(receipt["nonce"], nonce)
        self.assertEqual(receipt["source_path"], str(transcript))
        self.assertEqual(receipt["source_kind"], "jsonl")
        self.assertEqual(receipt["reply_sha256"], sha256_hex(reply_b))
        self.assertRegex(receipt["window_sha256"], r"^[0-9a-f]{64}$")

    def test_codex_requires_top_and_bottom_nonce_markers(self):
        transcript = self.root / "rollout.jsonl"
        nonce = "FED-abcdabcd-1111-2222-3333-abcdabcdabcd"
        transcript.write_text(codex_jsonl(nonce, "TRUNCATED_REPLY", close_marker=False))

        p = subprocess.run(
            [sys.executable, str(FED_READ), "codex", "--nonce", nonce,
             "--source", str(transcript)],
            capture_output=True, text=True)
        self.assertEqual(p.returncode, 3)
        self.assertIn("NOT FOUND", p.stderr)

        transcript.write_text(codex_jsonl(nonce, "COMPLETE_REPLY", close_marker=True))
        p = subprocess.run(
            [sys.executable, str(FED_READ), "codex", "--nonce", nonce,
             "--source", str(transcript)],
            capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.rstrip("\n"), "COMPLETE_REPLY")

    def test_hermes_requires_top_and_bottom_nonce_markers(self):
        db = self.root / "state.db"
        nonce = "FED-beadbead-1111-2222-3333-beadbeadbead"
        con = sqlite3.connect(db)
        con.execute(
            "CREATE TABLE messages ("
            "id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, active INTEGER)"
        )
        con.executemany(
            "INSERT INTO messages (id, session_id, role, content, active) VALUES (?, ?, ?, ?, ?)",
            [
                (1, "s1", "user", "[[%s]]\n\nbrief body" % nonce, 1),
                (2, "s1", "assistant", "TRUNCATED_REPLY", 1),
            ],
        )
        con.commit()
        con.close()

        p = subprocess.run(
            [sys.executable, str(FED_READ), "hermes", "--nonce", nonce,
             "--source", str(db)],
            capture_output=True, text=True)
        self.assertEqual(p.returncode, 3)
        self.assertIn("NOT FOUND", p.stderr)

    def test_remote_hermes_receipt_dir_and_source_reextract(self):
        nonce = "FED-remoterd-1111-2222-3333-remoterdtest"
        reply = "REMOTE_HERMES_REPLY"
        db = self.make_hermes_db([
            (1, "remote-session", "user", "[[%s]]\nbrief body\n[[%s]]" % (nonce, nonce), 1),
            (2, "remote-session", "assistant", reply, 1),
        ])
        relay = self.root / "relay-remote"
        relay.mkdir()
        env = self.remote_env(db)

        p = subprocess.run(
            [sys.executable, str(FED_READ), "hermes", "--nonce", nonce,
             "--receipt-dir", str(relay)],
            capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.rstrip("\n"), reply)
        self.assertIn("[fed_read hermes remote]", p.stderr)

        receipt = json.loads((relay / "receipt_hermes.json").read_text())
        self.assertEqual(receipt["source_kind"], "sqlite")
        self.assertTrue(receipt["source_path"].startswith("hermes+ssh://cmd-"))
        self.assertIsNone(receipt["source_file_sha256"])

        p2 = subprocess.run(
            [sys.executable, str(FED_READ), "hermes", "--nonce", nonce,
             "--source", receipt["source_path"]],
            capture_output=True, text=True, env=env)
        self.assertEqual(p2.returncode, 0, p2.stderr)
        self.assertEqual(p2.stdout.rstrip("\n"), reply)

    def test_remote_hermes_source_command_hash_mismatch_fails(self):
        nonce = "FED-remotehx-1111-2222-3333-remotehxtest"
        db = self.make_hermes_db([
            (1, "s1", "user", "[[%s]]\nbrief body\n[[%s]]" % (nonce, nonce), 1),
            (2, "s1", "assistant", "REMOTE_REPLY", 1),
        ])
        relay = self.root / "relay-remote-hash"
        relay.mkdir()
        env = self.remote_env(db, host="reviewer@host")
        p = subprocess.run(
            [sys.executable, str(FED_READ), "hermes", "--nonce", nonce,
             "--receipt-dir", str(relay)],
            capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 0, p.stderr)
        receipt = json.loads((relay / "receipt_hermes.json").read_text())

        mismatch_env = self.remote_env(db, host="other@host")
        p2 = subprocess.run(
            [sys.executable, str(FED_READ), "hermes", "--nonce", nonce,
             "--source", receipt["source_path"]],
            capture_output=True, text=True, env=mismatch_env)
        self.assertEqual(p2.returncode, 2)
        self.assertIn("different FED_HERMES_SSH_CMD", p2.stderr)

    def test_remote_hermes_source_hash_binds_expanded_env_argv(self):
        nonce = "FED-envhashx-1111-2222-3333-envhashxtest"
        db = self.make_hermes_db([
            (1, "s1", "user", "[[%s]]\nbrief body\n[[%s]]" % (nonce, nonce), 1),
            (2, "s1", "assistant", "REMOTE_REPLY", 1),
        ])
        relay = self.root / "relay-remote-env-hash"
        relay.mkdir()
        fake = self.make_fake_ssh()
        env = dict(
            os.environ,
            FED_HERMES_REMOTE_READ="ssh",
            FED_HERMES_SSH_CMD=f"{fake} $FED_REMOTE_HOST",
            FED_REMOTE_HOST="reviewer@host",
            FED_HERMES_REMOTE_STATE_DB=str(db),
        )
        p = subprocess.run(
            [sys.executable, str(FED_READ), "hermes", "--nonce", nonce,
             "--receipt-dir", str(relay)],
            capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 0, p.stderr)
        receipt = json.loads((relay / "receipt_hermes.json").read_text())

        mismatch_env = dict(env, FED_REMOTE_HOST="other@host")
        p2 = subprocess.run(
            [sys.executable, str(FED_READ), "hermes", "--nonce", nonce,
             "--source", receipt["source_path"]],
            capture_output=True, text=True, env=mismatch_env)
        self.assertEqual(p2.returncode, 2)
        self.assertIn("different FED_HERMES_SSH_CMD", p2.stderr)

    def test_remote_hermes_requires_top_and_bottom_nonce_markers(self):
        nonce = "FED-remoteno-1111-2222-3333-remotenotest"
        db = self.make_hermes_db([
            (1, "s1", "user", "[[%s]]\nbrief body" % nonce, 1),
            (2, "s1", "assistant", "TRUNCATED_REMOTE_REPLY", 1),
        ])
        p = subprocess.run(
            [sys.executable, str(FED_READ), "hermes", "--nonce", nonce],
            capture_output=True, text=True, env=self.remote_env(db))
        self.assertEqual(p.returncode, 3)
        self.assertIn("NOT FOUND", p.stderr)

    def test_remote_hermes_no_tool_window_rejects_tool_role(self):
        nonce = "FED-remotetl-1111-2222-3333-remotetltest"
        db = self.make_hermes_db([
            (1, "s1", "user", "[[%s]]\nbrief body\n[[%s]]" % (nonce, nonce), 1),
            (2, "s1", "tool", "tool output", 1),
            (3, "s1", "assistant", "REMOTE_REPLY", 1),
        ])
        p = subprocess.run(
            [sys.executable, str(FED_READ), "hermes", "--nonce", nonce,
             "--no-tool-window"],
            capture_output=True, text=True, env=self.remote_env(db))
        self.assertEqual(p.returncode, 5)
        self.assertIn("structured tool event", p.stderr)

    def test_hermes_no_tool_window_rejects_encoded_json_tool_event(self):
        nonce = "FED-localjsn-1111-2222-3333-localjsntest"
        encoded_tool = "\x00json:" + json.dumps({"type": "tool_use", "name": "shell"})
        db = self.make_hermes_db([
            (1, "s1", "user", "[[%s]]\nbrief body\n[[%s]]" % (nonce, nonce), 1),
            (2, "s1", "assistant", encoded_tool, 1),
            (3, "s1", "assistant", "REMOTE_REPLY", 1),
        ])
        p = subprocess.run(
            [sys.executable, str(FED_READ), "hermes", "--nonce", nonce,
             "--source", str(db), "--no-tool-window"],
            capture_output=True, text=True)
        self.assertEqual(p.returncode, 5)
        self.assertIn("structured tool event", p.stderr)

    def test_remote_hermes_no_tool_window_rejects_encoded_json_tool_event(self):
        nonce = "FED-remotjs-1111-2222-3333-remotjstest"
        encoded_tool = "\x00json:" + json.dumps({"type": "tool_use", "name": "shell"})
        db = self.make_hermes_db([
            (1, "s1", "user", "[[%s]]\nbrief body\n[[%s]]" % (nonce, nonce), 1),
            (2, "s1", "assistant", encoded_tool, 1),
            (3, "s1", "assistant", "REMOTE_REPLY", 1),
        ])
        p = subprocess.run(
            [sys.executable, str(FED_READ), "hermes", "--nonce", nonce,
             "--no-tool-window"],
            capture_output=True, text=True, env=self.remote_env(db))
        self.assertEqual(p.returncode, 5)
        self.assertIn("structured tool event", p.stderr)

    def test_remote_hermes_matched_empty_reply_exits_4(self):
        nonce = "FED-remoteem-1111-2222-3333-remoteemtest"
        db = self.make_hermes_db([
            (1, "s1", "user", "[[%s]]\nbrief body\n[[%s]]" % (nonce, nonce), 1),
            (2, "s1", "assistant", "   ", 1),
        ])
        p = subprocess.run(
            [sys.executable, str(FED_READ), "hermes", "--nonce", nonce],
            capture_output=True, text=True, env=self.remote_env(db))
        self.assertEqual(p.returncode, 4)
        self.assertIn("turn is EMPTY", p.stderr)

    def test_remote_hermes_receipt_verifies_through_fed_cross(self):
        hermes_nonce = "FED-remotecx-1111-2222-3333-remotecxtest"
        codex_nonce = "FED-codexcx-1111-2222-3333-codexcxtest"
        hermes_reply = "REMOTE_HERMES_CROSS_REPLY"
        codex_reply = "CODEX_CROSS_REPLY"
        db = self.make_hermes_db([
            (1, "remote-session", "user", "[[%s]]\nbrief body\n[[%s]]" % (hermes_nonce, hermes_nonce), 1),
            (2, "remote-session", "assistant", hermes_reply, 1),
        ])
        codex_transcript = self.root / "codex.jsonl"
        codex_transcript.write_text(codex_jsonl(codex_nonce, codex_reply))
        relay = self.root / "relay-cross-remote"
        relay.mkdir()
        env = self.remote_env(db)

        hp = subprocess.run(
            [sys.executable, str(FED_READ), "hermes", "--nonce", hermes_nonce,
             "--receipt-dir", str(relay)],
            capture_output=True, text=True, env=env)
        self.assertEqual(hp.returncode, 0, hp.stderr)
        cp = subprocess.run(
            [sys.executable, str(FED_READ), "codex", "--nonce", codex_nonce,
             "--source", str(codex_transcript), "--receipt-dir", str(relay)],
            capture_output=True, text=True, env=env)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        framing = relay / "framing.md"
        framing.write_text("coordinator framing\n")

        gen = subprocess.run(
            [sys.executable, str(FED_CROSS), "generate", "--relay", str(relay),
             "--peers", "hermes,codex", "--framing", str(framing)],
            capture_output=True, text=True, env=env)
        self.assertEqual(gen.returncode, 0, gen.stderr)
        ver = subprocess.run(
            [sys.executable, str(FED_CROSS), "verify", "--relay", str(relay)],
            capture_output=True, text=True, env=env)
        self.assertEqual(ver.returncode, 0, ver.stderr)
        self.assertIn("OK", ver.stdout)

    def test_no_tool_window_rejects_structured_codex_function_call_without_role_and_writes_no_receipt(self):
        transcript = self.root / "rollout-tool.jsonl"
        relay = self.root / "relay-tool"
        relay.mkdir()
        nonce = "FED-tooltool-1111-2222-3333-tooltooltool"
        transcript.write_text(codex_jsonl_with_tool_event(
            nonce, "NO_TOOL_AUDIT: no tools used\nThis line lies."))

        p = subprocess.run(
            [sys.executable, str(FED_READ), "codex", "--nonce", nonce,
             "--source", str(transcript), "--receipt-dir", str(relay),
             "--no-tool-window"],
            capture_output=True, text=True)
        self.assertEqual(p.returncode, 5)
        self.assertIn("tool event", p.stderr)
        self.assertFalse((relay / "reply_codex.txt").exists())
        self.assertFalse((relay / "receipt_codex.json").exists())

    def test_no_tool_window_allows_plain_quoted_tool_text(self):
        transcript = self.root / "rollout-tool-text.jsonl"
        nonce = "FED-texttext-1111-2222-3333-texttexttext"
        reply = "NO_TOOL_AUDIT: no tools used\nQuoted text says tool_use and run shell."
        transcript.write_text(codex_jsonl(nonce, reply))

        p = subprocess.run(
            [sys.executable, str(FED_READ), "codex", "--nonce", nonce,
             "--source", str(transcript), "--no-tool-window",
             "--require-no-tool-audit"],
            capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.rstrip("\n"), reply)

    def test_require_no_tool_audit_must_be_first_nonempty_reply_line(self):
        transcript = self.root / "rollout-no-audit.jsonl"
        nonce = "FED-auditaud-1111-2222-3333-auditaudita"
        transcript.write_text(codex_jsonl(
            nonce,
            "I used no tools.\nNO_TOOL_AUDIT: no tools used"))

        p = subprocess.run(
            [sys.executable, str(FED_READ), "codex", "--nonce", nonce,
             "--source", str(transcript), "--require-no-tool-audit"],
            capture_output=True, text=True)
        self.assertEqual(p.returncode, 5)
        self.assertIn("NO_TOOL_AUDIT", p.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
