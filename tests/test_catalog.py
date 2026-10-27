from __future__ import annotations

import os
import re
import stat
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from proj import lmod
from proj.render import Output, visible_length

AVAIL = """\
/opt/modulefiles:
gcc/
gcc/11.5.0
gcc/13.3.0
node/
node/24.21.0
solo
verilator/
verilator/5.039

/home/u/.cache/proj/modulefiles:
project/
project/atlas
"""
DEFAULTS = """\
/opt/modulefiles:
gcc/13.3.0
node/24.21.0
solo
verilator/5.039
/home/u/.cache/proj/modulefiles:
project/atlas
"""
WHATIS = """\
gcc/13.3.0          : Category: compiler
node/24.21.0        : Name: Node.js
node/24.21.0        : Version: 24.21.0
solo                : Category: Toolchain
solo                : Description: A module without versions
verilator/5.039     : Category: toolchain
"""


def fake_lmod(directory: Path) -> Path:
    """An executable that answers like `lmod bash ...` with canned messages."""
    script = directory / "lmod"
    script.write_text(
        "#!/bin/sh\n"
        "shift\n"  # the shell name
        'case "$*" in\n'
        f"  '--terse avail') cat >&2 <<'EOF'\n{AVAIL}EOF\n;;\n"
        f"  '--terse --default avail') cat >&2 <<'EOF'\n{DEFAULTS}EOF\n;;\n"
        f"  whatis*) cat >&2 <<'EOF'\n{WHATIS}EOF\n;;\n"
        "esac\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


class ParserTests(unittest.TestCase):
    def test_avail_groups_versions_and_skips_directories(self):
        modules = lmod.parse_avail(AVAIL)
        self.assertEqual(modules["gcc"], ["11.5.0", "13.3.0"])
        self.assertEqual(modules["solo"], [])
        self.assertIn("project", modules)

    def test_avail_excludes_proj_generated_modules(self):
        modules = lmod.parse_avail(AVAIL, [Path("/home/u/.cache/proj/modulefiles")])
        self.assertNotIn("project", modules)
        self.assertIn("gcc", modules)

    def test_whatis_lines_are_grouped_by_module_name(self):
        parsed = lmod.parse_whatis(WHATIS)
        self.assertEqual(parsed["node"], ["Name: Node.js", "Version: 24.21.0"])
        self.assertEqual(parsed["gcc"], ["Category: compiler"])


class CatalogTests(unittest.TestCase):
    def test_catalog_uses_modulefile_tags_defaults_and_descriptions(self):
        with tempfile.TemporaryDirectory() as directory:
            command = fake_lmod(Path(directory))
            with patch.dict(os.environ, {"LMOD_CMD": str(command)}):
                entries = {
                    entry.name: entry
                    for entry in lmod.catalog(exclude=[Path("/home/u/.cache/proj/modulefiles")])
                }
        self.assertEqual(sorted(entries), ["gcc", "node", "solo", "verilator"])
        self.assertEqual(entries["gcc"].category, "compiler")
        self.assertEqual(entries["gcc"].default, "13.3.0")
        self.assertEqual(entries["gcc"].versions, ("11.5.0", "13.3.0"))
        self.assertEqual(entries["node"].category, "")  # untagged
        self.assertEqual(entries["node"].description, "Node.js")
        self.assertEqual(entries["solo"].category, "toolchain")  # tags are case-insensitive
        self.assertEqual(entries["solo"].versions, ())
        self.assertEqual(entries["solo"].description, "A module without versions")

    def test_missing_lmod_is_a_clear_error(self):
        with patch.dict(os.environ, {"LMOD_CMD": "/nonexistent", "PATH": "/nonexistent"}):
            with self.assertRaisesRegex(Exception, "Lmod is not available"):
                lmod.catalog()


class RenderTests(unittest.TestCase):
    ROWS = [
        ("gcc", "11.5.0  13.3.0*  " + "9.5.0  " * 12, "atlas, birch"),
        ("node", "24.21.0*", ""),
    ]
    HEADERS = ("MODULE", "VERSIONS", "USED BY")

    def test_plain_output_is_aligned_columns(self):
        lines = Output(mode="never").table(self.HEADERS, [("gcc", "13.3.0*", "atlas")], title="T")
        self.assertEqual(
            lines,
            ["T", "MODULE  VERSIONS  USED BY", "------  --------  -------", "gcc     13.3.0*   atlas"],
        )

    def test_plain_table_without_title_matches_the_classic_layout(self):
        lines = Output(mode="never").table(("NAME", "ROOT"), [("a", "/x")])
        self.assertEqual(lines, ["NAME  ROOT", "----  ----", "a     /x"])

    def test_boxed_table_fits_the_width_and_aligns(self):
        for width in (60, 80, 120):
            for unicode in (True, False):
                out = Output(mode="always", width=width, unicode=unicode)
                lines = out.table(self.HEADERS, self.ROWS, title="Compilers (2)", flex=1)
                widths = {visible_length(line) for line in lines}
                self.assertEqual(len(widths), 1, (width, unicode, widths))
                self.assertLessEqual(widths.pop(), width)
                if unicode:
                    self.assertTrue(lines[0].startswith(("\x1b[2m╭", "╭")))

    def test_boxed_title_widens_a_narrow_table(self):
        out = Output(mode="always", width=100, unicode=True)
        lines = out.table(("A",), [("x",)], title="A rather long title", flex=0)
        self.assertEqual(len({visible_length(line) for line in lines}), 1)
        self.assertIn("A rather long title", re.sub(r"\x1b\[[0-9;]*m", "", lines[0]))

    def test_notes_wrap_only_on_a_terminal(self):
        text = "word " * 40
        self.assertEqual(Output(mode="never").note(text), text)
        wrapped = Output(mode="always", width=60).note(text)
        self.assertTrue(all(visible_length(line) <= 60 for line in wrapped.splitlines()))

    def test_no_color_disables_detection(self):
        class Terminal:
            encoding = "utf-8"

            def isatty(self):
                return True

        with patch.dict(os.environ, {"TERM": "xterm"}, clear=False):
            os.environ.pop("PROJ_COLOR", None)
            os.environ.pop("NO_COLOR", None)
            self.assertTrue(Output(stream=Terminal()).fancy)
            with patch.dict(os.environ, {"NO_COLOR": "1"}):
                self.assertFalse(Output(stream=Terminal()).fancy)


if __name__ == "__main__":
    unittest.main()
