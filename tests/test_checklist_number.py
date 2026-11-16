import tempfile
import unittest
from pathlib import Path

from server.core import checklist, store


class NumberItemsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.slug = store.create_feature("Numbering", "req", self.root)

    def write(self, text):
        (self.root / self.slug / "checklist.md").write_text(text, encoding="utf-8")

    def read(self):
        return (self.root / self.slug / "checklist.md").read_text(encoding="utf-8")

    def history(self):
        d = self.root / self.slug / ".history"
        return sorted(p.name for p in d.glob("checklist.md.*")) if d.is_dir() else []

    def test_numbers_in_order_with_history_and_second_run_is_noop(self):
        self.write("# Checklist\n\n- [ ] one\n- [ ] two\n- [x] three\n")
        r = checklist.number_checklist(self.slug, self.root)
        self.assertEqual(r["assigned"], ["FF-1", "FF-2", "FF-3"])
        text = self.read()
        self.assertEqual(text, "# Checklist\n\n- [ ] FF-1 one\n- [ ] FF-2 two\n- [x] FF-3 three\n")
        self.assertEqual(len(self.history()), 1)
        r2 = checklist.number_checklist(self.slug, self.root)
        self.assertEqual(r2["assigned"], [])
        self.assertEqual(self.read(), text)
        self.assertEqual(len(self.history()), 1)

    def test_existing_ids_untouched(self):
        src = "- [ ] FF-4 keep <!-- deps: -->\n  body\n- [ ] new\n"
        new, assigned = checklist.number_items(src)
        self.assertEqual(assigned, ["FF-5"])
        self.assertEqual(new, "- [ ] FF-4 keep <!-- deps: -->\n  body\n- [ ] FF-5 new\n")

    def refusal(self):
        res = checklist.preview(self.slug, {"ops": [{"op": "change", "id": "FF-1", "title": "x"}]}, self.root)
        return res[0]["summary"]

    def test_refusal_names_cause_when_idless(self):
        self.write("- [ ] a\n- [ ] b\n")
        s = self.refusal()
        self.assertIn("no such item FF-1", s)
        self.assertIn("items have no ids", s)
        self.assertIn("Number", s)

    def test_refusal_unchanged_when_numbered(self):
        self.write("- [ ] FF-2 a\n")
        self.assertEqual(self.refusal(), "no such item FF-1")


if __name__ == "__main__":
    unittest.main()
