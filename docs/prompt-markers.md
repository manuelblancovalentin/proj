# Prompt markers

While an environment is active, the shell adapters put a marker in front of the
prompt. It names the environment and, for each kind of environment that is on in
this shell, a small emoji (its tokens):

```text
[proj:atlas 🐍 🐺] user@host:atlas$
```

Outside an environment, proj does not touch the prompt, a Python manager's
settings, or `.condarc`; conda, wolf and the rest draw their own markers as
before.

## What proj does

- **Tokens, at every prompt.** A token is shown while its environment variable is
  set and not empty (`CONDA_PREFIX` for 🐍, `WOLF_ACTIVE_ENV` for 🐺). The
  adapters read the variables each time the prompt is drawn, with shell builtins
  only (no subprocess), so a `conda activate` or `wolf activate` typed inside the
  environment shows at the next prompt, and `deactivate` removes it. Bash and
  Zsh behave the same.
- **No second marker from the Python manager.** The Python manager's own
  `(environment)` prefix is switched off while proj is active, because the 🐍
  token says the same thing: `CONDA_CHANGEPS1=false` (conda, mamba) and
  `MAMBA_CHANGEPS1=false` (micromamba; it does not read the first). The
  person's own values are put back when the environment is deactivated, after a
  failed activation, and when switching to another environment (which is a
  deactivation followed by an activation). A prefix that was already in the
  prompt before `proj activate` is left exactly as it was.
- **Only when proj draws the marker.** If `PROJ_PROMPT=off` or, in Zsh, dots draws
  the badge (unless `DOTS_PROMPT=never`), proj draws no tokens and leaves the
  manager's prefix alone, so the information is never lost.
- **One code point.** Every emoji is a single code point of East Asian Wide
  width, with no variation selector and no joiner sequence, so Bash and Zsh
  count its width the same way as the terminal and a line that is edited or
  wrapped does not drift. The configuration rejects anything else.
- **Plain form.** The ASCII form is used when the locale is not UTF-8
  (`LC_ALL`, `LC_CTYPE`, then `LANG`), when `TERM` is `linux` or `dumb`, when
  `PROJ_PLAIN_PROMPT` is set (anything but empty, `0`, `off`, `no`, `false`), or
  when `prompt.plain = true` is configured:

  ```text
  [proj:atlas py wolf] user@host:atlas$
  ```

  `NO_COLOR` is honored (the marker has no color).

## For other tools: the variables proj exports

| Variable | While an environment is active |
|---|---|
| `PROJ_ACTIVE` | The environment's name. Non-empty exactly while one is active in this shell. |
| `PROJ_PROMPT_TOKENS` | The names of the tokens proj draws, separated by spaces (`python wolf`). **Unset** when proj is not drawing the marker (no environment, tokens switched off, `PROJ_PROMPT=off`, a framework drawing the badge). |
| `PROJ_PROMPT_TABLE` | Internal: the token table, so a shell started inside the environment draws the same tokens. Do not depend on its format. |

A tool that draws its own marker hides it while its name is in the list, and
reads nothing else (no call to `proj` at the prompt):

```sh
case " ${PROJ_PROMPT_TOKENS-} " in
  *" wolf "*) ;;               # proj shows the wolf: draw nothing
  *) draw_my_own_marker ;;
esac
```

The variable is set when the environment is activated. If a tool's prompt hook
may run before proj's, this is still safe: it never depends on the order of the
hooks.

## The emoji taken

One list, so that no two tools choose the same emoji. Add a row here when you add
a token.

| Emoji | Code point | Token | Shown while | Used by |
|---|---|---|---|---|
| 🐍 | U+1F40D | `python` | `CONDA_PREFIX` is set | proj (built in) |
| 🐺 | U+1F43A | `wolf` | `WOLF_ACTIVE_ENV` is set | proj (built in) |
| 🧭 | U+1F9ED | | | dots, for proj in its welcome table (kept out of the markers) |

## Configuration

In `config.toml` (site, then user; see the README). Everything is optional:

```toml
[prompt]
show_tokens = true            # false: just [proj:<name>], and the manager's prefix is left alone
hide_manager_prefix = true    # false: show the tokens and leave the manager's own prefix on
plain = false                 # true: always the ASCII form

# One row adds a token; a row naming an existing token changes only the fields it gives.
[[prompt.token]]
name = "fox"                  # lowercase letters, digits, - and _
emoji = "🦊"                  # one wide code point
plain = "fox"                 # ASCII fallback, 1-12 letters, digits or . _ + -
when = "FOX_ACTIVE"           # shown while this variable is set and not empty

[[prompt.token]]
name = "wolf"
enabled = false               # remove a built-in token
```

Site rows come first and the user's layer over them by name. Two tokens cannot
share an emoji. The table is read when an environment is activated; change it and
activate again. Per person, `PROJ_PLAIN_PROMPT=1` switches to the ASCII form and
`PROJ_PROMPT=off` stops proj from drawing the marker at all.

## What the tests cannot check

The tests check the text of the marker, the variables, the restore and the
manager's behavior (the real micromamba, and a conda stand-in that follows
`CONDA_CHANGEPS1` the way conda does). They do not render the marker in a real
terminal: that an emoji is drawn two cells wide, and that the cursor stays put
when a long line is edited or wrapped, rests on `wcwidth` in the shell and the
terminal. Real conda and mamba were not available to run.
