from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import access, python_envs
from .config import Config
from .discovery import scan
from .errors import ProjError


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def _writable_parent(path: Path) -> bool:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate.is_dir() and os.access(candidate, os.W_OK)


def run_checks(config: Config) -> list[Check]:
    lmod_cmd = os.environ.get("LMOD_CMD")
    lmod_path = Path(lmod_cmd) if lmod_cmd else None
    lmod_ok = bool(
        (lmod_path and lmod_path.is_file())
        or shutil.which("lmod")
        or shutil.which("modulecmd")
    )
    module_function = os.environ.get("PROJ_MODULE_FUNCTION") == "1"
    python_manager = python_envs.manager_for(config)
    python_program = python_envs.executable(python_manager)
    shell_adapter = os.environ.get("PROJ_SHELL_INTEGRATION", "")
    module_dirs = [
        path
        for path in os.environ.get("MODULEPATH", "").split(os.pathsep)
        if path and Path(path) != config.module_cache
    ]
    module_detail = "available"
    if not module_function:
        module_detail = "not initialized in this shell"
        # Exported Lmod variables survive starting zsh from bash; the module
        # function does not, so point at Lmod's own initialization script.
        lmod_pkg = os.environ.get("LMOD_PKG") or (
            str(lmod_path.parents[1]) if lmod_path else ""
        )
        init_script = Path(lmod_pkg) / "init" / (shell_adapter or "zsh")
        if lmod_pkg and init_script.is_file():
            module_detail += f"; add `source {init_script}` to your startup file"

    checks = [
        Check(
            "shell adapter",
            bool(shell_adapter),
            f"loaded ({shell_adapter})" if shell_adapter else "not loaded; run `proj init`",
        ),
        Check("Lmod", lmod_ok, lmod_cmd or shutil.which("lmod") or "not installed"),
        Check(
            "module function",
            module_function,
            module_detail,
        ),
        Check(
            "module path",
            bool(module_dirs),
            ", ".join(module_dirs)
            or "MODULEPATH lists no module directories; `module use <dir>` adds one to this "
            "shell, and the site init should add it for every shell",
        ),
        Check(
            "python manager",
            bool(python_program),
            f"{python_manager}: {python_program or 'not installed'}",
        ),
        Check(
            "module cache",
            _writable_parent(config.module_cache),
            str(config.module_cache),
        ),
    ]
    checks.append(
        Check("site config", True, str(config.site_config or "none"))
    )
    existing_roots = [root for root in config.project_roots if root.is_dir()]
    checks.append(
        Check(
            "project roots",
            bool(existing_roots),
            ", ".join(map(str, existing_roots)) or "none exist",
        )
    )
    if config.shared_registry:
        try:
            access.shared_registry(config)
            checks.append(
                Check(
                    "shared registry",
                    True,
                    f"{config.shared_registry} (group {config.group})",
                )
            )
        except ProjError as exc:
            checks.append(Check("shared registry", False, str(exc)))
    try:
        found = scan(config)
        problems = "; ".join(problem for _path, problem in found.problems)
        checks.append(
            Check(
                "metadata",
                not problems,
                problems or f"{len(found.projects)} project(s) valid",
            )
        )
    except ProjError as exc:
        checks.append(Check("metadata", False, str(exc)))
    return checks
