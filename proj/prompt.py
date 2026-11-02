"""The prompt marker's tokens: small emoji (with a plain fallback) that appear in
`[proj:<name> ...]` while an environment variable is set.

The table is data. proj reads it from the `[prompt]` configuration table when
an environment is activated and hands it to the shell adapter, which evaluates
it at every prompt with no subprocess. Nothing here runs in the prompt.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .errors import ConfigError

NAME_RE = re.compile(r"[a-z][a-z0-9_-]{0,31}")
VARIABLE_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
PLAIN_RE = re.compile(r"[A-Za-z0-9_.+-]{1,12}")
PROMPT_KEYS = {"show_tokens", "hide_manager_prefix", "plain", "token"}
TOKEN_KEYS = {"name", "emoji", "plain", "when", "enabled"}


@dataclass(frozen=True)
class Token:
    """Shown while the variable `when` is set and not empty."""

    name: str
    emoji: str
    plain: str
    when: str


# The first rows. A configured row with one of these names replaces it field by
# field; any other name adds a token.
DEFAULT_TOKENS = (
    Token("python", "\U0001F40D", "py", "CONDA_PREFIX"),
    Token("wolf", "\U0001F43A", "wolf", "WOLF_ACTIVE_ENV"),
)


@dataclass(frozen=True)
class PromptSettings:
    show_tokens: bool = True
    # Keep the Python manager from adding its own "(environment)" to the prompt
    # while an environment is active; the python token says the same thing.
    hide_manager_prefix: bool = True
    # Always use the ASCII form, whatever the terminal can show.
    plain: bool = False
    tokens: tuple[Token, ...] = DEFAULT_TOKENS

    def table(self) -> str:
        """The rows as the shell adapter reads them: one `name|emoji|plain|VARIABLE`
        per line. The emoji is empty when the plain form is always wanted."""
        if not self.show_tokens:
            return ""
        return "\n".join(
            f"{token.name}|{'' if self.plain else token.emoji}|{token.plain}|{token.when}"
            for token in self.tokens
        )


def check_emoji(value: object, label: str) -> str:
    """One code point of East Asian Wide width. Variation selectors and joiner
    sequences are several code points, and a narrow or ambiguous symbol is
    counted differently by different terminals; both make a line drift when it
    is edited or wrapped."""
    if not isinstance(value, str) or len(value) != 1:
        raise ConfigError(f"{label}: emoji must be exactly one code point")
    if unicodedata.category(value) != "So" or unicodedata.east_asian_width(value) != "W":
        raise ConfigError(
            f"{label}: emoji must be a single wide symbol (East Asian Width W), "
            f"not U+{ord(value):04X}"
        )
    return value


def _boolean(table: dict, key: str, source: str) -> bool | None:
    value = table.get(key)
    if value is not None and not isinstance(value, bool):
        raise ConfigError(f"{source}: prompt.{key} must be true or false")
    return value


def _rows(table: dict, source: str) -> list[dict]:
    rows = table.get("token", [])
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ConfigError(f"{source}: prompt.token must be an array of tables ([[prompt.token]])")
    return rows


def _apply(tokens: dict[str, Token], rows: list[dict], source: str) -> None:
    for number, row in enumerate(rows, 1):
        label = f"{source}: [[prompt.token]] #{number}"
        unknown = set(row) - TOKEN_KEYS
        if unknown:
            raise ConfigError(f"{label}: unknown keys: " + ", ".join(sorted(unknown)))
        name = row.get("name")
        if not isinstance(name, str) or not NAME_RE.fullmatch(name):
            raise ConfigError(f"{label}: name must be lowercase letters, digits, - or _")
        enabled = row.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ConfigError(f"{label}: enabled must be true or false")
        if not enabled:
            tokens.pop(name, None)
            continue
        known = tokens.get(name)
        fields = {
            "emoji": row.get("emoji", known.emoji if known else None),
            "plain": row.get("plain", known.plain if known else None),
            "when": row.get("when", known.when if known else None),
        }
        missing = [key for key, value in fields.items() if value is None]
        if missing:
            raise ConfigError(f"{label} ({name}): needs " + ", ".join(missing))
        emoji = check_emoji(fields["emoji"], f"{label} ({name})")
        plain, when = fields["plain"], fields["when"]
        if not isinstance(plain, str) or not PLAIN_RE.fullmatch(plain):
            raise ConfigError(f"{label} ({name}): plain must be 1-12 letters, digits or . _ + -")
        if not isinstance(when, str) or not VARIABLE_RE.fullmatch(when):
            raise ConfigError(f"{label} ({name}): when must be an environment variable name")
        tokens[name] = Token(name, emoji, plain, when)


def settings(site: object, user: object) -> PromptSettings:
    """Combine the site and user `[prompt]` tables: switches override key by
    key, and token rows are layered by name over the defaults (site first)."""
    tables = []
    for value, source in ((site, "site configuration"), (user, "user configuration")):
        if value is None:
            continue
        if not isinstance(value, dict):
            raise ConfigError(f"{source}: prompt must be a table")
        unknown = set(value) - PROMPT_KEYS
        if unknown:
            raise ConfigError(f"{source}: unknown prompt keys: " + ", ".join(sorted(unknown)))
        tables.append((value, source))
    flags = {"show_tokens": True, "hide_manager_prefix": True, "plain": False}
    tokens = {token.name: token for token in DEFAULT_TOKENS}
    for table, source in tables:
        for key in flags:
            value = _boolean(table, key, source)
            if value is not None:
                flags[key] = value
        _apply(tokens, _rows(table, source), source)
    seen: dict[str, str] = {}
    for token in tokens.values():
        if token.emoji in seen:
            raise ConfigError(
                f"prompt tokens {seen[token.emoji]!r} and {token.name!r} use the same emoji"
            )
        seen[token.emoji] = token.name
    return PromptSettings(tokens=tuple(tokens.values()), **flags)
