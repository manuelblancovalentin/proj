from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
from pathlib import Path

from . import __version__
from . import access, lmod, menu_runtime, python_envs
from .config import TOOL_ROOT, Config, load_config
from .discovery import discover, resolve, scan
from .doctor import run_checks
from .editor import (
    create_document,
    get_dotted,
    load_document,
    parse_value,
    set_dotted,
    update_document,
)
from .errors import ProjError
from .metadata import (
    MODULE_CATEGORIES,
    NAME_RE,
    PYTHON_MANAGERS,
    SHELLS,
    Project,
    load_project,
)
from .modulefile import materialize, render
from .render import Output
from .shell import activation_code, deactivation_code, orphan_deactivation_code


def _table(headers, rows, title=None, flex=None, styles=None) -> None:
    Output().print_table(headers, rows, title=title, flex=flex, styles=styles)


def _environment_rows(config: Config, projects) -> list[tuple[str, ...]]:
    return [
        (
            project.name,
            access.scope(config, project),
            access.project_owner(project),
            project.description,
            str(project.root),
        )
        for project in sorted(projects, key=lambda item: item.name)
    ]


NO_ENVIRONMENTS = "No environments yet. In a project directory, run: proj create <name>"


def cmd_list(config: Config, _args: argparse.Namespace) -> int:
    found = scan(config)
    if found.projects:
        _table(
            ("NAME", "SCOPE", "OWNER", "DESCRIPTION", "ROOT"),
            _environment_rows(config, found.projects.values()),
            flex=4,
        )
    else:
        print(NO_ENVIRONMENTS)
    for _path, problem in found.problems:
        print(f"proj: skipped invalid environment: {problem}", file=sys.stderr)
    return 0


CATEGORY_TITLES = {
    "compiler": "Compilers",
    "toolchain": "Toolchains",
    "application": "Applications",
    "project": "Project modules",
    "": "Uncategorized",
}


def _used_by(projects) -> dict[str, list[str]]:
    users: dict[str, list[str]] = {}
    for project in projects:
        for category in MODULE_CATEGORIES:
            for module in project.modules.get(category, ()):
                names = users.setdefault(module.partition("/")[0], [])
                if project.name not in names:
                    names.append(project.name)
    return users


def _print_catalog(config: Config, query: str | None, as_json: bool) -> int:
    out = Output()
    projects = list(discover(config).values())
    entries = lmod.catalog(exclude=(config.module_cache,))
    if query:
        needle = query.lower()
        entries = [
            entry
            for entry in entries
            if needle == entry.category or needle in entry.name.lower()
        ]
    if as_json:
        print(
            json.dumps(
                [
                    {
                        "name": entry.name,
                        "versions": list(entry.versions),
                        "default": entry.default,
                        "category": entry.category or None,
                        "description": entry.description or None,
                    }
                    for entry in entries
                ],
                indent=2,
            )
        )
        return 0 if entries else 1
    if not entries:
        print(f"No modules match {query!r}." if query else "Lmod lists no modules.")
        return 1
    users = _used_by(projects)
    groups: dict[str, list] = {}
    for entry in entries:
        groups.setdefault(entry.category, []).append(entry)
    known = [name for name in lmod.CATEGORIES if name in groups]
    extra = sorted(name for name in groups if name and name not in lmod.CATEGORIES)
    order = known + extra + ([""] if "" in groups else [])

    search = [
        path
        for path in os.environ.get("MODULEPATH", "").split(os.pathsep)
        if path and Path(path) != config.module_cache
    ]
    packages = len(entries)
    versions = sum(max(1, len(entry.versions)) for entry in entries)
    count = f"{packages} package{'s' * (packages != 1)}, {versions} version{'s' * (versions != 1)}"
    print(out.heading("Available modules") + out.paint("  " + count, "dim"))
    if search:
        print(out.note("Lmod search path: " + ", ".join(search)))
    for category in order:
        members = groups[category]
        title = CATEGORY_TITLES.get(category, category.title())
        with_description = any(entry.description for entry in members)
        headers = ["MODULE", "VERSIONS"]
        if with_description:
            headers.append("DESCRIPTION")
        if projects:
            headers.append("USED BY")
        rows = []
        for entry in members:
            shown = "  ".join(
                version + ("*" if version == entry.default else "")
                for version in entry.versions
            )
            row = [entry.name, shown]
            if with_description:
                row.append(entry.description)
            if projects:
                names = users.get(entry.name, [])
                row.append(
                    ", ".join(names[:3]) + (f" +{len(names) - 3}" if len(names) > 3 else "")
                )
            rows.append(row)
        print()
        out.print_table(
            headers,
            rows,
            title=f"{title} ({len(members)})",
            flex=1,
            styles=[("bold",), (), ("dim",), ("dim",)][: len(headers)],
        )
    print()
    print(out.note("* default version (loaded when no version is given; pin one in an environment)"))
    if "" in groups:
        print(
            out.note(
                'Uncategorized modules have no tag; add whatis("Category: toolchain") '
                "(compiler, toolchain, application, or project) to their modulefile."
            )
        )
    return 0


def cmd_avail(config: Config, args: argparse.Namespace) -> int:
    return _print_catalog(config, args.query, args.json)


def cmd_overview(config: Config) -> int:
    """`proj info` with no environment: what exists, and where to look next."""
    out = Output()
    found = scan(config)
    if found.projects:
        _table(
            ("NAME", "SCOPE", "OWNER", "DESCRIPTION", "ROOT"),
            _environment_rows(config, found.projects.values()),
            title=f"Environments ({len(found.projects)})",
            flex=4,
        )
    else:
        print(NO_ENVIRONMENTS)
    for _path, problem in found.problems:
        print(f"proj: skipped invalid environment: {problem}", file=sys.stderr)
    print()
    try:
        _print_catalog(config, None, False)
    except ProjError as exc:
        print(out.note(f"Modules: {exc}"))
    print()
    print(
        out.note(
            "proj info --env <name> shows one environment; proj avail [category|name] "
            "filters the modules; proj create <name> starts a new environment."
        )
    )
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
    if args.group_writable and not args.shared:
        raise ProjError("--group-writable requires --shared")
    existing = discover(config).get(args.name)
    if existing:
        raise ProjError(
            f"environment {args.name!r} already exists at {existing.metadata_path}"
        )
    mode = None
    if args.shared:
        metadata_path = access.shared_registry(config) / args.name / "project.toml"
        if metadata_path.exists():
            raise ProjError(f"environment {args.name!r} already exists at {metadata_path}")
        mode = access.prepare_shared_directory(
            config, metadata_path.parent, args.group_writable
        )
    else:
        metadata_path = config.registry / args.name / "project.toml"
    create_document(metadata_path, args.name, root, mode, config.python_manager)
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


def _info_rows(config: Config, project: Project) -> list[tuple[str, str]]:
    rows = [
        ("Description", project.description),
        ("Scope", access.describe_scope(config, project)),
        ("Owner", access.project_owner(project)),
        ("Root", str(project.root)),
        ("Metadata", str(project.metadata_path)),
        ("Shell", project.shell),
        ("Python manager", python_envs.manager_for(config, project)),
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
    if not (args.project or os.environ.get("PROJ_ACTIVE")):
        return cmd_overview(config)
    project = _selected_project(config, args.project)
    print(f"Project environment: {project.name}")
    _table(("FIELD", "VALUE"), _info_rows(config, project), flex=1)
    return 0


def cmd_info_code(config: Config, args: argparse.Namespace) -> int:
    if not (args.project or os.environ.get("PROJ_ACTIVE")):
        # No environment to render: let the CLI print the overview directly.
        print("_proj_cli info")
        return 0
    project = _selected_project(config, args.project)
    values = [project.name]
    for label, value in _info_rows(config, project):
        values.extend((label, value))
    print("_proj_render_info " + " ".join(shlex.quote(value) for value in values))
    return 0


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
    update_document(project, lambda data: set_dotted(data, assignment, value))
    print(f"Updated {assignment} in {project.metadata_path}")
    if os.environ.get("PROJ_ACTIVE") == project.name:
        print("Reactivate the project to apply environment changes.")
    return 0


def cmd_python_env_list(config: Config, args: argparse.Namespace) -> int:
    manager = args.manager or python_envs.manager_for(config)
    environments = python_envs.environments(manager)
    if not environments:
        print(f"No {manager} environments found.")
        return 0
    for name in sorted(environments):
        print(name)
    return 0


def cmd_set_python_env(config: Config, args: argparse.Namespace) -> int:
    project = _selected_project(config, args.project)
    manager = args.manager or python_envs.manager_for(config, project)
    if os.path.isabs(args.environment):
        prefix = Path(args.environment).resolve()
        if not (prefix / "conda-meta").is_dir():
            raise ProjError(f"not a {manager} environment prefix: {prefix}")
        environment = str(prefix)
    else:
        available = python_envs.environments(manager)
        if args.environment not in available:
            raise ProjError(
                f"unknown {manager} environment {args.environment!r}; "
                f"run `proj python-env list --manager {manager}`"
            )
        # Names resolve against each user's own root prefix, so a shared
        # environment records the prefix that every member activates.
        environment = args.environment
        if access.scope(config, project) == "shared":
            environment = str(available[args.environment])

    def mutate(data):
        set_dotted(data, "python.manager", manager)
        set_dotted(data, "python.environment", environment)

    update_document(project, mutate)
    print(f"Linked {manager} environment {environment!r} to {project.name}.")
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
    update_document(
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
    python_env = project.python_environment or ""
    if os.path.isabs(python_env):
        current_env = os.environ.get("CONDA_PREFIX", "")
    else:
        current_env = os.environ.get("CONDA_DEFAULT_ENV", "")
    drift = []
    if not module_loaded:
        drift.append("project module is not loaded")
    missing = expected - loaded
    if missing:
        drift.append("missing modules: " + ", ".join(sorted(missing)))
    if project.python_environment and current_env != project.python_environment:
        drift.append(
            f"Python environment is {current_env or 'inactive'}, "
            f"expected {project.python_environment}"
        )
    print(f"Project:      {project.name}")
    print(f"Root:         {project.root}")
    print(f"Metadata:     {project.metadata_path}")
    print(f"Lmod module:  {project.module_name}")
    print(f"Python env:   {_python_label(config, project)}")
    print(f"State:        {'drift: ' + '; '.join(drift) if drift else 'consistent'}")
    return 2 if drift else 0


def _python_label(config: Config, project: Project) -> str:
    if not project.python_environment:
        return "not configured"
    return f"{project.python_environment} ({python_envs.manager_for(config, project)})"


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
    print(f"Python env:    {_python_label(config, project)}")
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


def _confirm(question: str) -> bool:
    try:
        answer = input(f"{question} [y/N]: ")
    except EOFError:
        return False
    return answer.strip().lower() in {"y", "yes"}


def cmd_remove(config: Config, args: argparse.Namespace) -> int:
    project = resolve(config, args.project)
    name = project.name
    if os.environ.get("PROJ_ACTIVE") == name:
        raise ProjError(f"environment {name!r} is active in this shell; deactivate it first")
    directory = project.metadata_path.parent
    owner = access.project_owner(project)
    # The registry's sticky bit already limits removal to the owner; say so
    # plainly instead of failing halfway with a permission error.
    if os.getuid() not in (0, directory.stat().st_uid):
        raise ProjError(f"environment {name!r} belongs to {owner}; only its owner can remove it")
    if not (os.access(directory, os.W_OK) and os.access(directory.parent, os.W_OK)):
        raise ProjError(f"cannot remove {directory}: permission denied")

    cache = config.module_cache / "project"
    generated = [path for path in (cache / f"{name}.lua", cache / f"{name}.sha256") if path.exists()]
    others = sorted(
        path
        for path in directory.rglob("*")
        if path != project.metadata_path and not path.is_dir()
    )
    extra = [*others, *generated]

    print(f"Environment:   {name} ({access.describe_scope(config, project)}, owner {owner})")
    print(f"Metadata:      {project.metadata_path}")
    print(f"Project root:  {project.root} (kept)")
    if project.python_environment:
        print(f"Python env:    {_python_label(config, project)} (kept)")

    interactive = sys.stdin.isatty()
    if not args.yes:
        if not interactive:
            raise ProjError("refusing to remove without confirmation; pass --yes")
        if not _confirm(f"Remove environment {name!r}?"):
            print("Nothing removed.")
            return 1

    delete_files = args.delete_files
    if extra and delete_files is None:
        if interactive and not args.yes:
            print("Files created for this environment:")
            for path in extra:
                print(f"  {path}")
            delete_files = _confirm("Delete these files too?")
        else:
            delete_files = False

    if delete_files:
        shutil.rmtree(directory)
        for path in generated:
            path.unlink()
    else:
        project.metadata_path.unlink()
        try:
            directory.rmdir()
        except OSError:
            pass
    print(f"Removed environment {name!r}.")
    if extra and not delete_files:
        print("Kept files: " + ", ".join(str(path) for path in extra))
    return 0


def cmd_configmenu(config: Config, args: argparse.Namespace) -> int:
    if args.setup:
        menu_runtime.setup()
        return 0
    project = _selected_project(config, args.project)
    menu_runtime.launch(project.name)
    return 0


def cmd_hook(config: Config, args: argparse.Namespace) -> int:
    try:
        project = resolve(config, args.project)
    except ProjError:
        # Removed while active elsewhere: no shutdown hooks are left to run.
        if args.phase == "shutdown":
            return 0
        raise
    hooks = project.startup_hooks if args.phase == "startup" else project.shutdown_hooks
    for hook in hooks:
        argv = [project.expand(value) for value in hook.argv]
        completed = subprocess.run(argv, cwd=project.root, check=False)
        if completed.returncode:
            return completed.returncode
    return 0


INIT_BEGIN = "# >>> proj initialize >>>"
INIT_END = "# <<< proj initialize <<<"
INIT_BLOCK = re.compile(
    r"\n?" + re.escape(INIT_BEGIN) + r".*?" + re.escape(INIT_END) + r"\n?", re.S
)


def _detect_shell(requested: str | None) -> str:
    shell = requested or Path(os.environ.get("SHELL", "")).name
    if shell not in SHELLS:
        raise ProjError(
            f"cannot initialize shell {shell or 'unknown'!r}; "
            "pass --shell " + "|".join(SHELLS)
        )
    return shell


def _default_rc(shell: str) -> Path:
    if shell == "zsh":
        return Path(os.environ.get("ZDOTDIR", Path.home())) / ".zshrc"
    return Path.home() / ".bashrc"


def cmd_init(_config: Config, args: argparse.Namespace) -> int:
    shell = _detect_shell(args.shell)
    rc = Path(args.rc).expanduser() if args.rc else _default_rc(shell)
    # Edit the target of a symlinked startup file, not the link.
    rc = rc.resolve()
    adapter = shlex.quote(str(TOOL_ROOT / "shell" / f"init.{shell}"))
    original = rc.read_text() if rc.exists() else ""
    updated = INIT_BLOCK.sub("\n", original).rstrip("\n")
    if not args.reverse:
        block = (
            f"{INIT_BEGIN}\n"
            "# Managed by `proj init`; edits inside this block are replaced.\n"
            f"if [ -r {adapter} ]; then\n"
            f"    . {adapter}\n"
            "fi\n"
            f"{INIT_END}"
        )
        updated = f"{updated}\n\n{block}" if updated else block
    updated = updated + "\n" if updated else ""
    if updated == original:
        print(f"proj: {rc} already {'clean' if args.reverse else 'initialized'}")
        return 0
    rc.parent.mkdir(parents=True, exist_ok=True)
    temporary = rc.with_name(f".{rc.name}.proj-tmp")
    temporary.write_text(updated)
    if rc.exists():
        os.chmod(temporary, stat.S_IMODE(rc.stat().st_mode))
    temporary.replace(rc)
    if args.reverse:
        print(f"proj: removed initialization from {rc}")
    else:
        print(f"proj: initialized {shell} in {rc}; open a new shell to use it")
    return 0


def cmd_shell(config: Config, args: argparse.Namespace) -> int:
    if args.action == "activate":
        if os.environ.get("PROJ_ACTIVE"):
            raise ProjError(
                f"project {os.environ['PROJ_ACTIVE']!r} is already active; deactivate it first"
            )
        project = resolve(config, args.project)
        owner = access.project_owner(project)
        if owner != access.current_user():
            print(
                f"proj: environment {project.name!r} belongs to {owner}; "
                "its hooks and aliases run as you",
                file=sys.stderr,
            )
        print(activation_code(config, project))
        return 0
    active = os.environ.get("PROJ_ACTIVE")
    if not active:
        print("_proj_no_active")
        return 0
    try:
        project = resolve(config, active)
    except ProjError:
        print(
            f"proj: environment {active!r} no longer exists; deactivating from shell state",
            file=sys.stderr,
        )
        print(orphan_deactivation_code(config, active))
        return 0
    print(deactivation_code(config, project))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="proj")
    parser.add_argument("--version", action="version", version=f"proj {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list registered projects")
    avail = sub.add_parser(
        "avail", help="list the modules Lmod can load, by category"
    )
    avail.add_argument(
        "query",
        nargs="?",
        help="a category (compiler, toolchain, application, project) or part of a module name",
    )
    avail.add_argument("--json", action="store_true", help="print JSON")
    sub.add_parser("status", help="show active project state")
    sub.add_parser("current", help="print the active project name")
    sub.add_parser("doctor", help="check dependencies and integration")
    sub.add_parser("install", help="link proj into the bin directory beside its checkout")
    init = sub.add_parser("init", help="add proj to a shell startup file")
    init.add_argument("--shell", choices=SHELLS)
    init.add_argument("--rc", metavar="FILE", help="startup file to edit")
    init.add_argument(
        "--reverse", action="store_true", help="remove the initialization block"
    )
    info_parser = sub.add_parser("info", help="show project environment metadata")
    info_parser.add_argument(
        "--env", "--project", dest="project", metavar="NAME"
    )
    create = sub.add_parser("create", help="register a project environment")
    create.add_argument("name")
    create.add_argument("--root")
    create.add_argument(
        "--shared", action="store_true", help="create in the shared group registry"
    )
    create.add_argument(
        "--group-writable",
        action="store_true",
        help="let every group member change a shared environment",
    )
    config_parser = sub.add_parser("config", help="read or write project metadata")
    config_parser.add_argument(
        "--env", "--project", dest="project", metavar="NAME"
    )
    config_parser.add_argument("assignment")
    config_parser.add_argument("value", nargs="?")
    set_python = sub.add_parser(
        "set-python-env", help="link an existing conda-family Python environment"
    )
    set_python.add_argument("environment")
    set_python.add_argument("--manager", choices=PYTHON_MANAGERS)
    set_python.add_argument(
        "--env", "--project", dest="project", metavar="NAME"
    )
    python_env = sub.add_parser(
        "python-env", help="inspect available Python environments"
    )
    python_env_sub = python_env.add_subparsers(
        dest="python_env_command", required=True
    )
    python_env_list = python_env_sub.add_parser("list")
    python_env_list.add_argument("--manager", choices=PYTHON_MANAGERS)
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
    configmenu = sub.add_parser(
        "configmenu", help="edit an environment in an interactive menu"
    )
    configmenu.add_argument("--env", "--project", dest="project", metavar="NAME")
    configmenu.add_argument(
        "--setup", action="store_true", help="install the menu's private runtime"
    )
    remove = sub.add_parser("remove", help="delete a project environment")
    remove.add_argument("project", metavar="name")
    remove.add_argument(
        "-y", "--yes", action="store_true", help="remove without asking"
    )
    files = remove.add_mutually_exclusive_group()
    files.add_argument(
        "--delete-files",
        dest="delete_files",
        action="store_true",
        help="also delete other files in the environment and its generated module",
    )
    files.add_argument(
        "--keep-files",
        dest="delete_files",
        action="store_false",
        help="delete only the environment's project.toml",
    )
    remove.set_defaults(delete_files=None)
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
        if args.command == "avail":
            return cmd_avail(config, args)
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
        if args.command == "init":
            return cmd_init(config, args)
        if args.command == "env" and args.env_command == "list":
            return cmd_env_list(config, args)
        if args.command == "env" and args.env_command == "show":
            return cmd_env_show(config, args)
        if args.command == "configmenu":
            return cmd_configmenu(config, args)
        if args.command == "remove":
            return cmd_remove(config, args)
        if args.command == "_hook":
            return cmd_hook(config, args)
        if args.command == "_shell":
            if args.action == "activate" and not args.project:
                raise ProjError("activate requires a project")
            return cmd_shell(config, args)
        if args.command in {"activate", "deactivate"}:
            raise ProjError(
                f"{args.command} must run through the shell integration; "
                f"run `proj init` or source {TOOL_ROOT}/shell/init.<zsh|bash>"
            )
        parser.error("unhandled command")
    except ProjError as exc:
        print(f"proj: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nproj: aborted", file=sys.stderr)
        return 130
    except PermissionError as exc:
        print(f"proj: permission denied: {exc.filename or exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
