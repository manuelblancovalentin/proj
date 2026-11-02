from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from proj.config import load_config
from proj.errors import ConfigError
from proj.prompt import DEFAULT_TOKENS
from proj.shell import activation_code

SNAKE, WOLF, FOX = "\U0001F40D", "\U0001F43A", "\U0001F98A"


class PromptTableTests(unittest.TestCase):
    def load(self, user="", site=""):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "site.toml").write_text("schema = 1\n" + site)
            (base / "user.toml").write_text("schema = 1\n" + user)
            environment = {
                "PROJ_SITE_CONFIG": str(base / "site.toml"),
                "PROJ_CONFIG": str(base / "user.toml"),
            }
            with patch.dict(os.environ, environment):
                return load_config().prompt

    def row(self, name, emoji, plain, when):
        return f'[[prompt.token]]\nname = "{name}"\nemoji = "{emoji}"\nplain = "{plain}"\nwhen = "{when}"\n'

    def test_the_first_rows_are_python_and_wolf(self):
        prompt = self.load()
        self.assertEqual(
            [(t.name, t.emoji, t.plain, t.when) for t in prompt.tokens],
            [
                ("python", SNAKE, "py", "CONDA_PREFIX"),
                ("wolf", WOLF, "wolf", "WOLF_ACTIVE_ENV"),
            ],
        )
        self.assertEqual(prompt.tokens, DEFAULT_TOKENS)
        self.assertTrue(prompt.show_tokens and prompt.hide_manager_prefix and not prompt.plain)

    def test_the_shell_reads_one_row_per_line(self):
        table = self.load().table().split("\n")
        self.assertEqual(table, [f"python|{SNAKE}|py|CONDA_PREFIX", f"wolf|{WOLF}|wolf|WOLF_ACTIVE_ENV"])

    def test_a_later_token_is_one_row(self):
        prompt = self.load(user="[prompt]\n" + self.row("fox", FOX, "fox", "FOX_ACTIVE"))
        self.assertEqual([t.name for t in prompt.tokens], ["python", "wolf", "fox"])
        self.assertTrue(prompt.table().endswith(f"fox|{FOX}|fox|FOX_ACTIVE"))

    def test_a_row_for_an_existing_token_changes_only_the_fields_it_gives(self):
        prompt = self.load(user='[[prompt.token]]\nname = "python"\nwhen = "VIRTUAL_ENV"\n')
        python = prompt.tokens[0]
        self.assertEqual((python.emoji, python.plain, python.when), (SNAKE, "py", "VIRTUAL_ENV"))

    def test_a_token_can_be_switched_off(self):
        prompt = self.load(user='[[prompt.token]]\nname = "wolf"\nenabled = false\n')
        self.assertEqual([t.name for t in prompt.tokens], ["python"])

    def test_site_rows_come_first_and_the_user_layers_over_them(self):
        prompt = self.load(
            site="[prompt]\nhide_manager_prefix = false\n" + self.row("fox", FOX, "fox", "FOX_ACTIVE"),
            user='[prompt]\nplain = true\n[[prompt.token]]\nname = "fox"\nplain = "fx"\n',
        )
        fox = [t for t in prompt.tokens if t.name == "fox"][0]
        self.assertEqual((fox.emoji, fox.plain), (FOX, "fx"))
        self.assertFalse(prompt.hide_manager_prefix)
        self.assertTrue(prompt.plain)

    def test_switches_default_on_and_the_table_is_empty_when_tokens_are_off(self):
        self.assertEqual(self.load(user="[prompt]\nshow_tokens = false\n").table(), "")
        always_plain = self.load(user="[prompt]\nplain = true\n").table().split("\n")
        self.assertEqual(always_plain[0], "python||py|CONDA_PREFIX")

    def test_an_emoji_must_be_one_wide_code_point(self):
        for bad in ("", SNAKE + SNAKE, "❤️", "\U0001F468‍\U0001F4BB", "✔", "x", "é"):
            with self.assertRaises(ConfigError, msg=repr(bad)):
                self.load(user=self.row("fox", bad, "fox", "FOX_ACTIVE"))

    def test_mistakes_are_refused(self):
        bad = {
            "unknown key": '[prompt]\ncolor = "red"\n',
            "string switch": '[prompt]\nplain = "yes"\n',
            "name": self.row("Fox!", FOX, "fox", "FOX_ACTIVE"),
            "variable": self.row("fox", FOX, "fox", "FOX ACTIVE"),
            "variable with a command": self.row("fox", FOX, "fox", "X;reboot"),
            "plain with a bar": self.row("fox", FOX, "f|x", "FOX_ACTIVE"),
            "plain with a space": self.row("fox", FOX, "f x", "FOX_ACTIVE"),
            "missing field": '[[prompt.token]]\nname = "fox"\nemoji = "' + FOX + '"\n',
            "token key": '[[prompt.token]]\nname = "python"\ncolour = "red"\n',
            "same emoji twice": self.row("fox", SNAKE, "fox", "FOX_ACTIVE"),
        }
        for label, text in bad.items():
            with self.assertRaises(ConfigError, msg=label):
                self.load(user=text)

    def test_activation_hands_the_table_and_the_switch_to_the_shell(self):
        from proj.metadata import load_project
        from proj.editor import create_document

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            (base / "root").mkdir()
            environment = {
                "PROJ_HOME": str(base / "home"),
                "PROJ_CACHE_HOME": str(base / "cache"),
                "PROJ_SITE_CONFIG": str(base / "none.toml"),
                "PROJ_CONFIG": str(base / "none.toml"),
            }
            with patch.dict(os.environ, environment):
                config = load_config()
                path = config.registry / "demo" / "project.toml"
                create_document(path, "demo", base / "root")
                code = activation_code(config, load_project(path))
        self.assertIn(f"python|{SNAKE}|py|CONDA_PREFIX\nwolf|{WOLF}|wolf|WOLF_ACTIVE_ENV", code)
        self.assertTrue(code.endswith(" 1"))


class WidthTests(unittest.TestCase):
    def test_the_c_library_counts_every_default_emoji_two_cells_wide(self):
        """Readline and Zsh measure the prompt with wcwidth; if it agreed with the
        configuration check on the width, a line does not drift."""
        import ctypes
        import ctypes.util
        import locale

        library = ctypes.util.find_library("c")
        if not library:
            self.skipTest("no C library")
        libc = ctypes.CDLL(library)
        libc.wcwidth.argtypes = [ctypes.c_wchar]
        old = locale.setlocale(locale.LC_CTYPE)
        try:
            locale.setlocale(locale.LC_CTYPE, "C.UTF-8")
        except locale.Error:
            self.skipTest("no UTF-8 locale")
        try:
            for token in DEFAULT_TOKENS:
                self.assertEqual(libc.wcwidth(token.emoji), 2, token.name)
        finally:
            locale.setlocale(locale.LC_CTYPE, old)


if __name__ == "__main__":
    unittest.main()
