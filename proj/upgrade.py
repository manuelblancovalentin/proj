"""`proj upgrade`: reinstall proj from its source repository.

Downloads the archive for the configured repository and ref, compares its
version with the installed one, and runs that archive's own install.sh
against this installation with the options the installation was made with.
Configuration, shell startup files, and the optional configuration-menu
runtime are left alone; the previous version is kept for rollback.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

from . import __version__
from .config import TOOL_ROOT
from .errors import ProjError

DEFAULT_REPO = "manuelblancovalentin/proj"
DEFAULT_REF = "master"
MARKER = ".proj-install"
# What install.sh replaces; kept in sync with INSTALLED_ITEMS there.
INSTALLED_ITEMS = ("bin", "proj", "shell", "share", "templates", "docs", "README.md")
PREVIOUS = ".previous"
_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_REF = re.compile(r"^[A-Za-z0-9_.][A-Za-z0-9_./-]*$")


def _read_toml(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ProjError(f"cannot read {path}: {exc}") from exc


def settings(ref: str | None = None) -> tuple[str, str]:
    """The repository and ref to upgrade from.

    The command line wins, then PROJ_REPO and PROJ_REF, then the choice the
    installer recorded in etc/source.toml, then the defaults.
    """
    recorded = _read_toml(TOOL_ROOT / "etc" / "source.toml")
    repo = os.environ.get("PROJ_REPO") or recorded.get("repo") or DEFAULT_REPO
    chosen = ref or os.environ.get("PROJ_REF") or recorded.get("ref") or DEFAULT_REF
    if not isinstance(repo, str) or not _REPO.fullmatch(repo):
        raise ProjError(f"invalid repository {repo!r}; expected owner/name")
    if not isinstance(chosen, str) or not _REF.fullmatch(chosen) or ".." in chosen:
        raise ProjError(f"invalid ref {chosen!r}")
    return repo, chosen


def archive_url(repo: str, ref: str) -> str:
    base = os.environ.get("PROJ_UPGRADE_BASE", "https://github.com").rstrip("/")
    return f"{base}/{repo}/archive/{urllib.parse.quote(ref, safe='/')}.tar.gz"


def _download(url: str, destination: Path) -> None:
    try:
        with urllib.request.urlopen(url, timeout=60) as response, destination.open("wb") as out:
            shutil.copyfileobj(response, out)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise ProjError(
                f"{url} was not found: check the repository and ref (a private repository "
                "cannot be downloaded without credentials)"
            ) from exc
        raise ProjError(f"cannot download {url}: HTTP {exc.code}") from exc
    except (urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise ProjError(f"cannot download {url}: {reason}") from exc


def _extract(archive: Path, destination: Path) -> Path:
    destination.mkdir(parents=True)
    try:
        with tarfile.open(archive) as bundle:
            if hasattr(tarfile, "data_filter"):
                bundle.extractall(destination, filter="data")
            else:
                root = destination.resolve()
                for member in bundle.getmembers():
                    target = (destination / member.name).resolve()
                    if (
                        member.issym()
                        or member.islnk()
                        or (target != root and root not in target.parents)
                    ):
                        raise ProjError(f"refusing unsafe archive member {member.name!r}")
                bundle.extractall(destination)
    except tarfile.TarError as exc:
        raise ProjError(f"the downloaded file is not a valid archive: {exc}") from exc
    entries = list(destination.iterdir())
    if len(entries) != 1 or not entries[0].is_dir():
        raise ProjError("the downloaded archive does not have the expected layout")
    return entries[0]


def _version_of(source: Path) -> str:
    try:
        text = (source / "proj" / "__init__.py").read_text()
    except OSError as exc:
        raise ProjError("the downloaded archive is not a proj source tree") from exc
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.M)
    if not match:
        raise ProjError("cannot read the version of the downloaded archive")
    return match.group(1)


def _numbers(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", version))


def _require_installation() -> None:
    if (TOOL_ROOT / ".git").exists():
        raise ProjError(
            f"{TOOL_ROOT} is a git checkout, not an installation made by install.sh; "
            "update it with `git pull`"
        )
    if not (TOOL_ROOT / MARKER).is_file():
        raise ProjError(
            f"{TOOL_ROOT} was not installed by install.sh, so it cannot be upgraded in place"
        )


def _installer_options() -> list[str]:
    """Reuse the choices the installation was made with."""
    site = _read_toml(TOOL_ROOT / "etc" / "config.toml")
    if site.get("shared_registry") and site.get("group"):
        return ["--mode", "shared", "--group", str(site["group"])]
    return ["--mode", "private"]


def _keep_previous() -> Path:
    previous = TOOL_ROOT / PREVIOUS
    if previous.exists():
        shutil.rmtree(previous)
    previous.mkdir()
    for item in (*INSTALLED_ITEMS, MARKER):
        source = TOOL_ROOT / item
        if source.is_dir():
            shutil.copytree(source, previous / item, symlinks=True)
        elif source.exists():
            shutil.copy2(source, previous / item)
    return previous


def _confirm(question: str) -> bool:
    try:
        answer = input(f"{question} [y/N]: ")
    except EOFError:
        return False
    return answer.strip().lower() in {"y", "yes"}


def run(*, ref: str | None = None, check: bool = False, yes: bool = False, force: bool = False) -> int:
    _require_installation()
    repo, chosen = settings(ref)
    url = archive_url(repo, chosen)
    installed = __version__
    with tempfile.TemporaryDirectory(prefix="proj-upgrade.") as work:
        print(f"Checking {repo}@{chosen} …")
        archive = Path(work) / "proj.tar.gz"
        _download(url, archive)
        source = _extract(archive, Path(work) / "src")
        available = _version_of(source)

        newer = _numbers(available) > _numbers(installed)
        same = available == installed
        if check:
            if newer:
                print(f"proj {installed} is installed; {available} is available from {repo}@{chosen}.")
                print("Run `proj upgrade` to install it.")
                return 1
            print(f"proj {installed} is up to date with {repo}@{chosen} ({available}).")
            return 0
        if same and not force:
            print(f"proj {installed} is already up to date with {repo}@{chosen}. Use --force to reinstall it.")
            return 0
        if not same and not newer and not force:
            raise ProjError(
                f"installed proj {installed} is newer than {available} from {repo}@{chosen}; "
                "use --force to downgrade"
            )
        if not os.access(TOOL_ROOT, os.W_OK):
            raise ProjError(
                f"cannot write {TOOL_ROOT}; run `sudo {TOOL_ROOT}/bin/proj upgrade` "
                "(sudo needs the full path)"
            )

        print(f"Upgrade proj {installed} -> {available} in {TOOL_ROOT} from {repo}@{chosen}")
        if not yes:
            if not sys.stdin.isatty():
                raise ProjError("refusing to upgrade without confirmation; pass --yes")
            if not _confirm("Proceed?"):
                print("Nothing changed.")
                return 1

        installer = source / "install.sh"
        if not installer.is_file():
            raise ProjError("the downloaded archive has no install.sh")
        previous = _keep_previous()
        command = [
            "sh",
            str(installer),
            "--yes",
            "--prefix",
            str(TOOL_ROOT),
            *_installer_options(),
            "--no-init",
            "--no-system-init",
            "--no-install-deps",
        ]
        environment = {**os.environ, "PROJ_REPO": repo, "PROJ_REF": chosen}
        completed = subprocess.run(command, env=environment, check=False)
        if completed.returncode:
            raise ProjError(
                "the installer failed; the previous version is in "
                f"{previous}. Copy its contents back over {TOOL_ROOT}, or run `proj upgrade` again"
            )
        launcher = str(TOOL_ROOT / "bin" / "proj")
    print(f"Previous version kept in {previous} (copy its contents back over {TOOL_ROOT} to roll back).")
    subprocess.run([launcher, "--version"], check=False)
    print("Open a new shell to load the updated shell integration and completion.")
    return 0
