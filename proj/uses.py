"""`proj use`: pick a module by one word, from what Lmod can load.

A person says `alpha`, `beta/1.1`, or `simtool`; this module finds the
module, reads its category and access from its own whatis tags, and plans the
change to an environment's module lists. It starts no process; callers pass in
the Lmod catalog and family information.
"""

from __future__ import annotations

import grp
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, Mapping

from .errors import ProjError
from .lmod import CATEGORIES, ModuleEntry

# Libraries and tool suites are published under these prefixes, so a person can
# say `alpha` for the module `pdk-alpha`, and `flowkit` for `suite-flowkit`.
PREFIXES = ("pdk-", "suite-")


def short_name(module: str) -> str:
    """The word a person types for a module: its name without a pdk-/suite- prefix."""
    for prefix in PREFIXES:
        if module.startswith(prefix) and len(module) > len(prefix):
            return module[len(prefix):]
    return module


def split_spec(text: str) -> tuple[str, str]:
    base, _, version = text.strip().partition("/")
    return base, version


@dataclass(frozen=True)
class Resolved:
    typed: str  # what the person typed, without a version
    entry: ModuleEntry
    version: str  # "" when the module's own default decides

    @property
    def spec(self) -> str:
        return f"{self.entry.name}/{self.version}" if self.version else self.entry.name

    @property
    def category(self) -> str:
        return self.entry.category


def display_names(entries: Iterable[ModuleEntry]) -> dict[str, str]:
    """The name shown for each module: the short word, unless that is ambiguous."""
    entries = list(entries)
    names = {entry.name for entry in entries}
    shorts = Counter(short_name(entry.name) for entry in entries)
    shown = {}
    for entry in entries:
        short = short_name(entry.name)
        ambiguous = shorts[short] > 1 or (short != entry.name and short in names)
        shown[entry.name] = entry.name if ambiguous else short
    return shown


# --- access ---------------------------------------------------------------


def user_groups() -> set[str]:
    """The Unix groups of this process, which is what decides file access."""
    names = set()
    for gid in {os.getgid(), *os.getgroups()}:
        try:
            names.add(grp.getgrgid(gid).gr_name)
        except KeyError:
            pass
    return names


def required_groups(entry: ModuleEntry) -> list[str]:
    """Groups of which a person must be in one; empty means open to everyone."""
    raw = entry.group.strip()
    if not raw:
        return []
    groups = [group for group in re.split(r"[,\s]+", raw) if group]
    if any(group.lower() == "any" for group in groups):
        return []
    return groups


def allowed(entry: ModuleEntry, groups: set[str]) -> bool:
    needed = required_groups(entry)
    return not needed or bool(set(needed) & groups)


def refusal(typed: str, entry: ModuleEntry) -> str:
    needed = required_groups(entry)
    if len(needed) == 1:
        return f"{typed} needs the Unix group {needed[0]} (you are not in it). Ask an administrator."
    return (
        f"{typed} needs one of the Unix groups {', '.join(needed)} "
        "(you are in none of them). Ask an administrator."
    )


# --- resolution -----------------------------------------------------------


def resolve(text: str, entries: Iterable[ModuleEntry], groups: set[str] | None = None) -> Resolved:
    """Find the one module `text` names, or explain why that is not possible.

    The exact module name is tried, then pdk-<name>, then suite-<name>. If more
    than one of them exists the request is ambiguous and nothing is guessed.
    With `groups`, a module the person may not use is refused before anything
    else about it (its versions, for example) is revealed.
    """
    entries = list(entries)
    base, version = split_spec(text)
    if not base:
        raise ProjError("name a module to use, for example: proj use alpha")
    by_name = {entry.name: entry for entry in entries}
    matches = [by_name[name] for name in (base, *(prefix + base for prefix in PREFIXES)) if name in by_name]
    if not matches:
        needle = base.lower()
        near = sorted({entry.name for entry in entries if needle in entry.name.lower()})[:8]
        hint = f" Did you mean: {', '.join(short_name(name) for name in near)}?" if near else ""
        raise ProjError(f"no module matches {base!r}.{hint} See: proj use --list")
    if len(matches) > 1:
        names = ", ".join(entry.name for entry in matches)
        raise ProjError(
            f"{base!r} matches several modules ({names}); use the full module name to choose one"
        )
    entry = matches[0]
    if groups is not None and not allowed(entry, groups):
        raise ProjError(refusal(base, entry))
    if entry.category not in CATEGORIES:
        problem = (
            f"has the category {entry.category!r}, which proj does not use"
            if entry.category
            else "has no Category tag"
        )
        raise ProjError(
            f"{entry.name} {problem} (it must be one of {', '.join(CATEGORIES)}), so proj "
            f"cannot place it. Tag the modulefile with whatis(\"Category: ...\"), or use "
            f"`proj module add <category> {entry.name}`"
        )
    if version and version not in entry.versions:
        available = ", ".join(entry.versions) or "none"
        raise ProjError(f"{entry.name} has no version {version!r} (available: {available})")
    return Resolved(base, entry, version)


# --- planning -------------------------------------------------------------


@dataclass
class Plan:
    modules: dict[str, list[str]]  # the new module lists, every category
    added: list[Resolved] = field(default_factory=list)
    replaced: list[tuple[str, str, str]] = field(default_factory=list)  # old, new, why
    removed: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.added or self.replaced or self.removed)


def _copy(current: Mapping[str, Iterable[str]]) -> dict[str, list[str]]:
    return {category: list(current.get(category, ())) for category in CATEGORIES}


def plan_use(
    current: Mapping[str, Iterable[str]],
    additions: Iterable[Resolved],
    families: Mapping[str, str] | None = None,
) -> Plan:
    """Add modules, replacing what they cannot coexist with.

    An existing entry for the same module (another version, or a pin) is
    replaced, and so is an entry in the same Lmod family: two members of one
    family cannot be loaded together, so the environment would no longer load.
    """
    families = families or {}

    def family_of(spec: str) -> str | None:
        return families.get(spec) or families.get(spec.partition("/")[0])

    plan = Plan(modules=_copy(current))
    for item in additions:
        if any(item.spec in specs for specs in plan.modules.values()):
            plan.unchanged.append(item.spec)
            continue
        family = family_of(item.spec)
        for category, specs in plan.modules.items():
            for old in list(specs):
                if old.partition("/")[0] == item.entry.name:
                    why = "same module"
                elif family and family_of(old) == family:
                    why = f"same Lmod family '{family}'"
                else:
                    continue
                specs.remove(old)
                plan.replaced.append((old, item.spec, why))
        plan.modules[item.category].append(item.spec)
        plan.added.append(item)
    return plan


def match_used(text: str, current: Mapping[str, Iterable[str]]) -> list[tuple[str, str]]:
    """The (category, module) entries of an environment that `text` names."""
    base, version = split_spec(text)
    hits = []
    for category in CATEGORIES:
        for spec in current.get(category, ()):
            module, _, pinned = spec.partition("/")
            if base in (module, short_name(module)) and (not version or version == pinned):
                hits.append((category, spec))
    return hits


def plan_unuse(current: Mapping[str, Iterable[str]], texts: Iterable[str]) -> Plan:
    plan = Plan(modules=_copy(current))
    for text in texts:
        hits = match_used(text, plan.modules)
        if not hits:
            used = ", ".join(
                short_name(spec.partition("/")[0]) + ("/" + spec.partition("/")[2] if "/" in spec else "")
                for specs in plan.modules.values()
                for spec in specs
            )
            raise ProjError(
                f"this environment does not use {text!r}"
                + (f" (it uses: {used})" if used else " (it uses no modules)")
            )
        if len(hits) > 1:
            raise ProjError(
                f"{text!r} matches several modules ({', '.join(spec for _c, spec in hits)}); "
                "use the full module name"
            )
        category, spec = hits[0]
        plan.modules[category].remove(spec)
        plan.removed.append(spec)
    return plan
