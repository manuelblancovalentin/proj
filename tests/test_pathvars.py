from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from proj.editor import load_document, set_dotted, update_document
from proj.errors import MetadataError, ProjError
from proj.metadata import load_project
from proj.modulefile import render


class PathVariableTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "projects" / "atlas"
        self.root.mkdir(parents=True)
        self.metadata = self.root / "project.toml"
        self.write()

    def tearDown(self):
        self.temp.cleanup()

    def write(self, extra: str = "", environment: str = ""):
        self.metadata.write_text(
            textwrap.dedent(
                f"""
                schema = 1

                [project]
                name = "atlas"
                root = "{self.root}"

                [environment]
                {environment}

                [environment_paths.PYTHONPATH]
                prepend = ["${{user.home}}/atlas/repo/src", "${{user.home}}/atlas/repo/extra"]
                append = ["${{project.root}}/lib"]
                """
            )
            + extra
        )

    def test_loaded_and_expanded(self):
        project = load_project(self.metadata)
        entries = project.environment_paths["PYTHONPATH"]
        self.assertEqual(len(entries.prepend), 2)
        self.assertEqual(entries.append, ("${project.root}/lib",))

    def test_module_adds_existing_folders_only_with_undo_primitives(self):
        content = render(load_project(self.metadata))
        home = str(Path.home())
        src, extra = f'"{home}/atlas/repo/src"', f'"{home}/atlas/repo/extra"'
        self.assertIn(f'if isDir({src}) then prepend_path("PYTHONPATH", {src}) end', content)
        self.assertIn('append_path("PYTHONPATH", ', content)
        self.assertNotIn('setenv("PYTHONPATH"', content)
        self.assertNotIn('pushenv("PYTHONPATH"', content)
        # The first entry listed ends up first: Lmod stacks prepends, so it goes last.
        self.assertLess(content.index(extra), content.index(src))

    def test_entries_must_expand_to_one_absolute_path(self):
        for bad in ('"relative/dir"', '"/a:/b"', '"${user.home}/x\\ny"'):
            self.write()
            text = self.metadata.read_text().replace(
                '"${user.home}/atlas/repo/src"', bad
            )
            self.metadata.write_text(text)
            with self.assertRaises(MetadataError, msg=bad):
                load_project(self.metadata)

    def test_unknown_interpolation_and_fields_are_rejected(self):
        self.metadata.write_text(
            self.metadata.read_text().replace("user.home", "shell.command", 1)
        )
        with self.assertRaises(MetadataError):
            load_project(self.metadata)
        self.write(extra='\n[environment_paths.PATH]\nfront = ["/a"]\n')
        with self.assertRaises(MetadataError):
            load_project(self.metadata)

    def test_reserved_and_duplicate_variables_are_rejected(self):
        self.write(extra='\n[environment_paths.PROJ_ROOT]\nprepend = ["/a"]\n')
        with self.assertRaises(MetadataError):
            load_project(self.metadata)
        self.write(environment='PYTHONPATH = "/x"')
        with self.assertRaises(MetadataError):
            load_project(self.metadata)

    def test_config_sets_and_rewrites_without_losing_the_table(self):
        project = load_project(self.metadata)
        update_document(
            project,
            lambda data: set_dotted(
                data, "environment_paths.PATH.prepend", ["${user.home}/atlas/bin"]
            ),
        )
        document = load_document(self.metadata)
        self.assertEqual(document["environment_paths"]["PATH"]["prepend"], ["${user.home}/atlas/bin"])
        self.assertEqual(len(document["environment_paths"]["PYTHONPATH"]["prepend"]), 2)
        with self.assertRaises(ProjError):
            set_dotted(document, "environment_paths.PATH.front", ["/a"])
        with self.assertRaises(ProjError):
            set_dotted(document, "environment_paths.PATH", ["/a"])


if __name__ == "__main__":
    unittest.main()
