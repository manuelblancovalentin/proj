from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .errors import AccessDenied, ProjError
from .metadata import Project, load_project


@dataclass
class Discovery:
    projects: dict[str, Project] = field(default_factory=dict)
    problems: list[tuple[Path, str]] = field(default_factory=list)
    # Environments the person may not read (a shared one limited to a group they
    # are not in). That is normal, so they are counted, never reported one by one.
    unreadable: list[Path] = field(default_factory=list)


def _metadata_files(root: Path, strict: bool, result: Discovery) -> list[Path]:
    # Listing the registry for a program that publishes the result (strict): a
    # registry that cannot be read must fail, not look empty, and an entry that
    # fails in some other way than permission is reported instead of silently
    # missing. An entry the person has no permission to read is just counted.
    try:
        entries = sorted(root.iterdir())
    except OSError as exc:
        if strict:
            raise ProjError(f"cannot read the registry {root}: {exc.strerror or exc}") from exc
        return []
    found = []
    for entry in entries:
        metadata_path = entry / "project.toml"
        try:
            metadata_path.stat()
        except (FileNotFoundError, NotADirectoryError):
            continue
        except PermissionError:
            result.unreadable.append(metadata_path)
            continue
        except OSError as exc:
            if strict:
                result.problems.append(
                    (metadata_path, f"cannot read {metadata_path}: {exc.strerror or exc}")
                )
            continue
        if not os.access(metadata_path, os.R_OK):
            result.unreadable.append(metadata_path)
            continue
        found.append(metadata_path)
    return found


def scan(config: Config, strict: bool = False) -> Discovery:
    """Load every environment, skipping invalid ones.

    Shared registries hold other people's metadata, so one broken document
    must not disable proj for everyone. Earlier roots take precedence, which
    lets a private environment shadow a shared one with the same name.
    With `strict`, a registry that exists but cannot be listed is an error and
    an unreadable entry counts as a problem.
    """
    result = Discovery()
    for root in config.project_roots:
        if not root.is_dir():
            continue
        seen: dict[str, Path] = {}
        for metadata_path in _metadata_files(root, strict, result):
            try:
                project = load_project(metadata_path)
            except AccessDenied:
                result.unreadable.append(metadata_path)
                continue
            except (ProjError, OSError) as exc:
                result.problems.append((metadata_path, str(exc)))
                continue
            if project.name in seen:
                result.problems.append(
                    (
                        metadata_path,
                        f"duplicate project {project.name!r}: "
                        f"{seen[project.name]} and {metadata_path}",
                    )
                )
                continue
            seen[project.name] = metadata_path
            result.projects.setdefault(project.name, project)
    return result


def discover(config: Config) -> dict[str, Project]:
    return scan(config).projects


def resolve(config: Config, name: str) -> Project:
    found = scan(config)
    if name in found.projects:
        return found.projects[name]
    for metadata_path, problem in found.problems:
        if metadata_path.parent.name == name:
            raise ProjError(problem)
    if any(path.parent.name == name for path in found.unreadable):
        raise ProjError(
            f"environment {name!r} exists but you have no permission to read it "
            "(it may be limited to a group you are not in)"
        )
    roots = ", ".join(str(root) for root in config.project_roots)
    raise ProjError(f"unknown project {name!r} (searched: {roots})")
