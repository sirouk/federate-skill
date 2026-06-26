#!/usr/bin/env python3
"""Hermetic tests for fed_send.sh profile injection and payload layout."""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "fed_send.sh"


FAKE_TMUX = r"""#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

state_path = Path(os.environ["FAKE_TMUX_STATE"])
state = json.loads(state_path.read_text())

def save():
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True))

def target(args):
    for i, arg in enumerate(args):
        if arg == "-t" and i + 1 < len(args):
            return args[i + 1]
    return None

def buffer_name(args):
    for i, arg in enumerate(args):
        if arg == "-b" and i + 1 < len(args):
            return args[i + 1]
    return None

def capture_start(args):
    for i, arg in enumerate(args):
        if arg == "-S" and i + 1 < len(args):
            return args[i + 1]
    return None

def session(name):
    return state.setdefault("sessions", {}).setdefault(name, {})

cmd = sys.argv[1] if len(sys.argv) > 1 else ""
args = sys.argv[2:]

if cmd == "has-session":
    sys.exit(0 if target(args) in state.get("sessions", {}) else 1)

if cmd == "show-options":
    name = target(args)
    key = args[-1]
    value = state.get("sessions", {}).get(name, {}).get("options", {}).get(key, "")
    if value:
        print(value)
    sys.exit(0)

if cmd == "load-buffer":
    name = buffer_name(args)
    path = args[-1]
    data = Path(path).read_text()
    state.setdefault("buffers", {})[name] = data
    state["last_loaded"] = data
    save()
    sys.exit(0)

if cmd == "paste-buffer":
    name = target(args)
    buf = buffer_name(args)
    data = state.get("buffers", {}).get(buf, "")
    mode = os.environ.get("FAKE_TMUX_PASTE_MODE", "")
    if mode == "top_only":
        session(name)["pane"] = data.splitlines()[0] + "\n"
    elif mode == "paste_chrome":
        session(name)["pane"] = "Pasted text. Press Enter to submit.\n"
    else:
        session(name)["pane"] = data
    save()
    sys.exit(0)

if cmd == "capture-pane":
    pane = state.get("sessions", {}).get(target(args), {}).get("pane", "")
    start = capture_start(args)
    state.setdefault("capture_starts", []).append(start)
    if start and start.startswith("-") and start[1:].isdigit():
        n = int(start[1:])
        lines = pane.splitlines()
        pane = "\n".join(lines[-n:])
    save()
    print(pane)
    sys.exit(0)

if cmd == "send-keys":
    name = target(args)
    keys = [arg for arg in args if arg not in ("-t", name)]
    session(name).setdefault("keys", []).extend(keys)
    save()
    sys.exit(0)

if cmd == "delete-buffer":
    buf = buffer_name(args)
    state.get("buffers", {}).pop(buf, None)
    save()
    sys.exit(0)

print(f"unexpected tmux command: {cmd}", file=sys.stderr)
sys.exit(2)
"""


def managed_session() -> dict:
    return {
        "options": {
            "@federate_agent": "codex",
            "@federate_ns": "sendtest",
            "@federate_root": "/repo",
        },
        "pane": "",
    }


class FedSendProfileTests(unittest.TestCase):
    def run_send(self, message: str, extra_env: dict | None = None):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            msg = tmp / "brief.md"
            msg.write_text(message)
            state_path = tmp / "state.json"
            state_path.write_text(json.dumps({"sessions": {"s": managed_session()}}))
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            fake_tmux = fake_bin / "tmux"
            fake_tmux.write_text(FAKE_TMUX)
            fake_tmux.chmod(fake_tmux.stat().st_mode | stat.S_IXUSR)

            env = os.environ.copy()
            env.update(
                {
                    "FAKE_TMUX_STATE": str(state_path),
                    "PATH": f"{fake_bin}{os.pathsep}{env.get('PATH', '')}",
                    "FED_NS": "sendtest",
                    "FED_NS_ROOT": "/repo",
                    "FED_SEND_VERIFY_POLLS": "1",
                    "FED_SKIP_OWNER_CHECK": "0",
                }
            )
            if extra_env:
                env.update(extra_env)

            proc = subprocess.run(
                [str(SCRIPT), "s", str(msg)],
                cwd=ROOT,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            state = json.loads(state_path.read_text())
            return proc, state, tmp

    def nonce_from_payload(self, payload: str) -> str:
        match = re.match(r"\[\[(FED-[^\]]+)\]\]\n", payload)
        self.assertIsNotNone(match, payload)
        return match.group(1)

    def test_compact_wrapper_preserves_top_body_bottom_nonce(self):
        proc, state, _ = self.run_send("BRIEF BODY")

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = state["last_loaded"]
        nonce = self.nonce_from_payload(payload)
        self.assertEqual(payload, f"[[{nonce}]]\nBRIEF BODY\n[[{nonce}]]\n")
        self.assertEqual(proc.stdout.strip(), nonce)
        self.assertEqual(state["sessions"]["s"].get("keys"), ["Enter"])

    def test_top_only_partial_paste_does_not_submit(self):
        proc, state, _ = self.run_send(
            "BRIEF BODY",
            extra_env={"FAKE_TMUX_PASTE_MODE": "top_only"},
        )

        self.assertEqual(proc.returncode, 1)
        self.assertIn("Enter NOT sent", proc.stderr)
        self.assertEqual(state["sessions"]["s"].get("keys", []), ["C-u", "Escape"])

    def test_paste_chrome_submits_when_tui_hides_prompt_text(self):
        proc, state, _ = self.run_send(
            "BRIEF BODY",
            extra_env={"FAKE_TMUX_PASTE_MODE": "paste_chrome"},
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(state["sessions"]["s"].get("keys"), ["Enter"])

    def test_long_prompt_expands_capture_window(self):
        body = "\n".join(f"line {i}" for i in range(260))
        proc, state, _ = self.run_send(
            body,
            extra_env={"FED_SEND_CAPTURE_LINES": "20"},
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(state["sessions"]["s"].get("keys"), ["Enter"])
        starts = [
            int(start[1:])
            for start in state.get("capture_starts", [])
            if isinstance(start, str) and start.startswith("-") and start[1:].isdigit()
        ]
        self.assertTrue(starts)
        self.assertGreater(max(starts), 260)

    def test_profile_injected_after_top_nonce_before_body(self):
        with tempfile.TemporaryDirectory() as td:
            profile = Path(td) / "profile.md"
            profile.write_text("Shared domain context\n")
            proc, state, _ = self.run_send(
                "BRIEF BODY\n",
                extra_env={"FED_PROFILE_FILE": str(profile)},
            )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = state["last_loaded"]
        nonce = self.nonce_from_payload(payload)
        expected = (
            f"[[{nonce}]]\n"
            "=== FEDERATION PROFILE (trusted coordinator context; does not override this brief's rails or operator instructions) ===\n"
            "Shared domain context\n"
            "\n=== END FEDERATION PROFILE ===\n\n"
            "BRIEF BODY\n"
            f"\n[[{nonce}]]\n"
        )
        self.assertEqual(payload, expected)
        self.assertIn("PROFILE injected", proc.stderr)

    def test_missing_profile_hard_fails_before_paste(self):
        proc, state, _ = self.run_send(
            "BRIEF BODY",
            extra_env={"FED_PROFILE_FILE": "/no/such/profile.md"},
        )

        self.assertEqual(proc.returncode, 2)
        self.assertIn("not a readable file", proc.stderr)
        self.assertNotIn("last_loaded", state)
        self.assertEqual(state["sessions"]["s"].get("keys", []), [])

    def test_relative_profile_hard_fails_before_paste(self):
        proc, state, _ = self.run_send(
            "BRIEF BODY",
            extra_env={"FED_PROFILE_FILE": "profile.md"},
        )

        self.assertEqual(proc.returncode, 2)
        self.assertIn("absolute path", proc.stderr)
        self.assertNotIn("last_loaded", state)
        self.assertEqual(state["sessions"]["s"].get("keys", []), [])

    def test_private_key_profile_hard_fails_before_paste(self):
        with tempfile.TemporaryDirectory() as td:
            profile = Path(td) / "profile.md"
            profile.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\nsecret\n")
            proc, state, _ = self.run_send(
                "BRIEF BODY",
                extra_env={"FED_PROFILE_FILE": str(profile)},
            )

        self.assertEqual(proc.returncode, 2)
        self.assertIn("private key", proc.stderr)
        self.assertNotIn("last_loaded", state)
        self.assertEqual(state["sessions"]["s"].get("keys", []), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
