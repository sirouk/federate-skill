#!/usr/bin/env python3
"""Tests for update/install commit pinning and SHA validation."""
import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
UPDATE = ROOT / "scripts" / "fed_update_check.sh"
INSTALL = ROOT / "install.sh"
GOOD_SHA = "a" * 40
OTHER_SHA = "b" * 40


class UpdateHardening(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.skill = self.root / "skill"
        (self.skill / "scripts").mkdir(parents=True)
        shutil.copy2(UPDATE, self.skill / "scripts" / "fed_update_check.sh")

    def tearDown(self):
        self._tmp.cleanup()

    def write_meta(self, **overrides):
        data = {
            "source": "https://github.com/example/repo.git",
            "ref": "main",
            "commit": GOOD_SHA,
            "raw": "https://raw.githubusercontent.com/example/repo/%s" % GOOD_SHA,
            "dirty": False,
            "installed_at": "2026-06-25T00:00:00Z",
        }
        data.update(overrides)
        (self.skill / ".federate-install.json").write_text(json.dumps(data), encoding="utf-8")

    def run_update(self, env=None):
        merged = dict(os.environ)
        if env:
            merged.update(env)
        return subprocess.run(
            [str(self.skill / "scripts" / "fed_update_check.sh")],
            cwd=self.root,
            capture_output=True,
            text=True,
            env=merged,
        )

    def test_pinned_full_sha_ref_is_up_to_date_without_network(self):
        self.write_meta(ref=GOOD_SHA, commit=GOOD_SHA)
        p = self.run_update()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("UP_TO_DATE", p.stdout)

    def test_invalid_installed_commit_fails(self):
        self.write_meta(commit="abc123")
        p = self.run_update()
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("full 40-hex", p.stderr)

    def test_short_remote_sha_fails(self):
        self.write_meta(ref="main", commit=GOOD_SHA)
        fakebin = self.root / "bin"
        fakebin.mkdir()
        (fakebin / "git").write_text("#!/usr/bin/env bash\necho abc123 refs/heads/main\n")
        (fakebin / "curl").write_text("#!/usr/bin/env bash\necho '{\"sha\":\"abc123\"}'\n")
        for p in fakebin.iterdir():
            p.chmod(0o755)
        p = self.run_update(env={"PATH": str(fakebin) + os.pathsep + os.environ["PATH"]})
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("full 40-hex", p.stderr)

    def test_install_rejects_short_federate_commit(self):
        dest = self.root / "dest"
        p = subprocess.run(
            [str(INSTALL)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            env=dict(os.environ, FEDERATE_DEST=str(dest), FEDERATE_COMMIT="abc123"),
        )
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("full 40-hex", p.stderr)

    def test_local_install_success_installs_payload_to_requested_dest(self):
        dest = self.root / "local-dest"
        p = subprocess.run(
            [str(INSTALL)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            env=dict(os.environ, FEDERATE_DEST=str(dest)),
        )

        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue((dest / "scripts" / "fed_ready.sh").is_file())
        self.assertTrue((dest / "scripts" / "SPEC_fed_cross.md").is_file())
        self.assertTrue((dest / "scripts" / "tests" / "test_update_hardening.py").is_file())

    def test_release_payload_files_are_git_tracked(self):
        if not (ROOT / ".git").exists():
            self.skipTest("requires git checkout")
        expected = [
            "scripts/SPEC_fed_cross.md",
            "scripts/SPEC_fed_round_check.md",
            "scripts/fed_cross.py",
            "scripts/fed_ready.sh",
            "scripts/fed_round_check.py",
            "scripts/tests/test_fed_cross.py",
            "scripts/tests/test_fed_read_receipts_impl.py",
            "scripts/tests/test_fed_ready.py",
            "scripts/tests/test_fed_round_check.py",
            "scripts/tests/test_fed_send_profile.py",
            "scripts/tests/test_update_hardening.py",
        ]
        p = subprocess.run(
            ["git", "ls-files", "--error-unmatch", *expected],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(p.returncode, 0, p.stderr)

    def write_fake_curl(self, fakebin: Path, fail_name: str = "agents/openai.yaml"):
        curl = fakebin / "curl"
        curl.write_text(textwrap.dedent(f"""\
            #!/usr/bin/env python3
            import pathlib
            import sys

            args = sys.argv[1:]
            out = None
            url = ""
            i = 0
            while i < len(args):
                if args[i] == "-o":
                    out = args[i + 1]
                    i += 2
                elif args[i].startswith("-"):
                    i += 1
                else:
                    url = args[i]
                    i += 1

            if url.endswith("/install.sh"):
                data = pathlib.Path({str(INSTALL)!r}).read_text()
            elif url.endswith("/{fail_name}"):
                print("forced curl failure", file=sys.stderr)
                sys.exit(22)
            elif url.endswith("/SKILL.md"):
                data = "NEW SKILL\\n"
            else:
                data = "payload for " + url.rsplit("/", 1)[-1] + "\\n"

            if out:
                pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
                pathlib.Path(out).write_text(data)
            else:
                sys.stdout.write(data)
        """))
        curl.chmod(0o755)

    def test_remote_install_failure_leaves_existing_install_unchanged(self):
        dest = self.root / "dest"
        dest.mkdir()
        (dest / "SKILL.md").write_text("OLD SKILL\n")
        fakebin = self.root / "bin-install"
        fakebin.mkdir()
        self.write_fake_curl(fakebin)

        p = subprocess.run(
            ["bash", "-s"],
            input=INSTALL.read_text(),
            cwd=self.root,
            capture_output=True,
            text=True,
            env=dict(
                os.environ,
                PATH=str(fakebin) + os.pathsep + os.environ["PATH"],
                FEDERATE_DEST=str(dest),
                FEDERATE_COMMIT=GOOD_SHA,
                FEDERATE_SOURCE="https://github.com/example/repo.git",
                FEDERATE_RAW="https://raw.invalid/example/repo/main",
            ),
        )

        self.assertNotEqual(p.returncode, 0)
        self.assertEqual((dest / "SKILL.md").read_text(), "OLD SKILL\n")

    def test_update_apply_failure_leaves_existing_install_unchanged(self):
        self.write_meta(ref="main", commit=GOOD_SHA, dirty=False)
        (self.skill / "SKILL.md").write_text("OLD SKILL\n")
        fakebin = self.root / "bin-update"
        fakebin.mkdir()
        (fakebin / "git").write_text(f"#!/usr/bin/env bash\necho {OTHER_SHA} refs/heads/main\n")
        (fakebin / "git").chmod(0o755)
        self.write_fake_curl(fakebin)

        p = subprocess.run(
            [str(self.skill / "scripts" / "fed_update_check.sh"), "--apply"],
            cwd=self.root,
            capture_output=True,
            text=True,
            env=dict(os.environ, PATH=str(fakebin) + os.pathsep + os.environ["PATH"]),
        )

        self.assertNotEqual(p.returncode, 0)
        self.assertEqual((self.skill / "SKILL.md").read_text(), "OLD SKILL\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)
