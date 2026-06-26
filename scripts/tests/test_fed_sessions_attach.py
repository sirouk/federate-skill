#!/usr/bin/env python3
"""Hermetic coverage for fed_sessions.sh attach-command output."""

from __future__ import annotations

import json
import os
import re
import shlex
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "fed_sessions.sh"


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
    return state.setdefault("sessions", {}).setdefault(name, {"options": {}})

cmd = sys.argv[1] if len(sys.argv) > 1 else ""
args = sys.argv[2:]

if cmd in ("attach", "attach-session"):
    sentinel = os.environ.get("FAKE_TMUX_ATTACH_SENTINEL")
    if sentinel:
        Path(sentinel).write_text("attached\n")
    sys.exit(0)

if cmd == "start-server":
    sys.exit(0)

if cmd == "has-session":
    name = target(args)
    sys.exit(0 if name in state.get("sessions", {}) else 1)

if cmd == "new-session":
    name = None
    for i, arg in enumerate(args):
        if arg == "-s" and i + 1 < len(args):
            name = args[i + 1]
            break
    if not name or name in state.get("sessions", {}):
        sys.exit(1)
    state.setdefault("sessions", {})[name] = {"options": {}, "pane": "", "keys": []}
    state.setdefault("new_sessions", []).append(name)
    save()
    sys.exit(0)

if cmd == "set-option":
    name = target(args)
    key = args[-2]
    value = args[-1]
    session(name).setdefault("options", {})[key] = value
    save()
    sys.exit(0)

if cmd == "show-options":
    name = target(args)
    key = args[-1]
    value = state.get("sessions", {}).get(name, {}).get("options", {}).get(key, "")
    if value:
        print(value)
    sys.exit(0)

if cmd == "send-keys":
    name = target(args)
    keys = [arg for arg in args if arg not in ("-t", name)]
    session(name).setdefault("keys", []).extend(keys)
    save()
    sys.exit(0)

if cmd == "display-message":
    name = target(args)
    attached = state.get("sessions", {}).get(name, {}).get("attached", 0)
    print(attached)
    sys.exit(0)

if cmd == "capture-pane":
    name = target(args)
    print(state.get("sessions", {}).get(name, {}).get("pane", ""))
    sys.exit(0)

if cmd == "list-sessions":
    for name in state.get("sessions", {}):
        print(name)
    sys.exit(0)

if cmd == "resize-window":
    sys.exit(0)

print(f"unexpected tmux command: {cmd}", file=sys.stderr)
sys.exit(2)
"""


DEFAULT_CMDS = {
    "claude": "IS_SANDBOX=1 claude --dangerously-skip-permissions",
    "codex": "codex --dangerously-bypass-approvals-and-sandbox",
    "hermes": "hermes --cli --yolo",
}


def managed(agent: str) -> dict:
    return {
        "options": {
            "@federate_agent": agent,
            "@federate_ns": "fedtest",
            "@federate_root": "/repo",
            "@federate_cmd": DEFAULT_CMDS[agent],
        },
        "pane": "",
        "keys": [],
        "attached": 0,
    }


class FedSessionsAttachTests(unittest.TestCase):
    def run_sessions(
        self,
        *agents: str,
        executables: tuple[str, ...] = ("claude", "codex", "hermes"),
        state: dict | None = None,
        eval_stdout: bool = False,
    ):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            state_path = tmp / "state.json"
            state_path.write_text(json.dumps(state or {"sessions": {}}))
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            fake_tmux = fake_bin / "tmux"
            fake_tmux.write_text(FAKE_TMUX)
            fake_tmux.chmod(fake_tmux.stat().st_mode | stat.S_IXUSR)
            for exe in executables:
                path = fake_bin / exe
                path.write_text("#!/usr/bin/env bash\nexit 0\n")
                path.chmod(path.stat().st_mode | stat.S_IXUSR)

            sentinel = tmp / "attached"
            env = os.environ.copy()
            env.update(
                {
                    "FAKE_TMUX_STATE": str(state_path),
                    "FAKE_TMUX_ATTACH_SENTINEL": str(sentinel),
                    "PATH": f"{fake_bin}{os.pathsep}/usr/bin:/bin:/usr/sbin:/sbin",
                    "FED_NS": "fedtest",
                    "FED_NS_ROOT": "/repo",
                }
            )

            proc = subprocess.run(
                [str(SCRIPT), *agents],
                cwd=ROOT,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            eval_proc = None
            if eval_stdout:
                eval_proc = subprocess.run(
                    ["bash", "-c", 'eval "$(cat)"'],
                    input=proc.stdout,
                    cwd=ROOT,
                    env=env,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
            final_state = json.loads(state_path.read_text())
            return proc, final_state, eval_proc, sentinel.exists()

    def assignments(self, stdout: str) -> dict[str, str]:
        values = {}
        for line in stdout.splitlines():
            self.assertRegex(line, r"^[A-Za-z_][A-Za-z0-9_]*=", line)
            key, value = line.split("=", 1)
            values[key] = value
        return values

    def shell_value(self, value: str) -> str:
        parsed = shlex.split(value)
        self.assertEqual(len(parsed), 1, value)
        return parsed[0]

    def assert_attaches_match(self, values: dict[str, str], *agents: str):
        lines = list(values)
        for agent in agents:
            upper = agent.upper()
            session_key = f"{upper}_SESSION"
            attach_key = f"{upper}_ATTACH_CMD"
            self.assertIn(session_key, values)
            self.assertIn(attach_key, values)
            self.assertEqual(lines.index(attach_key), lines.index(session_key) + 1)
            self.assertEqual(
                self.shell_value(values[attach_key]),
                f"tmux attach-session -r -t {values[session_key]}",
            )

    def test_created_sessions_emit_eval_safe_attach_commands(self):
        proc, _state, eval_proc, attached = self.run_sessions(
            "claude",
            "codex",
            "hermes",
            eval_stdout=True,
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIsNotNone(eval_proc)
        self.assertEqual(eval_proc.returncode, 0, eval_proc.stderr)
        self.assertFalse(attached, "eval of stdout must not invoke tmux attach")
        self.assertIsNone(re.search(r"^tmux attach", proc.stdout, re.MULTILINE))
        values = self.assignments(proc.stdout)
        self.assert_attaches_match(values, "claude", "codex", "hermes")
        for agent in ("claude", "codex", "hermes"):
            self.assertIn(
                f"#   tmux attach-session -r -t {values[f'{agent.upper()}_SESSION']}",
                proc.stderr,
            )
        self.assertIn("# Attach commands to watch peers", proc.stderr)

    def test_skipped_agent_gets_no_session_or_attach_command(self):
        proc, _state, _eval_proc, _attached = self.run_sessions(
            "claude",
            "codex",
            "hermes",
            executables=("claude", "codex"),
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        values = self.assignments(proc.stdout)
        self.assert_attaches_match(values, "claude", "codex")
        self.assertNotIn("HERMES_SESSION", values)
        self.assertNotIn("HERMES_ATTACH_CMD", values)
        self.assertNotIn("#   tmux attach-session -r -t fed-fedtest-hermes-", proc.stderr)

    def test_reused_sessions_emit_attach_commands_without_relaunch(self):
        state = {
            "sessions": {
                "fed-fedtest-claude-0": managed("claude"),
                "fed-fedtest-codex-0": managed("codex"),
            }
        }
        proc, final_state, _eval_proc, _attached = self.run_sessions(
            "claude",
            "codex",
            state=state,
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        values = self.assignments(proc.stdout)
        self.assert_attaches_match(values, "claude", "codex")
        self.assertEqual(final_state.get("new_sessions", []), [])
        self.assertEqual(final_state["sessions"]["fed-fedtest-claude-0"].get("keys", []), [])
        self.assertEqual(final_state["sessions"]["fed-fedtest-codex-0"].get("keys", []), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
