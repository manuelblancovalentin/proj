from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from proj.cli import main
from proj.editor import create_document, load_document, set_dotted, write_document
from proj.errors import ProjError
from proj.menu_state import parse_variable


class UnsetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "atlas"
        self.root.mkdir()
        self.patch = patch.dict(
            os.environ,
            {
                "PROJ_HOME": str(self.base / "home"),
                "PROJ_CACHE_HOME": str(self.base / "cache"),
                "PROJ_CONFIG": str(self.base / "none.toml"),
                "PROJ_SITE_CONFIG": str(self.base / "none.toml"),
            },
        )
        self.patch.start()
        for name in ("PROJ_PROJECT_ROOTS", "PROJ_ACTIVE"):
            os.environ.pop(name, None)
        self.metadata = self.base / "home" / "envs" / "atlas" / "project.toml"
        create_document(self.metadata, "atlas", self.root)
        data = load_document(self.metadata)
        set_dotted(data, "environment.VIRTUAL_ENV", "${project.root}/.venv")
        set_dotted(data, "environment.ATLAS_MODE", "development")
        set_dotted(data, "aliases.go", "cd ${project.root}")
        set_dotted(data, "paths.prepend", ["${project.root}/bin"])
        set_dotted(data, "modules.toolchain", ["cmake/3.30"])
        set_dotted(data, "environment_paths.PYTHONPATH.prepend", ["/opt/atlas/src"])
        set_dotted(data, "environment_paths.PYTHONPATH.append", ["/opt/atlas/lib"])
        write_document(self.metadata, data)
        (self.root / "bin").mkdir()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def run_proj(self, *args: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["config", "--env", "atlas", *args])
        return code, out.getvalue(), err.getvalue()

    def test_unset_removes_a_variable_and_nothing_else(self):
        before = load_document(self.metadata)
        code, out, _ = self.run_proj("--unset", "environment.VIRTUAL_ENV")
        self.assertEqual(code, 0)
        self.assertIn("Removed environment.VIRTUAL_ENV", out)
        after = load_document(self.metadata)
        self.assertNotIn("VIRTUAL_ENV", after["environment"])
        del before["environment"]["VIRTUAL_ENV"]
        self.assertEqual(after, before)

    def test_unset_removes_keys_of_every_kind(self):
        for key in (
            "aliases.go",
            "paths.prepend",
            "modules.toolchain",
            "environment_paths.PYTHONPATH.append",
        ):
            self.assertEqual(self.run_proj("--unset", key)[0], 0, key)
        document = load_document(self.metadata)
        self.assertNotIn("go", document.get("aliases", {}))
        self.assertNotIn("prepend", document.get("paths", {}))
        self.assertNotIn("toolchain", document.get("modules", {}))
        self.assertEqual(
            document["environment_paths"], {"PYTHONPATH": {"prepend": ["/opt/atlas/src"]}}
        )

    def test_a_path_variable_goes_with_its_last_list_or_as_a_whole(self):
        self.run_proj("--unset", "environment_paths.PYTHONPATH.prepend")
        self.run_proj("--unset", "environment_paths.PYTHONPATH.append")
        self.assertNotIn("PYTHONPATH", load_document(self.metadata).get("environment_paths", {}))
        self.assertNotIn("[environment_paths.PYTHONPATH]", self.metadata.read_text())
        set_dotted(data := load_document(self.metadata), "environment_paths.PATH.append", ["/x"])
        write_document(self.metadata, data)
        self.assertEqual(self.run_proj("--unset", "environment_paths.PATH")[0], 0)
        self.assertNotIn("PATH", load_document(self.metadata).get("environment_paths", {}))

    def test_a_missing_key_is_an_error_and_changes_nothing(self):
        text = self.metadata.read_text()
        code, _, err = self.run_proj("--unset", "environment.NOT_THERE")
        self.assertEqual(code, 2)
        self.assertIn("'environment.NOT_THERE' is not set", err)
        self.assertEqual(self.metadata.read_text(), text)

    def test_the_name_and_the_root_stay(self):
        text = self.metadata.read_text()
        for key in ("project.name", "project.root"):
            code, _, err = self.run_proj("--unset", key)
            self.assertEqual(code, 2, key)
            self.assertIn("is required", err)
        self.assertEqual(self.metadata.read_text(), text)

    def test_unknown_keys_and_values_are_refused(self):
        self.assertEqual(self.run_proj("--unset", "bogus.key")[0], 2)
        self.assertEqual(self.run_proj("--unset", "environment")[0], 2)
        code, _, err = self.run_proj("--unset", "environment.ATLAS_MODE=x")
        self.assertEqual(code, 2)
        self.assertIn("key only", err)
        self.assertEqual(self.run_proj("--unset", "environment.ATLAS_MODE", "x")[0], 2)
        self.assertIn("ATLAS_MODE", load_document(self.metadata)["environment"])

    def test_it_says_to_reactivate_only_for_the_active_environment(self):
        _, out, _ = self.run_proj("--unset", "environment.ATLAS_MODE")
        self.assertNotIn("Reactivate", out)
        with patch.dict(os.environ, {"PROJ_ACTIVE": "atlas"}):
            _, out, _ = self.run_proj("--unset", "environment.VIRTUAL_ENV")
        self.assertIn("Reactivate the project to apply", out)

    def test_an_environment_that_is_not_yours_is_not_changed(self):
        self.metadata.parent.chmod(0o500)
        self.metadata.chmod(0o400)
        try:
            if os.access(self.metadata, os.W_OK):
                self.skipTest("this account can write read-only files")
            code, _, err = self.run_proj("--unset", "environment.ATLAS_MODE")
            self.assertEqual(code, 2)
            self.assertIn("only its owner", err)
        finally:
            self.metadata.parent.chmod(0o700)
            self.metadata.chmod(0o600)
        self.assertIn("ATLAS_MODE", load_document(self.metadata)["environment"])


class ParseVariableTests(unittest.TestCase):
    def test_name_and_value(self):
        self.assertEqual(parse_variable("  A=b=c "), ("A", "b=c"))
        self.assertEqual(parse_variable("A="), ("A", ""))
        self.assertEqual(parse_variable("A = x"), ("A", " x"))

    def test_mistakes(self):
        for text in ("", "NOPE", "=x", "  =  "):
            with self.assertRaises(ProjError, msg=text):
                parse_variable(text)


if __name__ == "__main__":
    unittest.main()
