from __future__ import annotations

import dataclasses
import grp
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from proj import sharing
from proj.config import load_config
from proj.discovery import scan
from proj.editor import create_document
from proj.errors import ProjError
from proj.metadata import load_project


class ShareTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.work = self.base / "work"
        self.work.mkdir()
        self.shared = self.base / "shared"
        self.shared.mkdir()
        self.shared.chmod(0o3770)
        self.group = grp.getgrgid(os.getgid()).gr_name
        site = self.base / "site.toml"
        site.write_text(
            f'schema = 1\nregistry = "{self.base / "private"}"\n'
            f'shared_registry = "{self.shared}"\ngroup = "{self.group}"\n'
        )
        self.patch = patch.dict(
            os.environ,
            {
                "PROJ_SITE_CONFIG": str(site),
                "PROJ_CONFIG": str(self.base / "user.toml"),
                "PROJ_CACHE_HOME": str(self.base / "cache"),
            },
        )
        self.patch.start()
        for variable in ("PROJ_HOME", "PROJ_PROJECT_ROOTS", "PROJ_ACTIVE"):
            os.environ.pop(variable, None)
        self.config = load_config()
        self.private = self.config.registry

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def make(self, registry: Path, name: str = "ledger", notes: bool = False) -> Path:
        document = registry / name / "project.toml"
        create_document(document, name, self.work)
        if notes:
            (document.parent / "notes.md").write_text("remember\n")
        return document

    def mode(self, path: Path) -> int:
        return stat.S_IMODE(path.stat().st_mode)

    def test_share_moves_the_environment_unchanged(self):
        document = self.make(self.private, notes=True)
        before = document.read_bytes()
        expected = load_project(document)
        target = sharing.share(self.config, "ledger", False)
        self.assertEqual(target, self.shared / "ledger" / "project.toml")
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual((target.parent / "notes.md").read_text(), "remember\n")
        self.assertEqual((self.mode(target.parent), self.mode(target)), (0o2755, 0o644))
        self.assertEqual(self.mode(target.parent / "notes.md"), 0o644)
        self.assertEqual(grp.getgrgid(target.stat().st_gid).gr_name, self.group)
        self.assertFalse((self.private / "ledger").exists())
        moved = load_project(target)
        self.assertEqual(
            (moved.name, moved.root, moved.description, moved.modules, moved.python_manager),
            (expected.name, expected.root, expected.description, expected.modules, expected.python_manager),
        )
        found = scan(self.config).projects
        self.assertEqual(list(found), ["ledger"])
        self.assertEqual(found["ledger"].metadata_path.parent.parent, self.shared)
        self.assertEqual(list(self.shared.glob(".*")), [])

    def test_share_group_writable(self):
        self.make(self.private)
        target = sharing.share(self.config, "ledger", True)
        self.assertEqual((self.mode(target.parent), self.mode(target)), (0o2775, 0o664))

    def test_share_refuses_a_name_that_exists_in_the_shared_registry(self):
        document = self.make(self.private)
        taken = self.make(self.shared)
        before = taken.read_bytes()
        with self.assertRaisesRegex(ProjError, "already exists"):
            sharing.share(self.config, "ledger", False)
        self.assertTrue(document.exists())
        self.assertEqual(taken.read_bytes(), before)
        self.assertEqual(sorted(path.name for path in self.shared.iterdir()), ["ledger"])

    def test_share_refuses_a_leftover_directory_without_touching_it(self):
        self.make(self.private)
        (self.shared / "ledger").mkdir()
        (self.shared / "ledger" / "old.txt").write_text("x")
        with self.assertRaisesRegex(ProjError, "holds other files"):
            sharing.share(self.config, "ledger", False)
        self.assertTrue((self.private / "ledger" / "project.toml").exists())
        self.assertEqual((self.shared / "ledger" / "old.txt").read_text(), "x")

    def test_share_needs_a_private_environment(self):
        self.make(self.shared)
        with self.assertRaisesRegex(ProjError, "not private"):
            sharing.share(self.config, "ledger", False)
        with self.assertRaisesRegex(ProjError, "unknown private"):
            sharing.share(self.config, "nothing", False)
        with self.assertRaises(ProjError):
            sharing.share(self.config, "../escape", False)

    def test_share_refuses_the_environment_active_in_this_shell(self):
        self.make(self.private)
        with patch.dict(os.environ, {"PROJ_ACTIVE": "ledger"}):
            with self.assertRaisesRegex(ProjError, "active in this shell"):
                sharing.share(self.config, "ledger", False)
        self.assertTrue((self.private / "ledger" / "project.toml").exists())
        self.assertEqual(list(self.shared.iterdir()), [])

    def test_share_without_a_shared_registry(self):
        self.make(self.private)
        config = dataclasses.replace(self.config, shared_registry=None)
        with self.assertRaisesRegex(ProjError, "no shared registry"):
            sharing.share(config, "ledger", False)

    def test_a_failed_copy_leaves_the_environment_where_it_was(self):
        document = self.make(self.private, notes=True)
        before = document.read_bytes()
        real = shutil.copyfile
        calls = []

        def flaky(source, target, *args, **kwargs):
            calls.append(target)
            if len(calls) == 2:
                raise OSError(28, "No space left on device")
            return real(source, target, *args, **kwargs)

        with patch("proj.sharing.shutil.copyfile", flaky):
            with self.assertRaises(OSError):
                sharing.share(self.config, "ledger", False)
        self.assertEqual(document.read_bytes(), before)
        self.assertTrue((document.parent / "notes.md").exists())
        self.assertEqual(list(self.shared.iterdir()), [])

    def test_the_environment_is_not_visible_before_it_is_complete(self):
        self.make(self.private)
        seen = []
        real = os.rename

        def watch(source, target):
            seen.append(sorted(str(path) for path in self.shared.glob("*/project.toml")))
            return real(source, target)

        with patch("proj.sharing.os.rename", watch):
            sharing.share(self.config, "ledger", False)
        self.assertEqual(seen, [[]])

    def test_unshare_is_the_reverse(self):
        self.make(self.private, notes=True)
        shared = sharing.share(self.config, "ledger", True)
        before = shared.read_bytes()
        target = sharing.unshare(self.config, "ledger", False)
        self.assertEqual(target, self.private / "ledger" / "project.toml")
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual((target.parent / "notes.md").read_text(), "remember\n")
        self.assertFalse((self.shared / "ledger").exists())
        self.assertEqual(scan(self.config).projects["ledger"].metadata_path.parent.parent, self.private)
        self.assertEqual(list(self.shared.glob(".*")), [])

    def test_only_the_creator_can_unshare(self):
        shared = self.make(self.shared)
        with patch("proj.sharing.os.getuid", return_value=os.getuid() + 1):
            with self.assertRaisesRegex(ProjError, "only its creator"):
                sharing.unshare(self.config, "ledger", False)
        self.assertTrue(shared.exists())
        self.assertFalse((self.private / "ledger").exists())

    def test_unshare_refuses_while_active(self):
        shared = self.make(self.shared)
        with patch.dict(os.environ, {"PROJ_ACTIVE": "ledger"}):
            with self.assertRaisesRegex(ProjError, "active in this shell"):
                sharing.unshare(self.config, "ledger", True)
        with patch("proj.sharing.active_elsewhere", return_value=["vim (pid 7, ana)"]):
            with self.assertRaisesRegex(ProjError, "looks active in vim"):
                sharing.unshare(self.config, "ledger", False)
            self.assertTrue(shared.exists())
            sharing.unshare(self.config, "ledger", True)
        self.assertTrue((self.private / "ledger" / "project.toml").exists())

    def test_active_elsewhere_sees_a_program_started_from_an_activated_shell(self):
        environment = {**os.environ, "PROJ_ACTIVE": "ledger"}
        other = {**os.environ, "PROJ_ACTIVE": "ledger-two"}
        with subprocess.Popen(["sleep", "30"], env=environment) as one, subprocess.Popen(["sleep", "30"], env=other) as two:
            try:
                found = sharing.active_elsewhere("ledger")
                self.assertEqual(len(found), 1)
                self.assertIn(f"pid {one.pid}", found[0])
                self.assertEqual(sharing.active_elsewhere("ledger-three"), [])
            finally:
                one.kill()
                two.kill()

    def test_unshare_refuses_a_name_taken_in_the_private_registry(self):
        shared = self.make(self.shared)
        mine = self.make(self.private)
        before = mine.read_bytes()
        with self.assertRaisesRegex(ProjError, "already exists"):
            sharing.unshare(self.config, "ledger", False)
        self.assertTrue(shared.exists())
        self.assertEqual(mine.read_bytes(), before)

    def test_unshare_unknown(self):
        with self.assertRaisesRegex(ProjError, "unknown shared"):
            sharing.unshare(self.config, "nothing", False)


if __name__ == "__main__":
    unittest.main()
