# Activation lifecycle

## Activation

1. Resolve and validate metadata without changing the shell.
2. Generate or reuse the cached Lmod modulefile.
3. Confirm the shell's `module` function exists.
4. `module use` the managed module cache.
5. Record the modules the login already has loaded (`PROJ_LOGIN_MODULES`; skipped
   when `behavior.restore_login_modules` is false; a plain variable, not
   exported, at most 4096 characters), then `module load project/<name>`.
6. Set up the prompt tokens (`_proj_prompt_begin`): export `PROJ_PROMPT_TOKENS`
   and `PROJ_PROMPT_TABLE` and switch off the Python manager's own prompt prefix
   (`CONDA_CHANGEPS1`, `MAMBA_CHANGEPS1`), remembering the person's values; see
   `prompt-markers.md`.
7. Activate the configured Python environment with its manager.
8. Change to the project root when configured.
9. Run startup hooks.

Failure after mutation unloads the project module, restores the login's modules, deactivates the newly created
Python environment level, removes the module path, restores the directory, and clears
adapter state.

Activating while another project is active fails. Lmod's `family("project")`
provides the underlying exclusivity.

## Deactivation

1. Verify Python environment state has not drifted from what *this shell*
   activated (the module's own `PROJ_MAMBA_ENV` and `PROJ_PYTHON_MANAGER`, not
   the project's current record).
2. Run shutdown hooks.
3. Deactivate exactly the Python environment level created by proj.
4. Unload the project module, then load back any login module the environment
   displaced (Lmod swaps another version or family member in without
   remembering it).
5. Remove the managed module path.
6. Restore the previous directory.
7. Clear adapter-owned state, including the prompt tokens: the person's
   `CONDA_CHANGEPS1` and `MAMBA_CHANGEPS1` come back and `PROJ_PROMPT_TOKENS` and
   `PROJ_PROMPT_TABLE` are removed (after the Python environment was deactivated,
   so the manager's prefix switch stays off until then).

A change of the project's Python record after activation is not drift: the
shell is left with what it recorded and told what changed (`proj reload` or
`proj activate` in that shell switches to the new one; `proj status` says "uses
the previous Python environment"). If the Python environment was changed by
hand, proj refuses to guess and names what differs; `proj deactivate --force`
leaves anyway (a failing shutdown hook or Python deactivation only warns) and
never touches a Python environment other than the recorded one.

`proj reload` is deactivation with the prompt-level messages off, followed by
activation, in the current directory; the shell remembers the directory from
before the first activation.

## Reversibility

Lmod reverses variables, paths, aliases, and dependency references. Micromamba
reverses its own environment level. External hook side effects are reversible
only when the project supplies an appropriate shutdown hook.
