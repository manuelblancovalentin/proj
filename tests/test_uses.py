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
    entry("pdk-gf22", "project", "gf22"),
    entry("pdk-saed32", "project", "any", ("04152022", "20200101")),
    entry("suite-cadence", "application", "cadence", ("2026.1",)),
    entry("genus", "application", "", ("20.1", "21.1")),
    entry("gcc", "compiler", "", ("13.3.0",)),
    entry("node", "", "", ("24.21.0",)),
    entry("odd", "library"),
    entry("foo", "toolchain"),
    entry("pdk-foo", "project", "any"),
]
MEMBER = {"gf22", "staff"}
OUTSIDER = {"staff"}


class NamesTests(unittest.TestCase):
    def test_short_names_drop_the_library_and_suite_prefixes(self):
        self.assertEqual(short_name("pdk-gf22"), "gf22")
        self.assertEqual(short_name("suite-cadence"), "cadence")
        self.assertEqual(short_name("genus"), "genus")
        self.assertEqual(short_name("pdk-"), "pdk-")

    def test_ambiguous_short_names_keep_the_full_name(self):
        shown = display_names(ENTRIES)
        self.assertEqual(shown["pdk-gf22"], "gf22")
        self.assertEqual(shown["suite-cadence"], "cadence")
        self.assertEqual(shown["foo"], "foo")
        self.assertEqual(shown["pdk-foo"], "pdk-foo")  # foo is also a module of its own


class ResolveTests(unittest.TestCase):
    def test_a_short_name_finds_the_prefixed_module_and_reads_its_category(self):
        item = resolve("saed32", ENTRIES, MEMBER)
        self.assertEqual((item.entry.name, item.category, item.spec), ("pdk-saed32", "project", "pdk-saed32"))
        self.assertEqual(resolve("cadence", ENTRIES, OUTSIDER | {"cadence"}).spec, "suite-cadence")
        self.assertEqual(resolve("genus", ENTRIES, MEMBER).category, "application")

    def test_exact_module_names_work_and_keep_the_bare_name_unpinned(self):
        self.assertEqual(resolve("pdk-saed32", ENTRIES, MEMBER).spec, "pdk-saed32")
        self.assertEqual(resolve("gcc", ENTRIES, MEMBER).spec, "gcc")

    def test_a_version_pins_and_must_exist(self):
        self.assertEqual(resolve("saed32/04152022", ENTRIES, MEMBER).spec, "pdk-saed32/04152022")
        self.assertEqual(resolve("genus/20.1", ENTRIES, MEMBER).spec, "genus/20.1")
        with self.assertRaisesRegex(ProjError, r"no version '1999'.*04152022, 20200101"):
            resolve("saed32/1999", ENTRIES, MEMBER)

    def test_several_matches_are_refused_not_guessed(self):
        with self.assertRaisesRegex(ProjError, r"matches several modules \(foo, pdk-foo\)"):
            resolve("foo", ENTRIES, MEMBER)
        self.assertEqual(resolve("pdk-foo", ENTRIES, MEMBER).spec, "pdk-foo")

    def test_no_match_suggests_close_names(self):
        with self.assertRaisesRegex(ProjError, r"no module matches 'saed'.*Did you mean: saed32"):
            resolve("saed", ENTRIES, MEMBER)
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
            resolve("gf22", ENTRIES, OUTSIDER)
        self.assertEqual(
            str(caught.exception),
            "gf22 needs the Unix group gf22 (you are not in it). Ask an administrator.",
        )
        # A refused person is not told which versions exist.
        with self.assertRaisesRegex(ProjError, "needs the Unix group"):
            resolve("gf22/9.9", ENTRIES, OUTSIDER)

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
        return [resolve(text, ENTRIES, MEMBER | {"cadence"}) for text in texts]

    def test_adds_go_to_the_modules_own_category(self):
        plan = plan_use({}, self.resolved("saed32", "genus", "gcc"))
        self.assertEqual(plan.modules["project"], ["pdk-saed32"])
        self.assertEqual(plan.modules["application"], ["genus"])
        self.assertEqual(plan.modules["compiler"], ["gcc"])
        self.assertTrue(plan.changed)

    def test_repeating_a_module_changes_nothing(self):
        plan = plan_use({"project": ["pdk-saed32"]}, self.resolved("saed32"))
        self.assertFalse(plan.changed)
        self.assertEqual(plan.unchanged, ["pdk-saed32"])

    def test_another_version_or_a_pin_replaces_the_same_module(self):
        plan = plan_use({"application": ["genus/21.1"]}, self.resolved("genus/20.1"))
        self.assertEqual(plan.modules["application"], ["genus/20.1"])
        self.assertEqual(plan.replaced, [("genus/21.1", "genus/20.1", "same module")])
        unpinned = plan_use({"application": ["genus/20.1"]}, self.resolved("genus"))
        self.assertEqual(unpinned.modules["application"], ["genus"])

    def test_a_module_of_the_same_family_replaces_its_sibling(self):
        families = {"pdk-saed32": "pdk", "pdk-gf22": "pdk", "genus": "genus"}
        plan = plan_use({"project": ["pdk-saed32"]}, self.resolved("gf22"), families)
        self.assertEqual(plan.modules["project"], ["pdk-gf22"])
        self.assertEqual(plan.replaced, [("pdk-saed32", "pdk-gf22", "same Lmod family 'pdk'")])
        # Unrelated modules stay, and unknown families never replace anything.
        keep = plan_use({"project": ["pdk-saed32"], "application": ["genus"]}, self.resolved("gf22"), families)
        self.assertEqual(keep.modules["application"], ["genus"])
        nofamilies = plan_use({"project": ["pdk-saed32"]}, self.resolved("gf22"), {})
        self.assertEqual(nofamilies.modules["project"], ["pdk-saed32", "pdk-gf22"])

    def test_the_input_is_never_modified(self):
        current = {"project": ["pdk-saed32"]}
        plan_use(current, self.resolved("genus"))
        self.assertEqual(current, {"project": ["pdk-saed32"]})


class UnuseTests(unittest.TestCase):
    CURRENT = {
        "project": ["pdk-saed32/04152022"],
        "application": ["suite-cadence", "genus/20.1"],
    }

    def test_short_full_and_pinned_names_all_match(self):
        self.assertEqual(match_used("saed32", self.CURRENT), [("project", "pdk-saed32/04152022")])
        self.assertEqual(match_used("pdk-saed32", self.CURRENT), [("project", "pdk-saed32/04152022")])
        self.assertEqual(match_used("saed32/04152022", self.CURRENT), [("project", "pdk-saed32/04152022")])
        self.assertEqual(match_used("saed32/1999", self.CURRENT), [])
        self.assertEqual(match_used("genus", self.CURRENT), [("application", "genus/20.1")])

    def test_unuse_removes_and_reports(self):
        plan = plan_unuse(self.CURRENT, ["cadence", "genus"])
        self.assertEqual(plan.removed, ["suite-cadence", "genus/20.1"])
        self.assertEqual(plan.modules["application"], [])
        self.assertTrue(plan.changed)

    def test_unknown_names_list_what_the_environment_uses(self):
        with self.assertRaisesRegex(ProjError, r"does not use 'gf22'.*cadence, genus/20.1, saed32/04152022"):
            plan_unuse(self.CURRENT, ["gf22"])
        with self.assertRaisesRegex(ProjError, "uses no modules"):
            plan_unuse({}, ["gf22"])

    def test_an_ambiguous_short_name_needs_the_full_one(self):
        both = {"project": ["pdk-foo"], "toolchain": ["suite-foo"]}
        with self.assertRaisesRegex(ProjError, "matches several modules"):
            plan_unuse(both, ["foo"])
        self.assertEqual(plan_unuse(both, ["pdk-foo"]).removed, ["pdk-foo"])


if __name__ == "__main__":
    unittest.main()
