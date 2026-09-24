from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__
from .config import Config, load_config
from .discovery import discover, resolve
from .doctor import run_checks
from .editor import (
    create_document,
    get_dotted,
    load_document,
    parse_value,
    set_dotted,
    write_document,
)
from .errors import ProjError
from .metadata import MODULE_CATEGORIES, NAME_RE, Project, load_project
from .modulefile import materialize, render
from .shell import activation_code, deactivation_code


def _table(headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> None:
    widths = [
        max(len(headers[i]), *(len(row[i]) for row in rows))
        if rows
        else len(headers[i])
        for i in range(len(headers))
    ]
    print("  ".join(value.ljust(widths[i]) for i, value in enumerate(headers)))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print("  ".join(value.ljust(widths[i]) for i, value in enumerate(row)))


def cmd_list(config: Config, _args: argparse.Namespace) -> int:
    projects = discover(config)
    rows = [
        (project.name, project.description, str(project.root))
        for project in sorted(projects.values(), key=lambda item: item.name)
    ]
    _table(("NAME", "DESCRIPTION", "ROOT"), rows)
    return 0


def cmd_complete(config: Config, args: argparse.Namespace) -> int:
    if args.entity == "projects":
        for name in sorted(discover(config)):
            print(name)
    return 0


def cmd_current(_config: Config, _args: argparse.Namespace) -> int:
    active = os.environ.get("PROJ_ACTIVE")
    if not active:
        return 1
    print(active)
    return 0


def cmd_create(config: Config, args: argparse.Namespace) -> int:
    if not NAME_RE.fullmatch(args.name):
        raise ProjError(
            "project names may contain letters, numbers, dots, underscores, and dashes"
        )
    root = Path(args.root or os.getcwd()).expanduser().resolve()
    if not root.is_dir():
        raise ProjError(f"project root does not exist: {root}")
    metadata_path = config.proj_home / "envs" / args.name / "project.toml"
    create_document(metadata_path, args.name, root)
    # Validate the generated document before reporting success.
    load_project(metadata_path)
    print(f"Environment {args.name!r} successfully created.")
    print(f"Metadata and configuration present at {metadata_path}")
    print(f"Activate it with: proj activate {args.name}")
    return 0


def _selected_project(config: Config, requested: str | None) -> Project:
    name = requested or os.environ.get("PROJ_ACTIVE")
    if not name:
        raise ProjError(
            "no project environment active; activate one or pass --env <name>"
        )
    return resolve(config, name)


def _info_rows(project: Project) -> list[tuple[str, str]]:
    rows = [
        ("Description", project.description),
        ("Root", str(project.root)),
        ("Metadata", str(project.metadata_path)),
        ("Shell", project.shell),
        ("Python manager", project.python_manager or "not configured"),
        ("Python environment", project.python_environment or "not configured"),
    ]
    for category in MODULE_CATEGORIES:
        rows.append(
            (
                f"{category.title()} modules",
                ", ".join(project.modules.get(category, ())) or "none",
            )
        )
    rows.extend(
        (f"Variable {key}", project.expand(value))
        for key, value in sorted(project.environment.items())
    )
    rows.extend(("PATH prepend", project.expand(value)) for value in project.prepend_paths)
    rows.extend(
        (f"Alias {key}", project.expand(value))
        for key, value in sorted(project.aliases.items())
    )
    rows.extend(
        ("Startup hook", shlex.join(project.expand(v) for v in hook.argv))
        for hook in project.startup_hooks
    )
    rows.extend(
        ("Shutdown hook", shlex.join(project.expand(v) for v in hook.argv))
        for hook in project.shutdown_hooks
    )
    rows.extend(
        (f"Task {name}", f"{command.description} (execution deferred)")
        for name, command in sorted(project.commands.items())
    )
    return rows


def cmd_info(config: Config, args: argparse.Namespace) -> int:
    project = _selected_project(config, args.project)
    print(f"Project environment: {project.name}")
    _table(("FIELD", "VALUE"), _info_rows(project))
    return 0


def cmd_info_code(config: Config, args: argparse.Namespace) -> int:
    project = _selected_project(config, args.project)
    values = [project.name]
    for label, value in _info_rows(project):
        values.extend((label, value))
    print("_proj_render_info " + " ".join(shlex.quote(value) for value in values))
    return 0


def _update_document(project: Project, mutate) -> None:
    path = project.metadata_path
    original = path.read_text()
    data = load_document(path)
    mutate(data)
    try:
        write_document(path, data)
        load_project(path)
    except Exception:
        path.write_text(original)
        raise


def cmd_config(config: Config, args: argparse.Namespace) -> int:
    project = _selected_project(config, args.project)
    assignment = args.assignment
    raw_value = args.value
    if "=" in assignment:
        if raw_value is not None:
            raise ProjError("use either key=value or key value, not both")
        assignment, raw_value = assignment.split("=", 1)
    if raw_value is None:
        value = get_dotted(load_document(project.metadata_path), assignment)
        if isinstance(value, (dict, list)):
            print(json.dumps(value, ensure_ascii=False))
        else:
            print(value)
        return 0
    value = parse_value(raw_value)
    _update_document(project, lambda data: set_dotted(data, assignment, value))
    print(f"Updated {assignment} in {project.metadata_path}")
    if os.environ.get("PROJ_ACTIVE") == project.name:
        print("Reactivate the project to apply environment changes.")
    return 0


def _micromamba_environments() -> list[str]:
    executable = os.environ.get("MAMBA_EXE") or shutil.which("micromamba")
    if not executable:
        raise ProjError("micromamba is not available")
    completed = subprocess.run(
        [executable, "env", "list", "--json"],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        raise ProjError(completed.stderr.strip() or "cannot list micromamba environments")
    try:
        paths = json.loads(completed.stdout).get("envs", [])
    except json.JSONDecodeError as exc:
        raise ProjError("micromamba returned invalid JSON") from exc
    return sorted({Path(path).name for path in paths})


def cmd_python_env_list(_config: Config, _args: argparse.Namespace) -> int:
    environments = _micromamba_environments()
    if not environments:
        print("No micromamba environments found.")
        return 0
    for name in environments:
        print(name)
    return 0


def cmd_set_python_env(config: Config, args: argparse.Namespace) -> int:
    project = _selected_project(config, args.project)
    available = _micromamba_environments()
    if args.environment not in available:
        raise ProjError(
            f"unknown micromamba environment {args.environment!r}; "
            "run `proj python-env list`"
        )

    def mutate(data):
        set_dotted(data, "python.manager", "micromamba")
        set_dotted(data, "python.environment", args.environment)

    _update_document(project, mutate)
    print(f"Linked micromamba environment {args.environment!r} to {project.name}.")
    print(f"Metadata updated at {project.metadata_path}")
    return 0


def cmd_module(config: Config, args: argparse.Namespace) -> int:
    project = _selected_project(config, args.project)
    if args.category not in MODULE_CATEGORIES:
        raise ProjError(
            "module category must be one of: " + ", ".join(MODULE_CATEGORIES)
        )
    data = load_document(project.metadata_path)
    values = list(data.get("modules", {}).get(args.category, []))
    if args.module_action == "list":
        for value in values:
            print(value)
        return 0
    if args.module_action == "add":
        if args.module not in values:
            values.append(args.module)
    else:
        if args.module not in values:
            raise ProjError(
                f"module {args.module!r} is not configured in {args.category}"
            )
        values.remove(args.module)
    _update_document(
        project,
        lambda document: set_dotted(
            document, f"modules.{args.category}", values
        ),
    )
    print(
        f"{'Added' if args.module_action == 'add' else 'Removed'} "
        f"{args.module!r} {'to' if args.module_action == 'add' else 'from'} "
        f"{project.name!r} {args.category} modules."
    )
    return 0


def _loaded_modules() -> set[str]:
    return {item for item in os.environ.get("LOADEDMODULES", "").split(":") if item}


def cmd_status(config: Config, _args: argparse.Namespace) -> int:
    active = os.environ.get("PROJ_ACTIVE")
    if not active:
        print("No project active.")
        return 0
    project = resolve(config, active)
    loaded = _loaded_modules()
    expected = {
        module
        for category in MODULE_CATEGORIES
        for module in project.modules.get(category, ())
    }
    module_loaded = project.module_name in loaded or os.environ.get("PROJ_MODULE") == project.module_name
    current_env = os.environ.get("CONDA_DEFAULT_ENV", "")
    drift = []
    if not module_loaded:
        drift.append("project module is not loaded")
    missing = expected - loaded
    if missing:
        drift.append("missing modules: " + ", ".join(sorted(missing)))
    if project.python_environment and current_env != project.python_environment:
        drift.append(
            f"micromamba environment is {current_env or 'inactive'}, "
            f"expected {project.python_environment}"
        )
    print(f"Project:      {project.name}")
    print(f"Root:         {project.root}")
    print(f"Metadata:     {project.metadata_path}")
    print(f"Lmod module:  {project.module_name}")
    print(f"Micromamba:   {project.python_environment or 'not configured'}")
    print(f"State:        {'drift: ' + '; '.join(drift) if drift else 'consistent'}")
    return 2 if drift else 0


def _module_state(config: Config, project: Project) -> str:
    output = config.module_cache / "project" / f"{project.name}.lua"
    digest_file = output.with_suffix(".sha256")
    expected = hashlib.sha256(render(project).encode()).hexdigest()
    if not output.is_file() or not digest_file.is_file():
        return "missing"
    return "current" if digest_file.read_text().strip() == expected else "stale"


def cmd_env_list(config: Config, _args: argparse.Namespace) -> int:
    projects = discover(config)
    rows = [
        (item.name, item.module_name, _module_state(config, item))
        for item in sorted(projects.values(), key=lambda value: value.name)
    ]
    _table(("PROJECT", "MODULE", "STATE"), rows)
    return 0


def cmd_env_show(config: Config, args: argparse.Namespace) -> int:
    project = resolve(config, args.project)
    output, changed = materialize(config, project)
    print(f"Name:          {project.name}")
    print(f"Description:   {project.description}")
    print(f"Root:          {project.root}")
    print(f"Metadata:      {project.metadata_path}")
    print(f"Shell:         {project.shell}")
    print(f"Modulefile:    {output} ({'generated' if changed else 'current'})")
    print(f"Micromamba:    {project.python_environment or 'not configured'}")
    for category in MODULE_CATEGORIES:
        values = ", ".join(project.modules.get(category, ())) or "-"
        print(f"{category.title():<14}{values}")
    print("Environment:")
    for key, value in sorted(project.environment.items()):
        print(f"  {key}={project.expand(value)}")
    print("Paths:")
    for value in project.prepend_paths:
        print(f"  {project.expand(value)}")
    print("Aliases:")
    for key, value in sorted(project.aliases.items()):
        print(f"  {key}={project.expand(value)}")
    print("Hooks:")
    for phase, hooks in (
        ("startup", project.startup_hooks),
        ("shutdown", project.shutdown_hooks),
    ):
        for hook in hooks:
            print(f"  {phase}: {shlex.join(project.expand(v) for v in hook.argv)}")
    print("Commands (execution deferred):")
    for name, command in sorted(project.commands.items()):
        print(f"  {name}: {command.description}")
    return 0


def cmd_doctor(config: Config, _args: argparse.Namespace) -> int:
    failed = False
    for check in run_checks(config):
        mark = "ok" if check.ok else "FAIL"
        print(f"{mark:<4} {check.name:<18} {check.detail}")
        failed |= not check.ok
    return 1 if failed else 0


def _install_link() -> int:
    root = Path(__file__).resolve().parents[1]
    global_bin = Path(os.environ.get("PROJ_GLOBAL_BIN", root.parent / "bin"))
    global_man = Path(
        os.environ.get("PROJ_GLOBAL_MAN", global_bin.parent / "share" / "man")
    )
    global_tldr = Path(
        os.environ.get("PROJ_GLOBAL_TLDR", global_man.parent / "tldr")
    )

    links = (
        (global_bin / "proj", Path("../proj/bin/proj")),
        (
            global_man / "man1" / "proj.1",
            Path("../../../proj/share/man/man1/proj.1"),
        ),
        (
            global_tldr / "pages" / "common" / "proj.md",
            Path("../../../../proj/share/tldr/pages/common/proj.md"),
        ),
    )

    def validate_link(destination: Path, target: Path) -> bool:
        if destination.is_symlink():
            if os.readlink(destination) == str(target):
                return False
            raise ProjError(
                f"refusing to replace symlink {destination} -> "
                f"{os.readlink(destination)}"
            )
        if destination.exists():
            raise ProjError(f"refusing to replace existing path {destination}")
        return True

    pending = [
        (destination, target)
        for destination, target in links
        if validate_link(destination, target)
    ]
    for destination, target in pending:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.symlink_to(target)
    print(f"proj: command exposed in {global_bin}")
    print(f"proj: manual exposed in {global_man / 'man1'}")
    print(f"proj: TLDR page exposed in {global_tldr / 'pages' / 'common'}")
    return 0


def cmd_hook(config: Config, args: argparse.Namespace) -> int:
    project = resolve(config, args.project)
    hooks = project.startup_hooks if args.phase == "startup" else project.shutdown_hooks
    for hook in hooks:
        argv = [project.expand(value) for value in hook.argv]
        completed = subprocess.run(argv, cwd=project.root, check=False)
        if completed.returncode:
            return completed.returncode
    return 0


def cmd_shell(config: Config, args: argparse.Namespace) -> int:
    if args.action == "activate":
        if os.environ.get("PROJ_ACTIVE"):
            raise ProjError(
                f"project {os.environ['PROJ_ACTIVE']!r} is already active; deactivate it first"
            )
        project = resolve(config, args.project)
        print(activation_code(config, project))
        return 0
    active = os.environ.get("PROJ_ACTIVE")
    if not active:
        print("_proj_no_active")
        return 0
    project = resolve(config, active)
    print(deactivation_code(config, project))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="proj")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list registered projects")
    sub.add_parser("status", help="show active project state")
    sub.add_parser("current", help="print the active project name")
    sub.add_parser("doctor", help="check dependencies and integration")
    sub.add_parser("install", help="expose proj through /tools/bin")
    info_parser = sub.add_parser("info", help="show project environment metadata")
    info_parser.add_argument(
        "--env", "--project", dest="project", metavar="NAME"
    )
    create = sub.add_parser("create", help="register a project environment")
    create.add_argument("name")
    create.add_argument("--root")
    config_parser = sub.add_parser("config", help="read or write project metadata")
    config_parser.add_argument(
        "--env", "--project", dest="project", metavar="NAME"
    )
    config_parser.add_argument("assignment")
    config_parser.add_argument("value", nargs="?")
    set_python = sub.add_parser(
        "set-python-env", help="link an existing micromamba environment"
    )
    set_python.add_argument("environment")
    set_python.add_argument(
        "--env", "--project", dest="project", metavar="NAME"
    )
    python_env = sub.add_parser(
        "python-env", help="inspect available Python environments"
    )
    python_env_sub = python_env.add_subparsers(
        dest="python_env_command", required=True
    )
    python_env_sub.add_parser("list")
    module = sub.add_parser("module", help="manage project module dependencies")
    module.add_argument("module_action", choices=("list", "add", "remove"))
    module.add_argument("category", choices=MODULE_CATEGORIES)
    module.add_argument("module", nargs="?")
    module.add_argument(
        "--env", "--project", dest="project", metavar="NAME"
    )
    env = sub.add_parser("env", help="inspect generated Lmod environments")
    env_sub = env.add_subparsers(dest="env_command", required=True)
    env_sub.add_parser("list")
    show = env_sub.add_parser("show")
    show.add_argument("project")
    activate = sub.add_parser("activate", help="activate a project")
    activate.add_argument("project")
    sub.add_parser("deactivate", help="deactivate the current project")
    shell = sub.add_parser("_shell", help=argparse.SUPPRESS)
    shell.add_argument("action", choices=("activate", "deactivate"))
    shell.add_argument("project", nargs="?")
    hook = sub.add_parser("_hook", help=argparse.SUPPRESS)
    hook.add_argument("phase", choices=("startup", "shutdown"))
    hook.add_argument("project")
    complete = sub.add_parser("_complete", help=argparse.SUPPRESS)
    complete.add_argument("entity", choices=("projects",))
    info_code = sub.add_parser("_info-code", help=argparse.SUPPRESS)
    info_code.add_argument(
        "--env", "--project", dest="project", metavar="NAME"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = load_config()
        if args.command == "list":
            return cmd_list(config, args)
        if args.command == "_complete":
            return cmd_complete(config, args)
        if args.command == "info":
            return cmd_info(config, args)
        if args.command == "_info-code":
            return cmd_info_code(config, args)
        if args.command == "status":
            return cmd_status(config, args)
        if args.command == "current":
            return cmd_current(config, args)
        if args.command == "create":
            return cmd_create(config, args)
        if args.command == "config":
            return cmd_config(config, args)
        if args.command == "python-env" and args.python_env_command == "list":
            return cmd_python_env_list(config, args)
        if args.command == "set-python-env":
            return cmd_set_python_env(config, args)
        if args.command == "module":
            if args.module_action != "list" and not args.module:
                raise ProjError("module add/remove requires a module specification")
            return cmd_module(config, args)
        if args.command == "doctor":
            return cmd_doctor(config, args)
        if args.command == "install":
            return _install_link()
        if args.command == "env" and args.env_command == "list":
            return cmd_env_list(config, args)
        if args.command == "env" and args.env_command == "show":
            return cmd_env_show(config, args)
        if args.command == "_hook":
            return cmd_hook(config, args)
        if args.command == "_shell":
            if args.action == "activate" and not args.project:
                raise ProjError("activate requires a project")
            return cmd_shell(config, args)
        if args.command in {"activate", "deactivate"}:
            raise ProjError(
                f"{args.command} must run through the Zsh integration; "
                "source /tools/proj/shell/init.zsh"
            )
        parser.error("unhandled command")
    except ProjError as exc:
        print(f"proj: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
