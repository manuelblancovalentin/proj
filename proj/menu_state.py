"""Editing state behind `proj configmenu`, independent of any UI library."""

from __future__ import annotations

import copy
import difflib
import os
import shlex
import tempfile
from pathlib import Path

from . import access, python_envs
from .config import Config
from .editor import load_document, render_document, update_document
from .errors import ProjError
from .lmod import available_modules
from .metadata import MODULE_CATEGORIES, PYTHON_MANAGERS, Project, load_project

HOOK_PHASES = ("startup", "shutdown")


class MenuState:
    """A working copy of one environment's document.

    Edits change only the copy; `preview` renders it exactly as it will be
    written, and `save` writes it through the same validated, atomic path as
    `proj config`.
    """

    def __init__(self, config: Config, project: Project):
        self.config = config
        self.project = project
        self.data = load_document(project.metadata_path)
        self.saved_text = render_document(self.data)
        try:
            access.require_writable(project)
            self.read_only_reason = None
        except ProjError as exc:
            self.read_only_reason = str(exc)

    # --- identity -------------------------------------------------------

    @property
    def name(self) -> str:
        return self.project.name

    def identity(self) -> list[tuple[str, str]]:
        active = os.environ.get("PROJ_ACTIVE") == self.name
        return [
            ("Name", self.name),
            ("Scope", access.describe_scope(self.config, self.project)),
            ("Owner", access.project_owner(self.project)),
            ("Metadata", str(self.project.metadata_path)),
            ("Active here", "yes" if active else "no"),
        ]

    # --- reading --------------------------------------------------------

    def _section(self, name: str) -> dict:
        return self.data.setdefault(name, {})

    @property
    def description(self) -> str:
        return self.data.get("project", {}).get("description", "")

    @property
    def root(self) -> str:
        return self.data.get("project", {}).get("root", "")

    @property
    def manager(self) -> str:
        return self.data.get("python", {}).get("manager") or self.config.python_manager

    @property
    def python_environment(self) -> str:
        return self.data.get("python", {}).get("environment", "")

    def hooks(self, phase: str) -> list[list[str]]:
        return [list(argv) for argv in self.data.get("hooks", {}).get(phase, [])]

    def modules(self, category: str) -> list[str]:
        return list(self.data.get("modules", {}).get(category, []))

    # --- editing --------------------------------------------------------

    def set_description(self, value: str) -> None:
        value = value.strip()
        if value:
            self._section("project")["description"] = value
        else:
            self._section("project").pop("description", None)

    def set_root(self, value: str) -> None:
        path = Path(os.path.expanduser(value.strip())).resolve()
        if not path.is_dir():
            raise ProjError(f"not a directory: {path}")
        self._section("project")["root"] = str(path)

    def set_manager(self, manager: str) -> None:
        if manager not in PYTHON_MANAGERS:
            raise ProjError("manager must be one of: " + ", ".join(PYTHON_MANAGERS))
        self._section("python")["manager"] = manager

    def set_python_environment(self, name: str | None, prefix: Path | None = None) -> None:
        python = self._section("python")
        if not name:
            python.pop("environment", None)
            return
        python.setdefault("manager", self.manager)
        # Shared environments record the prefix so every member activates the
        # same environment, exactly as `proj set-python-env` does.
        shared = access.scope(self.config, self.project) == "shared"
        python["environment"] = str(prefix) if shared and prefix else name

    def set_hooks(self, phase: str, hooks: list[list[str]]) -> None:
        if phase not in HOOK_PHASES:
            raise ProjError(f"unknown hook phase {phase!r}")
        section = self._section("hooks")
        if hooks:
            section[phase] = [list(argv) for argv in hooks]
        else:
            section.pop(phase, None)

    def set_modules(self, category: str, modules: list[str]) -> None:
        if category not in MODULE_CATEGORIES:
            raise ProjError(f"unknown module category {category!r}")
        section = self._section("modules")
        if modules:
            section[category] = list(dict.fromkeys(modules))
        else:
            section.pop(category, None)

    # --- rendering, validation, saving ----------------------------------

    def preview(self) -> str:
        return render_document(self.data)

    @property
    def dirty(self) -> bool:
        return self.preview() != self.saved_text

    def changed_lines(self) -> set[int]:
        """1-based line numbers of the preview that differ from the file."""
        changed = set()
        matcher = difflib.SequenceMatcher(
            a=self.saved_text.splitlines(), b=self.preview().splitlines()
        )
        for tag, _a1, _a2, b1, b2 in matcher.get_opcodes():
            if tag != "equal":
                changed.update(range(b1 + 1, b2 + 1))
        return changed

    def validate(self) -> str | None:
        """None when the working copy would load, else the problem."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / self.name / "project.toml"
            path.parent.mkdir()
            path.write_text(self.preview())
            try:
                load_project(path)
            except ProjError as exc:
                return str(exc).replace(str(path), "project.toml")
        return None

    def save(self) -> None:
        if self.read_only_reason:
            raise ProjError(self.read_only_reason)
        problem = self.validate()
        if problem:
            raise ProjError(problem)
        snapshot = copy.deepcopy(self.data)

        def replace(document: dict) -> None:
            document.clear()
            document.update(snapshot)

        update_document(self.project, replace)
        self.saved_text = self.preview()

    # --- discovery (slow; the UI runs these in worker threads) ----------

    @staticmethod
    def scan_managers() -> dict[str, str | None]:
        return {manager: python_envs.executable(manager) for manager in PYTHON_MANAGERS}

    def scan_python_environments(self) -> dict[str, Path]:
        return python_envs.environments(self.manager)

    @staticmethod
    def scan_modules() -> list[str]:
        return available_modules()


def format_hook(argv: list[str]) -> str:
    return shlex.join(argv)


def parse_hook(text: str) -> list[str]:
    try:
        argv = shlex.split(text)
    except ValueError as exc:
        raise ProjError(f"cannot parse command: {exc}") from exc
    if not argv:
        raise ProjError("a hook needs a command")
    return argv
