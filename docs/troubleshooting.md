# Troubleshooting

## Lmod unavailable

Run:

```zsh
proj doctor
```

Both Lmod itself and its `module` Zsh function are required. Installing a
package without sourcing Lmod's Zsh initialization is insufficient.

## Activation says to source the integration

Add this to the interactive Zsh configuration:

```zsh
source /tools/proj/shell/init.zsh
```

An executable cannot modify its parent shell.

## Micromamba integration unavailable

Initialize the micromamba Zsh hook before activating a project that declares a
Python environment. The convenience alias `mamba` does not replace the hook.

## State drift

`proj status` reports manual changes to loaded modules or micromamba state.
Restore the expected state before deactivation. The initial release does not
guess or force cleanup.

## A public command link conflicts

`proj install` never overwrites `/tools/bin/proj`. Inspect and resolve the
existing path manually, then rerun installation.
