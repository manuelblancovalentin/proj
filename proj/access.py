"""Ownership, scope, and permissions for private and shared environments."""

from __future__ import annotations

import grp
import os
import pwd
import stat
from pathlib import Path

from .config import Config
from .errors import ProjError
from .metadata import Project

# Owner-only and group-writable shared environments. The setgid bit keeps the
# registry group on every file created beneath the directory.
SHARED_DIR_MODES = {False: 0o2755, True: 0o2775}
SHARED_FILE_MODES = {False: 0o644, True: 0o664}


def owner_name(path: Path) -> str:
    uid = path.stat().st_uid
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return str(uid)


def project_owner(project: Project) -> str:
    # The directory keeps its creator; group members who edit a group-writable
    # environment replace the document itself.
    return owner_name(project.metadata_path.parent)


def current_user() -> str:
    try:
        return pwd.getpwuid(os.getuid()).pw_name
    except KeyError:
        return str(os.getuid())


def scope(config: Config, project: Project) -> str:
    registry = project.metadata_path.parent.parent
    if registry == config.registry:
        return "private"
    if registry == config.shared_registry:
        return "shared"
    return "external"


def group_writable(project: Project) -> bool:
    return bool(project.metadata_path.parent.stat().st_mode & stat.S_IWGRP)


def describe_scope(config: Config, project: Project) -> str:
    kind = scope(config, project)
    if kind != "shared":
        return kind
    editors = "group" if group_writable(project) else "owner"
    return f"shared (group {config.group}, editable by {editors})"


def require_writable(project: Project) -> None:
    directory = project.metadata_path.parent
    if os.access(directory, os.W_OK) and os.access(project.metadata_path, os.W_OK):
        return
    owner = project_owner(project)
    raise ProjError(
        f"environment {project.name!r} belongs to {owner}; "
        "only its owner (or its group, if group-writable) can change it"
    )


def group_id(config: Config) -> int:
    if not config.group:
        raise ProjError("no shared group is configured")
    try:
        return grp.getgrnam(config.group).gr_gid
    except KeyError as exc:
        raise ProjError(f"group {config.group!r} does not exist") from exc


def is_member(config: Config) -> bool:
    gid = group_id(config)
    return gid == os.getgid() or gid in os.getgroups()


def shared_registry(config: Config) -> Path:
    registry = config.shared_registry
    if registry is None:
        raise ProjError(
            "no shared registry is configured; reinstall in shared mode or set "
            "shared_registry and group in the proj configuration"
        )
    if not is_member(config):
        raise ProjError(
            f"you are not a member of group {config.group!r}; ask an administrator "
            f"to run `usermod -aG {config.group} {current_user()}`, then log in again"
        )
    if not registry.is_dir() or not os.access(registry, os.W_OK):
        raise ProjError(f"shared registry is not writable: {registry}")
    return registry


def prepare_shared_directory(config: Config, directory: Path, writable: bool) -> int:
    """Create a shared environment directory and return its file mode."""
    directory.mkdir()
    os.chown(directory, -1, group_id(config))
    os.chmod(directory, SHARED_DIR_MODES[writable])
    return SHARED_FILE_MODES[writable]
