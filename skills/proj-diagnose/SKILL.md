---
name: proj-diagnose
description: Use when a proj command fails or a project environment does not look right: read what a project is and what is active, check that proj, Lmod and the Python manager are set up, and fix the failures people really hit.
---

# Read the state of proj and fix common problems

Verified 2026-11-22 with proj 0.9.0 and Lmod 9.4.2 in a scratch HOME. Anything not listed is not verified.

## What is active, and what is this project?
```bash
proj current            # name of the active project; prints nothing and exits 1 when none
proj status             # the active project: root, module, Python env, "State: consistent" or "drift: ..." (exit 2)
proj status --env demo  # any project, "(not active in this shell)"
proj info --env demo    # the record: scope, owner, root, modules, Python link, "Your settings"
proj list               # every environment you can see, with scope and owner
proj env show demo      # the effective environment proj will generate: modules, variables, paths, aliases, hooks
proj env list           # the generated Lmod modules and whether each is current, stale or missing
```
Active state lives in this shell only (`PROJ_ACTIVE` and Lmod's loaded modules). Another terminal can have another project.

## Is proj set up correctly?
```bash
proj doctor      # one line per check, ok or FAIL; exits 1 when any FAIL
```
Checks: the shell adapter is loaded, Lmod is found, the `module` function exists, `MODULEPATH` lists module folders, the Python manager is installed, the module cache, the site configuration (which one is in use depends on how proj was installed), the shared registry if configured, project roots, and that every record is valid. A `FAIL` line says what to do. `proj doctor` run from a non-interactive shell always fails the first checks: source the adapter (`<proj root>/shell/init.bash` or `init.zsh`) after Lmod's own init.

## Why does `proj status` say "drift"?
| Line | Cause | What to do |
|---|---|---|
| `drift: missing modules: gcc/13.3` | a module of the project was unloaded by hand | `proj reload` |
| `project module is not loaded` | the project's Lmod module was unloaded by hand | `proj deactivate`, then `proj activate` |
| `Python environment is X, expected Y` | you activated another environment by hand | restore it, or `proj deactivate --force` |
| `this shell uses the previous Python environment (...): run proj reload` | someone relinked the project after you activated | `proj reload` |
| `Python environment is behind environment.yml` | the dependency file changed after the stamp | rebuild, then `proj python-env stamp` (see `proj-python`) |
`proj deactivate` still works with module drift; only a Python environment changed by hand is refused (and `--force` overrides it).

## Why did a proj command fail?
| Message | Cause | What to do |
|---|---|---|
| `activate must run through the shell integration; run proj init ...` (also `deactivate`, `reload`) | you ran `bin/proj` directly | use the `proj` shell function: `proj init`, or source the adapter |
| `Lmod is unavailable; run proj doctor` | `module` is not defined here | source Lmod's init first, then the adapter |
| `unknown project 'x' (searched: ...)` | wrong name, or you may not read it | `proj list`; a shared one you cannot read is not shown |
| `proj: 1 environment you have no permission to read not shown` | a shared environment or its folder is closed to you | not an error; ask its creator |
| `no module matches ...` | see `proj-modules` | `proj use --list` |
| `skipped invalid environment: <file> is world-writable; refusing to load it` | the record's permissions are unsafe (any other invalid record is skipped the same way, with its reason) | on your own record `chmod go-w <file>`; for a shared one ask its creator |

## What does this skill not cover?
Each task has its own skill: `proj-activate`, `proj-modules`, `proj-create-share`, `proj-python`. Changing the installed proj, the site configuration or Lmod's module path is for your site administrator.
