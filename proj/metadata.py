from __future__ import annotations

import os
import re
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import MetadataError

NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
ENVIRONMENT_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
VARIABLE_RE = re.compile(r"\$\{([^}]+)\}")
MODULE_CATEGORIES = ("project", "toolchain", "application", "compiler")


@dataclass(frozen=True)
class Hook:
    argv: tuple[str, ...]


@dataclass(frozen=True)
class Command:
    description: str
    argv: tuple[str, ...]


@dataclass(frozen=True)
class Project:
    name: str
    description: str
    root: Path
    shell: str
    metadata_path: Path
    python_manager: str | None = None
    python_environment: str | None = None
    modules: dict[str, tuple[str, ...]] = field(default_factory=dict)
    environment: dict[str, str] = field(default_factory=dict)
    prepend_paths: tuple[str, ...] = ()
    aliases: dict[str, str] = field(default_factory=dict)
    startup_hooks: tuple[Hook, ...] = ()
    shutdown_hooks: tuple[Hook, ...] = ()
    commands: dict[str, Command] = field(default_factory=dict)

    @property
    def module_name(self) -> str:
        return f"project/{self.name}"

    def context(self) -> dict[str, str]:
        return {
            "project.name": self.name,
            "project.root": str(self.root),
            "project.metadata": str(self.metadata_path),
            "user.home": str(Path.home()),
        }

    def expand(self, value: str) -> str:
        context = self.context()

        def replace(match: re.Match[str]) -> str:
            key = match.group(1)
            if key not in context:
                raise MetadataError(
                    f"{self.metadata_path}: unsupported interpolation ${{{key}}}"
                )
            return context[key]

        return VARIABLE_RE.sub(replace, value)


def _table(data: dict[str, Any], key: str, source: Path) -> dict[str, Any]:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise MetadataError(f"{source}: [{key}] must be a table")
    return value


def _string(table: dict[str, Any], key: str, source: Path, required=False):
    value = table.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value:
        raise MetadataError(f"{source}: {key} must be a non-empty string")
    return value


def _string_list(value: Any, label: str, source: Path) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise MetadataError(f"{source}: {label} must be an array of strings")
    return tuple(value)


def _hooks(value: Any, label: str, source: Path) -> tuple[Hook, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise MetadataError(f"{source}: {label} must be an array")
    result = []
    for index, argv in enumerate(value):
        if not isinstance(argv, list) or not argv or not all(
            isinstance(item, str) and item for item in argv
        ):
            raise MetadataError(
                f"{source}: {label}[{index}] must be a non-empty argv array"
            )
        result.append(Hook(tuple(argv)))
    return tuple(result)


def load_project(metadata_path: Path) -> Project:
    metadata_path = metadata_path.resolve()
    try:
        with metadata_path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise MetadataError(f"cannot read {metadata_path}: {exc}") from exc

    if data.get("schema") != 1:
        raise MetadataError(f"{metadata_path}: schema must be 1")

    project_data = _table(data, "project", metadata_path)
    name = _string(project_data, "name", metadata_path, required=True)
    if not NAME_RE.fullmatch(name):
        raise MetadataError(f"{metadata_path}: invalid project name {name!r}")
    description = _string(project_data, "description", metadata_path) or name
    raw_root = _string(project_data, "root", metadata_path, required=True)
    root = Path(os.path.expanduser(raw_root)).resolve()
    if not root.is_dir():
        raise MetadataError(f"{metadata_path}: project root does not exist: {root}")
    shell = _string(project_data, "shell", metadata_path) or "zsh"
    if shell != "zsh":
        raise MetadataError(f"{metadata_path}: only shell = 'zsh' is supported")
    python_data = _table(data, "python", metadata_path)
    python_manager = _string(python_data, "manager", metadata_path)
    python_environment = _string(python_data, "environment", metadata_path)
    if python_environment and not python_manager:
        python_manager = "micromamba"
    if python_manager and python_manager != "micromamba":
        raise MetadataError(f"{metadata_path}: only micromamba is supported")

    modules_data = _table(data, "modules", metadata_path)
    unknown_categories = set(modules_data) - set(MODULE_CATEGORIES)
    if unknown_categories:
        raise MetadataError(
            f"{metadata_path}: unknown module categories: "
            + ", ".join(sorted(unknown_categories))
        )
    modules = {
        category: _string_list(
            modules_data.get(category), f"modules.{category}", metadata_path
        )
        for category in MODULE_CATEGORIES
    }

    environment = _table(data, "environment", metadata_path)
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in environment.items()):
        raise MetadataError(f"{metadata_path}: environment values must be strings")
    invalid_environment = [
        key for key in environment if not ENVIRONMENT_NAME_RE.fullmatch(key)
    ]
    if invalid_environment:
        raise MetadataError(
            f"{metadata_path}: invalid environment names: "
            + ", ".join(sorted(invalid_environment))
        )
    paths = _table(data, "paths", metadata_path)
    prepend_paths = _string_list(paths.get("prepend"), "paths.prepend", metadata_path)
    aliases = _table(data, "aliases", metadata_path)
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in aliases.items()):
        raise MetadataError(f"{metadata_path}: aliases must map strings to strings")

    hooks = _table(data, "hooks", metadata_path)
    startup = _hooks(hooks.get("startup"), "hooks.startup", metadata_path)
    shutdown = _hooks(hooks.get("shutdown"), "hooks.shutdown", metadata_path)

    commands_data = _table(data, "commands", metadata_path)
    commands: dict[str, Command] = {}
    for command_name, command_data in commands_data.items():
        if not NAME_RE.fullmatch(command_name) or not isinstance(command_data, dict):
            raise MetadataError(f"{metadata_path}: invalid command {command_name!r}")
        command_description = _string(
            command_data, "description", metadata_path, required=True
        )
        argv = _string_list(
            command_data.get("command"),
            f"commands.{command_name}.command",
            metadata_path,
        )
        if not argv:
            raise MetadataError(
                f"{metadata_path}: commands.{command_name}.command cannot be empty"
            )
        commands[command_name] = Command(command_description, argv)

    result = Project(
        name=name,
        description=description,
        root=root,
        shell=shell,
        metadata_path=metadata_path,
        python_manager=python_manager,
        python_environment=python_environment,
        modules=modules,
        environment=dict(environment),
        prepend_paths=prepend_paths,
        aliases=dict(aliases),
        startup_hooks=startup,
        shutdown_hooks=shutdown,
        commands=commands,
    )

    # Validate every interpolation now, before activation.
    for value in (
        *result.environment.values(),
        *result.aliases.values(),
    ):
        result.expand(value)
    for value in result.prepend_paths:
        expanded_path = Path(result.expand(value))
        if not expanded_path.is_absolute():
            raise MetadataError(f"{metadata_path}: prepended paths must be absolute")
        try:
            expanded_path.resolve().relative_to(result.root)
        except ValueError as exc:
            raise MetadataError(
                f"{metadata_path}: prepended path escapes project root: {value}"
            ) from exc
    for hook in (*result.startup_hooks, *result.shutdown_hooks):
        for value in hook.argv:
            result.expand(value)
    for command in result.commands.values():
        for value in command.argv:
            result.expand(value)
    return result
