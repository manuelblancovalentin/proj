# AGENTS.md

## Purpose

`proj` is a project environment manager for Linux and interactive Zsh or Bash.
It is not a Git wrapper and does not implement Python environments. It coordinates
project metadata with Lmod and, when requested by metadata, a conda-family
Python manager (micromamba, conda, or mamba).

Lmod is mandatory and remains authoritative for module dependencies,
environment variables, paths, aliases, conflict handling, and the one-active-
project rule. The configured Python manager remains authoritative for Python environment
activation.

## Invariants

- Never hardcode an installation path. Everything is relative to the tool
  root (the directory holding `bin/`, `proj/`, and `shell/`): the checkout, or
  the prefix chosen in `install.sh` (default `/opt/proj`).
- Canonical executable: `<root>/bin/proj`; manual
  `<root>/share/man/man1/proj.1`; TLDR page
  `<root>/share/tldr/pages/common/proj.md`.
- A checkout used in place (legatum: `/tools/proj`) may expose relative links
  in the sibling `bin/` and `share/` directories through `proj install`:
  `/tools/bin/proj -> ../proj/bin/proj`,
  `/tools/share/man/man1/proj.1 -> ../../../proj/share/man/man1/proj.1`, and
  `/tools/share/tldr/pages/common/proj.md ->
  ../../../../proj/share/tldr/pages/common/proj.md`. The adapters prefer those
  links only when they resolve to the same checkout.
- Site configuration lives at `<root>/etc/config.toml` (written by
  `install.sh`, never overwritten on upgrade); user configuration overrides it
  key by key. Unknown keys are rejected.
- Interactive mutation goes through `shell/init.zsh` or `shell/init.bash`,
  which share `shell/core.sh`; an executable cannot mutate its parent shell.
  Keep `core.sh` portable between Bash and Zsh.
  Site-specific presentation (for example a host's banner or table renderer)
  belongs in that host's profile, sourced after the adapter, never in proj;
  `_proj_render_info` is the supported hook for `proj info`.
- `proj init` owns the marked `# >>> proj initialize >>>` block in startup
  files; it is idempotent and `--reverse` removes it.
- Use `/usr/bin/python3` and the standard library only (falling back to
  `tomli` before 3.11; minimum 3.9). The sole exception is the optional
  `proj configmenu` interface (`proj/menu.py`, Textual), which runs only from
  its private virtual environment, `<root>/libexec/menu`, created by
  `proj configmenu --setup`; nothing else may import it. Its editing logic
  lives in the standard-library `proj/menu_state.py`.
- The `project/` module namespace belongs to the modules proj generates from
  environments (`family("project")`). Metadata validation rejects any
  `modules.*` entry in it, and no picker, catalog, or completion may offer
  one. proj never edits `MODULEPATH` beyond its own cache; making module
  directories visible is the site init's job, and `proj doctor` reports when
  it was not done.
- The configuration menu's module pickers list modules by their Category tag
  (plus untagged ones, flagged, and anything already chosen), with a toggle
  for all categories.
- Modules declare their proj category with `whatis("Category: <compiler|
  toolchain|application|project>")`; `proj avail` and `proj info` build the
  catalog from Lmod output and those tags only, and never list the modules
  proj generates in its own cache. Terminal output goes through
  `proj/render.py`: boxed and colored on a terminal, plain columns when piped.
- `proj configmenu` dialogs close on Escape without changes; the main screen
  never quits with unsaved changes without asking, and the question defaults
  to staying. This prevents an active project
  environment from changing proj's runtime. Only `PREFIX/etc/python`
  (recorded by the installer when the system Python cannot read TOML) or
  `PROJ_PYTHON` may select another interpreter. The launcher replaces the
  working directory on `sys.path` with the tool root.
- `proj upgrade` reinstalls through the downloaded archive's own `install.sh`
  (same prefix, recorded mode and group, `--no-init`, `--no-system-init`,
  `--no-install-deps`), keeps `PREFIX/.previous`, never touches
  configuration or startup files, refuses git checkouts, and runs before
  configuration loads so a broken configuration cannot block it. The source
  repository and ref live in `PREFIX/etc/source.toml`; `PROJ_UPGRADE_BASE`
  replaces the host for tests.
- Activation records the login's loaded modules (`PROJ_LOGIN_MODULES`);
  deactivation, a failed activation, and `proj use`/`unuse` reloads load back
  whatever an environment displaced, so a login's own choices survive.
  `behavior.restore_login_modules` (strictly boolean, default true) switches
  this off. The record is a plain shell variable, never exported (not even
  under `set -a`), replaced at each activation, cleared when the environment
  ends, and not kept at all for a login longer than 4096 characters.
- `proj use`/`proj unuse` find a module by exact name, then `pdk-<name>`, then
  `suite-<name>`; several matches or none is an error, never a guess. Category
  comes from the module's `Category` tag and access from its `Group` tag
  (`any` or no tag means everyone); access is checked before anything else
  about a module is revealed. An entry for the same module, or the same Lmod
  family, is replaced so an environment always loads. For the active
  environment the CLI leaves a `_proj_reapply` snippet in
  `PROJ_SHELL_CODE_FILE` for the adapter to evaluate: unload the project
  module while the cached file is still the old one, regenerate it
  (`_materialize`), load it again, and clean up like a failed activation if
  that fails. The CLI never touches the parent shell itself.
- The adapters never take over a prompt. They maintain `PROJ_PROMPT_SEGMENT`
  (no subprocess per prompt) and, only when the prompt does not mention it
  and `PROJ_PROMPT` is not `off`, put it in front of `PS1`/`PROMPT`. A
  framework that renders the badge itself (dots, unless `DOTS_PROMPT=never`)
  takes precedence so the badge never appears twice. `PROMPT_COMMAND` is
  handled in both its string and array forms.
- Never emulate or fall back from Lmod.
- Project configuration is metadata-driven; never hardcode a project name.
- Managed metadata lives at `<registry>/<name>/project.toml` (private default
  `~/.proj/envs`) and points to the project root. `proj create` and
  `proj config` are the normal interface.
- Shared mode adds a group registry (mode `3770`). Shared environments are
  owner-only (`2755`/`644`) unless created `--group-writable`
  (`2775`/`664`). Writes keep the document's mode and group. The creator is
  the environment directory's owner. World-writable metadata is refused, and
  one invalid document must not break discovery for others.
- Precedence is private, shared, then extra roots; a private environment
  shadows a shared one with the same name.
- `--env` is the canonical explicit environment selector. Keep `--project` as
  a compatibility alias unless a deliberate breaking migration removes it.
- Shell initialization must never activate an environment. Only an explicit
  `proj activate` mutates activation state.
- Configuration writes are atomic, validated, and restore the previous document
  if validation fails. Unknown generic configuration keys must be rejected.
- Active state is shell-local. Files are never authoritative for activation.
- TOML interpolation is allowlisted and never evaluates shell syntax.
- Hooks run as child processes and cannot mutate the parent shell.
- Task definitions are validated, but `proj run` is not implemented.
- Shell initialization performs no project scans and starts no subprocesses.
- Completion may discover projects and Python environments only when
  the user requests completion, never while sourcing the adapter.
- Module completion follows action, category, then module. Add candidates come
  from the live Lmod namespace; remove candidates come from selected-project
  metadata. Proj categories are organizational and must not be presented as an
  Lmod taxonomy.
- Lifecycle messages use dots logging helpers when present, with a standalone
  Unicode fallback; proj must not require dots to function.
- Install the `mamba` convenience alias from a first-prompt hook, not while
  sourcing. An early alias breaks parsing of micromamba's generated Zsh hook.
  Never define it when a real `mamba` alias, function, or command exists.

## Architecture

- `bin/`: portable launcher.
- `proj/`: Python control plane.
- `shell/`: Zsh adapter and parent-shell lifecycle.
- `shell/core.sh`: portable lifecycle shared by both adapters.
- `shell/completion.zsh` and `shell/completions/_proj`: native, on-demand Zsh
  completion for both early and late `compinit` ordering.
- `shell/completions/proj.bash`: on-demand Bash completion.
- `install.sh`: POSIX installer (private or shared, prefix, registries, shell
  initialization, optional dependency installation).
- `templates/`: generated Lmod modulefile reference.
- `docs/`: architecture, schema, lifecycle, and troubleshooting.
- `tests/`: standard-library unit and shell integration tests.

Runtime files live under XDG directories:

- private project registry: `~/.proj/envs` unless configured;
- shared project registry: configured by the site configuration;
- configuration: `<root>/etc/config.toml`, then `~/.config/proj/config.toml`;
- cache/index/modulefiles: `~/.cache/proj`;
- optional diagnostics: `~/.local/state/proj`.

## Safety

Activation is a trust boundary. Aliases and hooks come from project metadata;
activating someone else's shared environment runs their hooks as you, and proj
says so.
`proj remove` deletes only what proj owns (the environment's document, and on
confirmation its directory and generated modulefile); it never deletes a
project root or a Python environment, asks before acting, and requires
`--yes` without a terminal.
Declarative Lmod state reverses cleanly. Arbitrary external hook side effects
cannot be automatically reversed and should have matching shutdown hooks.

Link installation is idempotent and must refuse conflicting destinations.
This applies independently to the command, manual, and TLDR links.

## Development

Run:

```sh
./tests/run
./tests/benchmark
```

The local development host may not have Lmod installed. Tests use a fake module
function for lifecycle coverage; `proj doctor` must still report the real host
accurately.
