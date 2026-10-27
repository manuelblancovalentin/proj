from __future__ import annotations

import os
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigError
from .metadata import PYTHON_MANAGERS

# The directory containing bin/, proj/, and shell/. Installers place the site
# configuration beneath it, so no installation path is hardcoded.
TOOL_ROOT = Path(__file__).resolve().parents[1]
CONFIG_KEYS = {
    "schema",
    "registry",
    "shared_registry",
    "group",
    "python_manager",
    "library_prefixes",
    "library_names",
    "project_roots",
    "module_cache",
    "behavior",
}

BEHAVIOR_KEYS = {"change_directory", "run_startup_hooks", "restore_login_modules"}


@dataclass(frozen=True)
class Config:
    proj_home: Path
    registry: Path
    project_roots: tuple[Path, ...]
    cache_home: Path
    module_cache: Path
    shared_registry: Path | None = None
    group: str | None = None
    site_config: Path | None = None
    python_manager: str = "micromamba"
    # Module-name prefixes and exact names that mark protected libraries;
    # machine-readable output never lists such names among ordinary modules
    # or bundles.
    library_prefixes: tuple[str, ...] = ("pdk-",)
    library_names: tuple[str, ...] = ()
    change_directory: bool = True
    run_startup_hooks: bool = True
    # Load back the modules a login had when an environment displaced them.
    restore_login_modules: bool = True

    def is_library(self, name: str) -> bool:
        """True for a protected library: listed by name, or starting with a prefix."""
        return name in self.library_names or any(
            name.startswith(prefix) for prefix in self.library_prefixes
        )


def _expand_path(value: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(value))).resolve()


def _read(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    if data.get("schema", 1) != 1:
        raise ConfigError(f"{path}: unsupported configuration schema: {data.get('schema')}")
    unknown = set(data) - CONFIG_KEYS
    if unknown:
        raise ConfigError(f"{path}: unknown configuration keys: " + ", ".join(sorted(unknown)))
    return data


def _optional_string(data: dict, key: str, source: str) -> str | None:
    value = data.get(key)
    if value is not None and (not isinstance(value, str) or not value):
        raise ConfigError(f"{source}: {key} must be a non-empty string")
    return value


def _home() -> Path:
    """The home directory, or a path that cannot exist when there is none.

    A service may run with no HOME and no passwd entry. Commands that only read
    (`proj list --json` with a site configuration) must still work there, and
    any command that tries to write under the missing home fails with an
    ordinary "no such directory" error.
    """
    try:
        return Path.home()
    except (RuntimeError, KeyError):
        return Path("/nonexistent-home")


def load_config() -> Config:
    xdg_config = Path(os.environ.get("XDG_CONFIG_HOME") or _home() / ".config")
    proj_home = _expand_path(os.environ.get("PROJ_HOME") or str(_home() / ".proj"))
    cache_home = _expand_path(
        os.environ.get("PROJ_CACHE_HOME") or str(_home() / ".cache" / "proj")
    )
    site_file = Path(
        os.environ.get("PROJ_SITE_CONFIG", TOOL_ROOT / "etc" / "config.toml")
    )
    config_file = Path(
        os.environ.get("PROJ_CONFIG", xdg_config / "proj" / "config.toml")
    )

    # User configuration overrides the site configuration key by key.
    site = _read(site_file)
    user = _read(config_file)
    data = {**site, **user}
    source = str(config_file if config_file.is_file() else site_file)
    behaviors = (site.get("behavior", {}), user.get("behavior", {}))
    if not all(isinstance(item, dict) for item in behaviors):
        raise ConfigError("behavior must be a table")
    behavior = {**behaviors[0], **behaviors[1]}
    unknown = sorted(set(behavior) - BEHAVIOR_KEYS)
    if unknown:
        raise ConfigError(f"unknown behavior key(s): {', '.join(unknown)}")
    for key in sorted(behavior):
        # A quoted "false" must not read as true: these switches are strict.
        if not isinstance(behavior[key], bool):
            raise ConfigError(f"behavior.{key} must be true or false")

    raw_registry = _optional_string(data, "registry", source)
    if "PROJ_HOME" in os.environ or not raw_registry:
        registry = proj_home / "envs"
    else:
        registry = _expand_path(raw_registry)

    raw_shared = os.environ.get("PROJ_SHARED_REGISTRY") or _optional_string(
        data, "shared_registry", source
    )
    shared_registry = _expand_path(raw_shared) if raw_shared else None
    group = os.environ.get("PROJ_GROUP") or _optional_string(data, "group", source)
    if shared_registry and not group:
        raise ConfigError(f"{source}: shared_registry requires group")

    python_manager = os.environ.get("PROJ_PYTHON_MANAGER") or _optional_string(
        data, "python_manager", source
    ) or "micromamba"
    if python_manager not in PYTHON_MANAGERS:
        raise ConfigError(
            f"{source}: python_manager must be one of: " + ", ".join(PYTHON_MANAGERS)
        )

    raw_prefixes = data.get("library_prefixes", ["pdk-"])
    if not isinstance(raw_prefixes, list) or not all(
        isinstance(item, str) and item for item in raw_prefixes
    ):
        raise ConfigError(f"{source}: library_prefixes must be an array of non-empty strings")
    raw_names = data.get("library_names", [])
    if not isinstance(raw_names, list) or not all(
        isinstance(item, str) and item and "/" not in item for item in raw_names
    ):
        raise ConfigError(
            f"{source}: library_names must be an array of module names without a version"
        )

    env_roots = os.environ.get("PROJ_PROJECT_ROOTS")
    raw_roots = env_roots.split(os.pathsep) if env_roots else data.get("project_roots", [])
    if not isinstance(raw_roots, list) or not all(
        isinstance(item, str) and item for item in raw_roots
    ):
        raise ConfigError("project_roots must be an array of non-empty strings")

    raw_module_cache = data.get("module_cache", str(cache_home / "modulefiles"))
    if not isinstance(raw_module_cache, str):
        raise ConfigError("module_cache must be a string")

    # Search order is also precedence: private, shared, then extra roots.
    roots: list[Path] = []
    for root in (registry, shared_registry, *map(_expand_path, raw_roots)):
        if root and root not in roots:
            roots.append(root)

    return Config(
        proj_home=proj_home,
        registry=registry,
        project_roots=tuple(roots),
        cache_home=cache_home,
        module_cache=_expand_path(raw_module_cache),
        shared_registry=shared_registry,
        group=group,
        site_config=site_file if site_file.is_file() else None,
        python_manager=python_manager,
        library_prefixes=tuple(raw_prefixes),
        library_names=tuple(raw_names),
        change_directory=bool(behavior.get("change_directory", True)),
        run_startup_hooks=bool(behavior.get("run_startup_hooks", True)),
        restore_login_modules=bool(behavior.get("restore_login_modules", True)),
    )
