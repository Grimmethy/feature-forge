"""Tests for POST /api/features/<slug>/sync through Flask's test client, with a temp project queue. Plain unittest; skipped
where flask or markdown is not installed."""
import json
import os
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
class SyncRouteTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        t = Path(tmp.name)
        self.root, pipe = t / "features", t / "pipe"
        (pipe / "queue" / "done").mkdir(parents=True)
        (pipe / "queue" / "review").mkdir(parents=True)
        (pipe / "queue" / "done" / "t-a.json").write_text(json.dumps({"status": "done", "mergedAt": "2026-11-14T05:00:00+00:00"}))
        (pipe / "queue" / "review" / "t-b.json").write_text(json.dumps({"status": "review"}))
        reg = t / "projects.json"
        reg.write_text(json.dumps([{"repoRoot": "/r/alpha", "pipelineDir": str(pipe), "domainsPath": "x", "label": "alpha"}]))
        saved = os.environ.get("FEATUREFORGE_PROJECTS")
        os.environ["FEATUREFORGE_PROJECTS"] = str(reg)
        self.addCleanup(lambda: os.environ.__setitem__("FEATUREFORGE_PROJECTS", saved) if saved else os.environ.pop("FEATUREFORGE_PROJECTS", None))
        self.client = appmod.create_app(self.root).test_client()
        self.slug = store.create_feature("Thing", "x\nrepo: alpha", self.root)
        store.write_file(self.slug, "checklist.md", "# Checklist: x\n\n- [ ] FF-1 a <!-- task: t-a filed: 2026-11-14T04:00:00Z deps: -->\n"
                         "- [ ] FF-2 b <!-- task: t-b filed: 2026-11-14T04:00:00Z deps: -->\n", self.root)

    def test_sync_ticks_the_merged_item_and_reports_states(self):
        r = self.client.post(f"/api/features/{self.slug}/sync")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["ticked"], ["FF-1"])
        self.assertEqual(body["states"]["FF-2"]["state"], "review")
        rows = {x["id"]: x for x in self.client.get(f"/api/features/{self.slug}/checklist").get_json()}
        self.assertTrue(rows["FF-1"]["ticked"])
        self.assertEqual(rows["FF-1"]["meta"]["took"], "60")
        self.assertFalse(rows["FF-2"]["ticked"])

    def test_pieces_are_ticked_through_the_route_and_the_rows_show_it(self):
        store.write_file(self.slug, "checklist.md", "# Checklist: x\n\n- [ ] FF-1 Step <!-- filed: 2026-11-14T04:00:00Z deps: -->\n"
                         "  - [ ] 1a One <!-- task: t-a filed: 2026-11-14T04:00:00Z -->\n  - [ ] 1b Two <!-- task: t-b filed: 2026-11-14T04:00:00Z -->\n", self.root)
        r = self.client.post(f"/api/features/{self.slug}/sync").get_json()
        self.assertEqual(r["ticked"], ["FF-1/1a"])
        self.assertEqual(r["states"]["FF-1/1b"]["state"], "review")
        rows = {x["id"]: x for x in self.client.get(f"/api/features/{self.slug}/checklist").get_json()}
        self.assertEqual((rows["FF-1"]["pieceDone"], rows["FF-1"]["pieceTotal"], rows["FF-1"]["ticked"]), (1, 2, False))
        self.assertEqual(rows["FF-1"]["pieces"][0]["meta"]["took"], "60")

    def test_unknown_feature_is_404_and_an_unregistered_repo_is_400(self):
        self.assertEqual(self.client.post("/api/features/nope/sync").status_code, 404)
        store.write_file(self.slug, "request.md", "# Thing\n\nrepo: gamma", self.root)
        self.assertEqual(self.client.post(f"/api/features/{self.slug}/sync").status_code, 400)


if __name__ == "__main__":
    unittest.main()
