---
name: proj-activate
description: Use when you want to enter or leave a project environment with proj, control which folder the shell lands in, or change how activation behaves for you only (personal settings with `proj config --mine`).
---

# Activate a project and choose where the shell lands

Verified 2026-11-22 with proj 0.9.0 plus the commit after it (the next release; `--mine` behavior settings do not exist in 0.9.0 itself, check `proj --version`), in Bash with Lmod 9.4.2. Anything not listed here is not verified.

## How do I enter and leave a project?
```bash
proj activate demo      # loads the project's Lmod module, its Python environment, aliases, hooks; goes to the project root
proj current            # prints the active name; exits 1 and prints nothing when none is active
proj status             # "State: consistent" when nothing was changed by hand
proj deactivate         # undoes it all and returns to the folder you were in
```
* One project per shell. `proj activate other` while `demo` is active is refused: deactivate first.
* `activate` and `deactivate` are shell functions. In a script, `bash -c` or an agent's non-interactive shell they do not exist: source `<proj root>/shell/init.bash` (or `init.zsh`) first.
* `proj reload` leaves and enters the active project again and keeps your folder. Use it after a change you made to the project while it is active (modules, Python link). `proj activate demo` in a shell holding an older record of `demo` does the same.

## Where does the shell land, and how do I change it?
By default in the project root. Your own settings change that for you only; nobody else sees them and the project is not edited:
```bash
proj config --env demo --mine 'behavior.activate_directory=${project.root}/${user}'
proj config --env demo --mine behavior.activate_directory        # print it
proj config --env demo --mine --unset behavior.activate_directory
```
* Keys you may set: `behavior.activate_directory`, `behavior.change_directory` (`false`: never move the shell), `behavior.run_startup_hooks`, `behavior.restore_login_modules` (`true` or `false`), and `python.environment`, `python.manager` (see the Python skill). Anything else (`project.root`, modules, hooks) is refused with this list.
* Put a setting in `[behavior]` of `~/.config/proj/config.toml` to apply it to every project. Order, later wins: the site's `[behavior]` (the site configuration file; `proj doctor` shows whether there is one), yours, then `~/.config/proj/projects/<name>.toml` (written by `--mine`).
* In `activate_directory` you may use `${project.root}`, `${user}`, `${project.name}`, `${project.metadata}`, `${user.home}`. It must expand to an absolute path.
* If that folder is missing or you cannot enter it, you land in the project root silently (`PROJ_VERBOSE=1` prints one line). A relative path or an unknown variable prints one line and also uses the root.
* `behavior.change_directory = false` wins over everything: the shell stays put.
* The setting is read at each `proj activate`; no new shell is needed. For a project already active, run `proj reload`.

## Why can't a startup hook change my directory?
Hooks (`hooks.startup`) run as child processes. A child cannot change its parent shell's folder: a hook that runs `cd /` works inside itself and the shell still lands in the project root. Use `behavior.activate_directory`.

## Why did it fail?
| Message | Cause | What to do |
|---|---|---|
| `project 'x' is already active; deactivate it first` | another project is active here | `proj deactivate` |
| `Lmod is unavailable; run proj doctor` | `module` is not defined in this shell | source Lmod's init, then the proj adapter |
| `Python environment state has drifted (...)` on deactivate | you changed the Python environment by hand | restore it, or `proj deactivate --force` |
| `the Python environment of 'x' was changed after this shell activated it` | someone relinked it while you were active | `proj deactivate`, or `proj reload` to use the new one |
| `'project.root' is not a setting one person can change` | `--mine` takes only the keys above | edit the project (its creator) or use a listed key |

## What does this skill not cover?
Adding tools: skill `proj-modules`. Creating and sharing: `proj-create-share`. Python environments: `proj-python`.
