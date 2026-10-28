from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from proj import access
from proj.cli import _environment_rows, main
from proj.config import load_config
from proj.discovery import resolve, scan
from proj.editor import create_document, load_document, set_dotted, write_document
from proj.errors import ProjError
from proj.export import environments_snapshot
from proj.metadata import load_project
from proj.modulefile import render
from proj.shell import activation_code


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        self.home = self.base / "home"
        self.patch = patch.dict(
            os.environ,
            {
                "PROJ_HOME": str(self.home),
                "PROJ_CACHE_HOME": str(self.base / "cache"),
                "PROJ_CONFIG": str(self.base / "none.toml"),
                "PROJ_SITE_CONFIG": str(self.base / "none.toml"),
            },
        )
        self.patch.start()
        os.environ.pop("PROJ_PROJECT_ROOTS", None)
        self.config = load_config()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def make(self, name: str, root: Path) -> Path:
        path = self.home / "envs" / name / "project.toml"
        create_document(path, name, root)
        return path


class UnreadableRootTests(Fixture):
    def setUp(self):
        super().setUp()
        if os.getuid() == 0:
            self.skipTest("root can read everything")

    def test_a_root_the_person_cannot_read_is_counted_like_an_unreadable_entry(self):
        gate = self.base / "gate"
        (gate / "secret-folder").mkdir(parents=True)
        (self.base / "open").mkdir()
        self.make("closed", gate / "secret-folder")
        self.make("fine", self.base / "open")
        gate.chmod(0)
        try:
            for strict in (False, True):
                found = scan(self.config, strict=strict)
                self.assertEqual(list(found.projects), ["fine"])
                self.assertEqual(found.problems, [])
                self.assertEqual(len(found.unreadable), 1)
            with self.assertRaises(ProjError) as caught:
                resolve(self.config, "closed")
            self.assertIn("no permission", str(caught.exception))
            self.assertNotIn("secret-folder", str(caught.exception))
            document = environments_snapshot(
                self.config, found.projects.values(), len(found.problems), unreadable=len(found.unreadable)
            )
            self.assertEqual((document["skipped"], document["unreadable"]), (0, 1))
            self.assertNotIn("secret-folder", json.dumps(document))
        finally:
            gate.chmod(0o755)

    def test_a_missing_root_is_still_an_invalid_environment(self):
        gone = self.base / "gone"
        gone.mkdir()
        self.make("lost", gone)
        gone.rmdir()
        found = scan(self.config)
        self.assertEqual((found.unreadable, len(found.problems)), ([], 1))


class VisibleRootTests(Fixture):
    def setUp(self):
        super().setUp()
        self.real = self.base / "gates" / "g1" / "atlas"
        (self.real / "bin").mkdir(parents=True)
        self.link = self.base / "projects" / "atlas"
        self.link.parent.mkdir()
        self.link.symlink_to(self.real)
        self.path = self.make("atlas", self.real)

    def test_config_accepts_a_link_and_people_see_it_as_written(self):
        self.assertEqual(main(["config", "--env", "atlas", f"project.root={self.link}"]), 0)
        self.assertIn(f'root = "{self.link}"', self.path.read_text())  # stored as given, not resolved
        project = load_project(self.path)
        self.assertEqual(project.root, self.real)  # checks and JSON use where it resolves
        self.assertEqual(project.visible_root, self.link)
        self.assertEqual(_environment_rows(self.config, [project])[0][-1], str(self.link))
        self.assertIn(f'setenv("PROJ_ROOT", "{self.link}")', render(project))
        self.assertIn(f"_proj_activate atlas {self.link} ", activation_code(self.config, project))
        snapshot = environments_snapshot(self.config, [project])
        self.assertEqual(snapshot["environments"][0]["project_root"], str(self.real))

    def test_interpolation_follows_the_written_path_and_stays_inside_the_root(self):
        main(["config", "--env", "atlas", f"project.root={self.link}"])
        main(["config", "--env", "atlas", "paths.prepend=[\"${project.root}/bin\"]"])
        project = load_project(self.path)
        self.assertEqual(project.expand("${project.root}/bin"), f"{self.link}/bin")
        outside = self.base / "outside"
        outside.mkdir()
        (self.real / "escape").symlink_to(outside)
        data = load_document(self.path)
        set_dotted(data, "paths.prepend", ["${project.root}/escape"])
        write_document(self.path, data)
        with self.assertRaisesRegex(ProjError, "escapes project root"):
            load_project(self.path)

    def test_a_relative_or_dotdot_root_is_shown_resolved(self):
        main(["config", "--env", "atlas", f"project.root={self.link}/../atlas"])
        project = load_project(self.path)
        self.assertEqual(project.visible_root, project.root)


class OwnerLabelTests(Fixture):
    def test_private_shows_the_user_and_shared_adds_the_group(self):
        work = self.base / "work"
        work.mkdir()
        self.make("mine", work)
        project = load_project(self.home / "envs" / "mine" / "project.toml")
        self.assertEqual(access.owner_label(self.config, project), access.owner_name(project.metadata_path.parent))
        shared = self.base / "shared"
        shared.mkdir()
        site = self.base / "site.toml"
        group = access.group_name(shared)
        site.write_text(f'schema = 1\nshared_registry = "{shared}"\ngroup = "{group}"\n')
        with patch.dict(os.environ, {"PROJ_SITE_CONFIG": str(site)}):
            config = load_config()
        create_document(shared / "team" / "project.toml", "team", work)
        team = load_project(shared / "team" / "project.toml")
        self.assertEqual(
            access.owner_label(config, team), f"{access.owner_name(shared / 'team')}:{group}"
        )


if __name__ == "__main__":
    unittest.main()
