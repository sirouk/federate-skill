#!/usr/bin/env python3
"""Regression tests for the shared default federation busy regex."""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATHS = {
    "fed_ready": ROOT / "scripts" / "fed_ready.sh",
    "fed_sessions": ROOT / "scripts" / "fed_sessions.sh",
    "fed_wait": ROOT / "scripts" / "fed_wait.sh",
}


def extract_default(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r'^[A-Za-z_][A-Za-z0-9_]*="\$\{FED_BUSY_RE:-(.*)\}"$', line)
        if match:
            # Shell double quotes collapse doubled backslashes before grep sees them.
            return match.group(1).replace("\\\\", "\\")
    raise AssertionError(f"busy regex default not found in {path}")


def grep_matches(pattern: str, text: str) -> bool:
    proc = subprocess.run(
        ["grep", "-qiE", pattern],
        input=text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode not in (0, 1):
        raise AssertionError(proc.stderr)
    return proc.returncode == 0


class BusyRegexDefaultTests(unittest.TestCase):
    def defaults(self) -> dict[str, str]:
        return {name: extract_default(path) for name, path in SCRIPT_PATHS.items()}

    def test_busy_regex_defaults_are_byte_identical_after_shell_unescape(self):
        defaults = self.defaults()
        self.assertEqual(defaults["fed_ready"], defaults["fed_sessions"])
        self.assertEqual(defaults["fed_ready"], defaults["fed_wait"])

    def test_default_busy_regex_does_not_match_idle_static_banners(self):
        pattern = self.defaults()["fed_ready"]
        idle_lines = [
            "Your bash commands will be sandboxed and unable to access the network",
            "? for shortcuts",
            "Running Chromium-family browser for tools",
            "Welcome to Hermes! Type your message or /help for commands.",
            "Write tests for @filename",
            "gpt-5.5 xhigh · ~/repo",
        ]
        for line in idle_lines:
            with self.subTest(line=line):
                self.assertFalse(grep_matches(pattern, line), line)

    def test_default_busy_regex_still_matches_active_turn_markers(self):
        pattern = self.defaults()["fed_ready"]
        active_lines = [
            "esc to interrupt",
            "Esc to interrupt",
            "ctrl-c to stop",
            "Ctrl+C cancel",
            "msg=interrupt",
            "Working (8s)",
        ]
        for line in active_lines:
            with self.subTest(line=line):
                self.assertTrue(grep_matches(pattern, line), line)


if __name__ == "__main__":
    unittest.main(verbosity=2)
