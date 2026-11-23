import tempfile
import unittest
from pathlib import Path
from unittest import mock

from server.core import checklist, checklist_deps, store


class NextFreeIdTests(unittest.TestCase):
    def test_empty_list_gives_ff1(self):
        self.assertEqual(checklist.next_free_id([]), "FF-1")

    def test_max_plus_one_ignoring_idless(self):
        items = [{"id": "FF-2"}, {"id": "FF-5"}, {"id": ""}]
        self.assertEqual(checklist.next_free_id(items), "FF-6")


class AddItemTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.slug = store.create_feature("Demo feature", "req", self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, text):
        store.write_file(self.slug, "checklist.md", text, self.root)

    def _read(self):
        return store.read_file(self.slug, "checklist.md", self.root)

    def test_blank_title_raises_and_writes_nothing(self):
        self._write("# Checklist\n\n")
        with mock.patch.object(store, "write_file") as wf:
            for t in ("", "   "):
                with self.assertRaises(ValueError):
                    checklist.add_item(self.slug, t, "x", root=self.root)
            wf.assert_not_called()

    def test_missing_feature_raises_value_error(self):
        with self.assertRaises(ValueError):
            checklist.add_item("no-such-feature", "Title", "x", root=self.root)

    def test_uses_slug_and_writes_max_plus_one(self):
        self._write("# Checklist\n\n- [ ] FF-2 old\n- [x] FF-5 done\n- [ ] loose line without id\n")
        new_id = checklist.add_item(self.slug, "Add me", "details", root=self.root)
        self.assertEqual(new_id, "FF-6")
        text = self._read()
        self.assertIn("- [ ] FF-6 Add me", text)
        self.assertIn("  details", text)

    def test_writes_history_copy(self):
        self._write("# Checklist\n\n- [ ] FF-1 first\n")
        checklist.add_item(self.slug, "Second", "", root=self.root)
        hist = self.root / self.slug / ".history"
        self.assertTrue(hist.is_dir() and any(hist.iterdir()))


class DepsNormalizeValidateTests(unittest.TestCase):
    def test_string_input(self):
        self.assertEqual(checklist_deps.normalize_deps("FF-1, FF-2"), ["FF-1", "FF-2"])
        self.assertEqual(checklist_deps.normalize_deps("FF-1 FF-2"), ["FF-1", "FF-2"])

    def test_list_input(self):
        self.assertEqual(checklist_deps.normalize_deps([" FF-1 ", "FF-2"]), ["FF-1", "FF-2"])

    def test_empty_or_missing(self):
        self.assertEqual(checklist_deps.normalize_deps(None), [])
        self.assertEqual(checklist_deps.normalize_deps(""), [])
        self.assertEqual(checklist_deps.normalize_deps("  "), [])
        self.assertEqual(checklist_deps.normalize_deps([]), [])

    def test_bad_type(self):
        for bad in (5, {"a": 1}, [1]):
            with self.assertRaises(ValueError):
                checklist_deps.normalize_deps(bad)

    def test_validate_known_ok(self):
        checklist_deps.validate_deps(["FF-1"], ["FF-1", "FF-2"])

    def test_validate_unknown(self):
        with self.assertRaises(ValueError) as cm:
            checklist_deps.validate_deps(["FF-1", "FF-99"], ["FF-1"])
        self.assertIn("Unknown dependency: FF-99", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
