from __future__ import annotations

import json
import os
import re
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from proj import lmod
from proj.config import Config, load_config
from proj.discovery import scan
from proj.errors import ConfigError
from proj.editor import create_document, load_document, set_dotted, write_document
from proj.export import SCHEMA, catalog_document, environments_snapshot, select_projects
from proj.lmod import ModuleEntry


def entry(name, category="application", group="", versions=("1.0",), default=None):
    return ModuleEntry(name, tuple(versions), default or versions[-1], category, "", group)


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.home = base / "home"
        self.roots = {name: base / "work" / name for name in ("atlas", "birch")}
        for root in self.roots.values():
            root.mkdir(parents=True)
        self.patch = patch.dict(
            os.environ,
            {
                "PROJ_HOME": str(self.home),
                "PROJ_CACHE_HOME": str(base / "cache"),
                "PROJ_CONFIG": str(base / "none.toml"),
                "PROJ_SITE_CONFIG": str(base / "none.toml"),
            },
        )
        self.patch.start()
        os.environ.pop("PROJ_PROJECT_ROOTS", None)
        self.make("atlas", {
            "project": ["site-defaults/2", "pdk-demo/3.1"],
            "application": ["simtool", "suite-lab/5"],
            "compiler": ["gcc/13.3.0"],
        })
        self.make("birch", {"toolchain": ["node/24.21.0"]})
        self.config = load_config()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def make(self, name, modules):
        path = self.home / "envs" / name / "project.toml"
        create_document(path, name, self.roots[name])
        data = load_document(path)
        for category, specs in modules.items():
            set_dotted(data, f"modules.{category}", specs)
        write_document(path, data)

    def snapshot(self, **options):
        found = scan(self.config)
        return environments_snapshot(self.config, found.projects.values(), len(found.problems), **options)

    def test_the_document_has_stable_keys(self):
        document = self.snapshot()
        self.assertEqual(document["schema"], SCHEMA)
        self.assertEqual(set(document), {"schema", "proj_version", "generated", "skipped", "unreadable", "environments"})
        self.assertRegex(document["generated"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        keys = {"name", "scope", "project_root", "bundles", "modules", "library_bundles", "updated"}
        for environment in document["environments"]:
            self.assertEqual(set(environment), keys)
            self.assertRegex(environment["updated"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual([e["name"] for e in document["environments"]], ["atlas", "birch"])
        json.dumps(document)  # serialisable

    def link(self, name, value, manager=None):
        path = self.home / "envs" / name / "project.toml"
        data = load_document(path)
        set_dotted(data, "python.environment", value)
        if manager:
            set_dotted(data, "python.manager", manager)
        write_document(path, data)

    def test_python_is_left_out_when_no_environment_is_linked(self):
        for environment in self.snapshot()["environments"]:
            self.assertNotIn("python", environment)
        self.assertEqual(SCHEMA, 1)

    def test_python_reports_what_the_metadata_says_and_nothing_more(self):
        real = Path(self.temp.name) / "mamba" / "envs" / "lab-env"  # does not exist: nothing is read
        alias = Path(self.temp.name) / "alias"
        alias.symlink_to(real)
        self.link("atlas", str(alias))
        self.link("birch", "lab-name", manager="conda")
        with patch("proj.python_envs.subprocess.run", side_effect=AssertionError("ran a manager")):
            found = {e["name"]: e for e in self.snapshot()["environments"]}
        self.assertEqual(
            found["atlas"]["python"],
            {"manager": "micromamba", "environment": "lab-env", "prefix": str(real.resolve())},
        )
        self.assertEqual(found["birch"]["python"], {"manager": "conda", "environment": "lab-name"})
        self.assertEqual(
            list(found["atlas"]),
            ["name", "scope", "project_root", "bundles", "modules", "library_bundles", "python", "updated"],
        )
        self.assertEqual(self.snapshot()["schema"], 1)
        json.dumps(found)

    def test_bundles_modules_and_library_names_are_kept_apart(self):
        atlas = self.snapshot()["environments"][0]
        self.assertEqual(atlas["bundles"], ["site-defaults"])
        self.assertEqual(atlas["library_bundles"], ["pdk-demo"])
        self.assertEqual(
            atlas["modules"],
            [
                {"name": "simtool", "version": None},
                {"name": "suite-lab", "version": "5"},
                {"name": "gcc", "version": "13.3.0"},
            ],
        )

    def test_no_library_version_and_no_user_appear_anywhere(self):
        text = json.dumps(self.snapshot())
        self.assertNotIn("3.1", text)  # the pinned library version
        self.assertNotIn(os.environ.get("USER", "\0"), text)
        self.assertNotIn("owner", text)
        self.assertEqual(self.snapshot()["environments"][0]["project_root"], str(self.roots["atlas"].resolve()))

    def test_library_prefixes_are_configurable(self):
        site = Path(self.temp.name) / "site.toml"
        site.write_text('schema = 1\nlibrary_prefixes = ["site-", "simtool"]\n')
        with patch.dict(os.environ, {"PROJ_SITE_CONFIG": str(site)}):
            config = load_config()
        found = scan(config)
        atlas = environments_snapshot(config, found.projects.values())["environments"][0]
        self.assertEqual(atlas["bundles"], ["pdk-demo"])
        self.assertEqual(atlas["library_bundles"], ["site-defaults", "simtool"])
        self.assertNotIn({"name": "simtool", "version": None}, atlas["modules"])
        self.assertTrue(config.is_library("site-x"))
        self.assertFalse(config.is_library("suite-x"))

    def test_library_names_mark_a_module_by_its_exact_name(self):
        site = Path(self.temp.name) / "names.toml"
        site.write_text('schema = 1\nlibrary_names = ["simtool", "suite-lab"]\n')
        with patch.dict(os.environ, {"PROJ_SITE_CONFIG": str(site)}):
            config = load_config()
        self.assertTrue(config.is_library("simtool"))
        self.assertTrue(config.is_library("pdk-demo"))  # the default prefix still applies
        self.assertFalse(config.is_library("simtool-extra"))  # exact names, not prefixes
        atlas = environments_snapshot(config, scan(config).projects.values())["environments"][0]
        self.assertEqual(atlas["library_bundles"], ["pdk-demo", "simtool", "suite-lab"])
        self.assertEqual(atlas["modules"], [{"name": "gcc", "version": "13.3.0"}])
        for bad in ('library_names = "x"', 'library_names = ["simtool/1.0"]', 'library_names = [""]'):
            site.write_text("schema = 1\n" + bad + "\n")
            with patch.dict(os.environ, {"PROJ_SITE_CONFIG": str(site)}):
                with self.assertRaises(ConfigError):
                    load_config()

    def test_scope_and_under_filters(self):
        self.assertEqual(self.snapshot(scope="private")["environments"].__len__(), 2)
        self.assertEqual(self.snapshot(scope="shared")["environments"], [])
        under = self.snapshot(under=[str(self.roots["birch"])])["environments"]
        self.assertEqual([e["name"] for e in under], ["birch"])
        self.assertEqual(self.snapshot(under=[str(self.roots["atlas"].parent)])["environments"].__len__(), 2)
        self.assertEqual(self.snapshot(under=["/nonexistent-folder"])["environments"], [])
        chosen = select_projects(self.config, scan(self.config).projects.values(), under=[str(self.roots["atlas"])])
        self.assertEqual([p.name for p in chosen], ["atlas"])

    def test_invalid_documents_are_counted_not_listed(self):
        broken = self.home / "envs" / "broken" / "project.toml"
        broken.parent.mkdir(parents=True)
        broken.write_text("schema = 2\n")
        document = self.snapshot()
        self.assertEqual(document["skipped"], 1)
        self.assertNotIn("broken", json.dumps(document))


class NoHomeTests(unittest.TestCase):
    def test_configuration_loads_with_no_home_and_no_passwd_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            site = Path(directory) / "site.toml"
            site.write_text(f'schema = 1\nshared_registry = "{directory}/shared"\ngroup = "lab"\n')
            environment = {"PROJ_SITE_CONFIG": str(site), "PROJ_CONFIG": str(Path(directory) / "none.toml")}
            with patch.dict(os.environ, environment, clear=True), patch(
                "pathlib.Path.home", side_effect=RuntimeError("Could not determine home directory.")
            ):
                config = load_config()
            self.assertEqual(config.shared_registry, Path(directory, "shared").resolve())
            self.assertFalse(config.registry.exists())


class CatalogTests(unittest.TestCase):
    ENTRIES = [
        entry("simtool", "application", "", ("20.1", "21.1")),
        entry("gated", "application", "eda", ("1.0",)),
        entry("node", "", "", ("24.21.0",)),
        entry("odd", "library"),
        entry("pdk-demo", "project", "demo"),
        entry("pdk-open", "project", "any"),
        entry("site-defaults", "project", "any", ("2",)),
        entry("suite-lab", "application", "lab", ("5",)),
    ]
    CONTENTS = {
        "suite-lab": ["simtool", "pdk-demo", "gated"],
        "site-defaults": [],
    }

    def document(self, groups):
        config = Config(
            proj_home=Path("/x"), registry=Path("/x"), project_roots=(), cache_home=Path("/x"),
            module_cache=Path("/x"),
        )
        return catalog_document(config, self.ENTRIES, groups, lambda name: self.CONTENTS.get(name))

    def test_libraries_are_counted_and_never_listed(self):
        document = self.document({"eda"})
        self.assertEqual(document["libraries_omitted"], 2)
        self.assertNotIn("pdk-", json.dumps(document))
        self.assertNotIn("demo", json.dumps(document))

    def test_modules_carry_group_and_access(self):
        by_name = {m["name"]: m for m in self.document({"eda"})["modules"]}
        self.assertEqual(by_name["simtool"], {
            "name": "simtool", "category": "application", "versions": ["20.1", "21.1"],
            "default": "21.1", "groups": [], "allowed": True,
        })
        self.assertEqual((by_name["gated"]["groups"], by_name["gated"]["allowed"]), (["eda"], True))
        self.assertFalse({m["name"]: m for m in self.document(set())["modules"]}["gated"]["allowed"])
        self.assertIsNone(by_name["node"]["category"])
        self.assertIsNone(by_name["odd"]["category"])  # an unknown category is not passed on

    def test_suites_and_bundles_list_member_names_only(self):
        sets = {s["name"]: s for s in self.document({"lab"})["suites"]}
        suite = sets["lab"]
        self.assertEqual((suite["kind"], suite["module"], suite["allowed"]), ("suite", "suite-lab", True))
        self.assertEqual(suite["contains"], ["simtool", "gated"])  # the library member is withheld
        self.assertEqual(suite["withheld"], 1)
        self.assertEqual(sets["site-defaults"]["kind"], "bundle")
        self.assertEqual(sets["site-defaults"]["contains"], [])
        self.assertFalse(self.document(set())["suites"][1]["allowed"])
        self.assertEqual(set(self.document(set())), {
            "schema", "proj_version", "generated", "modules", "suites", "libraries_omitted"})

    def test_a_library_named_exactly_is_withheld_like_a_prefixed_one(self):
        config = Config(
            proj_home=Path("/x"), registry=Path("/x"), project_roots=(), cache_home=Path("/x"),
            module_cache=Path("/x"), library_names=("iplibs",),
        )
        entries = [*self.ENTRIES, entry("iplibs", "project", "any"), entry("iplibs-extra")]
        contents = {"suite-lab": ["simtool", "iplibs", "iplibs-extra"]}
        document = catalog_document(config, entries, {"lab"}, lambda name: contents.get(name))
        self.assertEqual(document["libraries_omitted"], 3)
        self.assertNotIn("iplibs\"", json.dumps(document))  # only the unrelated name remains
        suite = {s["name"]: s for s in document["suites"]}["lab"]
        self.assertEqual(suite["contains"], ["simtool", "iplibs-extra"])
        self.assertEqual(suite["withheld"], 1)

    def test_unreadable_contents_are_null(self):
        document = catalog_document(
            Config(
                proj_home=Path("/x"), registry=Path("/x"), project_roots=(), cache_home=Path("/x"),
                module_cache=Path("/x"),
            ),
            self.ENTRIES, set(), lambda name: None,
        )
        self.assertIsNone(document["suites"][0]["contains"])


class MembersTests(unittest.TestCase):
    def test_only_dependency_commands_are_read_from_module_show(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "lmod"
            script.write_text(
                "#!/bin/sh\nshift\ncat >&2 <<'EOF'\n"
                "----\n   /mods/suite-lab/5.lua:\n----\n"
                'whatis("Category: application")\n'
                'setenv("SECRET_HOME","/very/private/place")\n'
                'depends_on("simtool/21.1","placer")\n'
                'load("runner")\n'
                "try_load('probe/23.1')\n"
                'depends_on("simtool/20.1")\n'
                "EOF\n"
            )
            script.chmod(script.stat().st_mode | stat.S_IXUSR)
            with patch.dict(os.environ, {"LMOD_CMD": str(script)}):
                self.assertEqual(lmod.members("suite-lab"), ["simtool", "placer", "runner", "probe"])

    def test_a_module_lmod_cannot_show_is_none(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "lmod"
            script.write_text("#!/bin/sh\necho 'Failed to find the module' >&2\n")
            script.chmod(script.stat().st_mode | stat.S_IXUSR)
            with patch.dict(os.environ, {"LMOD_CMD": str(script)}):
                self.assertIsNone(lmod.members("nosuch"))


if __name__ == "__main__":
    unittest.main()
