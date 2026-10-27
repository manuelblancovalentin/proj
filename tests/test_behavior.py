from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from proj.config import load_config
from proj.errors import ConfigError


class BehaviorSwitchTests(unittest.TestCase):
    def load(self, text):
        with tempfile.TemporaryDirectory() as directory:
            site = Path(directory) / "site.toml"
            site.write_text("schema = 1\n" + text)
            environment = {"PROJ_SITE_CONFIG": str(site), "PROJ_CONFIG": str(Path(directory) / "none.toml")}
            with patch.dict(os.environ, environment):
                return load_config()

    def test_restore_login_modules_defaults_on_and_can_be_switched_off(self):
        self.assertTrue(self.load("").restore_login_modules)
        self.assertFalse(self.load("[behavior]\nrestore_login_modules = false\n").restore_login_modules)

    def test_a_switch_must_be_a_real_boolean_and_a_typo_is_refused(self):
        for text in (
            '[behavior]\nrestore_login_modules = "false"\n',
            "[behavior]\nrestore_login_module = false\n",
            "[behavior]\nchange_directory = 0\n",
        ):
            with self.assertRaises(ConfigError, msg=text):
                self.load(text)
