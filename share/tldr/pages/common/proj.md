# proj

> Manage project development environments using Lmod and optional micromamba, conda, or mamba environments.
> Project metadata is stored under `~/.proj/envs`.
> More information: <https://github.com/tldr-pages/tldr>.

- Add proj to the current shell's startup file (Zsh or Bash):

`proj init`

- Register the current directory as a project:

`proj create {{project_name}}`

- Register a project that every member of the shared group can activate:

`proj create {{project_name}} --shared`

- Activate a project environment:

`proj activate {{project_name}}`

- Show the active project and check its state:

`proj status`

- Display the active or a named environment's effective metadata:

`proj info {{[--env environment_name]}}`

- Edit the active project in an interactive menu:

`proj configmenu`

- Set or read a configuration value for the active project:

`proj config {{project.description}}={{"Description"}}`

`proj config {{project.description}}`

- List and link an existing Python environment (micromamba, conda, or mamba):

`proj python-env list`

`proj set-python-env {{environment_name}}`

- Add an Lmod dependency from a supported category:

`proj module add {{compiler|toolchain|application|project}} {{module/version}}`

- Inspect a registered project's effective environment:

`proj env show {{project_name}}`

- Deactivate the current project and restore the previous shell state:

`proj deactivate`

- Delete a project environment, confirming first (the project files are kept):

`proj remove {{project_name}}`
