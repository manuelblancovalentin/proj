# Reply: a setting for the directory `proj activate` lands in

Implemented, together with one general way for a person to set anything of
their own for one environment. Not in 0.9.0; no version bump yet.

## What the person does

Either in their configuration, for every environment:

```toml
# ~/.config/proj/config.toml
[behavior]
activate_directory = "${project.root}/${user}"      # default when absent: the project root
```

or for one environment, with a command (this writes
`~/.config/proj/projects/ogrencilab-efpga.toml`, mode 0600, a configuration file
that applies to that environment only):

```sh
proj config --env ogrencilab-efpga --mine behavior.activate_directory='${project.root}/${user}'
proj config --env ogrencilab-efpga --mine behavior.activate_directory     # prints it
proj config --env ogrencilab-efpga --mine --unset behavior.activate_directory
```

The file for one environment beats the global key (and a site's `[behavior]`
sits below both). Your six rules:

1. No key: the project root, as before. No project record changes and nobody
   else's configuration is read.
2. `${project.root}` and `${user}` (login name), plus the ones proj already has
   (`${project.name}`, `${project.metadata}`, `${user.home}`). The result must be
   absolute; a relative result or an unknown variable prints one line and the root
   is used, and the activation still succeeds.
3. The per-environment setting beats the global key for that environment.
4. A folder that does not exist, is not a folder or cannot be entered: the root,
   silently. `PROJ_VERBOSE=1` (any value but `0`) adds one line. There was no
   verbose switch before; this is it.
5. `change_directory = false` still wins, globally or for one environment.
6. `[project] root`, `${project.root}`, aliases, `paths.prepend` and `PROJ_ROOT`
   are untouched; `${project.root}` is the root as written in the record.

## One mechanism for anything personal (the owner's design note)

Whatever is in a person's own files is their override; there is no separate
concept. The names are the record's and the configuration's own:

| key | meaning |
|---|---|
| `behavior.activate_directory` | where `proj activate` lands |
| `behavior.change_directory`, `behavior.run_startup_hooks`, `behavior.restore_login_modules` | the other `[behavior]` switches, for one environment |
| `python.environment`, `python.manager` | the person's own Python link for an environment that is not theirs |

`proj config --env NAME --mine KEY=VALUE` sets, `--mine KEY` reads and
`--mine --unset KEY` forgets, for any of them. `proj set-python-env --mine` is the
same thing for the Python link, and the 0.9.0 file for it
(`~/.proj/overrides/NAME.toml`) is still read and is folded into the new one the
next time the person changes a setting of that environment, so nothing breaks.
Anything else (`project.root`, modules, aliases, hooks, ...) is refused with the
list of what may be set.

For the next setting that should be personal: `BEHAVIOR_SETTINGS`
(`proj/config.py`) and `SETTABLE` (`proj/userconfig.py`) are the two registries;
a new entry there and a field in `Behavior` is all it takes, and the file,
`--mine`, validation and messages follow. A default set in a *project record* for
all its members (the "ROOT" level) would be one more layer under the person's; it
is not built because it changes the record's schema.

## Which version, and what the person needs to do

- **Not in 0.9.0.** It will be in the next release (I have not bumped the
  version). Until then a server has it only from the repository.
- Once the server has it (`proj upgrade`; from 0.8.0 `proj upgrade --force`): the
  setting is read by the `proj` executable at each `proj activate`, and the chosen
  folder is handed to the shell as the directory to enter. **No new shell is
  needed**, even in a terminal that loaded the adapter before the upgrade. The
  person runs the one `proj config --mine` command (or adds the line to
  `config.toml`) and then `proj activate` as usual.
- A project that is **already active** keeps where it landed. To use the setting
  there: `proj deactivate && proj activate <project>` (`proj reload` in a shell
  with the new adapter).
- `config.toml` is per person, so on a shared account's home the setting is that
  account's; a person's files live under their own `~/.config/proj/`.

## Tests

`tests/test_activate_directory.py` (25) and `tests/test_override.py` (18): no
key, existing and missing folders (silent, and one line with `PROJ_VERBOSE`), a
folder that cannot be entered, a file, the environment's own setting beating the
global one and not touching other environments, relative and unknown-variable
templates, the layers, every behavior switch for one environment, the file's mode
and the untouched record, read and forget, python and behavior sharing one file and
one command, refusal of keys a person may not set and of bad values, a broken file
stopping activation but not deactivation, `proj info` listing the settings, and a
0.9.0 file still read and folded in. `tests/run` drives a real Bash and a real Zsh
through six cases (none, global, missing, relative, your own for the environment,
stays put) and checks that `proj deactivate` returns to the starting folder; it
also covers the 0.9.0 file and `--unset`. Full `./tests/run`, the unit tests and
the benchmark pass.

Not tested: a real project with member folders on a shared file system, and a
folder reachable only through a group permission (checked with `os.access`, so it
should work; only an owner-readable folder ran).
