"""What one person sets for one environment, in their own configuration.

An environment's record (`project.toml`) is the same for everyone who uses it.
A person's own configuration (`~/.config/proj/config.toml`) holds their settings
for everything; their settings for *one* environment sit beside it, in
`~/.config/proj/projects/<name>.toml` (mode 0600), as a configuration file that
applies to that environment only, with the same names the record and the
configuration use:

    schema = 1

    [python]                       # their own Python environment for a shared one
    manager = "conda"
    environment = "mine"

    [behavior]                     # the same settings as [behavior] of config.toml
    activate_directory = "${project.root}/${user}"

Whatever is there overrides the same name set for everyone, and for this person
only. `proj config --env NAME --mine KEY=VALUE` and `--mine --unset KEY` write
and remove it (`proj set-python-env --mine` is the same thing for the Python
link). It holds only the keys in `SETTABLE`, so it can neither run anything nor
change what anyone else sees: the shared document is never written. The
`[python]` table applies only to environments that are not the person's own (a
private environment is simply edited); `[behavior]` applies to every
environment they use.

To make another setting personal, add it to `SETTABLE`: everything else (the
file, `--mine`, `--unset`, validation, messages) follows from it.

proj 0.9.0 kept the Python link in `<proj home>/overrides/<name>.toml`. That
file is still read, and is folded into the new one (and removed) the next time
the person changes a setting of that environment.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

from .config import BEHAVIOR_SETTINGS, Behavior, Config, behavior_table
from .errors import ConfigError, MetadataError
from .metadata import PYTHON_MANAGERS, Project, PythonOverride

# Dotted key -> what it holds. `python.*` keys describe one link, so they are
# written together; each `behavior.*` key stands alone.
SETTABLE: dict[str, type] = {
    "python.manager": str,
    "python.environment": str,
    **{f"behavior.{key}": kind for key, kind in BEHAVIOR_SETTINGS.items()},
}
PYTHON_KEYS = {"manager", "environment"}


@dataclass(frozen=True)
class Settings:
    python: tuple[str, str] | None = None  # (manager, environment)
    behavior: dict | None = None

    def keys(self) -> list[str]:
        found = []
        if self.python:
            found += ["python.manager", "python.environment"]
        found += [f"behavior.{key}" for key in sorted(self.behavior or {})]
        return found

    def value(self, key: str):
        if key == "python.manager":
            return self.python[0] if self.python else None
        if key == "python.environment":
            return self.python[1] if self.python else None
        return (self.behavior or {}).get(key.removeprefix("behavior."))


def directory(config: Config) -> Path:
    return (config.user_config_dir or config.proj_home / "config") / "projects"


def path(config: Config, name: str) -> Path:
    return directory(config) / f"{name}.toml"


def legacy_path(config: Config, name: str) -> Path:
    """Where proj 0.9.0 kept a person's Python link for an environment."""
    return config.proj_home / "overrides" / f"{name}.toml"


def _fail(source: Path, message: str) -> MetadataError:
    return MetadataError(f"your settings {source}: {message}")


def _text(table: dict, key: str, source: Path) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value:
        raise _fail(source, f"python.{key} must be a non-empty string")
    return value


def read(config: Config, name: str) -> Settings | None:
    """The person's settings for `name`, checked, or None when they have none.
    A Python link kept by proj 0.9.0 counts when the new file has none."""
    found = _read_file(path(config, name))
    if found is None or found.python is None:
        old = _read_file(legacy_path(config, name))
        if old is not None and old.python is not None:
            found = Settings(old.python, found.behavior if found else None)
    return found


def _read_file(source: Path) -> Settings | None:
    try:
        info = source.stat()
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError as exc:
        raise MetadataError(f"cannot read your settings {source}: {exc.strerror or exc}") from exc
    # Anyone who could write the file could point the environment elsewhere.
    for candidate, mode in ((source, info.st_mode), (source.parent, source.parent.stat().st_mode)):
        if mode & stat.S_IWOTH:
            raise MetadataError(f"{candidate} is world-writable; refusing to load your settings")
    try:
        with source.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise MetadataError(f"cannot read your settings {source}: {exc}") from exc
    if data.get("schema") != 1:
        raise _fail(source, "schema must be 1")
    unknown = set(data) - {"schema", "python", "behavior"}
    if unknown:
        raise _fail(source, "expected only [python] and [behavior] tables")
    python = None
    if "python" in data:
        table = data["python"]
        if not isinstance(table, dict):
            raise _fail(source, "python must be a table")
        extra = set(table) - PYTHON_KEYS
        if extra:
            raise _fail(source, "unknown python keys: " + ", ".join(sorted(extra)))
        environment = _text(table, "environment", source)
        manager = _text(table, "manager", source)
        if manager not in PYTHON_MANAGERS:
            raise _fail(source, "python.manager must be one of: " + ", ".join(PYTHON_MANAGERS))
        python = (manager, environment)
    try:
        behavior = behavior_table(data.get("behavior"), "behavior", f"your settings {source}")
    except ConfigError as exc:
        raise MetadataError(str(exc)) from exc
    return Settings(python, dict(behavior))


def python_override(config: Config, name: str) -> tuple[str, str] | None:
    found = read(config, name)
    return found.python if found else None


def apply(config: Config, project: Project) -> Project:
    """The project as this person uses it: their Python link in place of the
    shared one, when they have one. Everything else is the shared document's."""
    found = python_override(config, project.name)
    if found is None:
        return project
    manager, environment = found
    return replace(
        project,
        python_manager=manager,
        python_environment=environment,
        python_override=PythonOverride(
            manager, environment, project.python_manager, project.python_environment
        ),
    )


def behavior(config: Config, name: str, strict: bool = True) -> Behavior:
    """How activation and deactivation behave for this person and environment:
    the configuration's `[behavior]`, then their own overrides. With
    `strict=False` an unreadable file is ignored (deactivation must still work)."""
    try:
        found = read(config, name)
    except MetadataError:
        if strict:
            raise
        found = None
    if not found or not found.behavior:
        return config.behavior
    return replace(config.behavior, **found.behavior)


def validate(key: str, value: object) -> object:
    """A value for an overridable key, or ConfigError saying what is wrong."""
    kind = SETTABLE.get(key)
    if kind is None:
        raise ConfigError(
            f"{key!r} is not a setting one person can change for an environment; you can set: "
            + ", ".join(sorted(SETTABLE))
        )
    if key == "python.manager":
        if value not in PYTHON_MANAGERS:
            raise ConfigError(f"{key} must be one of: " + ", ".join(PYTHON_MANAGERS))
    elif kind is bool:
        if not isinstance(value, bool):
            raise ConfigError(f"{key} must be true or false")
    elif not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{key} must be a non-empty string")
    return value


def _quote(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return json.dumps(value, ensure_ascii=False)


def _write(config: Config, name: str, found: Settings) -> Path:
    target = path(config, name)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.parent.stat().st_uid == os.getuid():
        os.chmod(target.parent, 0o700)
    lines = [
        f"# Managed by proj (proj config --env {name} --mine): your own settings for {name}. Nothing in the environment is",
        "# changed, and nobody else is affected.",
        "schema = 1",
    ]
    if found.python:
        lines += ["", "[python]", f'manager = "{found.python[0]}"', f"environment = {_quote(found.python[1])}"]
    if found.behavior:
        lines += ["", "[behavior]"]
        lines += [f"{key} = {_quote(found.behavior[key])}" for key in sorted(found.behavior)]
    handle, temporary = tempfile.mkstemp(dir=target.parent, prefix=f".{name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w") as stream:
            stream.write("\n".join(lines) + "\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
        # Now the one place; the 0.9.0 file would only disagree.
        legacy_path(config, name).unlink(missing_ok=True)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return target


def set_python(config: Config, name: str, manager: str, environment: str) -> Path:
    found = read(config, name) or Settings()
    return _write(config, name, Settings((manager, environment), found.behavior))


def set_key(config: Config, name: str, key: str, value: object) -> Path:
    """Record one `behavior.*` key (the Python link goes through `set_python`)."""
    value = validate(key, value)
    if not key.startswith("behavior."):
        raise ConfigError(f"{key} is set with its environment; use `proj set-python-env --mine`")
    found = read(config, name) or Settings()
    behavior_values = {**(found.behavior or {}), key.removeprefix("behavior."): value}
    return _write(config, name, Settings(found.python, behavior_values))


def unset_key(config: Config, name: str, key: str) -> bool:
    """Forget one key (`python` forgets the whole link); False if it was not set.
    The file goes away with its last key."""
    found = read(config, name)
    if found is None:
        return False
    python, values = found.python, dict(found.behavior or {})
    if key in ("python", "python.manager", "python.environment"):
        if python is None:
            return False
        python = None
    elif key in SETTABLE:
        if values.pop(key.removeprefix("behavior."), None) is None:
            return False
    else:
        validate(key, "x")  # raises, naming what can be overridden
    if python is None and not values:
        return remove(config, name)
    _write(config, name, Settings(python, values))
    return True


def remove(config: Config, name: str) -> bool:
    removed = False
    for candidate in (path(config, name), legacy_path(config, name)):
        try:
            candidate.unlink()
            removed = True
        except FileNotFoundError:
            pass
    return removed


def source(config: Config, project: Project) -> str:
    """Where the Python link in use comes from: `override` (the person's own),
    `shared` (another person's environment) or `own`."""
    from . import access

    if project.python_override:
        return "override"
    return "own" if access.scope(config, project) == "private" else "shared"
