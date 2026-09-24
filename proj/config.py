from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigError


@dataclass(frozen=True)
class Config:
    proj_home: Path
    project_roots: tuple[Path, ...]
    cache_home: Path
    module_cache: Path
    change_directory: bool = True
    run_startup_hooks: bool = True


def _expand_path(value: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(value))).resolve()


def load_config() -> Config:
    xdg_config = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    proj_home = _expand_path(
        os.environ.get("PROJ_HOME", str(Path.home() / ".proj"))
    )
    registry = proj_home / "envs"
    cache_home = _expand_path(
        os.environ.get("PROJ_CACHE_HOME", str(Path.home() / ".cache" / "proj"))
    )
    config_file = Path(
        os.environ.get("PROJ_CONFIG", xdg_config / "proj" / "config.toml")
    )
    env_roots = os.environ.get("PROJ_PROJECT_ROOTS")

    data: dict = {}
    if config_file.is_file():
        try:
            with config_file.open("rb") as handle:
                data = tomllib.load(handle)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ConfigError(f"cannot read {config_file}: {exc}") from exc

    if data and data.get("schema", 1) != 1:
        raise ConfigError(f"unsupported configuration schema: {data.get('schema')}")

    raw_roots = (
        env_roots.split(os.pathsep)
        if env_roots
        else data.get("project_roots", [str(registry)])
    )
    if not isinstance(raw_roots, list) or not all(
        isinstance(item, str) and item for item in raw_roots
    ):
        raise ConfigError("project_roots must be an array of non-empty strings")

    raw_module_cache = data.get("module_cache", str(cache_home / "modulefiles"))
    if not isinstance(raw_module_cache, str):
        raise ConfigError("module_cache must be a string")
    behavior = data.get("behavior", {})
    if not isinstance(behavior, dict):
        raise ConfigError("behavior must be a table")

    roots = [_expand_path(item) for item in raw_roots]
    if registry not in roots:
        roots.insert(0, registry)

    return Config(
        proj_home=proj_home,
        project_roots=tuple(roots),
        cache_home=cache_home,
        module_cache=_expand_path(raw_module_cache),
        change_directory=bool(behavior.get("change_directory", True)),
        run_startup_hooks=bool(behavior.get("run_startup_hooks", True)),
    )
