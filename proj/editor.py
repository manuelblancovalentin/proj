from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

from .errors import MetadataError, ProjError

MODULE_CATEGORIES = ("project", "toolchain", "application", "compiler")
EXACT_CONFIG_KEYS = {
    "project.description",
    "project.root",
    "project.shell",
    "python.manager",
    "python.environment",
    "paths.prepend",
    "hooks.startup",
    "hooks.shutdown",
}
OPEN_CONFIG_SECTIONS = {"environment", "aliases"}


def _toml(value: Any) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "[" + ", ".join(_toml(item) for item in value) + "]"
    if isinstance(value, int):
        return str(value)
    raise ProjError(f"unsupported configuration value: {value!r}")


def load_document(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise MetadataError(f"cannot read {path}: {exc}") from exc


def _section(lines: list[str], name: str, values: dict[str, Any]) -> None:
    lines.extend(("", f"[{name}]"))
    for key, value in values.items():
        lines.append(f"{key} = {_toml(value)}")


def render_document(data: dict[str, Any]) -> str:
    project = dict(data.get("project", {}))
    python = dict(data.get("python", {}))
    modules = dict(data.get("modules", {}))
    environment = dict(data.get("environment", {}))
    paths = dict(data.get("paths", {}))
    aliases = dict(data.get("aliases", {}))
    hooks = dict(data.get("hooks", {}))
    commands = dict(data.get("commands", {}))

    lines = [
        "# Managed by proj. Commented fields are optional examples.",
        "schema = 1",
        "",
        "[project]",
        f"name = {_toml(project['name'])}",
        f"root = {_toml(project['root'])}",
    ]
    if project.get("description"):
        lines.append(f"description = {_toml(project['description'])}")
    else:
        lines.append('# description = "Short project description"')
    if project.get("shell"):
        lines.append(f"shell = {_toml(project['shell'])}")
    else:
        lines.append('# shell = "zsh" # defaults to zsh')

    lines.extend(("", "[python]"))
    lines.append(f"manager = {_toml(python.get('manager', 'micromamba'))}")
    if python.get("environment"):
        lines.append(f"environment = {_toml(python['environment'])}")
    else:
        lines.append('# environment = "environment-name"')

    lines.extend(("", "[modules]"))
    for category in MODULE_CATEGORIES:
        if modules.get(category):
            lines.append(f"{category} = {_toml(modules[category])}")
        else:
            lines.append(f"# {category} = []")

    lines.extend(("", "[environment]"))
    if environment:
        for key, value in sorted(environment.items()):
            lines.append(f"{key} = {_toml(value)}")
    else:
        lines.append('# PROJECT_MODE = "development"')

    lines.extend(("", "[paths]"))
    if paths.get("prepend"):
        lines.append(f"prepend = {_toml(paths['prepend'])}")
    else:
        lines.append('# prepend = ["${project.root}/bin"]')

    lines.extend(("", "[aliases]"))
    if aliases:
        for key, value in sorted(aliases.items()):
            lines.append(f"{key} = {_toml(value)}")
    else:
        lines.append('# project-root = "cd ${project.root}"')

    lines.extend(("", "[hooks]"))
    if hooks.get("startup"):
        lines.append(f"startup = {_toml(hooks['startup'])}")
    else:
        lines.append("# startup = []")
    if hooks.get("shutdown"):
        lines.append(f"shutdown = {_toml(hooks['shutdown'])}")
    else:
        lines.append("# shutdown = []")

    if commands:
        for name, command in sorted(commands.items()):
            _section(lines, f"commands.{name}", command)
    else:
        lines.extend(
            (
                "",
                "# Task execution is reserved for a later release:",
                "# [commands.build]",
                '# description = "Build the project"',
                '# command = ["./scripts/build"]',
            )
        )
    lines.append("")
    return "\n".join(lines)


def write_document(path: Path, data: dict[str, Any]) -> None:
    content = render_document(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".toml.tmp")
    temporary.write_text(content)
    temporary.replace(path)


def create_document(path: Path, name: str, root: Path) -> None:
    if path.exists():
        raise ProjError(f"environment {name!r} already exists at {path}")
    data = {
        "schema": 1,
        "project": {"name": name, "root": str(root.resolve())},
        "python": {"manager": "micromamba"},
    }
    write_document(path, data)


def get_dotted(data: dict[str, Any], dotted: str) -> Any:
    current: Any = data
    for component in dotted.split("."):
        if not isinstance(current, dict) or component not in current:
            raise ProjError(f"configuration key {dotted!r} is not set")
        current = current[component]
    return current


def set_dotted(data: dict[str, Any], dotted: str, value: Any) -> None:
    if dotted in {"project.name"}:
        raise ProjError("project.name cannot be changed after creation")
    components = dotted.split(".")
    if len(components) < 2:
        raise ProjError("configuration keys must include a section")
    allowed = (
        dotted in EXACT_CONFIG_KEYS
        or (
            components[0] == "modules"
            and len(components) == 2
            and components[1] in MODULE_CATEGORIES
        )
        or (components[0] in OPEN_CONFIG_SECTIONS and len(components) == 2)
    )
    if not allowed:
        raise ProjError(f"unknown or unsupported configuration key {dotted!r}")
    current = data
    for component in components[:-1]:
        child = current.setdefault(component, {})
        if not isinstance(child, dict):
            raise ProjError(f"cannot set nested key beneath {component!r}")
        current = child
    current[components[-1]] = value


def parse_value(raw: str) -> Any:
    try:
        return tomllib.loads(f"value = {raw}")["value"]
    except tomllib.TOMLDecodeError:
        return raw
