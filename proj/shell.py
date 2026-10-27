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
        project.root,
        project.module_name,
        config.module_cache,
        project.python_environment or "",
        project.metadata_path,
        "1" if config.change_directory else "0",
        "1" if config.run_startup_hooks else "0",
        manager_for(config, project) if project.python_environment else "",
    )
    return "_proj_activate " + " ".join(_q(value) for value in values)


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
        config.python_manager if mamba_env else "",
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


def deactivation_code(config: Config, project: Project) -> str:
    values = (
        project.name,
        project.module_name,
        config.module_cache,
        project.python_environment or "",
        project.metadata_path,
        "1" if config.change_directory else "0",
        manager_for(config, project) if project.python_environment else "",
    )
    return "_proj_deactivate " + " ".join(_q(value) for value in values)
