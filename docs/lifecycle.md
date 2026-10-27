# Activation lifecycle

## Activation

1. Resolve and validate metadata without changing the shell.
2. Generate or reuse the cached Lmod modulefile.
3. Confirm the shell's `module` function exists.
4. `module use` the managed module cache.
5. Record the modules the login already has loaded (`PROJ_LOGIN_MODULES`; skipped
   when `behavior.restore_login_modules` is false; a plain variable, not
   exported, at most 4096 characters), then `module load project/<name>`.
6. Activate the configured Python environment with its manager.
7. Change to the project root when configured.
8. Run startup hooks.

Failure after mutation unloads the project module, restores the login's modules, deactivates the newly created
Python environment level, removes the module path, restores the directory, and clears
adapter state.

Activating while another project is active fails. Lmod's `family("project")`
provides the underlying exclusivity.

## Deactivation

1. Verify Lmod and Python environment state have not drifted.
2. Run shutdown hooks.
3. Deactivate exactly the Python environment level created by proj.
4. Unload the project module, then load back any login module the environment
   displaced (Lmod swaps another version or family member in without
   remembering it).
5. Remove the managed module path.
6. Restore the previous directory.
7. Clear adapter-owned state.

If state drift is detected, proj refuses to guess. Automatic force recovery is
not part of the initial implementation.

## Reversibility

Lmod reverses variables, paths, aliases, and dependency references. Micromamba
reverses its own environment level. External hook side effects are reversible
only when the project supplies an appropriate shutdown hook.
