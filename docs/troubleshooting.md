# Troubleshooting

## Lmod unavailable

Run:

```zsh
proj doctor
```

Both Lmod itself and its `module` shell function are required. Installing a
package without sourcing Lmod's shell initialization is insufficient.

Starting Zsh from a Bash login shell is a common case: Lmod's exported
variables survive, but the `module` function does not. `proj doctor` then
names the script to source, typically `source $LMOD_PKG/init/zsh` in
`~/.zshrc` before the proj block.

## Activation says to source the integration

Run `proj init` (it detects Zsh or Bash from `$SHELL`) and open a new shell.
An executable cannot modify its parent shell.

## `proj` runs a different program

Some systems ship an unrelated `/usr/bin/proj` (the PROJ cartography tool).
Initialize the shell so proj's `bin/` directory comes first on `PATH`, or
call the installed launcher by its full path.

## Shared environments

`proj doctor` checks the shared registry. "not a member of group" means an
administrator must run `usermod -aG <group> <user>`, after which you log in
again. "belongs to <user>" means the environment is owner-only; ask its owner,
or create a group-writable environment.

## Python manager integration unavailable

Initialize the manager's shell hook before activating a project that declares
a Python environment: `micromamba shell init`, `conda init zsh` (or `bash`),
or `mamba shell init`. A `mamba` that was never initialized works when `conda`
is. The convenience alias `mamba` does not replace the hook. `proj doctor`
shows the default manager; `proj info` shows the one a project uses.

## State drift

`proj status` reports manual changes to loaded modules or Python environment
state.
Restore the expected state before deactivation. The initial release does not
guess or force cleanup.

## A public command link conflicts

`proj install` never overwrites an existing `bin/proj` beside the checkout. Inspect and resolve the
existing path manually, then rerun installation.
