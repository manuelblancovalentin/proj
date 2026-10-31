from __future__ import annotations

import os
import re
import stat
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import AccessDenied, MetadataError

NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
ENVIRONMENT_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
VARIABLE_RE = re.compile(r"\$\{([^}]+)\}")
MODULE_CATEGORIES = ("project", "toolchain", "application", "compiler")
SHELLS = ("zsh", "bash")
# proj generates one Lmod module per environment under this name, so it cannot
# also name a dependency: an environment would depend on itself or on another
# environment, and they all share the Lmod family of the same name.
RESERVED_MODULE_NAMESPACE = "project"
PYTHON_MANAGERS = ("micromamba", "conda", "mamba")


@dataclass(frozen=True)
class Hook:
    argv: tuple[str, ...]


@dataclass(frozen=True)
class PathVariable:
    """Entries added to a path-like variable (PYTHONPATH, PATH, ...) that Lmod
    removes again on unload, leaving the person's own entries alone."""

    prepend: tuple[str, ...] = ()
    append: tuple[str, ...] = ()


@dataclass(frozen=True)
class PythonStamp:
    """What the Python environment was built from: the SHA-256 of its
    dependency file when `proj python-env stamp` last ran."""

    sha256: str
    date: str
    by: str


@dataclass(frozen=True)
class Derived:
    """The environment this one was copied from by `proj create --from`."""

    source: str
    date: str
    digest: str


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
    # The project folder as the metadata writes it when that is a plain absolute
    # path (it may be a symbolic link); `root` is where it resolves, and is what
    # checks and comparisons use. People are shown and moved to the written path.
    shown_root: Path | None = None
    python_manager: str | None = None
    python_environment: str | None = None
    python_spec: str | None = None
    python_stamp: PythonStamp | None = None
    derived: Derived | None = None
    modules: dict[str, tuple[str, ...]] = field(default_factory=dict)
    environment: dict[str, str] = field(default_factory=dict)
    environment_paths: dict[str, PathVariable] = field(default_factory=dict)
    prepend_paths: tuple[str, ...] = ()
    aliases: dict[str, str] = field(default_factory=dict)
    startup_hooks: tuple[Hook, ...] = ()
    shutdown_hooks: tuple[Hook, ...] = ()
    commands: dict[str, Command] = field(default_factory=dict)

    @property
    def visible_root(self) -> Path:
        return self.shown_root or self.root

    @property
    def module_name(self) -> str:
        return f"project/{self.name}"

    def context(self) -> dict[str, str]:
        return {
            "project.name": self.name,
            "project.root": str(self.visible_root),
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


def _path_variables(
    table: dict[str, Any], environment: dict[str, Any], source: Path
) -> dict[str, PathVariable]:
    result: dict[str, PathVariable] = {}
    for variable, entries in table.items():
        label = f"environment_paths.{variable}"
        if not ENVIRONMENT_NAME_RE.fullmatch(variable):
            raise MetadataError(f"{source}: invalid variable name in {label}")
        if variable.startswith("PROJ_"):
            raise MetadataError(f"{source}: {label}: PROJ_* variables belong to proj")
        if variable in environment:
            raise MetadataError(
                f"{source}: {variable} is set in both [environment] and [{label}]"
            )
        if not isinstance(entries, dict) or set(entries) - {"prepend", "append"}:
            raise MetadataError(
                f"{source}: [{label}] takes only prepend and append arrays"
            )
        prepend = _string_list(entries.get("prepend"), f"{label}.prepend", source)
        append = _string_list(entries.get("append"), f"{label}.append", source)
        if prepend or append:
            result[variable] = PathVariable(prepend, append)
    return result


def _text_fields(value: Any, label: str, fields: tuple[str, ...], source: Path):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise MetadataError(f"{source}: [{label}] needs exactly: " + ", ".join(fields))
    if not all(isinstance(value[field], str) and value[field] for field in fields):
        raise MetadataError(f"{source}: [{label}] values must be non-empty strings")
    return [value[field] for field in fields]


def _stamp(value: Any, source: Path) -> PythonStamp | None:
    if value is None:
        return None
    sha256, date, by = _text_fields(value, "python.stamp", ("sha256", "date", "by"), source)
    if not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise MetadataError(f"{source}: python.stamp.sha256 must be a SHA-256 digest")
    return PythonStamp(sha256, date, by)


def _derived(value: Any, source: Path) -> Derived | None:
    if value is None:
        return None
    origin, date, digest = _text_fields(value, "derived", ("from", "date", "digest"), source)
    if not NAME_RE.fullmatch(origin):
        raise MetadataError(f"{source}: derived.from is not an environment name")
    return Derived(origin, date, digest)


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


def _reject_world_writable(metadata_path: Path) -> None:
    # Anyone could inject hooks or aliases into a world-writable document.
    for candidate in (metadata_path, metadata_path.parent):
        if candidate.stat().st_mode & stat.S_IWOTH:
            raise MetadataError(f"{candidate} is world-writable; refusing to load it")


def load_project(metadata_path: Path) -> Project:
    metadata_path = metadata_path.resolve()
    try:
        with metadata_path.open("rb") as handle:
            data = tomllib.load(handle)
        _reject_world_writable(metadata_path)
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
    written = Path(os.path.expanduser(raw_root))
    try:
        root = written.resolve()
        os.stat(root)
    except PermissionError as exc:
        # The folder may be private to a group the person is not in: not an error
        # to report (and its path stays out of the message).
        raise AccessDenied(f"{metadata_path}: no permission to read the project root") from exc
    except OSError:
        pass  # does not exist: the check below says so
    if not root.is_dir():
        raise MetadataError(f"{metadata_path}: project root does not exist: {root}")
    shell = _string(project_data, "shell", metadata_path) or "zsh"
    if shell not in SHELLS:
        raise MetadataError(
            f"{metadata_path}: shell must be one of: " + ", ".join(SHELLS)
        )
    python_data = _table(data, "python", metadata_path)
    python_manager = _string(python_data, "manager", metadata_path)
    python_environment = _string(python_data, "environment", metadata_path)
    python_spec = _string(python_data, "spec", metadata_path)
    python_stamp = _stamp(python_data.get("stamp"), metadata_path)
    derived = _derived(data.get("derived"), metadata_path)
    # Without a manager, the environment uses the configured default manager.
    if python_manager and python_manager not in PYTHON_MANAGERS:
        raise MetadataError(
            f"{metadata_path}: python.manager must be one of: "
            + ", ".join(PYTHON_MANAGERS)
        )

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
    for category, names in modules.items():
        for module in names:
            if module.partition("/")[0] == RESERVED_MODULE_NAMESPACE:
                raise MetadataError(
                    f"{metadata_path}: modules.{category}: {module!r} is in the "
                    f"{RESERVED_MODULE_NAMESPACE}/ namespace, which proj uses for the modules "
                    "it generates from environments; an environment cannot depend on itself "
                    "or on another environment"
                )

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
    environment_paths = _path_variables(
        _table(data, "environment_paths", metadata_path), environment, metadata_path
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
        shown_root=written if written.is_absolute() and ".." not in written.parts else None,
        python_manager=python_manager,
        python_environment=python_environment,
        python_spec=python_spec,
        python_stamp=python_stamp,
        derived=derived,
        modules=modules,
        environment=dict(environment),
        environment_paths=environment_paths,
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
    if result.python_spec:
        spec = result.expand(result.python_spec)
        if not os.path.isabs(spec):
            raise MetadataError(f"{metadata_path}: python.spec must be an absolute path")
    for variable, entries in result.environment_paths.items():
        for value in (*entries.prepend, *entries.append):
            expanded = result.expand(value)
            if not os.path.isabs(expanded) or ":" in expanded or "\n" in expanded:
                raise MetadataError(
                    f"{metadata_path}: environment_paths.{variable}: {value!r} must "
                    "expand to one absolute path"
                )
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
