"""Tests for the view routes in server/app.py through Flask's test client. Plain unittest; skipped where flask or markdown is not
installed."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from server import app as appmod
    from server.core import store
except ImportError:
    appmod = None


@unittest.skipIf(appmod is None, "flask and markdown are not installed")
class ViewRouteTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.client = appmod.create_app(self.root).test_client()
        self.slug = store.create_feature("One", "x\nrepo: alpha", self.root)
        store.write_file(self.slug, "checklist.md", "# Checklist: One\n\n- [ ] FF-1 a <!-- deps: -->\n- [ ] FF-2 b <!-- task: t deps: FF-1 -->\n", self.root)

    def test_board(self):
        cols = self.client.get("/api/views/board").get_json()["columns"]
        self.assertEqual([c["id"] for c in cols["Not filed"]], ["FF-1"])
        self.assertEqual([c["id"] for c in cols["In flight"]], ["FF-2"])
        self.assertEqual(cols["Done"], [])

    def test_repos(self):
        groups = self.client.get("/api/views/repos").get_json()
        self.assertEqual([(g["repo"], g["total"]) for g in groups], [("alpha", 2)])

    def test_graph_is_svg(self):
        r = self.client.get(f"/api/features/{self.slug}/graph.svg")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.mimetype, "image/svg+xml")
        self.assertIn('data-id="FF-2"', r.get_data(as_text=True))

    def test_graph_of_an_unknown_feature_is_404(self):
        self.assertEqual(self.client.get("/api/features/nope/graph.svg").status_code, 404)


if __name__ == "__main__":
    unittest.main()
