from __future__ import annotations

import io
import json
import os
import shlex
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from proj.cli import main
from proj.config import load_config
from proj.discovery import resolve
from proj.editor import create_document, load_document, set_dotted, write_document
from proj.modulefile import render
from proj.shell import (
    changed_python,
    deactivation_code,
    environment_label,
    recorded_python,
    reload_code,
)


class ChangedRecordTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        self.work = self.base / "work"
        self.work.mkdir()
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
        for name in ("PROJ_PROJECT_ROOTS", "PROJ_ACTIVE", "PROJ_MODULE", "PROJ_MAMBA_ENV", "PROJ_PYTHON_MANAGER"):
            os.environ.pop(name, None)
        self.config = load_config()
        self.document = self.config.registry / "atlas" / "project.toml"
        create_document(self.document, "atlas", self.work, python_manager="micromamba")
        self.link("atlas-a")

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def link(self, environment: str, manager: str | None = None):
        data = load_document(self.document)
        set_dotted(data, "python.environment", environment)
        if manager:
            set_dotted(data, "python.manager", manager)
        write_document(self.document, data)

    def proj(self, *args: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(list(args))
        return code, out.getvalue(), err.getvalue()

    def shell(self, environment: str = "atlas-a", manager: str = "micromamba"):
        """What a shell holds after activating: what the loaded module exported."""
        return patch.dict(
            os.environ,
            {
                "PROJ_ACTIVE": "atlas",
                "PROJ_MODULE": "project/atlas",
                "PROJ_MAMBA_ENV": environment,
                "PROJ_PYTHON_MANAGER": manager,
            },
        )

    def arguments(self, code: str) -> list[str]:
        return shlex.split(code)[1:]

    # --- what the module records -------------------------------------------

    def test_the_module_records_the_manager_it_activated_with(self):
        project = resolve(self.config, "atlas")
        self.assertIn('setenv("PROJ_PYTHON_MANAGER", "conda")', render(project, "conda"))
        self.assertNotIn("PROJ_PYTHON_MANAGER", render(project))
        create_document(self.config.registry / "bare" / "project.toml", "bare", self.work)
        self.assertNotIn("PROJ_PYTHON_MANAGER", render(resolve(self.config, "bare"), "conda"))

    # --- leaving -----------------------------------------------------------

    def test_deactivation_without_a_loaded_module_uses_the_document(self):
        arguments = self.arguments(deactivation_code(self.config, resolve(self.config, "atlas")))
        self.assertEqual(arguments[3], "atlas-a")
        self.assertEqual(arguments[6:], ["micromamba", "0", "0"])

    def test_deactivation_leaves_with_what_the_shell_recorded(self):
        self.link("atlas-b", "conda")
        with self.shell("atlas-a", "micromamba"):
            project = resolve(self.config, "atlas")
            self.assertEqual(recorded_python(project), ("atlas-a", "micromamba"))
            self.assertEqual(changed_python(self.config, project), ("atlas-a", "atlas-b"))
            arguments = self.arguments(deactivation_code(self.config, project, quiet=True, force=True))
        self.assertEqual(arguments[3], "atlas-a")
        self.assertEqual(arguments[6:], ["micromamba", "1", "1"])

    def test_a_shell_from_before_the_manager_was_recorded_falls_back_to_the_documents(self):
        self.link("atlas-b")
        with self.shell("atlas-a", ""):
            arguments = self.arguments(deactivation_code(self.config, resolve(self.config, "atlas")))
        self.assertEqual((arguments[3], arguments[6]), ("atlas-a", "micromamba"))

    def test_an_environment_added_or_dropped_after_activation_is_a_change_too(self):
        with self.shell("", ""):
            self.assertEqual(changed_python(self.config, resolve(self.config, "atlas")), ("", "atlas-a"))
            self.assertEqual(self.arguments(deactivation_code(self.config, resolve(self.config, "atlas")))[3], "")

    def test_nothing_changed_is_not_a_change(self):
        with self.shell():
            self.assertIsNone(changed_python(self.config, resolve(self.config, "atlas")))
        self.assertIsNone(changed_python(self.config, resolve(self.config, "atlas")))

    def test_the_cli_says_what_happened_before_the_shell_acts(self):
        self.link("atlas-b")
        with self.shell("atlas-a"):
            code, out, err = self.proj("_shell", "deactivate")
        self.assertEqual(code, 0)
        self.assertIn("was changed after this shell activated it (it was atlas-a, it is now atlas-b)", err)
        self.assertIn("proj activate atlas", err)
        self.assertTrue(out.startswith("_proj_deactivate "))

    def test_an_unchanged_project_deactivates_without_a_word(self):
        with self.shell("atlas-a"):
            code, out, err = self.proj("_shell", "deactivate")
        self.assertEqual((code, err), (0, ""))

    def test_a_prefix_is_named_by_its_last_component_unless_that_is_ambiguous(self):
        self.assertEqual(environment_label("/opt/envs/atlas"), "atlas")
        self.assertEqual(environment_label("/opt/a/atlas", "/opt/b/atlas"), "/opt/a/atlas")
        self.assertEqual(environment_label("/opt/a/atlas", "other"), "atlas")
        self.assertEqual(environment_label(""), "none")

    # --- switching ---------------------------------------------------------

    def test_activate_in_a_shell_with_an_old_record_reloads(self):
        self.link("atlas-b")
        with self.shell("atlas-a"):
            code, out, err = self.proj("_shell", "activate", "atlas")
        self.assertEqual(code, 0)
        self.assertIn("switching to the new one", err)
        self.assertIn("_proj_reload atlas", out)
        # An adapter from before `reload` is told what to do rather than crashing.
        self.assertIn("older than the proj it runs", out)

    def test_activate_when_nothing_changed_is_still_refused(self):
        with self.shell("atlas-a"):
            code, _, err = self.proj("_shell", "activate", "atlas")
        self.assertEqual(code, 2)
        self.assertIn("already active", err)

    def test_reload_needs_the_active_environment(self):
        code, _, err = self.proj("_shell", "reload")
        self.assertEqual(code, 2)
        self.assertIn("no project is active", err)
        with self.shell():
            self.assertEqual(self.proj("_shell", "reload", "elsewhere")[0], 2)
            code, out, _ = self.proj("_shell", "reload")
        self.assertEqual((code, out.strip()), (0, reload_code("atlas")))

    def test_reload_and_deactivate_are_shell_commands(self):
        for command in (("reload",), ("deactivate", "--force")):
            code, _, err = self.proj(*command)
            self.assertEqual(code, 2, command)
            self.assertIn("must run through the shell integration", err)

    # --- status ------------------------------------------------------------

    def test_status_names_the_previous_environment_not_a_hand_edit(self):
        self.link("atlas-b")
        with self.shell("atlas-a"), patch.dict(
            os.environ, {"CONDA_DEFAULT_ENV": "atlas-a", "LOADEDMODULES": "project/atlas"}
        ):
            code, out, _ = self.proj("status")
            _, document, _ = self.proj("status", "--json")
        self.assertEqual(code, 2)
        self.assertIn("this shell uses the previous Python environment (atlas-a; the project now has atlas-b)", out)
        self.assertNotIn("Python environment is", out)
        drift = json.loads(document)["drift"]
        self.assertEqual(len(drift), 1)
        self.assertIn("proj reload", drift[0])

    def test_status_still_reports_a_hand_edit_against_the_recorded_environment(self):
        self.link("atlas-b")
        with self.shell("atlas-a"), patch.dict(
            os.environ, {"CONDA_DEFAULT_ENV": "other", "LOADEDMODULES": "project/atlas"}
        ):
            _, out, _ = self.proj("status")
        self.assertIn("Python environment is other, expected atlas-a", out)

    def test_status_is_consistent_when_nothing_changed(self):
        with self.shell("atlas-a"), patch.dict(
            os.environ, {"CONDA_DEFAULT_ENV": "atlas-a", "LOADEDMODULES": "project/atlas"}
        ):
            code, out, _ = self.proj("status")
        self.assertEqual(code, 0)
        self.assertIn("consistent", out)


if __name__ == "__main__":
    unittest.main()
