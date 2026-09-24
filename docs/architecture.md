# Architecture

## Layers

The Zsh adapter owns parent-shell mutation. The Python control plane owns
discovery, validation, planning, diagnostics, and generated modulefiles. Lmod
owns modules, variables, paths, aliases, dependency reference counts, and the
project-family conflict. Micromamba owns Python environment activation.

The Zsh adapter also owns on-demand completion and lifecycle presentation.
Completion invokes discovery only after the user requests it. Lifecycle output
delegates to the dots logging API when available, with a standalone fallback;
proj does not require dots.

The CLI deliberately runs with `/usr/bin/python3` and only the standard library,
so an activated project cannot replace its runtime.

## Active state

Active state is shell-local and represented by Lmod plus exported variables:

```text
PROJ_ACTIVE
PROJ_ROOT
PROJ_METADATA
PROJ_MODULE
PROJ_MAMBA_ENV
PROJ_PREVIOUS_PWD
PROJ_MAMBA_SHLVL_BEFORE
```

No state file is authoritative. Separate terminals may activate different
projects.

## Discovery and generation

The primary registry is `~/.proj/envs/<name>/project.toml`. Registry documents
point to project roots, keeping environment policy separate from repositories.
`proj create` and the configuration helpers manage these documents atomically.
Optional additional roots support shared or pre-existing metadata.

Discovery scans one directory level beneath metadata roots only when a CLI
command needs projects. Shell initialization performs no scan or subprocess.

Validated metadata is rendered atomically to:

```text
~/.cache/proj/modulefiles/project/<name>.lua
```

A content digest prevents unnecessary rewrites. Every generated project module
uses `family("project")` and every dependency uses `depends_on()`.

## Command ownership

The canonical executable is `/tools/proj/bin/proj`. The unified public namespace
contains `/tools/bin/proj -> ../proj/bin/proj`. `proj install` manages the link
idempotently and refuses conflicts.

The canonical manual is `/tools/proj/share/man/man1/proj.1`. Installation
exposes `/tools/share/man/man1/proj.1` as a relative symbolic link, and the Zsh
adapter prepends `/tools/share/man` to `MANPATH` exactly once while preserving
the system defaults.

The canonical concise reference is
`/tools/proj/share/tldr/pages/common/proj.md`. Installation exposes it beneath
`/tools/share/tldr/pages/common`, the system-page layout defined by TLDR
clients. The adapter prepends `/tools/share` to `XDG_DATA_DIRS` exactly once,
preserving the standard XDG data directories. It does not modify or compete
with the user's downloaded TLDR cache.

Future tools own their own canonical `bin/` directories and may expose relative
links through `/tools/bin`.

## Trust

Activation is explicit and is a trust boundary. Declarative state is reversible
through Lmod. Hooks are argv arrays executed without a shell, but may still
produce external side effects. Task execution is deferred.
