"""`proj share` and `proj unshare`: move an environment between registries.

The document is copied byte for byte, so the metadata does not change. The new
directory is built beside its destination and renamed into place, and the
document is the last file to appear, so the environment is never visible
half-made. The old copy is removed only once the new one is complete.
"""

from __future__ import annotations

import os
import pwd
import shutil
import sys
from pathlib import Path

from . import access
from .config import Config
from .discovery import discover, resolve
from .errors import ProjError
from .metadata import NAME_RE, load_project

DOCUMENT = "project.toml"
# The document is copied under this name and renamed once the directory is in
# place, because discovery looks for `*/project.toml` and must not see a half-made environment.
PENDING = "project.toml.new"


def _entries(directory: Path) -> list[Path]:
    """Everything under an environment directory; only files and folders can move."""
    found = []
    for path in sorted(directory.rglob("*")):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ProjError(f"{path} is not a regular file or folder; move or remove it first")
        found.append(path)
    return found


def _copy_tree(source: Path, target: Path, dir_mode: int | None, file_mode: int | None, gid: int | None) -> None:
    """Fill the new directory `target` from `source`, the document under its pending name.

    With modes, everything gets the shared permissions and group; without, the
    ordinary ones for files a person makes (umask, primary group).
    """
    def settle(path: Path, mode: int | None) -> None:
        if mode is not None:
            os.chown(path, -1, gid)
            os.chmod(path, mode)

    settle(target, dir_mode)
    for path in _entries(source):
        relative = path.relative_to(source)
        copy = target / (PENDING if relative == Path(DOCUMENT) else relative)
        if path.is_dir():
            copy.mkdir()
            settle(copy, dir_mode)
        else:
            shutil.copyfile(path, copy)
            settle(copy, file_mode)


def _move(source: Path, destination: Path, dir_mode: int | None, file_mode: int | None, gid: int | None) -> bool:
    """Copy the environment directory `source` to `destination`, then remove it.

    Returns False when some leftovers of `source` could not be deleted; the
    environment itself has moved by then.
    """
    scratch = destination.with_name(f".{destination.name}.moving")
    if scratch.exists():
        shutil.rmtree(scratch)  # left by an interrupted move
    scratch.mkdir()
    try:
        _copy_tree(source, scratch, dir_mode, file_mode, gid)
        os.rename(scratch, destination)
    except BaseException:
        shutil.rmtree(scratch, ignore_errors=True)
        raise
    try:
        os.replace(destination / PENDING, destination / DOCUMENT)
        load_project(destination / DOCUMENT)
        (source / DOCUMENT).unlink()  # the environment leaves its old registry here
    except BaseException:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    try:
        shutil.rmtree(source)
    except OSError:
        return False
    return True


def _check_free(destination: Path, name: str) -> None:
    if (destination / DOCUMENT).exists():
        raise ProjError(f"environment {name!r} already exists at {destination / DOCUMENT}")
    if destination.exists():
        raise ProjError(
            f"{destination} exists and holds other files (left by `proj remove`); "
            "move them aside first"
        )


def _check_not_active(name: str) -> None:
    if os.environ.get("PROJ_ACTIVE") == name:
        raise ProjError(f"environment {name!r} is active in this shell; deactivate it first")


def active_elsewhere(name: str) -> list[str]:
    """Processes that look like they have `name` active, for what this user may see.

    Only an environment inherited at start-up is visible: a shell that activated
    it later shows nothing, but programs started from that shell do. Other
    people's processes are visible to root alone.
    """
    needle = f"PROJ_ACTIVE={name}".encode()
    found = []
    try:
        pids = [entry for entry in os.listdir("/proc") if entry.isdigit() and int(entry) != os.getpid()]
    except OSError:
        return found
    for pid in pids:
        try:
            with open(f"/proc/{pid}/environ", "rb") as handle:
                if needle not in handle.read().split(b"\0"):
                    continue
            with open(f"/proc/{pid}/comm") as handle:
                command = handle.read().strip()
            uid = os.stat(f"/proc/{pid}").st_uid
        except OSError:
            continue
        try:
            user = pwd.getpwuid(uid).pw_name
        except KeyError:
            user = str(uid)
        found.append(f"{command} (pid {pid}, {user})")
    return found


def share(config: Config, name: str, level: str = "owner", group: str | None = None) -> Path:
    """Move a private environment to the shared registry; returns its new document."""
    if not NAME_RE.fullmatch(name):
        raise ProjError("project names may contain letters, numbers, dots, underscores, and dashes")
    source = config.registry / name
    if not (source / DOCUMENT).is_file():
        found = discover(config).get(name)
        if found:
            raise ProjError(f"environment {name!r} is not private (it is {access.scope(config, found)})")
        raise ProjError(f"unknown private environment {name!r} (searched: {config.registry})")
    load_project(source / DOCUMENT)
    _check_not_active(name)
    registry = access.shared_registry(config)
    gid = access.environment_group_id(config, group)
    destination = registry / name
    _check_free(destination, name)
    if not (os.access(source, os.W_OK) and os.access(config.registry, os.W_OK)):
        raise ProjError(f"cannot move {source}: permission denied")
    complete = _move(
        source,
        destination,
        access.SHARED_DIR_MODES[level],
        access.SHARED_FILE_MODES[level],
        gid,
    )
    if not complete:
        print(f"proj: could not delete everything in {source}; the environment has moved", file=sys.stderr)
    return destination / DOCUMENT


def unshare(config: Config, name: str, force: bool) -> Path:
    """Move an environment its creator shared back to the private registry."""
    if not NAME_RE.fullmatch(name):
        raise ProjError("project names may contain letters, numbers, dots, underscores, and dashes")
    registry = access.shared_registry(config)
    source = registry / name
    if not (source / DOCUMENT).is_file():
        raise ProjError(f"unknown shared environment {name!r} (searched: {registry})")
    if os.getuid() != source.stat().st_uid:
        raise ProjError(
            f"environment {name!r} belongs to {access.owner_name(source)}; only its creator can unshare it"
        )
    load_project(source / DOCUMENT)
    _check_not_active(name)
    users = [] if force else active_elsewhere(name)
    if users:
        raise ProjError(
            f"environment {name!r} looks active in {', '.join(users)}; deactivate it there first "
            "(--force if that is out of date)"
        )
    destination = config.registry / name
    _check_free(destination, name)
    config.registry.mkdir(parents=True, exist_ok=True)
    if not _move(source, destination, None, None, None):
        print(f"proj: could not delete everything in {source}; the environment has moved", file=sys.stderr)
    return destination / DOCUMENT


def change_access(config: Config, name: str, level: str | None) -> tuple[Path, str, str]:
    """Show, or with `level` set, change who can see and change a shared environment.

    Returns its directory, the access it had and the access it has. Only the
    creator can change it; the group stays. The permissions of every file move
    together, the directory last when it opens up and first when it closes.
    """
    if not NAME_RE.fullmatch(name):
        raise ProjError("project names may contain letters, numbers, dots, underscores, and dashes")
    project = resolve(config, name)
    if access.scope(config, project) != "shared":
        raise ProjError(
            f"environment {name!r} is {access.scope(config, project)}; only a shared environment has an access level"
        )
    directory = project.metadata_path.parent
    before = access.level_of(project)
    if level is None or level == before:
        return directory, before, before
    if os.getuid() != directory.stat().st_uid:
        raise ProjError(
            f"environment {name!r} belongs to {access.owner_name(directory)}; only its creator can change its access"
        )
    mode = access.SHARED_FILE_MODES[level]
    files = [path for path in directory.rglob("*") if path.is_file() and not path.is_symlink()]
    folders = [directory, *(path for path in directory.rglob("*") if path.is_dir() and not path.is_symlink())]
    opening = level == "group-writable"  # more people can read or write than a private one allows
    for step in ("files", "folders") if opening else ("folders", "files"):
        for path in files if step == "files" else folders:
            os.chmod(path, mode if step == "files" else access.SHARED_DIR_MODES[level])
    return directory, before, level
