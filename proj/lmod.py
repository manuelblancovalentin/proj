"""Queries against the live Lmod installation."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .errors import ProjError

CATEGORIES = ("compiler", "toolchain", "application", "project")
# The module namespace proj uses for the modules it generates from environments.
RESERVED = "project"
_WHATIS_LINE = re.compile(r"^(\S+)\s+:\s?(.*)$")
_BLOCK_HEADER = re.compile(r"^\s+/.*:$")
_FAMILY = re.compile(r"""^family\(\s*["']([^"']+)["']\s*\)""")


@dataclass(frozen=True)
class ModuleEntry:
    """One module name with its versions, as Lmod can load it."""

    name: str
    versions: tuple[str, ...]
    default: str | None
    category: str  # one of CATEGORIES, another tag a modulefile chose, or ""
    description: str
    group: str = ""  # Unix group(s) a modulefile requires, "any", or "" when untagged


def lmod_command() -> str | None:
    command = os.environ.get("LMOD_CMD")
    if command and os.access(command, os.X_OK):
        return command
    return shutil.which("lmod")


def _lmod(*arguments: str) -> str:
    """Run an Lmod sub-command and return its message output (stderr)."""
    command = lmod_command()
    if not command:
        raise ProjError("Lmod is not available; set LMOD_CMD or initialize Lmod")
    completed = subprocess.run(
        [command, "bash", *arguments],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        raise ProjError(completed.stderr.strip() or f"module {' '.join(arguments)} failed")
    return completed.stderr


def parse_avail(text: str, exclude: Iterable[Path] = ()) -> dict[str, list[str]]:
    """Map module names to versions from `module --terse avail` output.

    The output is a sequence of "<directory>:" headers, "name/" lines for
    directories of versions, and one "name/version" line per module. Modules
    listed under an excluded directory (proj's own generated modules) are
    skipped.
    """
    skipped = [Path(path) for path in exclude]
    modules: dict[str, list[str]] = {}
    skipping = False
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.endswith(":"):
            directory = Path(line[:-1])
            skipping = any(directory == path or path in directory.parents for path in skipped)
            continue
        if skipping or line.endswith("/"):
            continue
        name, _, version = line.split()[0].partition("/")
        versions = modules.setdefault(name, [])
        if version and version not in versions:
            versions.append(version)
    return modules


def parse_whatis(text: str) -> dict[str, list[str]]:
    """Map module names to their whatis strings from `module whatis` output."""
    result: dict[str, list[str]] = {}
    for line in text.splitlines():
        match = _WHATIS_LINE.match(line.strip())
        if match:
            name = match.group(1).partition("/")[0]
            result.setdefault(name, []).append(match.group(2).strip())
    return result


def _tag(whatis: list[str], key: str) -> str:
    prefix = key.lower() + ":"
    for text in whatis:
        if text.lower().startswith(prefix):
            return text[len(prefix):].strip()
    return ""


def catalog(exclude: Iterable[Path] = ()) -> list[ModuleEntry]:
    """Every module Lmod can load, with the Category its modulefile declares.

    A modulefile declares its category with `whatis("Category: toolchain")`;
    the default version's tag is used for the whole module name.
    """
    exclude = tuple(exclude)
    versions = parse_avail(_lmod("--terse", "avail"), exclude)
    versions.pop(RESERVED, None)
    defaults = parse_avail(_lmod("--terse", "--default", "avail"), exclude)
    whatis = parse_whatis(_lmod("whatis", *sorted(versions))) if versions else {}
    entries = []
    for name in sorted(versions):
        tags = whatis.get(name, [])
        default = (defaults.get(name) or [None])[0]
        description = _tag(tags, "Description") or _tag(tags, "Name")
        entries.append(
            ModuleEntry(
                name=name,
                versions=tuple(versions[name]),
                default=default or None,
                category=_tag(tags, "Category").lower(),
                description=description,
                group=_tag(tags, "Group"),
            )
        )
    return entries


def families(specs: Iterable[str]) -> dict[str, str]:
    """The Lmod family each module declares, found with `module show`.

    A module that is missing, or declares no family, is left out; so does
    everything if Lmod cannot answer, because families only refine a decision.
    """
    result: dict[str, str] = {}
    for spec in dict.fromkeys(specs):
        try:
            text = _lmod("show", spec)
        except ProjError:
            continue
        # The output is "<file>:" followed by the modulefile's commands.
        if not any(_BLOCK_HEADER.match(line) for line in text.splitlines()):
            continue
        for line in text.splitlines():
            match = _FAMILY.match(line.strip())
            if match:
                result[spec] = match.group(1)
                break
    return result
