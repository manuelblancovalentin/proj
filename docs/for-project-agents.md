# proj for coding agents: Python environments

For an agent (or a script) working inside a project that has a `proj`
environment. Every name here is invented; replace `orbit` with the environment
name and `/work/orbit` with the project folder. Both recipes below were run for
real in Bash with Lmod and micromamba (only the package download of `python=3.12` was not); Zsh behaves the same.

## What proj does and does not do

| Kind of Python environment | Support |
|---|---|
| conda, mamba or micromamba environment, by name or by prefix path | **Yes.** proj links it (`python.environment`) and activates it with that manager. |
| `venv` / `virtualenv` inside the project folder | **Partly.** proj has no Python-manager support for it, but it can put the venv's `bin` directory on `PATH` and set `VIRTUAL_ENV` (below). |
| Creating an environment, installing packages | **No.** proj never creates or changes a Python environment, and never deletes one. Create it first with the tool of your choice. |

An environment holds **one** Python choice. Use the conda link *or* the venv
recipe for a given proj environment, not both.

## Before anything else

`proj activate` and `proj deactivate` are shell functions. In a non-interactive
shell they may not exist: `type proj` must say "function". If it does not, source the adapter from
proj's installation (`shell/init.bash` or `shell/init.zsh` next to `bin/proj`; it does not
activate anything), and `proj doctor` tells you what else is missing (the `module` function, the manager).
The commands that only read or edit metadata (`proj config`, `proj env show`,
`proj list`) work without it.

## A venv inside the project folder

```sh
cd /work/orbit
proj create orbit                                   # once; registers this folder
python3 -m venv /work/orbit/.venv                   # create it where it will live
proj config --env orbit paths.prepend='["${project.root}/.venv/bin"]'
proj config --env orbit environment.VIRTUAL_ENV='${project.root}/.venv'
proj env show orbit                                 # check the two settings
```

Write `${project.root}` literally, in single quotes: proj expands it, the
shell must not. Each `paths.prepend` entry has to be absolute after expansion
and **inside the project folder**; anything else is refused (`prepended path
escapes project root`). A venv is not relocatable, so create it at its final
place and do not move the project folder.

Enter, check, leave:

```sh
proj activate orbit        # python, pip and friends now come from /work/orbit/.venv/bin
command -v python          # /work/orbit/.venv/bin/python
echo "$VIRTUAL_ENV"        # /work/orbit/.venv
proj status                # "State: consistent"
proj deactivate            # PATH and VIRTUAL_ENV are exactly as before
```

`proj status` shows `Python env: not configured` for this recipe; that is
expected, because proj only knows about conda-family environments.

## A conda-family environment

```sh
micromamba create -p /work/orbit/.env -y python=3.12   # or conda / mamba; any prefix or name
proj python-env list                                   # names of that manager's environments
proj set-python-env --env orbit /work/orbit/.env       # by absolute prefix (must contain conda-meta/)
proj set-python-env --env orbit scratch                # or by name
proj set-python-env --env orbit scratch --manager conda  # when it is not the default manager
```

Then `proj activate orbit` calls the manager's own `activate`, and
`proj deactivate` its `deactivate`. `$CONDA_PREFIX` is the prefix while active.
The manager's shell integration has to be initialised in the shell
(`proj doctor` checks), and `proj python-env list` needs the manager's
executable on `PATH`.

## Things to know

* One environment is active per shell. If `proj activate` says "already
  active", run `proj deactivate` first; do not unset variables by hand.
* `proj deactivate` also undoes the directory change that `proj activate` made.
* Activation runs the environment's startup hooks and aliases as you. Do not
  activate an environment you did not create or were not told to use.
* Metadata lives outside the project folder (`proj env show orbit` prints the path);
  the project folder needs no proj file and should not get one.
* Never edit `project.toml` by hand if `proj config` can do it: it validates and
  restores the previous document on error.
