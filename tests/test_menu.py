"""Headless tests of `proj configmenu`, run with the menu's own interpreter.

Skipped where Textual is not installed (for example under /usr/bin/python3);
tests/run executes them with libexec/menu/bin/python when it exists.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import textual  # noqa: F401
except ImportError:  # pragma: no cover - depends on the interpreter
    textual = None

from proj.config import load_config
from proj.discovery import resolve
from proj.editor import create_document, load_document

if textual:
    from proj.menu import ENTRIES, ConfigMenu, LeaveDialog, ModulesDialog, TextDialog
    from proj.menu_state import MenuState

INDEX = {key: index for index, (key, _title) in enumerate(ENTRIES)} if textual else {}


@unittest.skipUnless(textual, "Textual is not installed for this interpreter")
class ConfigMenuTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.root = base / "work"
        self.root.mkdir()
        self.metadata = base / "home" / "envs" / "atlas" / "project.toml"
        create_document(self.metadata, "atlas", self.root)
        self.patch = patch.dict(
            os.environ,
            {
                "PROJ_HOME": str(base / "home"),
                "PROJ_CACHE_HOME": str(base / "cache"),
                "PROJ_CONFIG": str(base / "none.toml"),
                "PROJ_SITE_CONFIG": str(base / "none.toml"),
            },
        )
        self.patch.start()
        os.environ.pop("PROJ_ACTIVE", None)
        config = load_config()
        self.state = MenuState(config, resolve(config, "atlas"))
        self.state.scan_modules = lambda: ["cmake/3.30", "gcc/14", "ninja/1.12"]
        self.state.scan_managers = lambda: {"micromamba": None, "conda": "/opt/conda/bin/conda", "mamba": None}
        self.state.scan_python_environments = lambda: {
            "base": Path("/opt/conda"),
            "ml": Path("/opt/conda/envs/ml"),
        }
        self.app = ConfigMenu(self.state)

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    async def open_entry(self, pilot, key):
        self.app.query_one("#entries").index = INDEX[key]
        await pilot.press("enter")
        await pilot.pause()

    async def settle(self, pilot):
        await self.app.workers.wait_for_complete()
        await pilot.pause()

    async def test_description_dialog_applies_and_escape_discards(self):
        async with self.app.run_test(size=(120, 40)) as pilot:
            await self.open_entry(pilot, "description")
            self.assertIsInstance(self.app.screen, TextDialog)
            await pilot.press(*"Draft", "escape")
            await pilot.pause()
            self.assertIs(self.app.screen, self.app.screen_stack[0])
            self.assertEqual(self.state.description, "")
            await self.open_entry(pilot, "description")
            await pilot.press(*"Atlas simulation", "enter")
            await pilot.pause()
            self.assertEqual(self.state.description, "Atlas simulation")
            self.assertIn('description = "Atlas simulation"', self.state.preview())
            self.assertTrue(self.state.dirty)

    async def test_escape_with_unsaved_changes_asks_and_defaults_to_stay(self):
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.state.set_description("changed")
            await pilot.press("escape")
            await pilot.pause()
            self.assertIsInstance(self.app.screen, LeaveDialog)
            await pilot.press("escape")  # Escape in the question means stay.
            await pilot.pause()
            self.assertIs(self.app.screen, self.app.screen_stack[0])
            self.assertTrue(self.app.is_running)
            await pilot.press("escape", "enter")  # Enter defaults to stay too.
            await pilot.pause()
            self.assertIs(self.app.screen, self.app.screen_stack[0])
            self.assertTrue(self.app.is_running)
            await pilot.press("escape")
            await pilot.pause()
            await pilot.click("#discard")
            await pilot.pause()
        self.assertNotIn("changed", self.metadata.read_text())

    async def test_escape_without_changes_quits(self):
        async with self.app.run_test(size=(120, 40)) as pilot:
            await pilot.press("escape")
            await pilot.pause()
            self.assertFalse(self.app.is_running)

    async def test_save_writes_a_valid_document(self):
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.state.set_description("Saved description")
            await pilot.press("ctrl+s")
            await pilot.pause()
            self.assertFalse(self.state.dirty)
        self.assertEqual(load_document(self.metadata)["project"]["description"], "Saved description")

    async def test_modules_dialog_filters_selects_and_adds_custom(self):
        async with self.app.run_test(size=(120, 40)) as pilot:
            await self.open_entry(pilot, "modules:toolchain")
            self.assertIsInstance(self.app.screen, ModulesDialog)
            await self.settle(pilot)
            await pilot.press(*"nin", "tab", "space")  # toggle the one match
            await pilot.pause()
            await pilot.click("#filter")
            self.app.screen.query_one("#filter").value = ""
            await pilot.press(*"cma", "enter")  # Enter picks the only match
            await pilot.press(*"site/tools", "enter")  # unknown: added as typed
            await pilot.pause()
            await pilot.click("#apply")
            await pilot.pause()
            self.assertEqual(
                self.state.modules("toolchain"), ["cmake/3.30", "ninja/1.12", "site/tools"]
            )

    async def test_python_environment_and_manager_dialogs(self):
        async with self.app.run_test(size=(120, 40)) as pilot:
            await self.open_entry(pilot, "manager")
            await self.settle(pilot)
            await pilot.press("down", "enter")  # micromamba, then conda
            await pilot.pause()
            self.assertEqual(self.state.manager, "conda")
            await self.open_entry(pilot, "python")
            await self.settle(pilot)
            await pilot.press("end", "enter")  # (none), base, ml
            await pilot.pause()
            self.assertEqual(self.state.python_environment, "ml")

    async def test_hooks_dialog_adds_and_removes(self):
        async with self.app.run_test(size=(120, 40)) as pilot:
            await self.open_entry(pilot, "hooks:startup")
            await pilot.press(*"./check --fast", "enter")
            await pilot.press(*"./second", "enter")
            await pilot.pause()
            await pilot.click("#apply")
            await pilot.pause()
            self.assertEqual(self.state.hooks("startup"), [["./check", "--fast"], ["./second"]])
            self.assertIsNone(self.state.validate())


@unittest.skipUnless(textual, "Textual is not installed for this interpreter")
class MenuStateTests(unittest.TestCase):
    def test_validation_reports_problems_without_touching_the_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "work"
            root.mkdir()
            metadata = Path(directory) / "home" / "envs" / "atlas" / "project.toml"
            create_document(metadata, "atlas", root)
            before = metadata.read_text()
            with patch.dict(os.environ, {"PROJ_HOME": str(Path(directory) / "home")}):
                config = load_config()
                state = MenuState(config, resolve(config, "atlas"))
                state.data.setdefault("paths", {})["prepend"] = ["/outside"]
                self.assertIn("escapes project root", state.validate())
                with self.assertRaises(Exception):
                    state.save()
            self.assertEqual(metadata.read_text(), before)


if __name__ == "__main__":
    unittest.main()
