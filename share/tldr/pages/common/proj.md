# proj

> Manage project development environments using Lmod and optional micromamba environments.
> Project metadata is stored under `~/.proj/envs`.
> More information: <https://github.com/tldr-pages/tldr>.

- Register the current directory as a project:

`proj create {{project_name}}`

- Activate a project environment:

`proj activate {{project_name}}`

- Show the active project and check its state:

`proj status`

- Display the active or a named environment's effective metadata:

`proj info {{[--env environment_name]}}`

- Set or read a configuration value for the active project:

`proj config {{project.description}}={{"Description"}}`

`proj config {{project.description}}`

- List and link an existing micromamba environment:

`proj python-env list`

`proj set-python-env {{environment_name}}`

- Add an Lmod dependency from a supported category:

`proj module add {{compiler|toolchain|application|project}} {{module/version}}`

- Inspect a registered project's effective environment:

`proj env show {{project_name}}`

- Deactivate the current project and restore the previous shell state:

`proj deactivate`
