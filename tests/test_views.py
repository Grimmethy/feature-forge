"""Tests for server/core/views.py: the board columns, the by-repo roll-up and the dependency-graph SVG. Plain unittest, standard
library only."""
import re
import sys
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.core import store, views

ONE = """# Checklist: One

- [x] FF-1 Scaffold <!-- task: t1 manual: true -->
- [ ] FF-2 Build the <core> & more <!-- task: t2 premium: true deps: FF-1 -->
- [ ] FF-3 Wire it <!-- deps: FF-2 -->
- [ ] FF-4 Docs <!-- deps: FF-1 cloud: true -->
- [ ] FF-5 A very long title that has to be cut somewhere sensible <!-- deps: FF-3,FF-4 -->
"""


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.one = store.create_feature("One", "x\nrepo: alpha", self.root)
        store.write_file(self.one, "checklist.md", ONE, self.root)
        self.two = store.create_feature("Two", "y\nrepo: alpha", self.root)
        store.write_file(self.two, "checklist.md", "# Checklist: Two\n\n- [ ] FF-1 Only <!-- deps: -->\n", self.root)
        self.three = store.create_feature("Three", "z", self.root)
        store.write_file(self.three, "checklist.md", "# Checklist: Three\n\n- [x] FF-1 Done <!-- manual: true -->\n", self.root)


class BoardTests(Base):
    def test_items_land_in_the_column_their_comment_says(self):
        cols = views.board(self.root)["columns"]
        ids = {name: sorted((c["slug"], c["id"]) for c in cards) for name, cards in cols.items()}
        self.assertEqual(ids["Done"], sorted([(self.one, "FF-1"), (self.three, "FF-1")]))
        self.assertEqual(ids["In flight"], [(self.one, "FF-2")])
        self.assertEqual(ids["Not filed"], sorted([(self.one, "FF-3"), (self.one, "FF-4"), (self.one, "FF-5"), (self.two, "FF-1")]))

    def test_a_card_carries_the_flags_the_feature_and_the_repo(self):
        card = [c for c in views.board(self.root)["columns"]["In flight"] if c["id"] == "FF-2"][0]
        self.assertEqual((card["premium"], card["cloud"], card["repo"], card["feature"]), (True, False, "alpha", "One"))
        cloud = [c for c in views.board(self.root)["columns"]["Not filed"] if c["id"] == "FF-4"][0]
        self.assertTrue(cloud["cloud"])

    def test_the_three_columns_always_exist(self):
        self.assertEqual(list(views.board(self.root / "nowhere")["columns"]), ["Not filed", "In flight", "Done"])


class ByRepoTests(Base):
    def test_features_group_by_repo_with_totals_and_no_repo_last(self):
        groups = views.by_repo(self.root)
        self.assertEqual([g["repo"] for g in groups], ["alpha", ""])
        alpha = groups[0]
        self.assertEqual(sorted(f["slug"] for f in alpha["features"]), sorted([self.one, self.two]))
        self.assertEqual((alpha["ticked"], alpha["total"]), (1, 6))
        self.assertEqual([f["slug"] for f in groups[1]["features"]], [self.three])


class GraphTests(Base):
    def svg(self, slug=None):
        return views.graph_svg(slug or self.one, self.root)

    def test_it_is_well_formed_svg_with_one_node_per_item_and_one_edge_per_dependency(self):
        root = ET.fromstring(self.svg())
        ns = "{http://www.w3.org/2000/svg}"
        self.assertEqual(len(root.findall(f".//{ns}g")), 5)
        self.assertEqual(len([p for p in root.iter(f"{ns}path") if p.get("class") == "edge"]), 5)      # 2->1, 3->2, 4->1, 5->3, 5->4

    def test_node_state_classes(self):
        s = self.svg()
        self.assertRegex(s, r'class="gn done" data-id="FF-1"')
        self.assertRegex(s, r'class="gn filed" data-id="FF-2"')
        self.assertRegex(s, r'class="gn open" data-id="FF-3"')

    def test_layers_follow_the_longest_dependency_path(self):
        xs = {m.group(1): int(m.group(2)) for m in re.finditer(r'data-id="(FF-\d)"><title>[^<]*</title><rect x="(\d+)"', self.svg())}
        self.assertLess(xs["FF-1"], xs["FF-2"])
        self.assertLess(xs["FF-2"], xs["FF-3"])
        self.assertEqual(xs["FF-4"], xs["FF-2"])
        self.assertLess(xs["FF-3"], xs["FF-5"])

    def test_titles_are_escaped_and_long_ones_cut(self):
        s = self.svg()
        self.assertIn("Build the &lt;core&gt; &amp; more", s)
        shown = re.findall(r"<text[^>]*>([^<]*)</text>", s)
        self.assertIn("FF-5 A very long title that has …", shown)       # cut on screen
        self.assertIn("FF-5 A very long title that has to be cut somewhere sensible", s)     # whole in the hover tooltip

    def test_an_empty_checklist_is_a_message_not_a_crash(self):
        store.write_file(self.two, "checklist.md", "# Checklist: Two\n", self.root)
        self.assertIn("No checklist items yet", self.svg(self.two))

    def test_unknown_feature_raises(self):
        with self.assertRaises(store.StoreError):
            views.graph_svg("nope", self.root)


if __name__ == "__main__":
    unittest.main()
