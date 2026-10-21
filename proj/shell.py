from __future__ import annotations

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
