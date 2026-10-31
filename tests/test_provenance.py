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


class StatusTests(Fixture):
    def test_behind_environment_is_drift_with_exit_2_even_when_not_active(self):
        self.run_proj("python-env", "stamp", "--env", "atlas")
        self.assertEqual(self.run_proj("status", "--env", "atlas")[0], 0)
        self.spec.write_text("changed\n")
        code, out = self.run_proj("status", "--env", "atlas")
        self.assertEqual(code, 2)
        self.assertIn("behind", out)

    def test_json_record_has_no_paths_or_user_names(self):
        self.run_proj("python-env", "stamp", "--env", "atlas")
        code, out = self.run_proj("status", "--env", "atlas", "--json")
        self.assertEqual(code, 0)
        document = json.loads(out)
        self.assertEqual(document["schema"], 1)
        self.assertEqual(document["environment"]["name"], "atlas")
        self.assertEqual(document["python"]["dependencies"]["spec"], "environment.yml")
        self.assertEqual(document["python"]["dependencies"]["state"], "current")
        self.assertNotIn(str(self.base), out)
        self.assertNotIn(provenance.stamper(), out.replace('"stamped', ""))
        self.assertNotIn("checkout", document)

    def test_json_without_an_environment_is_still_a_document(self):
        code, out = self.run_proj("status", "--json")
        self.assertEqual(code, 0)
        self.assertIsNone(json.loads(out)["environment"])

    def test_active_environment_lists_loaded_modules(self):
        with patch.dict(os.environ, {"PROJ_ACTIVE": "atlas", "LOADEDMODULES": "gcc/14:project/atlas"}):
            code, out = self.run_proj("status", "--json")
        self.assertEqual(json.loads(out)["loaded_modules"], ["gcc/14", "project/atlas"])

    def test_checkout_needs_a_declared_spec(self):
        data = load_document(self.path)
        del data["python"]["spec"]
        write_document(self.path, data)
        self.assertNotEqual(self.run_proj("status", "--env", "atlas", "--checkout", str(self.base))[0], 0)


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class GitStateTests(Fixture):
    def git(self, *args):
        subprocess.run(
            ["git", "-C", str(self.clone), "-c", "user.email=a@b", "-c", "user.name=n", *args],
            check=True, capture_output=True,
        )

    def setUp(self):
        super().setUp()
        self.clone = self.base / "clone"
        self.clone.mkdir()
        self.git("init", "-q", "-b", "feature")
        (self.clone / "environment.yml").write_text(self.spec.read_text())
        self.git("add", ".")
        self.git("commit", "-qm", "first")

    def test_commit_branch_and_cleanliness(self):
        state = provenance.git_state(self.clone)
        self.assertEqual(len(state["commit"]), 40)
        self.assertEqual(state["branch"], "feature")
        self.assertFalse(state["dirty"])
        (self.clone / "new.txt").write_text("x")
        state = provenance.git_state(self.clone)
        self.assertTrue(state["dirty"])
        self.assertEqual(state["changed_files"], 1)

    def test_detached_head_has_no_branch(self):
        self.git("checkout", "-q", "--detach")
        self.assertIsNone(provenance.git_state(self.clone)["branch"])

    def test_not_a_checkout_is_an_error_and_nothing_is_changed(self):
        plain = self.base / "plain"
        plain.mkdir()
        with self.assertRaises(ProjError):
            provenance.git_state(plain)
        self.assertEqual(list(plain.iterdir()), [])

    def test_status_json_carries_the_checkout_without_its_path(self):
        code, out = self.run_proj("status", "--env", "atlas", "--json", "--checkout", str(self.clone))
        document = json.loads(out)
        self.assertEqual(document["checkout"]["branch"], "feature")
        self.assertNotIn(str(self.base), out)
        self.assertEqual(document["python"]["dependencies"]["checkout_state"], "unstamped")

    def test_a_repository_cannot_start_a_program_through_fsmonitor(self):
        marker = self.base / "ran"
        self.git("config", "core.fsmonitor", f"touch {marker}; echo")
        provenance.git_state(self.clone)
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
