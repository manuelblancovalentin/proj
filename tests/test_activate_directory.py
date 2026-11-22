from __future__ import annotations

import io
import os
import shlex
import stat
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from proj import userconfig
from proj.access import current_user
from proj.cli import main
from proj.config import load_config
from proj.discovery import resolve
from proj.editor import create_document, load_document, set_dotted, write_document
from proj.errors import ConfigError, ProjError
from proj.shell import activation_code, activation_directory


class ActivateDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "lab"
        (self.root / current_user()).mkdir(parents=True)
        self.user_config = self.base / "user.toml"
        self.site_config = self.base / "site.toml"
        self.patch = patch.dict(
            os.environ,
            {
                "PROJ_HOME": str(self.base / "home"),
                "PROJ_CACHE_HOME": str(self.base / "cache"),
                "PROJ_CONFIG": str(self.user_config),
                "PROJ_SITE_CONFIG": str(self.site_config),
            },
        )
        self.patch.start()
        for name in ("PROJ_PROJECT_ROOTS", "PROJ_ACTIVE", "PROJ_VERBOSE"):
            os.environ.pop(name, None)
        create_document(
            self.base / "home" / "envs" / "efpga" / "project.toml", "efpga", self.root
        )
        create_document(
            self.base / "home" / "envs" / "other" / "project.toml", "other", self.root
        )

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def where(self, text: str = "", name: str = "efpga", site: str = "") -> tuple[str, str]:
        self.user_config.write_text(text)
        self.site_config.write_text(site)
        config = load_config()
        err = io.StringIO()
        with redirect_stderr(err):
            return activation_directory(config, resolve(config, name)), err.getvalue()

    # --- the directory -----------------------------------------------------

    def test_no_key_is_the_project_root(self):
        self.assertEqual(self.where(""), (str(self.root), ""))
        self.assertEqual(self.where("[behavior]\nchange_directory = true\n")[0], str(self.root))

    def test_a_folder_that_exists_is_where_activation_lands(self):
        text = '[behavior]\nactivate_directory = "${project.root}/${user}"\n'
        self.assertEqual(self.where(text), (str(self.root / current_user()), ""))

    def test_a_missing_folder_means_the_root_silently(self):
        text = '[behavior]\nactivate_directory = "${project.root}/nobody-here"\n'
        self.assertEqual(self.where(text), (str(self.root), ""))

    def test_a_missing_folder_is_said_once_when_asked_for(self):
        text = '[behavior]\nactivate_directory = "${project.root}/nobody-here"\n'
        with patch.dict(os.environ, {"PROJ_VERBOSE": "1"}):
            target, err = self.where(text)
        self.assertEqual(target, str(self.root))
        self.assertEqual(err.count("\n"), 1)
        self.assertIn("nobody-here does not exist or cannot be entered", err)

    def test_a_folder_that_cannot_be_entered_means_the_root(self):
        locked = self.root / "locked"
        locked.mkdir()
        locked.chmod(0o000)
        try:
            if os.access(locked, os.X_OK):
                self.skipTest("this account can enter any folder")
            text = '[behavior]\nactivate_directory = "${project.root}/locked"\n'
            self.assertEqual(self.where(text)[0], str(self.root))
        finally:
            locked.chmod(0o700)

    def test_a_file_is_not_a_folder(self):
        (self.root / "notes").write_text("x")
        text = '[behavior]\nactivate_directory = "${project.root}/notes"\n'
        self.assertEqual(self.where(text)[0], str(self.root))

    def mine(self, *arguments: str, name: str = "efpga") -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["config", "--env", name, "--mine", *arguments])
        return code, out.getvalue(), err.getvalue()

    def test_your_override_beats_the_global_key_for_that_environment_only(self):
        (self.root / "special").mkdir()
        text = '[behavior]\nactivate_directory = "${project.root}/${user}"\n'
        self.user_config.write_text(text)
        self.assertEqual(self.mine("activate_directory=${project.root}/special")[0], 2)  # needs its table
        code, out, _ = self.mine("behavior.activate_directory=${project.root}/special")
        self.assertEqual(code, 0)
        self.assertIn("only you see it", out)
        self.assertEqual(self.where(text, "efpga")[0], str(self.root / "special"))
        self.assertEqual(self.where(text, "other")[0], str(self.root / current_user()))

    def test_an_override_alone_leaves_the_other_environments_at_the_root(self):
        self.mine("behavior.activate_directory=${project.root}/${user}")
        self.assertEqual(self.where("", "efpga")[0], str(self.root / current_user()))
        self.assertEqual(self.where("", "other")[0], str(self.root))

    def test_a_relative_result_is_a_message_and_the_root(self):
        for template in ("${user}", "work", "~/lab"):
            target, err = self.where(f'[behavior]\nactivate_directory = "{template}"\n')
            self.assertEqual(target, str(self.root), template)
            self.assertIn("not an absolute path", err)
            self.assertIn("using the project root", err)

    def test_an_unknown_variable_is_a_message_and_the_root(self):
        target, err = self.where('[behavior]\nactivate_directory = "${project.root}/${group}"\n')
        self.assertEqual(target, str(self.root))
        self.assertIn("unsupported interpolation ${group}", err)

    def test_the_variables_proj_already_has_work(self):
        (self.root / "efpga").mkdir()
        target, _ = self.where('[behavior]\nactivate_directory = "${project.root}/${project.name}"\n')
        self.assertEqual(target, str(self.root / "efpga"))

    def test_the_project_root_variable_is_the_visible_root(self):
        link = self.base / "link"
        link.symlink_to(self.root)
        document = self.base / "home" / "envs" / "linked" / "project.toml"
        create_document(document, "linked", self.root)
        data = load_document(document)
        set_dotted(data, "project.root", str(link))
        write_document(document, data)
        (self.root / current_user()).mkdir(exist_ok=True)
        target, _ = self.where(
            '[behavior]\nactivate_directory = "${project.root}/${user}"\n', name="linked"
        )
        self.assertEqual(target, str(link / current_user()))

    # --- what activation does with it --------------------------------------

    def test_activation_enters_it_and_nothing_else_moves(self):
        self.user_config.write_text('[behavior]\nactivate_directory = "${project.root}/${user}"\n')
        config = load_config()
        project = resolve(config, "efpga")
        arguments = shlex.split(activation_code(config, project))
        self.assertEqual(arguments[2], str(self.root / current_user()))
        self.assertEqual(arguments[1], "efpga")
        # The root itself, ${project.root}, aliases and paths are not touched.
        self.assertEqual(str(project.visible_root), str(self.root))

    def test_change_directory_false_is_passed_through_and_still_wins(self):
        self.user_config.write_text(
            '[behavior]\nchange_directory = false\nactivate_directory = "${project.root}/${user}"\n'
        )
        config = load_config()
        arguments = shlex.split(activation_code(config, resolve(config, "efpga")))
        self.assertEqual(arguments[7], "0")

    # --- the configuration -------------------------------------------------

    def test_the_layers_are_the_site_then_you_then_your_override(self):
        self.site_config.write_text('[behavior]\nactivate_directory = "${project.root}/site"\n')
        self.assertEqual(load_config().activate_directory, "${project.root}/site")
        self.user_config.write_text('[behavior]\nactivate_directory = "${project.root}/me"\n')
        config = load_config()
        self.assertEqual(config.activate_directory, "${project.root}/me")
        self.assertEqual(userconfig.behavior(config, "efpga").activate_directory, "${project.root}/me")
        self.mine("behavior.activate_directory=${project.root}/mine")
        self.assertEqual(userconfig.behavior(config, "efpga").activate_directory, "${project.root}/mine")
        self.assertEqual(userconfig.behavior(config, "other").activate_directory, "${project.root}/me")
        self.assertEqual(config.activate_directory, "${project.root}/me")

    def test_every_behavior_setting_can_be_overridden_for_one_environment(self):
        self.user_config.write_text("[behavior]\nrun_startup_hooks = false\n")
        for key, value in (
            ("run_startup_hooks", "true"),
            ("change_directory", "false"),
            ("restore_login_modules", "false"),
        ):
            self.assertEqual(self.mine(f"behavior.{key}={value}")[0], 0, key)
        config = load_config()
        efpga, other = userconfig.behavior(config, "efpga"), userconfig.behavior(config, "other")
        self.assertEqual(
            (efpga.run_startup_hooks, efpga.change_directory, efpga.restore_login_modules),
            (True, False, False),
        )
        self.assertEqual(
            (other.run_startup_hooks, other.change_directory, other.restore_login_modules),
            (False, True, True),
        )
        arguments = shlex.split(activation_code(config, resolve(config, "efpga")))
        self.assertEqual((arguments[7], arguments[8], arguments[10]), ("0", "1", "0"))

    def test_the_file_is_private_and_the_environment_is_not_touched(self):
        document = self.base / "home" / "envs" / "efpga" / "project.toml"
        before = document.read_bytes()
        self.mine("behavior.activate_directory=${project.root}/${user}")
        target = userconfig.path(load_config(), "efpga")
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        self.assertEqual(document.read_bytes(), before)
        text = target.read_text()
        self.assertIn("[behavior]", text)
        self.assertNotIn("[python]", text)

    # --- the one way to override anything ----------------------------------

    def test_read_and_forget_an_override(self):
        self.mine("behavior.change_directory=false")
        self.mine("behavior.activate_directory=${project.root}/x")
        self.assertEqual(self.mine("behavior.change_directory")[1].strip(), "false")
        self.assertEqual(self.mine("behavior.activate_directory")[1].strip(), "${project.root}/x")
        self.assertEqual(self.mine("--unset", "behavior.change_directory")[0], 0)
        self.assertEqual(self.mine("behavior.change_directory")[0], 2)
        self.assertEqual(self.mine("--unset", "behavior.change_directory")[0], 2)
        # The file goes with its last key.
        self.assertEqual(self.mine("--unset", "behavior.activate_directory")[0], 0)
        self.assertFalse(userconfig.path(load_config(), "efpga").exists())

    def test_python_and_behavior_share_one_file_and_one_command(self):
        prefix = self.base / "envs" / "mine"
        (prefix / "conda-meta").mkdir(parents=True)
        self.mine("behavior.activate_directory=${project.root}/${user}")
        # The Python link of a shared environment: the same command, the same file.
        shared = self.base / "shared" / "team" / "project.toml"
        with patch.dict(os.environ, {"PROJ_SHARED_REGISTRY": str(self.base / "shared"), "PROJ_GROUP": "anything"}):
            create_document(shared, "team", self.root, python_manager="micromamba")
            code, _, err = self.mine("python.manager=conda", name="team")
            self.assertEqual(code, 2)
            self.assertIn("set the Python environment first", err)
            code, out, err = self.mine(f"python.environment={prefix}", name="team")
            self.assertEqual(code, 0, err)
            self.mine("behavior.change_directory=false", name="team")
            config = load_config()
            project = resolve(config, "team")
            self.assertEqual(project.python_environment, str(prefix))
            self.assertFalse(userconfig.behavior(config, "team").change_directory)
            self.assertEqual(userconfig.read(config, "team").keys(), [
                "python.manager", "python.environment", "behavior.change_directory"])
            # Forgetting one leaves the other.
            self.assertEqual(self.mine("--unset", "python", name="team")[0], 0)
            self.assertIsNone(resolve(load_config(), "team").python_override)
            self.assertFalse(userconfig.behavior(load_config(), "team").change_directory)

    def test_only_what_a_person_may_override_is_accepted(self):
        for key in ("project.root", "aliases.go", "hooks.startup", "modules.toolchain", "bogus"):
            code, _, err = self.mine(f"{key}=x")
            self.assertEqual(code, 2, key)
            self.assertIn("is not a setting one person can change", err)
            self.assertIn("behavior.activate_directory", err)
        self.assertFalse(userconfig.directory(load_config()).exists())

    def test_values_are_checked(self):
        for argument, message in (
            ("behavior.change_directory=maybe", "must be true or false"),
            ("behavior.activate_directory=", "non-empty string"),
        ):
            code, _, err = self.mine(argument)
            self.assertEqual(code, 2, argument)
            self.assertIn(message, err)

    def test_your_own_environment_takes_behavior_but_not_a_python_override(self):
        code, _, err = self.mine("python.environment=whatever")
        self.assertEqual(code, 2)
        self.assertIn("your own environment", err)
        self.assertEqual(self.mine("behavior.change_directory=false")[0], 0)

    def test_info_lists_your_settings(self):
        self.mine("behavior.activate_directory=${project.root}/${user}")
        out = io.StringIO()
        with redirect_stdout(out):
            main(["info", "--env", "efpga"])
        self.assertIn("Your settings", out.getvalue())
        self.assertIn("activate_directory = ${project.root}/${user}", out.getvalue())

    def test_a_broken_file_stops_activation_but_not_deactivation(self):
        target = userconfig.path(load_config(), "efpga")
        target.parent.mkdir(parents=True)
        target.write_text("not toml [")
        config = load_config()
        with self.assertRaises(ProjError):
            activation_code(config, resolve(config, "efpga"))
        self.assertTrue(userconfig.behavior(config, "efpga", strict=False).change_directory)

    # --- the configuration -------------------------------------------------

    def test_mistakes_in_the_configuration_are_refused(self):
        for text, message in (
            ("[behavior]\nactivate_directory = true\n", "non-empty string"),
            ('[behavior]\nactivate_directory = ""\n', "non-empty string"),
            ('[behavior]\nchange_directory = "false"\n', "true or false"),
            ('[behavior]\nbogus = 1\n', "unknown behavior key(s): bogus"),
            ("[projects.efpga]\nactivate_directory = 'x'\n", "unknown configuration keys: projects"),
        ):
            self.user_config.write_text(text)
            with self.assertRaises(ConfigError, msg=text) as caught:
                load_config()
            self.assertIn(message, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
