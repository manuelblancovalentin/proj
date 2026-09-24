# Project metadata

Managed environments live at `~/.proj/envs/<name>/project.toml`. The metadata
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

[modules]
project = []
toolchain = ["cmake/3.30", "ninja/1.12"]
application = []
compiler = ["gcc/14"]

[environment]
EXAMPLE_MODE = "development"
EXAMPLE_DATA = "${project.root}/data"

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

Only `project.name` and `project.root` are required. Description defaults to
the name, shell defaults to Zsh, and the managed starter enables micromamba as
the manager without selecting an environment.

Use `proj config` for ordinary changes:

```zsh
proj config project.description="Example environment"
proj config environment.EXAMPLE_MODE=development
proj config paths.prepend='["${project.root}/bin"]'
proj config hooks.startup='[["./scripts/check-config"]]'
```

Values use TOML syntax when needed. Plain unquoted text is treated as a string.
Supported generic keys are `project.description`, `project.root`,
`project.shell`, `python.manager`, `python.environment`, `paths.prepend`,
`hooks.startup`, `hooks.shutdown`, `modules.<category>`,
`environment.<variable>`, and `aliases.<name>`. Dedicated helpers are preferred
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
