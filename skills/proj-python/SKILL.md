---
name: proj-python
description: Use when you want to link a conda-family Python environment to a proj project, use your own Python environment with a shared project without changing it for others, or find out why a project's Python environment is out of date.
---

# The Python environment of a project, and your own

Verified 2026-11-22 with proj 0.10.1 (micromamba on the host; paths used instead of environment names, so no environment was built). Not verified: activating a real conda or mamba environment through proj with a personal setting.

## How do I link a Python environment to a project?
proj does not build Python environments; it records which existing one to activate.
```bash
proj python-env list                                  # environments of the default manager (add --manager conda|mamba)
proj set-python-env --env demo my-env                 # a name from that list, or an absolute prefix
proj set-python-env --env demo /path/to/env --manager conda
proj info --env demo                                  # Python manager / Python environment
```
* For a shared project the record keeps the prefix path, so every member activates the same environment. Only the project's creator can relink it (the project is theirs, not yours).
* Activation needs the manager's shell integration (`micromamba shell init` or `conda init`) in your startup file.
* Reactivate to use a change: `proj reload`. A shell that activated the old link says `the Python environment of 'demo' was changed after this shell activated it` when you deactivate: that is not an error.

## How do I use my own environment with a shared project?
Without touching the project or anyone else's view:
```bash
proj set-python-env --env demo --mine /path/to/my-env        # or: proj config --env demo --mine python.environment=...
proj set-python-env --env demo --mine my-env --manager conda
proj set-python-env --env demo --mine --unset                # back to the shared one
```
* Modules, variables, paths, hooks and the root stay the project's. Only the Python link changes, for you.
* It is one file of your own configuration, `~/.config/proj/projects/demo.toml` (mode 0600, `[python] manager`, `environment`). Older proj kept it in `~/.proj/overrides/demo.toml`; that file is still read and moves into the new place the next time you change a setting of that project.
* `proj info` shows `Python override: yours; the shared environment links ...`. `proj status --json` has `"environment_source": "override"` (`shared` or `own` otherwise).
* For your own private project, link normally (no `--mine`).
* Unsetting never deletes a Python environment.

## How do I know the environment matches its dependency file?
```bash
proj config --env demo python.spec='${project.root}/environment.yml'
proj python-env stamp --env demo         # after you rebuilt the environment from that file
proj status --env demo                   # "Dependencies: environment.yml, stamped <date>, unchanged since"
```
When the file changes after the stamp, `proj status` says `the environment is behind it` and exits 2; `--json` has `python.dependencies.state` (`current`, `behind`, `unstamped`, `no-spec`, `unreadable`). proj only hashes the file; it never reads or builds the environment.

## Why did it fail?
| Message | Cause | What to do |
|---|---|---|
| `unknown micromamba environment 'x'; run proj python-env list ...` | no such name for that manager | list them, or give an absolute prefix; check `--manager` |
| `not a micromamba environment prefix: <path>` | the prefix has no `conda-meta` | check the path |
| `micromamba is not available` | the manager is not on `PATH` | load it, or use another `--manager` |
| `micromamba shell integration is unavailable; initialize it in your startup file` | its shell hook is not loaded | run its `shell init`/`conda init`, open a new shell |
| `is your own environment: link its Python environment with proj set-python-env, without --mine` | `--mine` is for environments that are not yours | drop `--mine` |
| `your settings ...: python.manager must be one of ...` or a world-writable file | a hand-edited file of yours is invalid | fix or delete `~/.config/proj/projects/demo.toml`; others are not affected |
| `you have no Python override for 'demo'` | nothing to unset | none |

## What does this skill not cover?
Creating the environment itself (conda or micromamba docs, or your project's setup). Activation: `proj-activate`.
