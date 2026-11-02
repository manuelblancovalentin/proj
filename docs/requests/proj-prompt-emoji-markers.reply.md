# Reply: short emoji markers inside proj (2026-11-02)

Done as asked, with the placement inside the brackets: `[proj:atlas 🐍 🐺]`. Nothing
is committed or released yet (version still 0.8.0).

## The variable for the wolf agent (item 4)

**`PROJ_PROMPT_TOKENS`**: the names of the tokens proj draws, separated by spaces
(`python wolf`), exported while an environment is active and removed on deactivate.
The wolf agent hides its own marker while `wolf` is in it, and never calls `proj`:

```sh
case " ${PROJ_PROMPT_TOKENS-} " in *" wolf "*) ;; *) draw_wolf_marker ;; esac
```

It is deliberately **unset** whenever proj is *not* the one drawing the marker
(`PROJ_PROMPT=off`, or, in Zsh, dots drawing the badge), so wolf keeps its own marker
exactly when proj would not show the 🐺. It is set when the environment is
activated, so it does not depend on the order of the two prompt hooks.
`PROJ_ACTIVE` (the environment's name, already exported) still says only "an
environment is active". Documented in `docs/prompt-markers.md`, the README and the
man page. A second variable, `PROJ_PROMPT_TABLE`, is internal (it lets a shell
started inside the environment draw the same tokens); nobody should read it.

## What was done, against your eight items

1. **Token table as data.** `[prompt]` in the configuration, one `[[prompt.token]]`
   row per token (`name`, `emoji`, `plain`, `when`). Built in: `python` 🐍 `py`
   `CONDA_PREFIX`, `wolf` 🐺 `wolf` `WOLF_ACTIVE_ENV`. A later token is one row and
   no code; a row naming an existing token changes only the fields it gives;
   `enabled = false` removes one. Site rows first, the user's over them by name.
   Every row is validated (emoji, name, variable name, ASCII form, no two tokens
   with the same emoji). The table is read when an environment is activated, so a
   change needs a new `proj activate`.
2. **Evaluated at prompt time**, in Bash (`PROMPT_COMMAND`, string and array forms,
   as before) and Zsh (`precmd`), with shell builtins only: no subprocess per
   prompt. A `conda activate` or `wolf activate` typed inside proj shows at the next
   prompt, and `deactivate` removes it. The person's own prompt is only added to, as
   with the current marker.
3. **The manager's prefix is off only inside proj.** On `proj activate`:
   `CONDA_CHANGEPS1=false` (conda, mamba) and `MAMBA_CHANGEPS1=false` (micromamba).
   I checked on this machine that micromamba 2.8.1 **ignores** `CONDA_CHANGEPS1` and
   honors `MAMBA_CHANGEPS1`, so both are set. The person's values (set or unset) are
   restored on `proj deactivate`, after a failed activation, and when switching (a
   deactivation then an activation). The switch stays off while the manager
   deactivates, so a prefix that was already in the prompt before `proj activate`
   (a `(base)`, say) is not touched in either direction; checked with the real
   micromamba. Outside proj nothing is set and nothing is edited: no `.condarc`, no
   `conda config`. This also removes the long path prefix you saw, without needing to
   find out why `conda config --set` did not stick.
4. **The variable**: above.
5. **Width.** Each emoji is one code point of East Asian Wide width, checked when the
   configuration is read (no variation selector, no joiner sequence, no narrow or
   ambiguous symbol). A unit test checks that the C library's `wcwidth` gives 2 for
   both defaults, which is what readline and Zsh use.
6. **Plain form** when the locale is not UTF-8 (`LC_ALL`, `LC_CTYPE`, then `LANG`),
   `TERM` is `linux` or `dumb`, `PROJ_PLAIN_PROMPT` is set (not empty/`0`/`off`/`no`/
   `false`) or `prompt.plain = true`: `[proj:atlas py wolf]`. `NO_COLOR` is honored.
7. **One list of the emoji taken**: `docs/prompt-markers.md`. 🐍, 🐺, and 🧭 (dots uses
   it for proj in its welcome table, so I kept it out of the markers).
8. **Tests**: `tests/test_prompt.py` (table, layering, validation, width) and a block
   in `tests/run`, in Bash and Zsh: token appears and disappears with the variable at
   the prompt; plain form (four triggers); restore of the person's own
   `CONDA_CHANGEPS1` after deactivate and after a failed activation; conda's prefix
   suppressed only inside proj and back outside (a stand-in that follows
   `CONDA_CHANGEPS1`); a prefix already in the prompt kept; the person's own prompt
   surviving; each switch off; dots taking over in Zsh; the real micromamba in both
   shells. I broke the suppression on purpose to confirm the tests notice. The whole
   suite and the benchmark pass (shell init still ~2 ms).

## How to switch it off

| What | How |
|---|---|
| No tokens at all (just `[proj:name]`, manager's prefix left alone) | `[prompt] show_tokens = false` |
| Tokens, but keep the manager's own prefix | `[prompt] hide_manager_prefix = false` |
| Always ASCII | `[prompt] plain = true`, or `PROJ_PLAIN_PROMPT=1` per person |
| One token (say the wolf) | `[[prompt.token]]` with `name = "wolf"` and `enabled = false` |
| proj does not draw the marker at all | `PROJ_PROMPT=off` (as before; the tokens and the prefix change go with it) |

## What could not be tested, and what to watch

- **A real terminal's rendering.** That the emoji is drawn two cells wide and the
  cursor does not drift on a long, edited or wrapped line rests on `wcwidth` in
  readline/Zsh and on the terminal. I checked the code points and `wcwidth`, not the
  pixels; no narrow-terminal run was done. Please try a long line in a 40-column
  window on kona.
- **Real conda and mamba**: not installed here. The suppression for them is the
  documented `CONDA_CHANGEPS1`, exercised only through a stand-in. micromamba 2.8.1
  was exercised for real.
- **Real Lmod, and kona's own zsh setup.** If kona's Zsh runs dots, dots draws the
  badge (unless `DOTS_PROMPT=never`), so proj shows no tokens and leaves conda's
  prefix alone, by the existing rule that the badge never appears twice. Then the
  prompt would look as it does today. Tell me if that is your case and I will look at
  letting dots show the tokens.
- **Shells started inside proj** inherit the table and the exported variables, so they
  should show the tokens too; I did not test that. `proj deactivate` is meant for the
  shell that activated.

## Before you use it on kona

- An **older proj rejects `[prompt]`** in `config.toml` ("unknown configuration
  keys"). The built-in defaults need no `[prompt]` table, so do not add one to the
  site configuration until every user is upgraded. Upgrading is still
  `proj upgrade --force` until a version is released.
- The adapter and the executable come from the same tree; with an old adapter and
  the new executable the tokens simply do not appear.
