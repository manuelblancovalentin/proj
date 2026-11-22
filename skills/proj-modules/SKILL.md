---
name: proj-modules
description: Use when you want to add or remove tools (compilers, toolchains, applications, library bundles) of a proj project environment, see what you can add, or work out why a tool's version or command is not the one you expected.
---

# Add and remove the tools of a project

Verified 2026-11-22 with proj 0.9.0 and Lmod 9.4.2, using invented modules (`gcc`, `cmake`, `simtool`, `pdk-demo`, `suite-team`) in a scratch module folder. Which modules exist, and their categories, depend on the modulefiles your site provides (`MODULEPATH`; `proj doctor` checks it): use `proj avail` on your installation.

## What can I add?
```bash
proj avail                 # every module Lmod can load, grouped: Compilers, Toolchains, Applications (a * marks the default version)
proj avail compiler        # one category, or part of a name: proj avail gcc
proj use --list            # what you may add to a project, by category (names without prefixes)
proj catalog               # the same as JSON, for programs (never shows library files or versions)
```
A module is in a category only if its modulefile says `whatis("Category: compiler|toolchain|application|project")`. Modules without it, or that need a Unix group you are not in, are not offered (`proj catalog` shows `allowed: false`).

## How do I add and remove a tool?
```bash
proj use --env demo gcc cmake simtool/20.1   # a bare name follows the module's default version; name/version pins one
proj use --env demo                          # what demo uses now
proj unuse --env demo cmake
```
* `proj use <name>` looks for `<name>`, `pdk-<name>` and `suite-<name>`. If more than one exists, or none, it is an error, never a guess: give the full name. A module of the same Lmod family replaces the old one (`Replaced gcc/12.2 with gcc/13.3`).
* If `demo` is the active project in this shell, `proj use` reloads it for you (`Project 'demo' updated in this shell`). Otherwise it takes effect the next time `demo` is activated.
* Without `--env` the active project is used.
* The low-level form edits the list only: `proj module add application simtool/20.1 --env demo`, `proj module remove application simtool/20.1 --env demo`, `proj module list application --env demo`. It does **not** reload: run `proj reload` yourself to apply it to an active project.

## How do I add a library module?
Library modules are the ones whose names start with a prefix the site configures (`library_prefixes`, default `pdk-`) or are listed in `library_names`. They are added by name like anything else: `proj use --env demo pdk-demo`. proj never opens or lists their files, and its JSON output only counts them. Which ones exist depends on your site: ask the project's creator or your site administrator.

## Why do I get the wrong version or the wrong command?
* The modules of a project load in this order: `project`, `toolchain`, `application`, `compiler`. When two of them provide the same command, the one loaded last is found first on `PATH`: an application's `tool` beats a toolchain's `tool`. Check with `command -v tool` and `proj use --env demo`.
* A bare name follows the default version of the module, which can change when the site updates it. Pin it: `proj use --env demo simtool/20.1`.
* A private environment of the same name hides the shared one for you. `proj info --env demo` says `Scope: private` or `shared`. Rename or remove your private copy (`proj remove demo`), or use the shared name.

## Why did it fail?
| Message | Cause | What to do |
|---|---|---|
| `no module matches 'zzz'. See: proj use --list` | no such name, or no `Category` tag, or not allowed for you | `proj use --list`; ask your site administrator if you expected it |
| `'x' matches several modules (x, pdk-x, suite-x)` | more than one of the three exists | give the full name |
| `no module matches 'project'` | the `project/` namespace is proj's own: you cannot add it | never add it |
| the tool is missing after `proj module add` | the project was already active | `proj reload` |

## What does this skill not cover?
Entering the project: `proj-activate`. Creating or sharing it: `proj-create-share`. The Python environment: `proj-python`.
