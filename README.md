# proj

`proj` is a small, metadata-driven project environment manager for Linux with
Zsh or Bash. It coordinates Lmod and optional micromamba environments; it does
not replace Git, Lmod, or Python environment management.

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

- Linux with Zsh 5.9+ or Bash 4.4+
- Lmod, initialized so the `module` shell function is available
- `/usr/bin/python3` 3.11 or newer (for `tomllib`)
- micromamba when a Python environment is configured

Run the installer from a checkout, or pipe it from GitHub:

```sh
sh install.sh
curl -fsSL https://raw.githubusercontent.com/manuelblancovalentin/proj/master/install.sh | sh
```

Like the conda installer, it asks for each choice with a default; `--yes`
accepts the defaults and `--help` lists the flags for unattended installs:

- **Mode**: `private` (only you) or `shared` (members of a group, default
  `proj`). Shared is the default when run as root.
- **Location**: default `/opt/proj`; a private install by a user who cannot
  write `/opt` defaults to `~/.local/opt/proj`. Any directory works.
- **Registries**: where private environments live (default `~/.proj/envs`)
  and, in shared mode, the group registry (default `PREFIX/envs`).
- **Shell**: detected from `$SHELL`; with consent it runs `proj init`, which
  adds a marked block to `~/.zshrc` or `~/.bashrc`. As root it can instead add
  the block to the system-wide `zshrc`/`bash.bashrc` for every user.
- **Dependencies**: if Lmod is missing it offers the distribution package
  (`apt-get install lmod`, `dnf install Lmod`), which needs sudo. If
  micromamba is missing it offers micromamba's official per-user installer.

Choices are written to `PREFIX/etc/config.toml`. Rerunning the installer on
the same prefix upgrades the code and keeps that configuration. To uninstall,
run `proj init --reverse` and remove the prefix.

A checkout can also be used in place, as on legatum: `proj install` links the
command, manual, and TLDR page into the `bin/` and `share/` directories beside
the checkout (`/tools/bin` for `/tools/proj`), and the startup file sources
`shell/init.zsh` or `shell/init.bash` directly.

The adapter adds the command, manual, and TLDR directories to their search
paths exactly once, defines the parent-shell `proj` function, and provides
`mamba` as a shorter alias for `micromamba` after shell startup completes.
Deferring that alias lets micromamba's generated shell hook parse safely.

Both adapters register native completion for commands, configuration keys,
module categories, micromamba environments, and registered project names.
Discovery happens only after Tab is pressed, never during shell startup.

## Sharing environments

A shared installation adds a group registry (mode `3770`: setgid keeps the
group on new files, sticky stops members from deleting or renaming other
people's environments). Every group member can activate every shared
environment:

```sh
proj create atlas --shared                    # only you can change it
proj create atlas --shared --group-writable   # any group member can change it
proj list                                     # SCOPE and OWNER columns
```

Private environments keep working alongside shared ones, and a private
environment shadows a shared one of the same name. In a shared environment,
`proj set-python-env` records the micromamba prefix path instead of the name,
so every member activates the same Python environment; that prefix and the
project root must be readable by the group.

Activation is a trust boundary: hooks and aliases from someone else's
environment run as you, and proj prints a notice when you activate an
environment you do not own. A group-writable environment lets every member
change those hooks. World-writable metadata is always refused.

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
proj create <name> [--root <directory>] [--shared [--group-writable]]
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
proj init [--shell zsh|bash] [--rc <file>] [--reverse]
proj install
proj --version
```

Task definitions are represented in the schema, but `proj run` is intentionally
not implemented yet. A guided terminal UI may be added later; the primary
workflow remains dependency-free and scriptable.

## Global configuration

Configuration is layered: the installer's site file `PREFIX/etc/config.toml`,
then the optional user file `~/.config/proj/config.toml`, which overrides it
key by key. Both accept the same keys; unknown keys are rejected:

```toml
schema = 1
registry = "~/.proj/envs"            # private registry; ~ is per user
shared_registry = "/opt/proj/envs"   # shared mode only
group = "proj"                       # required with shared_registry
project_roots = ["/shared/project-environments"]
module_cache = "~/.cache/proj/modulefiles"

[behavior]
change_directory = true
run_startup_hooks = true
```

Discovery order is also precedence: private registry, shared registry, then
`project_roots`.

Environment overrides for testing and automation include `PROJ_HOME`,
`PROJ_CONFIG`, `PROJ_SITE_CONFIG`, `PROJ_SHARED_REGISTRY`, `PROJ_GROUP`,
`PROJ_PROJECT_ROOTS` (colon-separated), `PROJ_CACHE_HOME`, and
`PROJ_GLOBAL_BIN`, `PROJ_GLOBAL_MAN`, and `PROJ_GLOBAL_TLDR`.

See [metadata](docs/metadata.md), [architecture](docs/architecture.md),
[lifecycle](docs/lifecycle.md), and
[troubleshooting](docs/troubleshooting.md).
