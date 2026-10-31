"""What an environment was built from, and what a checkout is at.

proj does not build Python environments and is not a Git wrapper. This module
only hashes the dependency file an environment names (`python.spec`) against the
hash recorded when its maintainer last ran `proj python-env stamp`, and, when a
person asks with `--checkout`, reads a checkout's commit with three read-only
Git queries. Nothing is fetched, changed, or sent anywhere.
"""

from __future__ import annotations

import getpass
import hashlib
import os
import subprocess
from pathlib import Path

from .errors import ProjError
from .metadata import Project

GIT_TIMEOUT = 15


def file_digest(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def spec_path(project: Project) -> Path | None:
    return Path(project.expand(project.python_spec)) if project.python_spec else None


def stamper() -> str:
    try:
        return getpass.getuser()
    except Exception:  # no passwd entry for this uid
        return str(os.getuid())


def checkout_spec(project: Project, checkout: Path) -> Path:
    """The dependency file inside a checkout: the same file name at its top, or
    the file itself when the checkout argument names one."""
    if checkout.is_file():
        return checkout
    return checkout / spec_path(project).name


def freshness(project: Project, checkout: Path | None = None) -> dict:
    """Compare the dependency file with the hash recorded at the last stamp.

    state: no-spec (nothing declared), unreadable, unstamped, current, or behind
    (the file changed after the environment was stamped). With a checkout it
    also says whether that copy of the file matches the stamp, which is how a
    branch author learns the shared environment is behind their change.
    """
    spec = spec_path(project)
    if spec is None:
        return {"state": "no-spec"}
    stamp = project.python_stamp
    current = file_digest(spec)
    result: dict = {"spec": spec.name, "state": "unreadable"}
    if stamp:
        result["stamped_sha256"] = stamp.sha256
        result["stamped_date"] = stamp.date
    if current:
        result["current_sha256"] = current
        result["state"] = (
            "unstamped" if not stamp else "current" if current == stamp.sha256 else "behind"
        )
    if checkout is not None:
        mine = file_digest(checkout_spec(project, checkout))
        result["checkout_sha256"] = mine
        result["checkout_state"] = (
            "missing" if mine is None
            else "unstamped" if not stamp
            else "matches" if mine == stamp.sha256 else "differs"
        )
    return result


def describe(report: dict) -> str:
    state = report["state"]
    if state == "no-spec":
        return "no dependency file declared (proj config python.spec=/path/to/file)"
    stamped = report.get("stamped_date")
    text = {
        "unreadable": f"{report['spec']} cannot be read",
        "unstamped": f"{report['spec']}, never stamped (proj python-env stamp)",
        "current": f"{report['spec']}, stamped {stamped}, unchanged since",
        "behind": f"{report['spec']}, stamped {stamped}, changed since: the environment is behind it",
    }[state]
    if "checkout_state" in report:
        text += {
            "missing": "; the checkout has no copy of it",
            "unstamped": "",
            "matches": "; the checkout's copy matches the stamp",
            "differs": "; the checkout's copy differs from the stamp",
        }[report["checkout_state"]]
    return text


def _git(checkout: Path, *arguments: str) -> str:
    # core.fsmonitor can name a program to run; a read must not start one.
    command = [
        "git", "-C", str(checkout), "--no-optional-locks", "-c", "core.fsmonitor=false",
        *arguments,
    ]
    environment = dict(os.environ, GIT_TERMINAL_PROMPT="0", LC_ALL="C")
    try:
        done = subprocess.run(
            command, capture_output=True, text=True, timeout=GIT_TIMEOUT, env=environment
        )
    except FileNotFoundError as exc:
        raise ProjError("git is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise ProjError(f"git did not answer within {GIT_TIMEOUT} seconds in {checkout}") from exc
    if done.returncode != 0:
        detail = done.stderr.strip().splitlines()[-1:] or ["git failed"]
        raise ProjError(f"cannot read {checkout} as a Git checkout: {detail[0]}")
    return done.stdout


def git_state(checkout: Path) -> dict:
    """Commit, branch and whether the working tree differs from it (three
    read-only queries; no paths or user names in the answer)."""
    if not checkout.is_dir():
        raise ProjError(f"checkout is not a folder: {checkout}")
    commit = _git(checkout, "rev-parse", "HEAD").strip()
    branch = _git(checkout, "rev-parse", "--abbrev-ref", "HEAD").strip()
    changed = [line for line in _git(checkout, "status", "--porcelain").splitlines() if line]
    return {
        "commit": commit,
        "branch": None if branch == "HEAD" else branch,
        "dirty": bool(changed),
        "changed_files": len(changed),
    }
