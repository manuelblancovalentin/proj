# Architecture

## Layers

The shell adapters own parent-shell mutation. The Python control plane owns
discovery, validation, planning, diagnostics, and generated modulefiles. Lmod
owns modules, variables, paths, aliases, dependency reference counts, and the
project-family conflict. Micromamba owns Python environment activation.

The adapters also own on-demand completion and lifecycle presentation.
Completion invokes discovery only after the user requests it. Lifecycle output
delegates to the dots logging API when available, with a standalone fallback;
proj does not require dots.

`shell/init.zsh` and `shell/init.bash` hold only shell-specific glue (locating
the tool root, completion registration, the first-prompt hook, the dots panel).
Activation, deactivation, rollback, and the `proj` function live in the
portable `shell/core.sh`, sourced by both.

The CLI deliberately runs with `/usr/bin/python3 -P` and only the standard
library, so neither an activated project nor the working directory can replace
its runtime.

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

The private registry is `~/.proj/envs/<name>/project.toml` unless configured.
A shared installation adds a group registry; see Sharing. Registry documents
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

## Installation layout

Nothing is tied to a fixed path. The tool root is the directory holding `bin/`,
`proj/`, and `shell/`, and every other location derives from it:

```text
PREFIX/                    default /opt/proj, chosen in install.sh
  bin/proj                 launcher
  proj/ shell/ share/      code, adapters, manual and TLDR page
  etc/config.toml          site configuration (kept across upgrades)
  envs/                    default shared registry (shared mode)
  .proj-install            installed version marker
```

`proj init` adds a marked block to a startup file that sources the adapter
from the tool root. The adapter puts `PREFIX/bin`, `PREFIX/share/man`, and
`PREFIX/share` on their search paths.

## Sharing

The shared registry is owned by the configured group with mode `3770`: setgid
gives every new environment that group, sticky prevents removing or renaming
another member's environment, and non-members have no access. Each shared
environment directory belongs to its creator: `2755` with a `644` document
(owner-only) or `2775` with a `664` document (`--group-writable`). Metadata
writes are atomic and keep the existing mode and group.

Module caches stay per user, so activation needs only read access to shared
metadata. Discovery skips invalid documents and reports them, so one broken
environment cannot break proj for the whole group.

## Command ownership

On a checkout used in place (legatum keeps `/tools/proj`), `proj install`
exposes `/tools/bin/proj -> ../proj/bin/proj` idempotently and refuses
conflicts. The adapters use such links only when they resolve to the same
checkout.

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

Activation is explicit and is a trust boundary. A shared environment's hooks
and aliases run as whoever activates it, so proj prints a notice when the
owner is someone else, and refuses world-writable metadata. Declarative state is reversible
through Lmod. Hooks are argv arrays executed without a shell, but may still
produce external side effects. Task execution is deferred.
