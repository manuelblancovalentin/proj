"""Queries against the live Lmod installation."""

from __future__ import annotations

import os
import shutil
import subprocess

from .errors import ProjError


def lmod_command() -> str | None:
    command = os.environ.get("LMOD_CMD")
    if command and os.access(command, os.X_OK):
        return command
    return shutil.which("lmod")


def available_modules() -> list[str]:
    """Every module Lmod can load with the current MODULEPATH."""
    command = lmod_command()
    if not command:
        raise ProjError("Lmod is not available; set LMOD_CMD or initialize Lmod")
    completed = subprocess.run(
        [command, "bash", "--terse", "avail"],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        raise ProjError(completed.stderr.strip() or "module avail failed")
    modules = []
    # Terse output goes to stderr: "path:" headers, "name/" directory lines,
    # and one "name/version" per module, possibly followed by markers.
    for line in completed.stderr.splitlines():
        line = line.strip()
        if not line or line.endswith((":", "/")):
            continue
        modules.append(line.split()[0])
    return sorted(set(modules))
