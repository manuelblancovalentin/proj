from __future__ import annotations

import os
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from proj import access
from proj.config import load_config
from proj.discovery import discover, resolve, scan
from proj.editor import (
    create_document,
    load_document,
    parse_value,
    set_dotted,
    write_document,
)
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

    def test_rejects_dependencies_in_the_generated_module_namespace(self):
        for module in ("project/demo", "project/other", "project"):
            self.metadata.write_text(
                project_toml(self.root).replace(
                    'compiler = ["gcc/14"]', f'compiler = ["{module}"]'
                )
            )
            with self.assertRaisesRegex(MetadataError, "cannot depend on itself"):
                load_project(self.metadata)
        self.metadata.write_text(
            project_toml(self.root).replace('project = ["shared/data"]', 'project = ["projects/data"]')
        )
        load_project(self.metadata)  # a different name is fine

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

    def test_user_variables_are_pushed_so_deactivation_restores_them(self):
        project = load_project(self.metadata)
        content = render(project)
        user_keys = sorted(project.environment)
        self.assertTrue(user_keys)
        for key in user_keys:
            self.assertIn(f'pushenv("{key}", ', content)
            self.assertNotIn(f'setenv("{key}", ', content)
        # proj's own markers are not the person's variables.
        self.assertIn('setenv("PROJ_ACTIVE", "demo")', content)

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


class SharingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "work"
        self.root.mkdir()
        self.private = self.base / "private"
        self.shared = self.base / "shared"
        self.site = self.base / "site.toml"
        self.site.write_text(
            f'schema = 1\nregistry = "{self.private}"\n'
            f'shared_registry = "{self.shared}"\ngroup = "staff"\n'
        )
        self.environment = {
            "PROJ_SITE_CONFIG": str(self.site),
            "PROJ_CONFIG": str(self.base / "user.toml"),
            "PROJ_CACHE_HOME": str(self.base / "cache"),
        }
        self.patch = patch.dict(os.environ, self.environment)
        self.patch.start()
        os.environ.pop("PROJ_HOME", None)
        os.environ.pop("PROJ_PROJECT_ROOTS", None)

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def write(self, registry: Path, name: str, description: str) -> Path:
        path = registry / name / "project.toml"
        create_document(path, name, self.root)
        data = load_document(path)
        data["project"]["description"] = description
        write_document(path, data)
        return path

    def test_user_configuration_overrides_site_configuration(self):
        Path(self.environment["PROJ_CONFIG"]).write_text(
            f'schema = 1\nregistry = "{self.base / "mine"}"\n'
        )
        config = load_config()
        self.assertEqual(config.registry, self.base / "mine")
        self.assertEqual(config.shared_registry, self.shared)
        self.assertEqual(config.group, "staff")
        self.assertEqual(config.project_roots[:2], (self.base / "mine", self.shared))

    def test_python_manager_is_configurable_and_validated(self):
        self.assertEqual(load_config().python_manager, "micromamba")
        Path(self.environment["PROJ_CONFIG"]).write_text(
            'schema = 1\npython_manager = "conda"\n'
        )
        self.assertEqual(load_config().python_manager, "conda")
        Path(self.environment["PROJ_CONFIG"]).write_text(
            'schema = 1\npython_manager = "pip"\n'
        )
        with self.assertRaises(ProjError):
            load_config()

    def test_unknown_configuration_keys_are_rejected(self):
        self.site.write_text("schema = 1\nregistyr = '/tmp'\n")
        with self.assertRaises(ProjError):
            load_config()

    def test_private_shadows_shared_and_invalid_documents_are_skipped(self):
        self.write(self.shared, "atlas", "shared")
        self.write(self.private, "atlas", "private")
        broken = self.shared / "broken" / "project.toml"
        broken.parent.mkdir(parents=True)
        broken.write_text("schema = 2\n")
        found = scan(load_config())
        self.assertEqual(found.projects["atlas"].description, "private")
        self.assertEqual([path for path, _ in found.problems], [broken.resolve()])
        with self.assertRaises(ProjError):
            resolve(load_config(), "broken")

    def test_world_writable_metadata_is_rejected(self):
        path = self.write(self.private, "open", "open")
        path.chmod(0o666)
        with self.assertRaises(MetadataError):
            load_project(path)

    def test_read_only_environment_names_its_owner(self):
        path = self.write(self.shared, "locked", "locked")
        project = load_project(path)
        path.parent.chmod(0o555)
        try:
            with self.assertRaisesRegex(ProjError, "belongs to"):
                access.require_writable(project)
        finally:
            path.parent.chmod(0o755)


if __name__ == "__main__":
    unittest.main()
