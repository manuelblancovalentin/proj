# proj

`proj` is a small, metadata-driven project environment manager for Fedora and
Zsh. It coordinates Lmod and optional micromamba environments; it does not
replace Git, Lmod, or Python environment management.

## Quick start

From an existing project directory:

```zsh
proj create atlas
proj activate atlas
proj config project.description="Atlas development environment"
proj set-python-env atlas
proj module add compiler gcc/14
```

`proj create` registers the current directory and creates:

```text
~/.proj/envs/atlas/project.toml
```

It prints that path after creation. The generated file is immediately valid:
only the schema, name, root, and default `python.manager = "micromamba"` are
active. Optional fields and examples are present but commented out.

Configuration defaults to the active project:

```zsh
proj config project.description="New description"
proj config project.description
proj config environment.ATLAS_MODE=development
proj config aliases.atlas-root='cd ${project.root}'
proj module list compiler
proj module add toolchain cmake/3.30
proj module remove toolchain cmake/3.30
```

Use `--env atlas` with configuration commands when the environment is not
active. When `PROJ_ACTIVE` is set, it is always preferred; the micromamba or
Conda environment name (including `base`) is never used to select a project.
Reactivate after a change that affects the loaded environment.

Inspect the active environment as a bordered, colored panel:

```zsh
proj info
proj info --env atlas
```

The panel presents the effective metadata: identity, paths, Python selection,
all four module categories, variables, aliases, hooks, and future task
definitions. `--project` remains accepted as a compatibility alias, but new
documentation and completion consistently use `--env`.

List and link existing micromamba environments:

```zsh
proj python-env list
proj set-python-env atlas
```

The second command validates that the environment exists. `proj` never creates
or replaces micromamba environments. Use `mamba create -n atlas ...` for that.

## Installation

Requirements:

- Fedora and Zsh 5.9 or newer
- Lmod, initialized so the `module` shell function is available
- `/usr/bin/python3` with `tomllib`
- micromamba when a Python environment is configured

Expose the canonical command and load its Zsh adapter:

```zsh
/tools/proj/bin/proj install
source /tools/proj/shell/init.zsh
```

`proj install` also exposes the canonical `proj(1)` manual beneath
`/tools/share/man/man1` and the concise TLDR page beneath
`/tools/share/tldr/pages/common`. The adapter adds `/tools/bin`,
`/tools/share/man`, and `/tools/share` to their respective search paths exactly
once, defines the parent-shell `proj` function, and provides `mamba` as a
shorter alias for `micromamba` after shell startup completes. Deferring that
alias lets micromamba's generated Zsh hook parse safely.

When Zsh completion has already been initialized, the adapter registers native
completion for commands, configuration keys, module categories, micromamba
environments, and registered project names. Discovery happens only after Tab
is pressed, never during shell startup.

Completion follows the full command hierarchy. For example:

```text
proj activate <Tab>                  registered project environments
proj module add <Tab>                supported module categories
proj module add toolchain <Tab>      modules currently available in Lmod
proj module remove toolchain <Tab>   modules configured on the active project
```

The four categories organize project metadata; Lmod has no matching universal
category system. Consequently, `add` offers the available Lmod namespace after
you choose a category.

Lifecycle messages use the dots `ok`, `info`, and `error` helpers when dots is
loaded. A Unicode fallback keeps proj fully usable on its own.

After sourcing the adapter, read the full command reference with:

```zsh
man proj
tldr proj
```

Check the host with `proj doctor`.

## Command overview

```text
proj create <name> [--root <directory>]
proj list
proj activate <name>
proj deactivate
proj current
proj status
proj info [--env <name>]
proj config [--env <name>] <key>[=<value>]
proj set-python-env [--env <name>] <environment>
proj python-env list
proj module {list|add|remove} <category> [module] [--env <name>]
proj env list
proj env show <name>
proj doctor
proj install
```

Task definitions are represented in the schema, but `proj run` is intentionally
not implemented yet. A guided terminal UI may be added later; the primary
workflow remains dependency-free and scriptable.

## Global configuration

The managed registry is always `~/.proj/envs`. Additional metadata roots may be
added with optional `~/.config/proj/config.toml`:

```toml
schema = 1
project_roots = ["/shared/project-environments"]
module_cache = "~/.cache/proj/modulefiles"

[behavior]
change_directory = true
run_startup_hooks = true
```

Environment overrides for testing and automation include `PROJ_HOME`,
`PROJ_CONFIG`, `PROJ_PROJECT_ROOTS` (colon-separated), `PROJ_CACHE_HOME`, and
`PROJ_GLOBAL_BIN`, `PROJ_GLOBAL_MAN`, and `PROJ_GLOBAL_TLDR`.

See [metadata](docs/metadata.md), [architecture](docs/architecture.md),
[lifecycle](docs/lifecycle.md), and
[troubleshooting](docs/troubleshooting.md).
