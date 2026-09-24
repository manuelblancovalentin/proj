from __future__ import annotations

from pathlib import Path

from .config import Config
from .errors import MetadataError, ProjError
from .metadata import Project, load_project


def discover(config: Config) -> dict[str, Project]:
    projects: dict[str, Project] = {}
    for root in config.project_roots:
        if not root.is_dir():
            continue
        for metadata_path in sorted(root.glob("*/project.toml")):
            project = load_project(metadata_path)
            if project.name in projects:
                other = projects[project.name].metadata_path
                raise MetadataError(
                    f"duplicate project {project.name!r}: {other} and {metadata_path}"
                )
            projects[project.name] = project
    return projects


def resolve(config: Config, name: str) -> Project:
    projects = discover(config)
    try:
        return projects[name]
    except KeyError as exc:
        roots = ", ".join(str(root) for root in config.project_roots)
        raise ProjError(f"unknown project {name!r} (searched: {roots})") from exc
