# Reply: a per-user override of the Python environment of a shared environment

Implemented as your first option (a user-level overlay), plus the documentation
and the machine-readable parts of your third. Not released: `__version__` is
still 0.8.0, so a server gets it with `proj upgrade --force` once a release
exists.

## The command

```sh
proj set-python-env --env atlas --mine my-atlas             # a name, or an absolute prefix
proj set-python-env --env atlas --mine my-atlas --manager conda
proj set-python-env --env atlas --mine --unset              # back to the shared one
```

`--mine` writes one file of yours, `~/.proj/overrides/atlas.toml`
(`$PROJ_HOME/overrides/` when `PROJ_HOME` is set; directory 0700, file 0600):

```toml
schema = 1

[python]
manager = "conda"
environment = "my-atlas"
```

Example, as a member of the project (names invented):

```text
$ proj set-python-env --env atlas --mine my-atlas
Your Python environment for 'atlas' is now micromamba 'my-atlas'.
The shared environment is unchanged for everyone else; it links /projects/atlas/atlas.pyenv (conda).
Recorded in /home/ada/.proj/overrides/atlas.toml; remove it with `proj set-python-env --env atlas --mine --unset`.

$ proj info --env atlas
  ...
  Python manager       micromamba
  Python environment   my-atlas
  Python override      yours; the shared environment links /projects/atlas/atlas.pyenv (conda)

$ proj status --env atlas --json
  "python": {"manager": "micromamba", "environment": "my-atlas",
             "environment_source": "override", "dependencies": {...}}
```

Reactivate to apply (`proj deactivate && proj activate atlas`); the command says
so when the environment is active in that shell.

## What it does and does not do

- `proj activate`, the generated Lmod module, `proj info`, `proj status` and
  `proj env show` all use the override, because it replaces the Python link on
  the loaded environment in one place (discovery). Modules, variables, paths,
  aliases, hooks and the root are the shared document's.
- The shared document is never written (a test compares its bytes before and
  after), nobody else sees the choice (another person's `PROJ_HOME` has no such
  file), no access changes, and the file can hold nothing that runs: only
  `manager` and `environment`; any other key makes the file invalid.
- The manager defaults to the shared environment's (or your existing
  override's); pass `--manager` when your environment belongs to another one.
- It applies to environments that are not yours. For an environment of your own
  the command refuses and says to link normally (without `--mine`). A leftover
  file for an environment that became private is ignored.
- An invalid or world-writable override file makes that environment unusable
  *for that person* until fixed or removed, with the file named in the error.
  It never silently falls back to the shared Python environment, which would
  hide a typo. Everyone else is unaffected, and `proj list` reports it as a
  skipped document.
- `--mine --unset` removes only that file, never a conda environment. A
  `--unset` with no override is an error ("you have no Python override").
- `proj set-python-env` without `--mine` still changes the shared document, for
  its owner, and now uses the document's own manager as its base rather than a
  person's override of it.

## For the website

- `proj status --env NAME --json` has `python.environment_source` (present with
  `python.environment`): `override` (yours), `shared` (an environment that is
  not yours, no override) or `own` (an environment of yours). It is read for the
  person who runs proj, so a service running as itself sees *its own* overrides,
  not a member's. To show a member's, run `proj status --json` as that member.
- `proj list --json` and `proj catalog` never read overrides: they describe the
  documents, as before, and `schema` stays 1 (an optional key was added).
- `python.environment` in the override case is the last component of the
  prefix when you gave a path, like any other environment; no paths or user
  names are in `status --json`.

## Same-name precedence (your item 3, documentation)

The behavior stays: `proj create` and `proj share` refuse a name that exists
anywhere. A private environment can shadow a shared one of the same name only
when the private one was made before the shared one existed, or lives in
another root; discovery then takes the private one. The documentation said a
person could do this on purpose; it now says that, and points to `--mine` for
the Python case (`README.md`, `docs/shared-software-projects.md` section 2b,
the man page). There is no `--shadow`.

## Stamp state of `python.spec` (your item 3, JSON)

It was already in `proj status --json` as `python.dependencies.state`, with
the same four situations under other words (renaming them would have raised
`schema`). Mapping:

| yours | `state` | meaning |
|---|---|---|
| `up-to-date` | `current` | the file's hash equals the stamp |
| `file-changed` | `behind` | the file changed after the stamp |
| `never-built` | `unstamped` | never stamped (`proj python-env stamp`) |
| `no-file` | `no-spec` | no `python.spec` declared |
| (none) | `unreadable` | declared, but the file cannot be read |

The mapping is now in `docs/machine-readable.md`. With an override the state is
still the shared environment's: it describes what the *shared* environment was
built from.

## What was not tested

- A real `proj activate` with a real conda/micromamba and an override. The
  tests check that the activation code and the generated module carry the
  override's environment and manager, and that the shared document and
  everything else are unchanged.
- A person whose `~/.proj` is on a read-only or unusual file system.
- An older proj (0.8.0 or earlier) ignores the file: activation there uses the
  shared Python link. So the override only works on a host that has the new
  proj, and the override file is harmless on one that does not.
