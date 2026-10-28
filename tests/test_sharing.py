from __future__ import annotations

import dataclasses
import grp
import json
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
from proj.discovery import resolve, scan
from proj.editor import create_document
from proj.errors import ProjError
from proj.export import environments_snapshot
from proj.metadata import load_project


class Fixture(unittest.TestCase):
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


class ShareTests(Fixture):
    def test_share_moves_the_environment_unchanged(self):
        document = self.make(self.private, notes=True)
        before = document.read_bytes()
        expected = load_project(document)
        target = sharing.share(self.config, "ledger")
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
        target = sharing.share(self.config, "ledger", "group-writable")
        self.assertEqual((self.mode(target.parent), self.mode(target)), (0o2775, 0o664))

    def test_share_refuses_a_name_that_exists_in_the_shared_registry(self):
        document = self.make(self.private)
        taken = self.make(self.shared)
        before = taken.read_bytes()
        with self.assertRaisesRegex(ProjError, "already exists"):
            sharing.share(self.config, "ledger")
        self.assertTrue(document.exists())
        self.assertEqual(taken.read_bytes(), before)
        self.assertEqual(sorted(path.name for path in self.shared.iterdir()), ["ledger"])

    def test_share_refuses_a_leftover_directory_without_touching_it(self):
        self.make(self.private)
        (self.shared / "ledger").mkdir()
        (self.shared / "ledger" / "old.txt").write_text("x")
        with self.assertRaisesRegex(ProjError, "holds other files"):
            sharing.share(self.config, "ledger")
        self.assertTrue((self.private / "ledger" / "project.toml").exists())
        self.assertEqual((self.shared / "ledger" / "old.txt").read_text(), "x")

    def test_share_needs_a_private_environment(self):
        self.make(self.shared)
        with self.assertRaisesRegex(ProjError, "not private"):
            sharing.share(self.config, "ledger")
        with self.assertRaisesRegex(ProjError, "unknown private"):
            sharing.share(self.config, "nothing")
        with self.assertRaises(ProjError):
            sharing.share(self.config, "../escape")

    def test_share_refuses_the_environment_active_in_this_shell(self):
        self.make(self.private)
        with patch.dict(os.environ, {"PROJ_ACTIVE": "ledger"}):
            with self.assertRaisesRegex(ProjError, "active in this shell"):
                sharing.share(self.config, "ledger")
        self.assertTrue((self.private / "ledger" / "project.toml").exists())
        self.assertEqual(list(self.shared.iterdir()), [])

    def test_share_without_a_shared_registry(self):
        self.make(self.private)
        config = dataclasses.replace(self.config, shared_registry=None)
        with self.assertRaisesRegex(ProjError, "no shared registry"):
            sharing.share(config, "ledger")

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
                sharing.share(self.config, "ledger")
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
            sharing.share(self.config, "ledger")
        self.assertEqual(seen, [[]])

    def test_unshare_is_the_reverse(self):
        self.make(self.private, notes=True)
        shared = sharing.share(self.config, "ledger", "group-writable")
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
                sharing.unshare(self.config, "ledger", "group-writable")
        with patch("proj.sharing.active_elsewhere", return_value=["vim (pid 7, ana)"]):
            with self.assertRaisesRegex(ProjError, "looks active in vim"):
                sharing.unshare(self.config, "ledger", False)
            self.assertTrue(shared.exists())
            sharing.unshare(self.config, "ledger", "group-writable")
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


class AccessTests(Fixture):
    """Groups and access levels on top of the same fixture."""

    def other_group(self):
        """A group the user is in that is not the registry's, or None."""
        for gid in os.getgroups():
            if gid != os.getgid():
                return grp.getgrgid(gid).gr_name
        return None

    def foreign_group(self):
        """A group the user is not in, or None."""
        mine = set(os.getgroups()) | {os.getgid()}
        return next((g.gr_name for g in grp.getgrall() if g.gr_gid not in mine), None)

    def test_share_to_a_named_group_and_access_level(self):
        group = self.other_group()
        if group is None or os.getuid() == 0:
            self.skipTest("needs a second group")
        expected = {"owner": (0o2755, 0o644), "group-writable": (0o2775, 0o664), "private": (0o2770, 0o660)}
        for level, (directory_mode, document_mode) in expected.items():
            self.make(self.private, "ledger", notes=True)
            target = sharing.share(self.config, "ledger", level, group)
            self.assertEqual((self.mode(target.parent), self.mode(target)), (directory_mode, document_mode))
            self.assertEqual(self.mode(target.parent / "notes.md"), document_mode)
            self.assertEqual(grp.getgrgid(target.stat().st_gid).gr_name, group)
            self.assertEqual(grp.getgrgid(target.parent.stat().st_gid).gr_name, group)
            sharing.unshare(self.config, "ledger", False)
            shutil.rmtree(self.private / "ledger")

    def test_a_group_the_creator_is_not_in_or_that_does_not_exist_is_refused(self):
        self.make(self.private)
        with self.assertRaisesRegex(ProjError, "does not exist"):
            sharing.share(self.config, "ledger", "owner", "no-such-group-here")
        foreign = self.foreign_group()
        if foreign and os.getuid() != 0:
            with self.assertRaisesRegex(ProjError, "not a member"):
                sharing.share(self.config, "ledger", "owner", foreign)
        self.assertTrue((self.private / "ledger" / "project.toml").exists())
        self.assertEqual(list(self.shared.iterdir()), [])

    def test_access_changes_every_file_and_keeps_the_group(self):
        document = self.make(self.shared, notes=True)
        document.parent.chmod(0o2755)
        group = grp.getgrgid(document.stat().st_gid).gr_name
        for level, (directory_mode, file_mode) in {
            "group-writable": (0o2775, 0o664), "private": (0o2770, 0o660), "owner": (0o2755, 0o644),
        }.items():
            directory, _before, after = sharing.change_access(self.config, "ledger", level)
            self.assertEqual(after, level)
            self.assertEqual(self.mode(directory), directory_mode)
            self.assertEqual({self.mode(document), self.mode(directory / "notes.md")}, {file_mode})
            self.assertEqual(grp.getgrgid(document.stat().st_gid).gr_name, group)

    def test_access_without_a_level_only_reports(self):
        document = self.make(self.shared)
        document.parent.chmod(0o2775)
        _directory, before, after = sharing.change_access(self.config, "ledger", None)
        self.assertEqual((before, after), ("group-writable", "group-writable"))
        self.assertEqual(self.mode(document.parent), 0o2775)

    def test_only_the_creator_changes_access_and_private_environments_have_none(self):
        document = self.make(self.shared)
        document.parent.chmod(0o2755)
        with patch("proj.sharing.os.getuid", return_value=os.getuid() + 1):
            with self.assertRaisesRegex(ProjError, "only its creator"):
                sharing.change_access(self.config, "ledger", "private")
        self.assertEqual(self.mode(document.parent), 0o2755)
        self.make(self.private, "mine")
        with self.assertRaisesRegex(ProjError, "private"):
            sharing.change_access(self.config, "mine", "private")

    def test_description_names_the_environments_group_and_access(self):
        from proj import access
        document = self.make(self.shared)
        for level, text in {"owner": "editable by owner", "group-writable": "editable by group", "private": "only"}.items():
            document.parent.chmod(access.SHARED_DIR_MODES[level])
            project = load_project(document)
            self.assertEqual(access.level_of(project), level)
            self.assertIn(text, access.describe_scope(self.config, project))
            self.assertIn(access.group_name(document.parent), access.describe_scope(self.config, project))


class UnreadableTests(Fixture):
    def setUp(self):
        super().setUp()
        if os.getuid() == 0:
            self.skipTest("root can read everything")

    def test_an_environment_the_person_cannot_read_is_counted_not_reported(self):
        self.make(self.shared, "open")
        gated = self.make(self.shared, "gated")
        gated.parent.chmod(0)
        try:
            found = scan(self.config)
            self.assertEqual(list(found.projects), ["open"])
            self.assertEqual(found.problems, [])
            self.assertEqual(len(found.unreadable), 1)
            strict = scan(self.config, strict=True)
            self.assertEqual((strict.problems, len(strict.unreadable)), ([], 1))
            with self.assertRaisesRegex(ProjError, "no permission"):
                resolve(self.config, "gated")
            document = environments_snapshot(
                self.config, found.projects.values(), len(found.problems), unreadable=len(found.unreadable)
            )
            self.assertEqual((document["skipped"], document["unreadable"]), (0, 1))
            self.assertNotIn("gated", json.dumps(document))
        finally:
            gated.parent.chmod(0o2770)

    def test_a_document_that_cannot_be_opened_counts_the_same_way(self):
        locked = self.make(self.shared, "locked")
        locked.chmod(0)
        try:
            found = scan(self.config)
            self.assertEqual((found.projects, found.problems, len(found.unreadable)), ({}, [], 1))
        finally:
            locked.chmod(0o644)


if __name__ == "__main__":
    unittest.main()
