from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .errors import ProjError
from .metadata import Project, load_project


@dataclass
class Discovery:
    projects: dict[str, Project] = field(default_factory=dict)
    problems: list[tuple[Path, str]] = field(default_factory=list)


def _metadata_files(root: Path, strict: bool, problems: list[tuple[Path, str]]) -> list[Path]:
    if not strict:
        return sorted(root.glob("*/project.toml"))
    # Listing the registry for a program that publishes the result: a registry
    # that cannot be read must fail, not look empty, and an entry that cannot be
    # read is reported instead of silently missing.
    try:
        entries = sorted(root.iterdir())
    except OSError as exc:
        raise ProjError(f"cannot read the registry {root}: {exc.strerror or exc}") from exc
    found = []
    for entry in entries:
        metadata_path = entry / "project.toml"
        try:
            metadata_path.stat()
        except FileNotFoundError:
            continue
        except NotADirectoryError:
            continue
        except OSError as exc:
            problems.append((metadata_path, f"cannot read {metadata_path}: {exc.strerror or exc}"))
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
        for metadata_path in _metadata_files(root, strict, result.problems):
            try:
                project = load_project(metadata_path)
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
    roots = ", ".join(str(root) for root in config.project_roots)
    raise ProjError(f"unknown project {name!r} (searched: {roots})")
