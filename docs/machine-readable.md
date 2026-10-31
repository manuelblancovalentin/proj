# Machine-readable output

Two commands print one JSON document for other programs, such as a website or a
login tool. Both are read-only, their keys are stable, and each carries a
`schema` number that only grows: removing or renaming a key, or changing what
one means, raises it; adding an optional key does not, so a consumer must ignore
keys it does not know. All names below are invented.

Neither document ever contains the path of a library, a library version, or a
user name (no owner field). The only paths are an environment's `project_root`
and its Python `prefix`, both taken from its metadata. Protected libraries are recognised by module **name**, set in the
site configuration (`PREFIX/etc/config.toml`): a prefix list, `pdk-` by
default, and an exact-name list for libraries that do not follow the prefix:

```toml
library_prefixes = ["pdk-"]
library_names = ["iplibs"]
```

A module whose name starts with one of the prefixes, or equals one of the
names (no version, no pattern), is a *library module*. It is never listed among
ordinary modules or bundles, its version is never printed, and an environment
that uses one names it only under `library_bundles` (name, no version). When a
suite or bundle depends on a library, the member is left out of `contains` and
counted in `withheld`.

## `proj list --json`: the environments

```sh
proj list --json [--scope all|shared|private] [--under DIR]...
```

It reads only the registries. It needs no Lmod, writes nothing, and creates no
cache. `--scope shared` leaves out the invoking user's private registry (a
program that runs as a service wants this), and each `--under DIR` keeps only
environments whose project folder is inside `DIR`; both also filter the table
of `proj list`. An invalid environment is counted in `skipped` and named on
stderr. A shared environment limited to a group you are not in (see
`proj access`) is expected, so it is only counted, in `unreadable`, and never
named; the table of `proj list` sums them up in one line on stderr.

**For a service** (for example a systemd timer), the complete command is

```sh
proj list --json --scope shared --under /projects
```

with a site configuration that names the shared registry. It works with an empty
environment: no `HOME` (not even a passwd entry), no Lmod, no `PROJ_*`
variables. It writes only to standard output (the registry, the cache and the
home are never created or modified). It builds the whole document first, so a
failure exits non-zero (status 2) with **nothing** on standard output and the
reason on standard error. These are failures, not empty lists: no shared
registry configured, a shared registry that does not exist, a registry that
cannot be listed. An environment inside the registry whose document is invalid
is *not* a failure: it is counted in `skipped` and named on stderr, so a service
should alert on `skipped > 0` if it cares. One that the service's user has no
permission to read (limited to a group it is not in) is counted in `unreadable`
instead, with nothing on stderr: it is normal for gated projects, and the
service can tell how many it cannot see.
`--scope shared` also keeps a private environment of the same name from hiding
a shared one. A project appears on the site only if its environment lives in
the shared registry (`proj create ... --shared`) and its folder is under `DIR`.

```json
{
  "schema": 1,
  "proj_version": "0.8.0",
  "generated": "2026-10-27T18:00:00Z",
  "skipped": 0,
  "unreadable": 0,
  "environments": [
    {
      "name": "atlas",
      "scope": "shared",
      "project_root": "/projects/atlas",
      "bundles": ["site-defaults"],
      "modules": [
        {"name": "simtool", "version": null},
        {"name": "gcc", "version": "13.3.0"}
      ],
      "library_bundles": ["pdk-example"],
      "python": {
        "manager": "micromamba",
        "environment": "atlas-env",
        "prefix": "/projects/envs/atlas-env"
      },
      "updated": "2026-10-26T09:14:51Z"
    },
    {
      "name": "birch",
      "scope": "shared",
      "project_root": "/projects/birch",
      "bundles": [],
      "modules": [{"name": "node", "version": "24.21.0"}],
      "library_bundles": [],
      "updated": "2026-10-25T16:02:10Z"
    }
  ]
}
```

* `name`, `scope` (`private`, `shared`, or `external` for an extra metadata
  root), and `updated` (when the environment's metadata last changed, UTC).
* `project_root` is the project folder the environment belongs to, as an
  absolute path with symbolic links resolved (even when the metadata, and so
  `proj list`, shows a link). **Compare it with the resolved
  path of the project's folder** (`realpath`), because the same folder can be
  reached through several mount aliases.
* `bundles`: the environment's modules of the `project` category, by name only.
* `modules`: every other module, with its pinned version, or `null` when the
  module's own default decides at load time.
* `library_bundles`: names of library modules (any category), kept apart so a
  consumer can drop them. Versions are never printed.
* `python` (optional): the conda-family environment linked with
  `proj set-python-env`; the key is **absent** when none is linked. `manager` is
  `micromamba`, `conda` or `mamba`. `environment` is the environment's name.
  `prefix` is its folder as an absolute path with symbolic links resolved, and
  is present only when the metadata records a path (`proj set-python-env`
  records one for a shared environment); when the metadata holds just a name, there is no
  `prefix`, because turning a name into a folder would mean asking the manager,
  and each person's manager may answer differently. Only the metadata is
  reported: proj does not run the manager or look inside the folder, so the
  prefix may not exist. Everywhere else proj shows the name alone.

### How a project folder is marked

It is not. The folder is not changed and holds no marker file. The only record
is the registry entry `<registry>/<name>/project.toml`, whose `project.root`
points at the folder; one folder can have several environments. A consumer
matches `project_root` against the folder it knows.

## `proj catalog`: what a person may add to a login

```sh
proj catalog
```

It asks Lmod what exists (it reads modulefile text and tags, never a library
tree) and answers for the person who runs it.

```json
{
  "schema": 1,
  "proj_version": "0.8.0",
  "generated": "2026-10-27T18:00:00Z",
  "modules": [
    {"name": "simtool", "category": "application", "versions": ["20.1", "21.1"],
     "default": "21.1", "groups": [], "allowed": true},
    {"name": "gated", "category": "application", "versions": ["1.0"],
     "default": "1.0", "groups": ["eda"], "allowed": false}
  ],
  "suites": [
    {"name": "lab", "module": "suite-lab", "kind": "suite", "versions": ["5"],
     "default": "5", "groups": ["lab"], "allowed": true,
     "contains": ["simtool", "gated"], "withheld": 1}
  ],
  "libraries_omitted": 3
}
```

* `modules`: every non-library module that is not a suite or bundle.
  `category` is its proj category, or `null` when it has none.
* `suites`: the curated sets. The rule, in this order, for a non-library
  module: if its name starts with `suite-`, it is a suite (`kind: suite`,
  `name` is the rest of the name); otherwise, if its `Category` tag is
  `project`, it is a bundle (`kind: bundle`, `name` is the module name). Nothing
  else is a suite: not a `family`, not a dependency count. `contains` is the
  **names** of the modules the set depends on or loads (`depends_on`, `load`,
  `always_load`, `try_load`), read from `module show` for its default version
  (null when Lmod cannot show it).
* `groups` and `allowed`, on both lists. A module declares who may use it with
  one tag, `whatis("Group: <unix group>")`. Several groups are written
  separated by commas or spaces (`whatis("Group: alpha, beta")`) and mean
  **any of them**. The word `any`, or no `Group` tag at all, means open to
  everyone: `groups` is `[]` and `allowed` is `true`. With a tag, `groups` lists
  the groups and `allowed` is true when the caller (the process's primary and
  supplementary groups) is in at least one. `allowed` is computed only from
  this tag and the caller's groups. **It is never derived from file
  permissions**: a module without a tag is `allowed: true` even if the tool
  directory behind it is not readable by the caller. A site whose access is
  Unix permission alone must add the tag to the modulefile for the catalogue to
  say so.
* `libraries_omitted`: how many library modules exist. Nothing else about them
  is reported, and libraries are not something a login loads.

## `proj status --json`: a provenance record

Where `list --json` describes every environment, this describes one environment
and, on request, one checkout, so it can be stored beside a result. It never
contains a path or a user name. The format (`schema` 1):

```json
{
  "schema": 1,
  "proj_version": "0.8.0",
  "generated": "2026-10-30T20:09:50Z",
  "environment": {"name": "atlas", "scope": "shared", "active": true, "copied_from": null},
  "state": "consistent",
  "drift": [],
  "modules": {"project": [], "toolchain": ["cmake/3.30"], "application": [], "compiler": ["gcc/14"]},
  "loaded_modules": ["gcc/14", "cmake/3.30", "project/atlas"],
  "python": {
    "manager": "conda",
    "environment": "atlas",
    "dependencies": {
      "spec": "environment.yml",
      "state": "current",
      "stamped_sha256": "dd82557f4b9b…",
      "stamped_date": "2026-10-12",
      "current_sha256": "dd82557f4b9b…",
      "checkout_sha256": "dd82557f4b9b…",
      "checkout_state": "matches"
    }
  },
  "checkout": {"commit": "63afc214ca88…", "branch": "ada/new-loss", "dirty": false, "changed_files": 0}
}
```

- `proj status --json` describes the active environment; `--env NAME` selects
  another. With none, `environment` is `null` and `state` is `"no environment"`.
- `state` is `drift` (exit status 2) or `consistent`. `drift` lists the reasons:
  modules or the Python environment not as the metadata says, or a dependency
  file that changed since the environment was stamped.
- `loaded_modules` is Lmod's list as loaded now (names with versions), or `null`
  when the environment is not active in this shell.
- `python.dependencies.state` is `no-spec`, `unreadable`, `unstamped`, `current`
  or `behind`. The dependency file is named by its file name only. `by` of the
  stamp is not exported.
- `checkout` and `checkout_*` appear only with `--checkout PATH`. `checkout_state`
  compares the checkout's copy of the file (the same name at its top, or the
  file itself if PATH is one) with the stamp: `matches`, `differs`, `missing` or
  `unstamped`. `branch` is `null` for a detached HEAD; `dirty` includes
  untracked files.
- The Git queries are `rev-parse HEAD`, `rev-parse --abbrev-ref HEAD` and `status
  --porcelain`, read-only, without optional locks or fsmonitor, with a 15 second
  limit. Nothing is fetched. A key may be added without raising `schema`.

## Login modules and environments

A login (site defaults, then a person's own choices) may already have modules
loaded when `proj activate` runs. The order is: login, then the environment.

* A conflict is possible: another version of a tool the login loaded, or
  another member of the same Lmod family. Lmod resolves it by swapping the
  environment's module in, silently; **inside the environment, the
  environment wins.**
* Lmod does not remember what it replaced. proj therefore records the loaded
  modules (`PROJ_LOGIN_MODULES`) when it activates, and on `proj deactivate`
  (and when `proj use`/`unuse` reload the environment, or an activation fails)
  it loads back any of them that the environment displaced. After deactivation
  the login's modules are exactly as they were. The record is a plain shell
  variable: it is not exported (tools and hooks never see it), it is replaced
  at each activation and dropped when the environment ends, and a login whose
  module list is longer than 4096 characters is not remembered at all (proj
  says so). `restore_login_modules = false` in the `[behavior]` table of the
  site or user configuration turns the whole mechanism off; the value must be
  a real boolean, and unknown `[behavior]` keys are rejected.
* A bare module name in an environment (no version) is satisfied by whatever
  version the login already loaded, so only a pinned version overrides it.
