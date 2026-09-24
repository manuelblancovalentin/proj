from __future__ import annotations

import os
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from proj.config import load_config
from proj.discovery import discover
from proj.editor import create_document, load_document, parse_value, set_dotted
from proj.errors import MetadataError
from proj.errors import ProjError
from proj.metadata import load_project
from proj.modulefile import materialize, render


def project_toml(root: Path, extra: str = "") -> str:
    return (
        textwrap.dedent(
            f"""
            schema = 1

            [project]
            name = "demo"
            description = "Demo project"
            root = "{root}"
            shell = "zsh"

            [python]
            manager = "micromamba"
            environment = "demo"

            [modules]
            project = ["shared/data"]
            toolchain = ["cmake/3.30"]
            application = []
            compiler = ["gcc/14"]

            [environment]
            DEMO_ROOT = "${{project.root}}"

            [paths]
            prepend = ["${{project.root}}/bin"]

            [aliases]
            demo-home = "cd ${{project.root}}"

            [commands.build]
            description = "Build"
            command = ["./build"]
            """
        )
        + extra
    )


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "projects" / "demo"
        self.root.mkdir(parents=True)
        self.metadata = self.root / "project.toml"
        self.metadata.write_text(project_toml(self.root))

    def tearDown(self):
        self.temp.cleanup()

    def test_load_and_interpolate(self):
        project = load_project(self.metadata)
        self.assertEqual(project.name, "demo")
        self.assertEqual(project.expand("${project.root}/bin"), str(self.root / "bin"))
        self.assertIn("build", project.commands)

    def test_discovery_and_duplicate_validation(self):
        environment = {
            "PROJ_HOME": str(Path(self.temp.name) / "proj-home"),
            "PROJ_PROJECT_ROOTS": str(self.root.parent),
            "PROJ_CACHE_HOME": str(Path(self.temp.name) / "cache"),
        }
        with patch.dict(os.environ, environment, clear=False):
            projects = discover(load_config())
        self.assertEqual(list(projects), ["demo"])

    def test_rejects_unknown_interpolation(self):
        self.metadata.write_text(
            project_toml(self.root).replace(
                'DEMO_ROOT = "${project.root}"',
                'DEMO_ROOT = "${shell.command}"',
            )
        )
        with self.assertRaises(MetadataError):
            load_project(self.metadata)

    def test_rejects_path_outside_project(self):
        self.metadata.write_text(
            project_toml(self.root).replace(
                'prepend = ["${project.root}/bin"]',
                'prepend = ["/tmp/unowned"]',
            )
        )
        with self.assertRaises(MetadataError):
            load_project(self.metadata)

    def test_modulefile_uses_lmod_primitives(self):
        project = load_project(self.metadata)
        content = render(project)
        self.assertIn('family("project")', content)
        self.assertIn('depends_on("gcc/14")', content)
        self.assertIn('setenv("PROJ_ACTIVE", "demo")', content)
        self.assertIn('set_alias("demo-home"', content)

    def test_materialization_is_idempotent(self):
        environment = {
            "PROJ_HOME": str(Path(self.temp.name) / "proj-home"),
            "PROJ_PROJECT_ROOTS": str(self.root.parent),
            "PROJ_CACHE_HOME": str(Path(self.temp.name) / "cache"),
        }
        with patch.dict(os.environ, environment, clear=False):
            config = load_config()
            project = load_project(self.metadata)
            output, first_changed = materialize(config, project)
            same_output, second_changed = materialize(config, project)
        self.assertTrue(first_changed)
        self.assertFalse(second_changed)
        self.assertEqual(output, same_output)

    def test_managed_starter_is_valid_and_keeps_examples_commented(self):
        registry = Path(self.temp.name) / "home" / "envs" / "starter"
        metadata = registry / "project.toml"
        create_document(metadata, "starter", self.root)
        content = metadata.read_text()
        project = load_project(metadata)
        self.assertEqual(project.name, "starter")
        self.assertEqual(project.description, "starter")
        self.assertEqual(project.python_manager, "micromamba")
        self.assertIn('# description = "Short project description"', content)
        self.assertIn('# environment = "environment-name"', content)

    def test_config_values_and_key_validation(self):
        data = {"project": {"name": "demo", "root": str(self.root)}}
        set_dotted(data, "project.description", parse_value("Useful project"))
        set_dotted(data, "environment.DEMO_MODE", parse_value('"development"'))
        self.assertEqual(data["project"]["description"], "Useful project")
        self.assertEqual(data["environment"]["DEMO_MODE"], "development")
        with self.assertRaises(ProjError):
            set_dotted(data, "project.descriptino", "typo")


if __name__ == "__main__":
    unittest.main()
