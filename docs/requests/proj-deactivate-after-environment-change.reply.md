# Reply: leaving a project whose Python environment was changed under the shell

All four items are implemented. Not released: `__version__` is still 0.8.0, so a
server gets it with `proj upgrade --force` once a release exists.

## What was wrong

`proj deactivate` built its undo from the project's *current* record. After
`proj set-python-env` changed the record, the shell still had the old Python
environment active, so the check "is the recorded environment the active one?"
failed and `deactivate` refused, with no way out.

## What it does now

The generated module already exported the environment the shell activated
(`PROJ_MAMBA_ENV`); it now also exports its manager (`PROJ_PYTHON_MANAGER`).
`proj deactivate` undoes **that**, not the project's current record, so a changed
record is no longer drift:

```text
$ proj deactivate
proj: the Python environment of 'atlas' was changed after this shell activated it
(it was atlas-3.11, it is now atlas-3.12); deactivating what this shell recorded;
run `proj activate atlas` to use the new one
 ✅ - Project 'atlas' deactivated ✨
```

(A prefix is named by its last component, or in full when the two would read the
same. "it was none" / "it is now none" when an environment was added or dropped.)

1. **`proj deactivate`** works, restores the PATH and variables Lmod and the
   manager saved, and says what happened (above).
2. **`proj reload`**, and **`proj activate atlas`** in a shell that holds an old
   record of that same project: deactivate quietly, then activate. Your current
   directory stays; a later `proj deactivate` still returns to where the shell
   was before the first activation. `proj activate atlas` in a shell where
   nothing changed is still "already active; deactivate it first", and
   `proj reload` with nothing active is an error.
3. **`proj status`** in such a shell:

   ```text
   State:        drift: this shell uses the previous Python environment (atlas-3.11; the project now has atlas-3.12): run `proj reload`
   ```

   Exit status 2, as for any drift, and the same text is in `drift` of
   `status --json`. It is not also reported as "Python environment is X,
   expected Y": that comparison is now against what the shell activated, so it
   only fires for a real hand edit. `state` stays `drift`/`consistent` and
   `schema` stays 1; the reasons were already free text.
4. **A hand edit is still refused**, now naming what differs, with the way out:

   ```text
   Python environment state has drifted (this shell has other active, expected atlas-3.11); restore it, or run `proj deactivate --force` to leave anyway
   ```

   `proj deactivate --force` skips that check. It deactivates the recorded
   environment only if it is the one active, never any other, and says what it
   skipped; a failing shutdown hook or manager deactivation only warns. Lmod's
   unload failing is still an error.

## Shells that are already open

This is the case that matters for the website: terminals opened before the
upgrade run the old adapter (`core.sh` is sourced once per shell) with the new
`proj` executable.

- **`proj deactivate` works there, and says why.** The executable decides which
  environment to undo and writes the message, so the old adapter needs nothing
  new. The undo uses `PROJ_MAMBA_ENV` from the module the shell loaded, which old
  modules already export. Only the manager is missing for shells activated
  before this version (no `PROJ_PYTHON_MANAGER`): it falls back to the project's
  current manager, which is right unless the manager itself changed.
- **`proj reload` and the switching `proj activate` need the new adapter.** An
  old adapter does not know `_proj_reload`; the second prints "this shell
  integration is older than the proj it runs; run `proj deactivate`, then
  `proj activate atlas`", and the first says it must run through the shell
  integration. A new shell has both.
- **`proj deactivate --force`** reaches the executable in an old shell, but the
  old function ignores it, so it only helps in a new one.

## What was tested

`tests/run` drives a real Bash and a real Zsh with a fake Lmod and manager:
activate, change the record in the document, then `status` (names the previous
environment, not a hand edit), `deactivate` (clean, message, directory
restored), `activate` (switches, keeps the directory), `reload`, a refusal for a
hand edit naming `other` against the expected environment, and `--force`
leaving with the other environment untouched. Against the old `core.sh` the
block fails. `tests/test_changed_record.py` covers the code the executable emits,
the notes, the module's new variable, and `status` (16 tests). Full
`./tests/run` and `./tests/benchmark` pass (shell init still about 2.3 ms).

## What was not tested

- Real Lmod, and a real conda or micromamba. The fakes follow what each does to
  `CONDA_*` and the exported variables, but `module unload` of a project module
  whose cached file was regenerated after the load (because someone activated
  the changed record in another shell with the same cache) relies on Lmod
  reversing `setenv`/`pushenv` and path entries from its own record; only
  variables or paths that *differ* between the old and new file could leave
  something behind.
- A project whose *modules* (not its Python environment) changed under an open
  shell. That is not covered here: `proj status` still reports it as the
  generic "missing modules" drift, and `proj reload` does pick the new list up.
  Say if you want it to read the same way.
- A shell started by another user, or `tmux`/desktop sessions: nothing is
  shell-specific beyond the variables above, but only Bash and Zsh were run.
