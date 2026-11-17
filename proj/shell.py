from __future__ import annotations

import os
import shlex

from .config import Config
from .metadata import Project
from .modulefile import materialize
from .python_envs import manager_for


def _q(value: object) -> str:
    return shlex.quote(str(value))


def activation_code(config: Config, project: Project) -> str:
    materialize(config, project)
    values = (
        project.name,
        project.visible_root,
        project.module_name,
        config.module_cache,
        project.python_environment or "",
        project.metadata_path,
        "1" if config.change_directory else "0",
        "1" if config.run_startup_hooks else "0",
        manager_for(config, project) if project.python_environment else "",
        "1" if config.restore_login_modules else "0",
        config.prompt.table(),
        "1" if config.prompt.hide_manager_prefix else "0",
    )
    return "_proj_activate " + " ".join(_q(value) for value in values)


def recorded_python(project: Project | None = None) -> tuple[str, str] | None:
    """The Python environment and manager this shell activated, from what the
    loaded project module exported, or None when this shell has no such module
    (then the project's current record is the only one there is). The record can
    differ from the project's document: someone changed it after this shell
    activated it, and the shell still holds what it was given."""
    if not os.environ.get("PROJ_MODULE"):
        return None
    return os.environ.get("PROJ_MAMBA_ENV", ""), os.environ.get("PROJ_PYTHON_MANAGER", "")


def environment_label(value: str, other: str = "") -> str:
    """A name for a Python environment in a message: the last component of a
    prefix, unless the other one would read the same."""
    if not value:
        return "none"
    if value.startswith("/"):
        short = os.path.basename(value.rstrip("/")) or value
        if short != os.path.basename(other.rstrip("/")):
            return short
    return value


def changed_python(config: Config, project: Project) -> tuple[str, str] | None:
    """(what this shell has, what the project has now) when they differ."""
    recorded = recorded_python(project)
    if recorded is None:
        return None
    current = project.python_environment or ""
    return (recorded[0], current) if recorded[0] != current else None


def orphan_deactivation_code(config: Config, name: str) -> str:
    # The environment was removed while active; its metadata is gone, so undo
    # the activation from the state the module exported into this shell.
    mamba_env = os.environ.get("PROJ_MAMBA_ENV", "")
    values = (
        name,
        os.environ.get("PROJ_MODULE", f"project/{name}"),
        config.module_cache,
        mamba_env,
        os.environ.get("PROJ_METADATA", ""),
        "1" if config.change_directory else "0",
        os.environ.get("PROJ_PYTHON_MANAGER") or config.python_manager if mamba_env else "",
    )
    return "_proj_deactivate " + " ".join(_q(value) for value in values)


def reapply_code(config: Config, project: Project) -> str:
    """Reload the active environment after its module list changed."""
    values = (
        project.name,
        project.module_name,
        config.module_cache,
        project.python_environment or "",
        manager_for(config, project) if project.python_environment else "",
    )
    return "_proj_reapply " + " ".join(_q(value) for value in values)


def deactivation_code(
    config: Config, project: Project, quiet: bool = False, force: bool = False
) -> str:
    """Leave the environment with what this shell recorded at activation: the
    Python environment it activated, not the one the project names now."""
    recorded = recorded_python(project)
    if recorded is None:
        environment = project.python_environment or ""
        manager = manager_for(config, project) if environment else ""
    else:
        environment = recorded[0]
        manager = (recorded[1] or manager_for(config, project)) if environment else ""
    values = (
        project.name,
        project.module_name,
        config.module_cache,
        environment,
        project.metadata_path,
        "1" if config.change_directory else "0",
        manager,
        "1" if quiet else "0",
        "1" if force else "0",
    )
    return "_proj_deactivate " + " ".join(_q(value) for value in values)


def reload_code(name: str) -> str:
    """Deactivate and activate again. An adapter from before `reload` existed
    has no `_proj_reload`; it is told what to do by hand."""
    return (
        f"if _proj_is_function _proj_reload; then _proj_reload {_q(name)}; "
        f"else _proj_log_error {_q('this shell integration is older than the proj it runs; run `proj deactivate`, then `proj activate ' + name + '`')}; "
        "false; fi"
    )
