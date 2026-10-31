from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from proj import provenance
from proj.cli import main
from proj.config import load_config
from proj.editor import create_document, load_document, set_dotted, write_document
from proj.errors import ProjError
from proj.metadata import load_project


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        self.home = self.base / "home"
        self.root = self.base / "atlas"
        self.root.mkdir()
        self.spec = self.root / "environment.yml"
        self.spec.write_text("dependencies: [numpy]\n")
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
        for name in ("PROJ_PROJECT_ROOTS", "PROJ_ACTIVE", "LOADEDMODULES"):
            os.environ.pop(name, None)
        self.config = load_config()
        self.path = self.home / "envs" / "atlas" / "project.toml"
        create_document(self.path, "atlas", self.root)
        data = load_document(self.path)
        set_dotted(data, "python.spec", "${project.root}/environment.yml")
        write_document(self.path, data)

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def run_proj(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(list(argv))
        self.stderr = err.getvalue()
        return code, out.getvalue()


class FreshnessTests(Fixture):
    def state(self, **kw):
        return provenance.freshness(load_project(self.path), **kw)["state"]

    def test_states_follow_the_file_and_the_stamp(self):
        self.assertEqual(self.state(), "unstamped")
        self.assertEqual(self.run_proj("python-env", "stamp", "--env", "atlas")[0], 0)
        self.assertEqual(self.state(), "current")
        self.spec.write_text("dependencies: [numpy, scipy]\n")
        self.assertEqual(self.state(), "behind")
        self.spec.unlink()
        self.assertEqual(self.state(), "unreadable")

    def test_stamp_needs_a_declared_readable_file(self):
        data = load_document(self.path)
        del data["python"]["spec"]
        write_document(self.path, data)
        code, _ = self.run_proj("python-env", "stamp", "--env", "atlas")
        self.assertNotEqual(code, 0)
        self.assertIn("python.spec", self.stderr)
        self.assertEqual(provenance.freshness(load_project(self.path))["state"], "no-spec")

    def test_checkout_copy_is_compared_with_the_stamp(self):
        self.run_proj("python-env", "stamp", "--env", "atlas")
        clone = self.base / "clone"
        clone.mkdir()
        project = load_project(self.path)
        report = provenance.freshness(project, clone)
        self.assertEqual(report["checkout_state"], "missing")
        (clone / "environment.yml").write_text(self.spec.read_text())
        self.assertEqual(provenance.freshness(project, clone)["checkout_state"], "matches")
        (clone / "environment.yml").write_text("dependencies: [torch]\n")
        self.assertEqual(provenance.freshness(project, clone)["checkout_state"], "differs")

    def test_stamp_survives_other_edits_and_is_not_settable_by_config(self):
        self.run_proj("python-env", "stamp", "--env", "atlas")
        self.run_proj("config", "--env", "atlas", "environment.X=1")
        self.assertIsNotNone(load_project(self.path).python_stamp)
        self.assertNotEqual(
            self.run_proj("config", "--env", "atlas", "python.stamp.sha256=abc")[0], 0
        )
