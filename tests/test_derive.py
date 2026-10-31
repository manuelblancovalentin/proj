from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from proj.cli import main
from proj.config import load_config
from proj.editor import create_document, load_document, set_dotted, write_document
from proj.metadata import load_project


class DeriveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        self.home = self.base / "home"
        self.root = self.base / "atlas"
        self.root.mkdir()
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
        self.original = self.home / "envs" / "atlas" / "project.toml"
        create_document(self.original, "atlas", self.root)
        data = load_document(self.original)
        set_dotted(data, "modules.toolchain", ["cmake/3.30"])
        set_dotted(data, "environment.ATLAS_MODE", "development")
        set_dotted(data, "paths.prepend", ["${project.root}/bin"])
        set_dotted(data, "python.spec", "${project.root}/repo/environment.yml")
        data["python"]["stamp"] = {"sha256": "a" * 64, "date": "2026-10-01", "by": "lead"}
        write_document(self.original, data)
        (self.root / "bin").mkdir()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def run_proj(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(list(argv))
        self.stderr = err.getvalue()
        return code, out.getvalue()

    def copy(self, *extra):
        return self.run_proj("create", "atlas-topic", "--from", "atlas", *extra)

    def test_copy_has_the_same_definition_under_a_new_name(self):
        self.assertEqual(self.copy()[0], 0)
        path = self.home / "envs" / "atlas-topic" / "project.toml"
        copy, original = load_project(path), load_project(self.original)
        self.assertEqual(copy.name, "atlas-topic")
        self.assertEqual(copy.modules, original.modules)
        self.assertEqual(copy.environment, original.environment)
        self.assertEqual(copy.prepend_paths, original.prepend_paths)
        self.assertEqual(copy.root, original.root)
        self.assertEqual(copy.python_spec, original.python_spec)

    def test_the_build_stamp_is_not_copied_but_the_origin_is_recorded(self):
        self.copy()
        copy = load_project(self.home / "envs" / "atlas-topic" / "project.toml")
        self.assertIsNone(copy.python_stamp)
        self.assertEqual(copy.derived.source, "atlas")
        self.assertIsNotNone(load_project(self.original).python_stamp)

    def test_info_says_when_the_original_changed_or_disappeared(self):
        self.copy()
        info = lambda: self.run_proj("info", "--env", "atlas-topic")[1]
        self.assertIn("atlas on", info())
        self.assertNotIn("has changed", info())
        self.run_proj("config", "--env", "atlas", "environment.ATLAS_MODE=other")
        self.assertIn("the original has changed since", info())
        self.original.unlink()
        self.assertIn("no longer readable", info())

    def test_a_stamp_alone_does_not_count_as_a_change(self):
        self.copy()
        data = load_document(self.original)
        data["python"]["stamp"] = {"sha256": "b" * 64, "date": "2026-10-20", "by": "lead"}
        write_document(self.original, data)
        self.assertNotIn("has changed", self.run_proj("info", "--env", "atlas-topic")[1])

    def test_root_and_use_can_be_given_and_the_name_must_be_free(self):
        elsewhere = self.base / "elsewhere"
        elsewhere.mkdir()
        self.copy("--root", str(elsewhere))
        copy = load_project(self.home / "envs" / "atlas-topic" / "project.toml")
        self.assertEqual(copy.root, elsewhere)
        self.assertNotEqual(self.copy()[0], 0)
        self.assertIn("already exists", self.stderr)

    def test_unknown_source_creates_nothing(self):
        self.assertNotEqual(self.run_proj("create", "x", "--from", "nope")[0], 0)
        self.assertIn("unknown project", self.stderr)
        self.assertFalse((self.home / "envs" / "x").exists())

    def test_python_environment_must_exist(self):
        with patch("proj.python_envs.environments", return_value={"atlas-topic": Path("/p")}):
            self.copy("--python", "atlas-topic")
        copy = load_project(self.home / "envs" / "atlas-topic" / "project.toml")
        self.assertEqual(copy.python_environment, "atlas-topic")
        with patch("proj.python_envs.environments", return_value={}):
            code = self.run_proj("create", "other", "--from", "atlas", "--python", "ghost")[0]
            self.assertNotEqual(code, 0)
            self.assertIn("unknown micromamba environment", self.stderr)
        self.assertFalse((self.home / "envs" / "other").exists())


if __name__ == "__main__":
    unittest.main()
