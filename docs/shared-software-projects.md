# Working on software in a shared project

A team develops a Python package that the project's shared environment also
installs. Everyone works in their own clone (here `~/atlas/repo`, branches
named `<user>/<topic>`) and opens pull requests into `main`. The project has one
shared proj environment, `atlas`. This page shows how to run different versions
of the package at once without anyone changing what another person runs.

Every name is invented. proj stays out of Git: it does not know about branches,
remotes or pull requests. It knows where *your* code lives, what the Python
environment was built from, and, only when you ask, which commit a checkout is at.

## The pattern

| You want | Use |
|---|---|
| `import pkg` to resolve to your clone, only for you | `environment_paths` (below) |
| A branch with different dependencies | `proj create --from` and your own Python environment |
| To know the shared Python environment is out of date | `python.spec`, `proj python-env stamp`, `proj status` |
| To record which commit and environment produced a result | `proj status --json --checkout` |

## 1. Your clone first on `import`

The environment's owner adds one line to the shared environment (once):

```sh
proj config --env atlas 'environment_paths.PYTHONPATH.prepend=["${user.home}/atlas/repo/src"]'
```

`${user.home}` is the home of whoever activates, so every member gets their own
clone; a member with no clone at that path gets nothing added and therefore the
installed (main) version. `proj deactivate` removes just that entry and leaves
the `PYTHONPATH` you had. Lmod does all of this (`prepend_path` guarded by
`isDir`); proj only writes it.

What it covers: `import pkg`, and console scripts that already exist (they import
the package by name). What it does not: compiled extensions, new entry points,
changed package metadata (`pip show`), which need a real install, see section 2.

A per-person tool folder works the same way:

```sh
proj config --env atlas 'environment_paths.PATH.append=["${user.home}/atlas/bin"]'
```

Trust: the table can only be changed by whoever may change the environment
(owner-only by default). It adds nothing hooks could not already do. Do not make
environments for software projects `--group-writable`: then any member could add
folders, and hooks, that run as the others.

## 2. A branch with different dependencies

Make your own Python environment from the shared one, install your clone into
it, and a private copy of the proj environment that uses it:

```sh
conda create -n atlas-topic --clone atlas
conda activate atlas-topic && pip install -e ~/atlas/repo   # then the new dependencies
proj create atlas-topic --from atlas --python atlas-topic
proj activate atlas-topic
```

`--from` copies the modules, variables, paths, aliases and hooks and records
where it came from. It is a snapshot: when `atlas` changes, `proj info
--env atlas-topic` says "the original has changed since". Use a different name:
a private environment shadows a shared one of the same name. `proj remove
atlas-topic` deletes the copy and never the conda environment.

An editable install made with `pip install --user` does **not** work as a
lighter alternative. In a virtual environment (tested; a conda environment lays
its paths out the same way) pip refuses to install to the user site when the
package is already in the environment, and setuptools' editable finder does not
shadow an installed copy.

## 3. Is the shared Python environment out of date?

The shared environment's maintainer says which file it is built from and stamps
it after each rebuild:

```sh
proj config --env atlas python.spec=/projects/atlas/environment.yml
# ... rebuild the conda environment from that file ...
proj python-env stamp --env atlas
```

Anyone can then ask, and a scheduled job can mail the maintainer on exit
status 2:

```sh
proj status --env atlas
# Dependencies: environment.yml, stamped 2026-10-12, changed since: the environment is behind it
```

proj only hashes the file. Keeping the file current (for example a read-only
export of `main`) and rebuilding the environment are yours; proj never builds a
Python environment or uses the network. A branch author can compare their own
copy:

```sh
proj status --env atlas --checkout ~/atlas/repo
# ... the checkout's copy differs from the stamp
```

## 4. Recording what produced a result

```sh
proj status --env atlas --json --checkout ~/atlas/repo > results/run-0007/provenance.json
```

It holds the environment name, the modules as loaded, the Python manager and
environment name, the stamped and current hashes of the dependency file, and
the checkout's commit, branch and whether the tree has changes (`dirty`). It has
no paths and no user names (format: [machine-readable.md](machine-readable.md)).
A dirty tree is not reproducible from the commit alone; commit or note the diff.
To pin the packages themselves, add the manager's own record, for example
`conda list --explicit --md5 | sha256sum`.

## Upgrading first

Older proj versions ignore `environment_paths`, `python.spec` and the stamp
tables and drop them the next time they rewrite a document. Upgrade every user
of a shared installation before using any of this.
