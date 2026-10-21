from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import access
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
    mamba = shutil.which("micromamba") or os.environ.get("MAMBA_EXE")
    shell_adapter = os.environ.get("PROJ_SHELL_INTEGRATION", "")

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
            "available" if module_function else "not initialized in this shell",
        ),
        Check("micromamba", bool(mamba), mamba or "not installed"),
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
