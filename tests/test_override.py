from __future__ import annotations

import io
import json
import os
import stat
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from proj import userconfig
from proj.cli import main
from proj.config import load_config
from proj.discovery import resolve, scan
from proj.editor import create_document, load_document, set_dotted, write_document
from proj.errors import ProjError
from proj.menu_state import MenuState
from proj.modulefile import render
from proj.shell import activation_code


class OverrideTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        self.work = self.base / "work"
        self.work.mkdir()
        self.shared = self.base / "shared"
        self.shared.mkdir()
        self.home = self.base / "home"
        for name in ("lab", "mine", "other"):
            (self.base / "envs" / name / "conda-meta").mkdir(parents=True)
        self.patch = patch.dict(
            os.environ,
            {
                "PROJ_HOME": str(self.home),
                "PROJ_SHARED_REGISTRY": str(self.shared),
                "PROJ_GROUP": "anything",
                "PROJ_CACHE_HOME": str(self.base / "cache"),
                "PROJ_CONFIG": str(self.base / "none.toml"),
                "PROJ_SITE_CONFIG": str(self.base / "none.toml"),
            },
        )
        self.patch.start()
        for name in ("PROJ_PROJECT_ROOTS", "PROJ_ACTIVE"):
            os.environ.pop(name, None)
        self.config = load_config()
        self.document = self.shared / "trunorth" / "project.toml"
        create_document(self.document, "trunorth", self.work, python_manager="micromamba")
        data = load_document(self.document)
        set_dotted(data, "python.environment", self.prefix("lab"))
        set_dotted(data, "environment.TN_MODE", "shared")
        set_dotted(data, "modules.toolchain", ["cmake/3.30"])
        set_dotted(data, "python.spec", "${project.root}/environment.yml")
        write_document(self.document, data)

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def prefix(self, name: str) -> str:
        return str(self.base / "envs" / name)

    def proj(self, *args: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(list(args))
        return code, out.getvalue(), err.getvalue()

    def mine(self, *extra: str) -> tuple[int, str, str]:
        return self.proj("set-python-env", "--env", "trunorth", "--mine", *extra)

    # --- writing and removing -------------------------------------------

    def test_mine_writes_a_private_file_and_leaves_the_shared_document_alone(self):
        before = self.document.read_bytes()
        code, out, _ = self.mine("--manager", "conda", self.prefix("mine"))
        self.assertEqual(code, 0)
        self.assertEqual(self.document.read_bytes(), before)
        target = userconfig.path(self.config, "trunorth")
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(target.parent.stat().st_mode), 0o700)
        self.assertIn("unchanged for everyone else", out)
        self.assertIn(self.prefix("lab"), out)
        # Only a manager and an environment are recorded: nothing that runs.
        self.assertEqual(
            userconfig.python_override(self.config, "trunorth"), ("conda", self.prefix("mine"))
        )
        self.assertEqual(
            sorted(line.split(" = ")[0] for line in target.read_text().splitlines() if " = " in line),
            ["environment", "manager", "schema"],
        )

    def test_unset_removes_it_and_is_an_error_when_there_is_none(self):
        self.mine(self.prefix("mine"))
        code, out, _ = self.mine("--unset")
        self.assertEqual(code, 0)
        self.assertIn("uses the shared environment's again", out)
        self.assertFalse(userconfig.path(self.config, "trunorth").exists())
        self.assertEqual(resolve(self.config, "trunorth").python_environment, self.prefix("lab"))
        code, _, err = self.mine("--unset")
        self.assertEqual(code, 2)
        self.assertIn("no Python override", err)

    def test_the_arguments_are_checked(self):
        self.assertEqual(self.mine()[0], 2)  # no environment
        self.assertEqual(self.mine("--unset", self.prefix("mine"))[0], 2)
        code, _, err = self.proj("set-python-env", "--env", "trunorth", "--unset")
        self.assertEqual(code, 2)
        self.assertIn("--mine", err)
        code, _, err = self.mine(str(self.base / "no-such-prefix"))
        self.assertEqual(code, 2)
        self.assertFalse(userconfig.path(self.config, "trunorth").exists())

    def test_a_private_environment_is_edited_not_overridden(self):
        create_document(self.config.registry / "own" / "project.toml", "own", self.work)
        code, _, err = self.proj("set-python-env", "--env", "own", "--mine", self.prefix("mine"))
        self.assertEqual(code, 2)
        self.assertIn("your own environment", err)
        self.assertFalse(userconfig.directory(self.config).exists())

    def test_the_reactivate_hint_is_for_the_active_environment(self):
        self.assertNotIn("Reactivate", self.mine(self.prefix("mine"))[1])
        with patch.dict(os.environ, {"PROJ_ACTIVE": "trunorth"}):
            self.assertIn("Reactivate the project", self.mine("--unset")[1])

    # --- what it changes -------------------------------------------------

    def test_only_the_python_link_changes_for_this_person(self):
        shared = resolve(self.config, "trunorth")
        self.mine("--manager", "conda", self.prefix("mine"))
        mine = resolve(self.config, "trunorth")
        self.assertEqual(mine.python_environment, self.prefix("mine"))
        self.assertEqual(mine.python_manager, "conda")
        self.assertEqual(mine.shared_python_environment, self.prefix("lab"))
        self.assertEqual(mine.shared_manager, "micromamba")
        for field in ("modules", "environment", "root", "python_spec", "metadata_path", "aliases"):
            self.assertEqual(getattr(mine, field), getattr(shared, field), field)

    def test_activation_and_the_module_use_the_override(self):
        self.mine("--manager", "conda", self.prefix("mine"))
        project = resolve(self.config, "trunorth")
        code = activation_code(self.config, project)
        self.assertIn(self.prefix("mine"), code)
        self.assertNotIn(self.prefix("lab"), code)
        self.assertIn(f'setenv("PROJ_MAMBA_ENV", "{self.prefix("mine")}")', render(project))

    def test_another_person_does_not_see_it(self):
        self.mine(self.prefix("mine"))
        other_home = self.base / "other-home"
        with patch.dict(
            os.environ,
            {"PROJ_HOME": str(other_home), "PROJ_CONFIG": str(self.base / "other-config" / "config.toml")},
        ):
            other = load_config()
            self.assertEqual(
                resolve(other, "trunorth").python_environment, self.prefix("lab")
            )
            self.assertIsNone(resolve(other, "trunorth").python_override)

    def test_a_stale_file_for_a_private_environment_is_ignored(self):
        create_document(self.config.registry / "own" / "project.toml", "own", self.work)
        userconfig.set_python(self.config, "own", "conda", self.prefix("mine"))
        self.assertIsNone(resolve(self.config, "own").python_override)

    def test_a_link_kept_by_0_9_0_still_counts_and_moves_to_the_new_file(self):
        old = userconfig.legacy_path(self.config, "trunorth")
        old.parent.mkdir(parents=True)
        old.write_text(
            f'schema = 1\n\n[python]\nmanager = "conda"\nenvironment = "{self.prefix("mine")}"\n'
        )
        found = resolve(self.config, "trunorth")
        self.assertEqual((found.python_manager, found.python_environment), ("conda", self.prefix("mine")))
        self.proj("config", "--env", "trunorth", "--mine", "behavior.change_directory=false")
        self.assertFalse(old.exists())
        self.assertEqual(
            userconfig.python_override(self.config, "trunorth"), ("conda", self.prefix("mine"))
        )
        self.assertFalse(userconfig.behavior(self.config, "trunorth").change_directory)
        self.assertEqual(userconfig.path(self.config, "trunorth").parent.name, "projects")

    def test_the_shared_environment_can_still_be_relinked_by_its_owner(self):
        self.mine("--manager", "conda", self.prefix("mine"))
        code, _, _ = self.proj("set-python-env", "--env", "trunorth", self.prefix("other"))
        self.assertEqual(code, 0)
        data = load_document(self.document)
        # The document's own manager is the base, not the person's override.
        self.assertEqual(data["python"]["manager"], "micromamba")
        self.assertEqual(data["python"]["environment"], self.prefix("other"))
        self.assertEqual(resolve(self.config, "trunorth").python_environment, self.prefix("mine"))

    # --- what it reports -------------------------------------------------

    def test_info_and_status_say_so(self):
        self.mine(self.prefix("mine"))
        _, info, _ = self.proj("info", "--env", "trunorth")
        self.assertIn("Python override", info)
        self.assertIn("the shared environment links " + self.prefix("lab"), info)
        _, status, _ = self.proj("status", "--env", "trunorth")
        self.assertIn("your override", status)

    def test_status_json_has_the_source_and_no_paths(self):
        for expected, prepare in (("shared", lambda: None), ("override", lambda: self.mine(self.prefix("mine")))):
            prepare()
            code, out, _ = self.proj("status", "--env", "trunorth", "--json")
            python = json.loads(out)["python"]
            self.assertEqual(python["environment_source"], expected)
            self.assertNotIn(str(self.base), out)
        self.assertEqual(python["environment"], "mine")

    def test_the_dependency_states_a_service_can_show(self):
        spec = self.work / "environment.yml"
        states = []

        def state() -> str:
            _, out, _ = self.proj("status", "--env", "trunorth", "--json")
            return json.loads(out)["python"]["dependencies"]["state"]

        states.append(state())                                   # no file yet
        spec.write_text("name: lab\n")
        states.append(state())                                   # never stamped
        self.proj("python-env", "stamp", "--env", "trunorth")
        states.append(state())                                   # up to date
        spec.write_text("name: lab\ndependencies: [numpy]\n")
        states.append(state())                                   # file changed
        self.assertEqual(states, ["unreadable", "unstamped", "current", "behind"])
        # With an override the dependency state is the shared environment's.
        self.mine(self.prefix("mine"))
        self.assertEqual(state(), "behind")

    def test_list_json_describes_the_document_not_a_person(self):
        self.mine(self.prefix("mine"))
        code, out, _ = self.proj("list", "--json")
        self.assertEqual(code, 0)
        listed = {item["name"]: item for item in json.loads(out)["environments"]}
        self.assertEqual(listed["trunorth"]["python"]["environment"], "lab")
        _, text, _ = self.proj("list")
        self.assertIn("trunorth", text)

    def test_the_menu_names_the_override_without_changing_the_shared_link(self):
        self.mine(self.prefix("mine"))
        state = MenuState(self.config, resolve(self.config, "trunorth"))
        self.assertIn(("Your Python", self.prefix("mine")), state.identity())
        self.assertEqual(state.python_environment, self.prefix("lab"))
        self.assertFalse(state.dirty)

    # --- refusals ---------------------------------------------------------

    def test_an_invalid_file_stops_that_environment_for_this_person_only(self):
        target = userconfig.directory(self.config) / "trunorth.toml"
        target.parent.mkdir(parents=True)
        for content, message in (
            ('schema = 1\n[python]\nmanager = "conda"\nenvironment = "x"\nrun = "rm"\n', "unknown python keys"),
            ('schema = 1\n[python]\nmanager = "pip"\nenvironment = "x"\n', "manager must be one of"),
            ('schema = 1\n[python]\nmanager = "conda"\n', "environment must be"),
            ('schema = 2\n[python]\nmanager = "conda"\nenvironment = "x"\n', "schema must be 1"),
            ('schema = 1\n[hooks]\nstartup = []\n', "only [python] and [behavior] tables"),
            ('schema = 1\n[behavior]\nrun = "rm"\n', "unknown behavior key(s): run"),
            ('schema = 1\n[behavior]\nchange_directory = "no"\n', "behavior.change_directory must be true or false"),
            ("not toml [", "cannot read"),
        ):
            target.write_text(content)
            with self.assertRaises(ProjError, msg=content) as caught:
                resolve(self.config, "trunorth")
            self.assertIn(message, str(caught.exception))
            self.assertIn("your settings", str(caught.exception))
        found = scan(self.config)
        self.assertEqual(len(found.problems), 1)
        self.assertNotIn("trunorth", found.projects)

    def test_a_world_writable_file_is_refused(self):
        self.mine(self.prefix("mine"))
        target = userconfig.path(self.config, "trunorth")
        target.chmod(0o666)
        with self.assertRaises(ProjError) as caught:
            resolve(self.config, "trunorth")
        self.assertIn("world-writable", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
