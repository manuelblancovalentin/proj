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

    def test_the_origin_is_recorded(self):
        self.copy()
        copy = load_project(self.home / "envs" / "atlas-topic" / "project.toml")
        self.assertEqual(copy.derived.source, "atlas")

    def test_info_says_when_the_original_changed_or_disappeared(self):
        self.copy()
        info = lambda: self.run_proj("info", "--env", "atlas-topic")[1]
        self.assertIn("atlas on", info())
        self.assertNotIn("has changed", info())
        self.run_proj("config", "--env", "atlas", "environment.ATLAS_MODE=other")
        self.assertIn("the original has changed since", info())
        self.original.unlink()
        self.assertIn("no longer readable", info())

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



if __name__ == "__main__":
    unittest.main()
