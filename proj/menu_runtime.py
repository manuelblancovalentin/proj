"""The private runtime of `proj configmenu`.

The menu is the one part of proj that uses third-party code (Textual, which
brings Rich). It runs from a virtual environment owned by this installation,
<root>/libexec/menu, so neither a project's Python environment nor the
system's packages can change it, and the rest of proj never imports it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .config import TOOL_ROOT
from .errors import ProjError

REQUIREMENT = "textual==8.2.8"
MENU_DIR = TOOL_ROOT / "libexec" / "menu"
MENU_PYTHON = MENU_DIR / "bin" / "python"
MARKER = MENU_DIR / ".proj-requirement"

# Replace the working directory on sys.path with the tool root, as bin/proj
# does, then start the menu.
BOOTSTRAP = """
import sys
sys.path[0] = sys.argv.pop(1)
from proj.menu import main
raise SystemExit(main(sys.argv[1:]))
"""


def installed() -> bool:
    return (
        MENU_PYTHON.is_file()
        and MARKER.is_file()
        and MARKER.read_text().strip() == REQUIREMENT
    )


def setup_hint() -> str:
    command = f"{TOOL_ROOT}/bin/proj configmenu --setup"
    if not os.access(TOOL_ROOT, os.W_OK):
        return f"ask an administrator to run `sudo {command}`"
    return f"run `{command}` (needs network access)"


def setup() -> None:
    libexec = TOOL_ROOT / "libexec"
    if not os.access(libexec if libexec.exists() else TOOL_ROOT, os.W_OK):
        raise ProjError(f"cannot write {MENU_DIR}; {setup_hint()}")
    libexec.mkdir(exist_ok=True)
    if not MENU_PYTHON.is_file():
        print(f"proj: creating {MENU_DIR}")
        created = subprocess.run([sys.executable, "-m", "venv", str(MENU_DIR)], check=False)
        if created.returncode:
            raise ProjError(
                "cannot create a virtual environment; install your distribution's "
                "venv support (for example `apt install python3-venv`)"
            )
    print(f"proj: installing {REQUIREMENT}")
    installed_ok = subprocess.run(
        [
            str(MENU_PYTHON),
            "-m",
            "pip",
            "install",
            "--quiet",
            "--disable-pip-version-check",
            REQUIREMENT,
        ],
        check=False,
    )
    if installed_ok.returncode:
        raise ProjError(f"could not install {REQUIREMENT}")
    MARKER.write_text(REQUIREMENT + "\n")
    # Shared installations are used by everyone who can run proj.
    for path in (MENU_DIR, *MENU_DIR.rglob("*")):
        if not path.is_symlink():
            mode = os.stat(path).st_mode
            executable = path.is_dir() or mode & 0o100
            os.chmod(path, mode | 0o044 | (0o011 if executable else 0))
    print("proj: configuration menu ready; run `proj configmenu`")


def launch(name: str) -> None:
    if not installed():
        raise ProjError(f"the configuration menu is not installed; {setup_hint()}")
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise ProjError("proj configmenu needs an interactive terminal")
    python = str(MENU_PYTHON)
    os.execv(python, [python, "-c", BOOTSTRAP, str(TOOL_ROOT), name])
