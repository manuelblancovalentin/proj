"""Discovery of conda-family Python environments (micromamba, conda, mamba)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from .config import Config
from .errors import ProjError
from .metadata import Project


def manager_for(config: Config, project: Project | None = None) -> str:
    if project and project.python_manager:
        return project.python_manager
    return config.python_manager


def executable(manager: str) -> str | None:
    # Activation hooks export the executable they wrap: micromamba and mamba
    # set MAMBA_EXE, conda sets CONDA_EXE.
    exported = os.environ.get("CONDA_EXE" if manager == "conda" else "MAMBA_EXE")
    if exported and Path(exported).name == manager and os.access(exported, os.X_OK):
        return exported
    return shutil.which(manager)


def environments(manager: str) -> dict[str, Path]:
    """Map environment names to prefixes, naming the root prefix `base`."""
    program = executable(manager)
    if not program:
        raise ProjError(f"{manager} is not available")
    completed = subprocess.run(
        [program, "env", "list", "--json"],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        raise ProjError(completed.stderr.strip() or f"cannot list {manager} environments")
    try:
        paths = [Path(path) for path in json.loads(completed.stdout).get("envs", [])]
    except json.JSONDecodeError as exc:
        raise ProjError(f"{manager} returned invalid JSON") from exc
    # The root prefix is listed by path but activated as `base`. It is the
    # configured root, the directory holding named environments, or, for
    # conda and mamba, the installation containing the executable.
    roots = {
        Path(value)
        for value in (os.environ.get("MAMBA_ROOT_PREFIX"), os.environ.get("CONDA_ROOT"))
        if value
    }
    roots.update(path.parent.parent for path in paths if path.parent.name == "envs")
    if manager != "micromamba":
        roots.add(Path(program).resolve().parents[1])
    return {
        ("base" if path in roots else path.name): path
        for path in sorted(paths)
    }
