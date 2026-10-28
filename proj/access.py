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

# What a shared environment lets people do. Everyone who reaches the registry
# may read an "owner" or "group-writable" one; a "private" one is limited to
# its group, whose members may also change it. The setgid bit keeps the
# environment's group on every file created beneath the directory.
LEVELS = ("owner", "group-writable", "private")
SHARED_DIR_MODES = {"owner": 0o2755, "group-writable": 0o2775, "private": 0o2770}
SHARED_FILE_MODES = {"owner": 0o644, "group-writable": 0o664, "private": 0o660}


def level_for(group_writable: bool = False, private: bool = False) -> str:
    if group_writable and private:
        raise ProjError("--group-writable and --private cannot be combined")
    return "private" if private else "group-writable" if group_writable else "owner"


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


def level_of(project: Project) -> str:
    """The access a shared environment's directory currently gives."""
    mode = project.metadata_path.parent.stat().st_mode
    if not mode & stat.S_IROTH:
        return "private"
    return "group-writable" if mode & stat.S_IWGRP else "owner"


def group_name(path: Path) -> str:
    gid = path.stat().st_gid
    try:
        return grp.getgrgid(gid).gr_name
    except KeyError:
        return str(gid)


def describe_scope(config: Config, project: Project) -> str:
    kind = scope(config, project)
    if kind != "shared":
        return kind
    group = group_name(project.metadata_path.parent)
    level = level_of(project)
    if level == "private":
        return f"shared (group {group} only)"
    editors = "group" if level == "group-writable" else "owner"
    return f"shared (group {group}, editable by {editors})"


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


def environment_group_id(config: Config, requested: str | None) -> int:
    """The group an environment will belong to: the one asked for, which the
    caller must be in (the system allows nothing else), or the registry's."""
    if not requested:
        return group_id(config)
    try:
        gid = grp.getgrnam(requested).gr_gid
    except KeyError as exc:
        raise ProjError(f"group {requested!r} does not exist") from exc
    if os.getuid() != 0 and gid != os.getgid() and gid not in os.getgroups():
        raise ProjError(
            f"you are not a member of group {requested!r}, so you cannot give it an environment"
        )
    return gid


def prepare_shared_directory(
    config: Config, directory: Path, level: str, group: str | None = None
) -> int:
    """Create (or reuse, after `proj remove --keep-files`) a shared environment
    directory and return its file mode."""
    gid = environment_group_id(config, group)
    directory.mkdir(exist_ok=True)
    os.chown(directory, -1, gid)
    os.chmod(directory, SHARED_DIR_MODES[level])
    return SHARED_FILE_MODES[level]
