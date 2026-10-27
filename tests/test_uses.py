from __future__ import annotations

import unittest

from proj.errors import ProjError
from proj.lmod import ModuleEntry
from proj.uses import (
    allowed,
    display_names,
    match_used,
    plan_unuse,
    plan_use,
    required_groups,
    resolve,
    short_name,
)


def entry(name, category="application", group="", versions=("1.0",), default=None):
    return ModuleEntry(name, tuple(versions), default or versions[-1], category, "", group)


ENTRIES = [
    entry("pdk-alpha", "project", "alpha"),
    entry("pdk-beta", "project", "any", ("1.1", "2.0")),
    entry("suite-flowkit", "application", "flowkit", ("2026.1",)),
    entry("simtool", "application", "", ("20.1", "21.1")),
    entry("gcc", "compiler", "", ("13.3.0",)),
    entry("node", "", "", ("24.21.0",)),
    entry("odd", "library"),
    entry("foo", "toolchain"),
    entry("pdk-foo", "project", "any"),
]
MEMBER = {"alpha", "staff"}
OUTSIDER = {"staff"}


class NamesTests(unittest.TestCase):
    def test_short_names_drop_the_library_and_suite_prefixes(self):
        self.assertEqual(short_name("pdk-alpha"), "alpha")
        self.assertEqual(short_name("suite-flowkit"), "flowkit")
        self.assertEqual(short_name("simtool"), "simtool")
        self.assertEqual(short_name("pdk-"), "pdk-")

    def test_ambiguous_short_names_keep_the_full_name(self):
        shown = display_names(ENTRIES)
        self.assertEqual(shown["pdk-alpha"], "alpha")
        self.assertEqual(shown["suite-flowkit"], "flowkit")
        self.assertEqual(shown["foo"], "foo")
        self.assertEqual(shown["pdk-foo"], "pdk-foo")  # foo is also a module of its own


class ResolveTests(unittest.TestCase):
    def test_a_short_name_finds_the_prefixed_module_and_reads_its_category(self):
        item = resolve("beta", ENTRIES, MEMBER)
        self.assertEqual((item.entry.name, item.category, item.spec), ("pdk-beta", "project", "pdk-beta"))
        self.assertEqual(resolve("flowkit", ENTRIES, OUTSIDER | {"flowkit"}).spec, "suite-flowkit")
        self.assertEqual(resolve("simtool", ENTRIES, MEMBER).category, "application")

    def test_exact_module_names_work_and_keep_the_bare_name_unpinned(self):
        self.assertEqual(resolve("pdk-beta", ENTRIES, MEMBER).spec, "pdk-beta")
        self.assertEqual(resolve("gcc", ENTRIES, MEMBER).spec, "gcc")

    def test_a_version_pins_and_must_exist(self):
        self.assertEqual(resolve("beta/1.1", ENTRIES, MEMBER).spec, "pdk-beta/1.1")
        self.assertEqual(resolve("simtool/20.1", ENTRIES, MEMBER).spec, "simtool/20.1")
        with self.assertRaisesRegex(ProjError, r"no version '1999'.*1\.1, 2\.0"):
            resolve("beta/1999", ENTRIES, MEMBER)

    def test_several_matches_are_refused_not_guessed(self):
        with self.assertRaisesRegex(ProjError, r"matches several modules \(foo, pdk-foo\)"):
            resolve("foo", ENTRIES, MEMBER)
        self.assertEqual(resolve("pdk-foo", ENTRIES, MEMBER).spec, "pdk-foo")

    def test_no_match_suggests_close_names(self):
        with self.assertRaisesRegex(ProjError, r"no module matches 'bet'.*Did you mean: beta"):
            resolve("bet", ENTRIES, MEMBER)
        with self.assertRaisesRegex(ProjError, "no module matches 'zzz'"):
            resolve("zzz", ENTRIES, MEMBER)
        with self.assertRaises(ProjError):
            resolve("", ENTRIES, MEMBER)

    def test_untagged_and_unknown_categories_are_refused_with_the_fix(self):
        with self.assertRaisesRegex(ProjError, r"node has no Category tag.*proj module add"):
            resolve("node", ENTRIES, MEMBER)
        with self.assertRaisesRegex(ProjError, r"odd has the category 'library'"):
            resolve("odd", ENTRIES, MEMBER)

    def test_access_is_checked_first_with_the_documented_message(self):
        with self.assertRaises(ProjError) as caught:
            resolve("alpha", ENTRIES, OUTSIDER)
        self.assertEqual(
            str(caught.exception),
            "alpha needs the Unix group alpha (you are not in it). Ask an administrator.",
        )
        # A refused person is not told which versions exist.
        with self.assertRaisesRegex(ProjError, "needs the Unix group"):
            resolve("alpha/9.9", ENTRIES, OUTSIDER)

    def test_group_rules(self):
        self.assertEqual(required_groups(entry("m", group="any")), [])
        self.assertEqual(required_groups(entry("m", group="")), [])
        self.assertEqual(required_groups(entry("m", group="a, b  c")), ["a", "b", "c"])
        self.assertEqual(required_groups(entry("m", group="seasoned")), ["seasoned"])
        two = entry("m", group="eda,fpga")
        self.assertTrue(allowed(two, {"fpga"}))
        self.assertFalse(allowed(two, {"other"}))
        with self.assertRaisesRegex(ProjError, r"one of the Unix groups eda, fpga \(you are in none"):
            resolve("m", [two], {"other"})


class PlanTests(unittest.TestCase):
    def resolved(self, *texts):
        return [resolve(text, ENTRIES, MEMBER | {"flowkit"}) for text in texts]

    def test_adds_go_to_the_modules_own_category(self):
        plan = plan_use({}, self.resolved("beta", "simtool", "gcc"))
        self.assertEqual(plan.modules["project"], ["pdk-beta"])
        self.assertEqual(plan.modules["application"], ["simtool"])
        self.assertEqual(plan.modules["compiler"], ["gcc"])
        self.assertTrue(plan.changed)

    def test_repeating_a_module_changes_nothing(self):
        plan = plan_use({"project": ["pdk-beta"]}, self.resolved("beta"))
        self.assertFalse(plan.changed)
        self.assertEqual(plan.unchanged, ["pdk-beta"])

    def test_another_version_or_a_pin_replaces_the_same_module(self):
        plan = plan_use({"application": ["simtool/21.1"]}, self.resolved("simtool/20.1"))
        self.assertEqual(plan.modules["application"], ["simtool/20.1"])
        self.assertEqual(plan.replaced, [("simtool/21.1", "simtool/20.1", "same module")])
        unpinned = plan_use({"application": ["simtool/20.1"]}, self.resolved("simtool"))
        self.assertEqual(unpinned.modules["application"], ["simtool"])

    def test_a_module_of_the_same_family_replaces_its_sibling(self):
        families = {"pdk-beta": "pdk", "pdk-alpha": "pdk", "simtool": "simtool"}
        plan = plan_use({"project": ["pdk-beta"]}, self.resolved("alpha"), families)
        self.assertEqual(plan.modules["project"], ["pdk-alpha"])
        self.assertEqual(plan.replaced, [("pdk-beta", "pdk-alpha", "same Lmod family 'pdk'")])
        # Unrelated modules stay, and unknown families never replace anything.
        keep = plan_use({"project": ["pdk-beta"], "application": ["simtool"]}, self.resolved("alpha"), families)
        self.assertEqual(keep.modules["application"], ["simtool"])
        nofamilies = plan_use({"project": ["pdk-beta"]}, self.resolved("alpha"), {})
        self.assertEqual(nofamilies.modules["project"], ["pdk-beta", "pdk-alpha"])

    def test_the_input_is_never_modified(self):
        current = {"project": ["pdk-beta"]}
        plan_use(current, self.resolved("simtool"))
        self.assertEqual(current, {"project": ["pdk-beta"]})


class UnuseTests(unittest.TestCase):
    CURRENT = {
        "project": ["pdk-beta/1.1"],
        "application": ["suite-flowkit", "simtool/20.1"],
    }

    def test_short_full_and_pinned_names_all_match(self):
        self.assertEqual(match_used("beta", self.CURRENT), [("project", "pdk-beta/1.1")])
        self.assertEqual(match_used("pdk-beta", self.CURRENT), [("project", "pdk-beta/1.1")])
        self.assertEqual(match_used("beta/1.1", self.CURRENT), [("project", "pdk-beta/1.1")])
        self.assertEqual(match_used("beta/1999", self.CURRENT), [])
        self.assertEqual(match_used("simtool", self.CURRENT), [("application", "simtool/20.1")])

    def test_unuse_removes_and_reports(self):
        plan = plan_unuse(self.CURRENT, ["flowkit", "simtool"])
        self.assertEqual(plan.removed, ["suite-flowkit", "simtool/20.1"])
        self.assertEqual(plan.modules["application"], [])
        self.assertTrue(plan.changed)

    def test_unknown_names_list_what_the_environment_uses(self):
        with self.assertRaisesRegex(ProjError, r"does not use 'alpha'.*flowkit, simtool/20.1, beta/1.1"):
            plan_unuse(self.CURRENT, ["alpha"])
        with self.assertRaisesRegex(ProjError, "uses no modules"):
            plan_unuse({}, ["alpha"])

    def test_an_ambiguous_short_name_needs_the_full_one(self):
        both = {"project": ["pdk-foo"], "toolchain": ["suite-foo"]}
        with self.assertRaisesRegex(ProjError, "matches several modules"):
            plan_unuse(both, ["foo"])
        self.assertEqual(plan_unuse(both, ["pdk-foo"]).removed, ["pdk-foo"])


if __name__ == "__main__":
    unittest.main()
