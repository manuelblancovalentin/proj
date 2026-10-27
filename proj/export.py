"""Machine-readable documents: the environment snapshot and the module catalogue.

Both are meant for other programs (the website, `kona init`), so their keys are
stable and carry a `schema` number that only grows. Neither contains paths of
protected libraries, library versions, or user names: library modules are
recognised by the configured name prefixes and exact names and are kept out of
the ordinary lists.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Callable, Iterable

from . import __version__, uses
from .config import Config
from .errors import ProjError
from .lmod import CATEGORIES, ModuleEntry
from .metadata import MODULE_CATEGORIES, Project

SCHEMA = 1


def utc(timestamp: float | None = None) -> str:
    moment = datetime.datetime.fromtimestamp(
        timestamp if timestamp is not None else datetime.datetime.now().timestamp(),
        datetime.timezone.utc,
    )
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _under(root: Path, prefixes: list[Path]) -> bool:
    return not prefixes or any(root == prefix or prefix in root.parents for prefix in prefixes)


def check_registries(config: Config, scope: str) -> None:
    """Fail before listing when the registries a program relies on are not usable.

    `--scope shared` is how a service publishes the shared environments: an
    unconfigured or missing shared registry must be an error there, never an
    empty list that would look like "nothing is shared".
    """
    if scope == "shared":
        if config.shared_registry is None:
            raise ProjError("no shared registry is configured (shared_registry in the site configuration)")
        if not config.shared_registry.is_dir():
            raise ProjError(f"the shared registry {config.shared_registry} does not exist")


def select_projects(
    config: Config,
    projects: Iterable[Project],
    scope: str = "all",
    under: Iterable[str] = (),
    scope_of: Callable[[Config, Project], str] | None = None,
) -> list[Project]:
    """Environments by name, optionally only private or shared ones, and only
    those whose project folder is inside one of the `under` folders."""
    from . import access

    scope_of = scope_of or access.scope
    wanted = [Path(prefix).resolve() for prefix in under]
    chosen = []
    for project in sorted(projects, key=lambda item: item.name):
        kind = scope_of(config, project)
        if scope == "private" and kind != "private":
            continue
        if scope == "shared" and kind == "private":
            continue
        if _under(project.root, wanted):
            chosen.append(project)
    return chosen


def environments_snapshot(
    config: Config,
    projects: Iterable[Project],
    skipped: int = 0,
    scope: str = "all",
    under: Iterable[str] = (),
    scope_of: Callable[[Config, Project], str] | None = None,
) -> dict:
    """The registered environments in a stable, publishable form.

    Per environment: its name and scope, the project folder it belongs to
    (resolved, so compare with a resolved path), the bundles it uses (modules
    of the project category, names only), its other modules with versions (null
    when the module's default decides), the names of library modules kept apart
    in `library_bundles`, and when its metadata last changed.
    """
    from . import access

    scope_of = scope_of or access.scope
    environments = []
    for project in select_projects(config, projects, scope, under, scope_of):
        kind = scope_of(config, project)
        bundles: list[str] = []
        libraries: list[str] = []
        modules: list[dict] = []
        for category in MODULE_CATEGORIES:
            for spec in project.modules.get(category, ()):
                name, _, version = spec.partition("/")
                if config.is_library(name):
                    if name not in libraries:
                        libraries.append(name)
                elif category == "project":
                    if name not in bundles:
                        bundles.append(name)
                else:
                    modules.append({"name": name, "version": version or None})
        environments.append(
            {
                "name": project.name,
                "scope": kind,
                "project_root": str(project.root),
                "bundles": bundles,
                "modules": modules,
                "library_bundles": libraries,
                "updated": utc(project.metadata_path.stat().st_mtime),
            }
        )
    return {
        "schema": SCHEMA,
        "proj_version": __version__,
        "generated": utc(),
        "skipped": skipped,
        "environments": environments,
    }


def catalog_document(
    config: Config,
    entries: Iterable[ModuleEntry],
    groups: set[str],
    contents: Callable[[str], list[str] | None],
) -> dict:
    """What a person may add to a login: tools, and the curated suites/bundles.

    Library modules are left out and only counted. Each module says which Unix
    groups gate it and whether this person is in one; each suite or bundle lists
    the names of the modules it brings (library names withheld, and counted).
    """
    tools: list[dict] = []
    sets: list[dict] = []
    libraries = 0
    for entry in sorted(entries, key=lambda item: item.name):
        if config.is_library(entry.name):
            libraries += 1
            continue
        common = {
            "versions": list(entry.versions),
            "default": entry.default,
            "groups": uses.required_groups(entry),
            "allowed": uses.allowed(entry, groups),
        }
        is_suite = entry.name.startswith("suite-")
        if is_suite or entry.category == "project":
            names = contents(entry.name)
            kept = [] if names is None else [n for n in names if not config.is_library(n)]
            sets.append(
                {
                    "name": uses.short_name(entry.name) if is_suite else entry.name,
                    "module": entry.name,
                    "kind": "suite" if is_suite else "bundle",
                    **common,
                    "contains": None if names is None else kept,
                    "withheld": 0 if names is None else len(names) - len(kept),
                }
            )
        else:
            tools.append(
                {
                    "name": entry.name,
                    "category": entry.category if entry.category in CATEGORIES else None,
                    **common,
                }
            )
    return {
        "schema": SCHEMA,
        "proj_version": __version__,
        "generated": utc(),
        "modules": tools,
        "suites": sets,
        "libraries_omitted": libraries,
    }
