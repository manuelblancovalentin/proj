# Project metadata

Managed environments live at `<registry>/<name>/project.toml`, by default
`~/.proj/envs`, or in the shared registry when created with `--shared`. The metadata
is a pointer to the actual project root, so the repository does not need a
`project.toml` and may live anywhere.

Create the starter document with:

```zsh
cd /path/to/example
proj create example
```

The complete schema is:

```toml
schema = 1

[project]
name = "example"
description = "Example development environment"
root = "/path/to/example"
shell = "zsh"

[python]
manager = "micromamba"
environment = "example"
spec = "/path/to/example/environment.yml"

[modules]
project = []
toolchain = ["cmake/3.30", "ninja/1.12"]
application = []
compiler = ["gcc/14"]

[environment]
EXAMPLE_MODE = "development"
EXAMPLE_DATA = "${project.root}/data"

[environment_paths.PYTHONPATH]
prepend = ["${user.home}/example/repo/src"]

[paths]
prepend = ["${project.root}/bin"]

[aliases]
example-root = "cd ${project.root}"

[hooks]
startup = [["./scripts/check-config"]]
shutdown = [["./scripts/stop-services"]]

[commands.build]
description = "Build the project"
command = ["./scripts/build"]
```

`project.shell` may be `zsh` or `bash`. `python.manager` may be `micromamba`,
`conda`, or `mamba`; when omitted, the configured `python_manager` applies.
`python.environment` is an environment name or an absolute prefix path; shared environments store the
prefix so that every member resolves the same environment.

`python.spec` optionally names the dependency file the Python environment is
built from (an absolute path after interpolation). `proj python-env stamp`
records its SHA-256 and the date in a `[python.stamp]` table (`sha256`, `date`,
`by`); `proj status` compares the file with that hash. proj only hashes the file;
it never builds the environment or reads inside it.

A `[derived]` table (`from`, `date`, `digest`) is written by `proj create
--from` and records which environment this one was copied from and a digest of
its definition then (ignoring the stamp), so `proj info` can say when the
original changed. Neither table is settable with `proj config`.

`[environment]` variables are set with Lmod `pushenv`: the person's previous
value comes back when the environment ends. `[environment_paths.<VARIABLE>]`
takes `prepend` and `append` arrays for list variables (`PYTHONPATH`, `PATH`,
...). Every entry must be one absolute path after interpolation (no `:`), may lie
anywhere, and is added only if the folder exists; Lmod removes just those entries
on unload. The first `prepend` entry ends up first. A variable may not be in both
tables, and names starting with `PROJ_` are proj's.

`project.root` is kept exactly as written when it is an absolute path without
`..`, and it may be a symbolic link (for example a stable `/projects/atlas`
pointing into a folder you would rather not show). `proj list`, `proj info`,
`proj status`, `${project.root}`, `PROJ_ROOT` and the directory proj changes to
on activation all use the path as written, so people see the link, not its
target. proj still resolves the link every time it loads the metadata, and uses
where it resolves for its checks (a `paths.prepend` entry must stay inside the
real folder) and for `proj list --json`, whose `project_root` is the resolved
folder. A path that cannot be entered by the person running proj (a folder private to
a group they are not in) makes the environment count as one they cannot read.
`proj create` still records the resolved folder; set a link with
`proj config --env NAME project.root /projects/atlas`.

Only `project.name` and `project.root` are required. Description defaults to
the name, shell defaults to Zsh, and the managed starter records the
configured Python manager without selecting an environment.

Use `proj config` for ordinary changes:

```zsh
proj config project.description="Example environment"
proj config environment.EXAMPLE_MODE=development
proj config paths.prepend='["${project.root}/bin"]'
proj config hooks.startup='[["./scripts/check-config"]]'
```

Values use TOML syntax when needed. Plain unquoted text is treated as a string.
Supported generic keys are `project.description`, `project.root`,
`project.shell`, `python.manager`, `python.environment`, `python.spec`,
`paths.prepend`, `hooks.startup`, `hooks.shutdown`, `modules.<category>`,
`environment.<variable>`, `environment_paths.<variable>.prepend|append`, and
`aliases.<name>`. Dedicated helpers are preferred
for Python environments and modules.

Supported module categories are exactly `project`, `toolchain`, `application`,
and `compiler`.

Interpolation is limited to `${project.name}`, `${project.root}`,
`${project.metadata}`, and `${user.home}`. Shell expansion, command
substitution, and arbitrary environment interpolation are rejected.

Prepended paths must be absolute after interpolation and remain beneath the
project root. Hooks and future commands are argv arrays. Hooks run without a
shell. Commands are validated and displayed by `proj env show`, but execution
is deferred.
