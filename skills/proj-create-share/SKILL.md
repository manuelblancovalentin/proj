---
name: proj-create-share
description: Use when you want to create a proj project environment, share it with a Unix group, change who may see or edit it, make it private again, copy another one, or delete it.
---

# Create, share and remove a project environment

Verified 2026-11-22 with proj 0.10.1 in a scratch HOME with a scratch shared registry and your own primary group.

## How do I create an environment?
```bash
proj create demo --root /path/to/project/folder          # private: only you see it
proj create demo --root <folder> --python <env> --use gcc --use cmake
proj create demo2 --from demo --root <other folder>      # a snapshot copy: modules, variables, paths, hooks (not the Python stamp)
```
* A private environment is one file, `~/.proj/envs/demo/project.toml`, pointing at your folder (check: `proj list`).
* `--root` is where `proj activate` takes you. `--python` links an existing conda-family environment (name or prefix); proj never builds one. `--use` adds modules (see `proj-modules`).
* A name that already exists in your registry or the shared one is refused.

## How do I share it with my group?
```bash
proj create demo --shared --root <folder>                # create it shared from the start
proj share demo                                          # or move a private one
proj list                                                # SCOPE shared, OWNER user:group
```
* A shared environment is stored in the shared registry, with the registry's Unix group. Where that registry is and which group it uses depend on the site's configuration (`shared_registry` and `group`); `proj doctor` shows them as `shared registry <path> (group <g>)`. Everyone with access to the registry can read it by default; only its creator changes it.
* Members who activate it run **its hooks and aliases as themselves**; proj prints a notice. Share only what you would accept others running.
* `proj share` refuses a name the shared registry already has. It copies the file unchanged and removes the private copy last.
* `--group <group>` gives it to another group you belong to instead of the registry's.

## Who can see and change it?
```bash
proj access demo                 # shows the level
proj access demo --owner-only    # everyone with access to the registry reads, only the creator changes (default)
proj access demo --group-writable   # the group changes it too
proj access demo --private       # only the group sees and changes it
```
Only the creator can change the level. Someone who may not read an environment never sees its name: `proj list` prints `N environment(s) you have no permission to read not shown`.

## How do I make it private again, or delete it?
```bash
proj unshare demo      # back to ~/.proj/envs; only its creator
proj remove demo       # asks first; with no terminal it needs --yes
```
* `unshare` refuses while a process of yours looks like it has the environment active; close it, or `--force` if sure. It never moves the environment active in the current shell.
* `proj remove` deletes the environment's record (and with `--delete-files` its other files and generated module). It **never** deletes the project folder or a Python environment, and never the active environment.
* For your own variant of someone's shared environment use `--from`, or your personal settings (`proj-activate`, `proj-python`).

## Why did it fail?
| Message | Cause | What to do |
|---|---|---|
| `environment 'x' already exists` | the name is taken here or in the shared registry | choose another; `proj list` |
| `environment 'x' belongs to <user>; only its owner (or its group, if group-writable) can change it` | you are not the creator | ask the creator, or copy it with `--from` |
| `no shared registry is configured; ...` | this proj has no shared registry | it is a site setting: ask your site administrator, or see `proj doctor` |
| `group 'g' does not exist` (or you are not in it) | `--group` takes a group you belong to | use one from `id -Gn`; ask your site administrator to add you |

## What does this skill not cover?
Entering it: `proj-activate`. Tools: `proj-modules`. Python: `proj-python`. Group membership, the registry's folder and its permissions belong to your site administrator.
