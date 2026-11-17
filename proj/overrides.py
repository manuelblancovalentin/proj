"""A person's own Python environment for an environment they do not own.

Members of a shared project often have their own conda environment and want
`proj activate <project>` to use it while the project's modules, variables and
paths stay as they are for everybody. The choice is one small file per person
and environment, `<proj home>/overrides/<name>.toml` (private to the person):

    schema = 1

    [python]
    manager = "conda"
    environment = "mine"

It holds a manager and an environment name or prefix and nothing else, so it
can neither run anything nor change what anyone else sees: the shared document
is never written, and the file is read only for environments that are not the
person's own (a private environment is simply edited).
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from dataclasses import replace
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

from .config import Config
from .errors import MetadataError
from .metadata import PYTHON_MANAGERS, Project, PythonOverride

KEYS = {"manager", "environment"}


def directory(config: Config) -> Path:
    return config.proj_home / "overrides"


def path(config: Config, name: str) -> Path:
    return directory(config) / f"{name}.toml"


def _text(table: dict, key: str, source: Path, required: bool = False) -> str | None:
    value = table.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value:
        raise MetadataError(f"your Python override {source}: python.{key} must be a non-empty string")
    return value


def load(config: Config, name: str) -> tuple[str, str] | None:
    """(manager, environment) of the person's override of `name`, or None."""
    source = path(config, name)
    try:
        info = source.stat()
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError as exc:
        raise MetadataError(f"cannot read your Python override {source}: {exc.strerror or exc}") from exc
    # Anyone who could write the file could point the environment elsewhere.
    for candidate, mode in ((source, info.st_mode), (source.parent, source.parent.stat().st_mode)):
        if mode & stat.S_IWOTH:
            raise MetadataError(f"{candidate} is world-writable; refusing to load your Python override")
    try:
        with source.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise MetadataError(f"cannot read your Python override {source}: {exc}") from exc
    if data.get("schema") != 1:
        raise MetadataError(f"your Python override {source}: schema must be 1")
    unknown = set(data) - {"schema", "python"}
    python = data.get("python")
    if unknown or not isinstance(python, dict):
        raise MetadataError(f"your Python override {source}: expected only a [python] table")
    extra = set(python) - KEYS
    if extra:
        raise MetadataError(f"your Python override {source}: unknown python keys: " + ", ".join(sorted(extra)))
    environment = _text(python, "environment", source, required=True)
    manager = _text(python, "manager", source, required=True)
    if manager not in PYTHON_MANAGERS:
        raise MetadataError(f"your Python override {source}: python.manager must be one of: " + ", ".join(PYTHON_MANAGERS))
    return manager, environment


def apply(config: Config, project: Project) -> Project:
    """The project as this person uses it: their Python link in place of the
    shared one, when they have one. Everything else is the shared document's."""
    found = load(config, project.name)
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


def write(config: Config, name: str, manager: str, environment: str) -> Path:
    target = path(config, name)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lines = (
        f"# Managed by proj: your own Python environment for {name}. Nothing else of the",
        "# environment is changed, and nobody else is affected.",
        "schema = 1",
        "",
        "[python]",
        f'manager = "{manager}"',
        f"environment = {_quote(environment)}",
        "",
    )
    handle, temporary = tempfile.mkstemp(dir=target.parent, prefix=f".{name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w") as stream:
            stream.write("\n".join(lines))
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return target


def remove(config: Config, name: str) -> bool:
    try:
        path(config, name).unlink()
    except FileNotFoundError:
        return False
    return True


def _quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def source(config: Config, project: Project) -> str:
    """Where the Python link in use comes from: `override` (the person's own),
    `shared` (another person's environment) or `own`."""
    from . import access

    if project.python_override:
        return "override"
    return "own" if access.scope(config, project) == "private" else "shared"
