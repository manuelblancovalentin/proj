# AGENTS.md

## Purpose

`proj` is a project environment manager for Fedora and interactive Zsh. It is
not a Git wrapper and does not implement Python environments. It coordinates
project metadata with Lmod and, when requested by metadata, micromamba.

Lmod is mandatory and remains authoritative for module dependencies,
environment variables, paths, aliases, conflict handling, and the one-active-
project rule. Micromamba remains authoritative for Python environment
activation.

## Invariants

- Canonical executable: `/tools/proj/bin/proj`.
- Public link: `/tools/bin/proj -> ../proj/bin/proj`.
- Canonical manual: `/tools/proj/share/man/man1/proj.1`.
- Public manual link:
  `/tools/share/man/man1/proj.1 -> ../../../proj/share/man/man1/proj.1`.
- Canonical TLDR page: `/tools/proj/share/tldr/pages/common/proj.md`.
- Public TLDR link:
  `/tools/share/tldr/pages/common/proj.md ->
  ../../../../proj/share/tldr/pages/common/proj.md`.
- Interactive mutation goes through `shell/init.zsh`; an executable cannot
  mutate its parent shell.
- Use `/usr/bin/python3` and the standard library only. This prevents an active
  project environment from changing proj's runtime.
- Never emulate or fall back from Lmod.
- Project configuration is metadata-driven; never hardcode a project name.
- Managed metadata lives at `~/.proj/envs/<name>/project.toml` and points to
  the project root. `proj create` and `proj config` are the normal interface.
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
- `shell/completion.zsh` and `shell/completions/_proj`: native, on-demand Zsh
  completion for both early and late `compinit` ordering.
- `templates/`: generated Lmod modulefile reference.
- `docs/`: architecture, schema, lifecycle, and troubleshooting.
- `tests/`: standard-library unit and shell integration tests.

Runtime files live under XDG directories:

- managed project registry: `~/.proj/envs`;
- configuration: `~/.config/proj/config.toml`;
- cache/index/modulefiles: `~/.cache/proj`;
- optional diagnostics: `~/.local/state/proj`.

## Safety

Activation is a trust boundary. Aliases and hooks come from project metadata.
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
