"""Tests for server/core/store.py: creation, safe paths, history copies, checklist parsing and status derivation.
Plain unittest (standard library only), so they run with `python3 -m unittest` as well as under pytest."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.core import store

seven_unfiled = "# Checklist: Fixture\n\n" + "".join(f"- [ ] FF-{i} Item {i} <!-- deps: -->\n" for i in range(1, 8))


class StoreTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_create_feature_scaffolds_four_files(self):
        slug = store.create_feature("My Feature!", "do the thing", self.root)
        self.assertEqual(slug, "my-feature")
        for name in store.FILES:
            self.assertTrue((self.root / slug / name).is_file(), name)
        self.assertIn("do the thing", store.read_file(slug, "request.md", self.root))

    def test_slug_collisions_raise_duplicate_feature_error(self):
        store.create_feature("Same", "first", self.root)
        with self.assertRaises(store.DuplicateFeatureError):
            store.create_feature("Same", "second", self.root)
        # Only one feature directory should exist
        self.assertEqual(len([d for d in self.root.iterdir() if d.is_dir()]), 1)

    def test_blank_title_is_refused(self):
        with self.assertRaises(store.StoreError):
            store.create_feature("   ", "x", self.root)

    def test_unsafe_paths_are_rejected(self):
        slug = store.create_feature("Safe", "x", self.root)
        for bad in ["../x.md", "/etc/passwd.md", "plan.txt", "../../plan.md", "sub/../../../x.md", ""]:
            with self.subTest(path=bad):
                with self.assertRaises(store.StoreError):
                    store.write_file(slug, bad, "nope", self.root)
                with self.assertRaises(store.StoreError):
                    store.read_file(slug, bad, self.root)

    def test_bad_slug_and_unknown_feature(self):
        with self.assertRaises(store.StoreError):
            store.read_file("../etc", "plan.md", self.root)
        with self.assertRaisesRegex(store.StoreError, "no such"):
            store.read_file("missing", "plan.md", self.root)

    def test_missing_file_is_no_such(self):
        slug = store.create_feature("Gap", "x", self.root)
        with self.assertRaisesRegex(store.StoreError, "no such"):
            store.read_file(slug, "nofile.md", self.root)

    def test_overwrite_keeps_a_history_copy(self):
        slug = store.create_feature("Hist", "x", self.root)
        before = store.read_file(slug, "plan.md", self.root)
        store.write_file(slug, "plan.md", "version two", self.root)
        copies = list((self.root / slug / ".history").iterdir())
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0].read_text(encoding="utf-8"), before)
        self.assertEqual(store.read_file(slug, "plan.md", self.root), "version two")

    def test_checklist_line_with_all_keys(self):
        items = store.parse_checklist_text(
            "- [ ] FF-3 Add intake form <!-- task: adhoc-x premium: true cloud: false deps: FF-1,FF-2 filed: 2026-11-13T10:00 -->")
        self.assertEqual(items, [{"id": "FF-3", "title": "Add intake form", "ticked": False,
                                  "meta": {"task": "adhoc-x", "premium": "true", "cloud": "false",
                                           "deps": "FF-1,FF-2", "filed": "2026-11-13T10:00"}}])

    def test_empty_value_does_not_swallow_the_next_key(self):
        item = store.parse_checklist_text("- [x] FF-1 T <!-- deps: premium: true -->")[0]
        self.assertTrue(item["ticked"])
        self.assertEqual(item["meta"], {"deps": "", "premium": "true"})

    def test_lines_that_are_not_items_are_ignored(self):
        self.assertEqual(store.parse_checklist_text("# Title\n\nsome prose\n- [ ] not an item id\n"), [])

    def test_status_derivation(self):
        cases = [
            ([], "Grilling"),
            (["- [ ] FF-1 a"], "Planned"),
            (["- [ ] FF-1 a <!-- task: t -->", "- [ ] FF-2 b"], "Filed"),
            (["- [ ] FF-1 a <!-- filed: 2026-11-13 -->"], "Filed"),
            (["- [x] FF-1 a", "- [ ] FF-2 b"], "Building"),
            (["- [x] FF-1 a", "- [x] FF-2 b"], "Done"),
        ]
        for lines, expected in cases:
            with self.subTest(expected=expected, lines=lines):
                self.assertEqual(store.derive_status(store.parse_checklist_text("\n".join(lines))), expected)

    def test_progress_counts_ticked_over_total(self):
        items = store.parse_checklist_text("- [x] FF-1 a\n- [ ] FF-2 b\n- [x] FF-3 c")
        self.assertEqual(store.progress(items), (2, 3))

    def test_fixture_with_seven_unfiled_items_is_planned(self):
        # A fixture, not the live features/feature-forge entry: that entry's status changes as its tasks are filed and merged.
        slug = store.create_feature("Fixture", "x", self.root)
        store.write_file(slug, "checklist.md", seven_unfiled, self.root)
        items = store.parse_checklist(slug, self.root)
        self.assertEqual(len(items), 7)
        self.assertFalse(any(i["ticked"] for i in items))
        self.assertEqual(store.derive_status(items), "Planned")

    def test_list_features_reports_title_status_progress_and_repo(self):
        slug = store.create_feature("Alpha", "repo: some-repo\nbuild it", self.root)
        store.write_file(slug, "checklist.md", "# Checklist: Alpha\n\n- [x] FF-1 a\n- [ ] FF-2 b\n", self.root)
        (row,) = store.list_features(self.root)
        self.assertEqual((row["slug"], row["title"], row["repo"]), (slug, "Alpha", "some-repo"))
        self.assertEqual((row["status"], row["ticked"], row["total"]), ("Building", 1, 2))

    def test_list_features_on_a_missing_folder(self):
        self.assertEqual(store.list_features(self.root / "nowhere"), [])


if __name__ == "__main__":
    unittest.main()
