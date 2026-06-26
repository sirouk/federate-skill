#!/usr/bin/env python3
"""Hermetic coverage for fed_ready.sh startup-prompt handling."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "fed_ready.sh"


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

def session(name):
    return state.setdefault("sessions", {}).setdefault(name, {})

cmd = sys.argv[1] if len(sys.argv) > 1 else ""
args = sys.argv[2:]

if cmd == "has-session":
    name = target(args)
    sys.exit(0 if name in state.get("sessions", {}) else 1)

if cmd == "show-options":
    name = target(args)
    key = args[-1]
    value = state.get("sessions", {}).get(name, {}).get("options", {}).get(key, "")
    if value:
        print(value)
    sys.exit(0)

if cmd == "capture-pane":
    name = target(args)
    print(state.get("sessions", {}).get(name, {}).get("pane", ""))
    sys.exit(0)

if cmd == "send-keys":
    name = target(args)
    keys = [arg for arg in args if arg not in ("-t", name)]
    sess = session(name)
    sess.setdefault("keys", []).extend(keys)
    pane = sess.get("pane", "")
    for key in keys:
        if key == "Down":
            if "› 1. Update now" in pane and "  2. Skip" in pane:
                pane = pane.replace("› 1. Update now", "  1. Update now")
                pane = pane.replace("  2. Skip", "› 2. Skip")
            elif "› 1. Update now" in pane and "  3. Skip until next version" in pane:
                pane = pane.replace("› 1. Update now", "  1. Update now")
                pane = pane.replace("  3. Skip until next version", "› 3. Skip until next version")
        elif key == "Enter":
            if "› 1. Update now" in pane:
                sess["bad_enter_on_update"] = True
            if "› 2. Skip" in pane:
                pane = "Codex ready\nCtrl+J newline\n›\n"
    sess["pane"] = pane
    save()
    sys.exit(0)

print(f"unexpected tmux command: {cmd}", file=sys.stderr)
sys.exit(2)
"""


def managed(agent: str, pane: str, ns: str = "fedtest", root: str = "/repo") -> dict:
    return {
        "options": {
            "@federate_agent": agent,
            "@federate_ns": ns,
            "@federate_root": root,
        },
        "pane": pane,
    }


class FedReadyTests(unittest.TestCase):
    def run_ready(self, sessions: dict, *names: str, extra_env: dict | None = None):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            state_path = tmp / "state.json"
            state_path.write_text(json.dumps({"sessions": sessions}))
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
                    "FED_NS": "fedtest",
                    "FED_NS_ROOT": "/repo",
                    "FED_READY_TIMEOUT": "1",
                    "FED_READY_POLL": "1",
                    "FED_SKIP_OWNER_CHECK": "0",
                    "FED_BUSY_RE": "esc to interrupt|Esc to int|ctrl-c to stop|Ctrl\\+C cancel|msg=interrupt|running|thinking|working|executing|processing|waiting for|tool use",
                }
            )
            if extra_env:
                env.update(extra_env)

            proc = subprocess.run(
                [str(SCRIPT), *names],
                cwd=ROOT,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            state = json.loads(state_path.read_text())
            return proc, state

    def test_ready_composer_prints_ready_without_keys(self):
        proc, state = self.run_ready(
            {"h": managed("hermes", "Welcome to Hermes! Type your message or /help for commands.\n")},
            "h",
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("READY h", proc.stdout)
        self.assertEqual(state["sessions"]["h"].get("keys", []), [])

    def test_codex_update_menu_selects_plain_skip_only(self):
        pane = textwrap.dedent(
            """\
            Update available! 0.140.0 -> 0.142.2
            › 1. Update now
              2. Skip
              3. Skip until next version
            Press enter to continue
            """
        )
        proc, state = self.run_ready({"c": managed("codex", pane)}, "c")

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("READY c", proc.stdout)
        self.assertEqual(state["sessions"]["c"].get("keys"), ["Down", "Enter"])
        self.assertFalse(state["sessions"]["c"].get("bad_enter_on_update", False))

    def test_codex_placeholder_prompt_is_ready(self):
        proc, state = self.run_ready(
            {"c": managed("codex", "› Write tests for @filename\n\ngpt-5.5 xhigh · ~/repo\n")},
            "c",
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("READY c", proc.stdout)
        self.assertEqual(state["sessions"]["c"].get("keys", []), [])

    def test_codex_selected_auth_prompt_is_not_ready(self):
        pane = textwrap.dedent(
            """\
            Sign in to continue
            › Sign in with ChatGPT
              Use API key
            """
        )
        proc, state = self.run_ready({"c": managed("codex", pane)}, "c")

        self.assertEqual(proc.returncode, 1)
        self.assertIn("auth prompt needs manual action", proc.stdout)
        self.assertEqual(state["sessions"]["c"].get("keys", []), [])

    def test_codex_selected_trust_prompt_is_not_ready(self):
        pane = textwrap.dedent(
            """\
            Do you trust this folder?
            › Yes
              No
            """
        )
        proc, state = self.run_ready({"c": managed("codex", pane)}, "c")

        self.assertEqual(proc.returncode, 1)
        self.assertIn("trust/confirmation prompt needs manual action", proc.stdout)
        self.assertEqual(state["sessions"]["c"].get("keys", []), [])

    def test_auto_skip_can_be_disabled_without_keys(self):
        pane = textwrap.dedent(
            """\
            Update available! 0.140.0 -> 0.142.2
            › 1. Update now
              2. Skip
            Press enter to continue
            """
        )
        proc, state = self.run_ready(
            {"c": managed("codex", pane)},
            "c",
            extra_env={"FED_NO_AUTO_SKIP": "1"},
        )

        self.assertEqual(proc.returncode, 1)
        self.assertIn("NOT_READY c", proc.stdout)
        self.assertEqual(state["sessions"]["c"].get("keys", []), [])

    def test_malformed_update_prompt_gets_no_enter(self):
        pane = textwrap.dedent(
            """\
            Update available! 0.140.0 -> 0.142.2
            › 1. Update now
              3. Skip until next version
            Press enter to continue
            """
        )
        proc, state = self.run_ready({"c": managed("codex", pane)}, "c")

        self.assertEqual(proc.returncode, 1)
        self.assertIn("NOT_READY c", proc.stdout)
        self.assertNotIn("Enter", state["sessions"]["c"].get("keys", []))

    def test_unmanaged_session_is_rejected_without_keys(self):
        proc, state = self.run_ready({"c": {"options": {}, "pane": "Ctrl+J newline\n›\n"}}, "c")

        self.assertEqual(proc.returncode, 1)
        self.assertIn("unmanaged session", proc.stdout)
        self.assertEqual(state["sessions"]["c"].get("keys", []), [])

    def test_foreign_namespace_is_rejected_without_keys(self):
        proc, state = self.run_ready(
            {"c": managed("codex", "Ctrl+J newline\n›\n", ns="other")},
            "c",
        )

        self.assertEqual(proc.returncode, 1)
        self.assertIn("foreign namespace", proc.stdout)
        self.assertEqual(state["sessions"]["c"].get("keys", []), [])

    def test_busy_pane_is_not_ready_even_with_composer_text(self):
        proc, state = self.run_ready(
            {
                "h": managed(
                    "hermes",
                    "Welcome to Hermes! Type your message or /help for commands.\nmsg=interrupt\n",
                )
            },
            "h",
        )

        self.assertEqual(proc.returncode, 1)
        self.assertIn("pane appears busy", proc.stdout)
        self.assertEqual(state["sessions"]["h"].get("keys", []), [])

    def test_mixed_sessions_emit_all_statuses_and_fail(self):
        proc, state = self.run_ready(
            {
                "h": managed("hermes", "Welcome to Hermes! Type your message or /help for commands.\n"),
                "c": managed("codex", "msg=interrupt\n"),
            },
            "h",
            "c",
        )

        self.assertEqual(proc.returncode, 1)
        self.assertIn("READY h", proc.stdout)
        self.assertIn("NOT_READY c", proc.stdout)
        self.assertEqual(state["sessions"]["h"].get("keys", []), [])
        self.assertEqual(state["sessions"]["c"].get("keys", []), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
