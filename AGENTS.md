# AGENTS.md

## Purpose

`proj` is a project environment manager for Linux and interactive Zsh or Bash.
It is not a Git wrapper and does not implement Python environments. It coordinates
project metadata with Lmod and, when requested by metadata, micromamba.

Lmod is mandatory and remains authoritative for module dependencies,
environment variables, paths, aliases, conflict handling, and the one-active-
project rule. Micromamba remains authoritative for Python environment
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
- `proj init` owns the marked `# >>> proj initialize >>>` block in startup
  files; it is idempotent and `--reverse` removes it.
- Use `/usr/bin/python3` (3.11+) with `-P` and the standard library only. This
  prevents an active project environment or the working directory from
  changing proj's runtime.
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
- Zsh completion may discover projects and micromamba environments only when
  the user requests completion, never while sourcing the adapter.
- Module completion follows action, category, then module. Add candidates come
  from the live Lmod namespace; remove candidates come from selected-project
  metadata. Proj categories are organizational and must not be presented as an
  Lmod taxonomy.
- Lifecycle messages use dots logging helpers when present, with a standalone
  Unicode fallback; proj must not require dots to function.
- Install the `mamba` convenience alias from a first-prompt hook, not while
  sourcing. An early alias breaks parsing of micromamba's generated Zsh hook.

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
