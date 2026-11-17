"""Tests for sync_all: every feature gets its merged tasks ticked on board/library load and via POST /api/sync-all.

Uses only temporary fixture dirs; never touches the real features/ folder. Plain unittest; skipped where flask is
not installed."""
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


@unittest.skipIf(appmod is None, "flask is not installed")
class SyncAllTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        t = Path(tmp.name)
        self.root, pipe = t / "features", t / "pipe"
        (pipe / "queue" / "done").mkdir(parents=True)
        # Feature A: one merged task (t-a). The client will NEVER open its checklist.
        (pipe / "queue" / "done" / "t-a.json").write_text(
            json.dumps({"status": "done", "mergedAt": "2026-11-14T05:00:00+00:00"}))
        # Feature B: one non-merged task (t-b), just so sync_all has something to iterate.
        (pipe / "queue" / "review").mkdir(parents=True)
        (pipe / "queue" / "review" / "t-b.json").write_text(
            json.dumps({"status": "review"}))
        reg = t / "projects.json"
        reg.write_text(json.dumps([
            {"repoRoot": "/r/alpha", "pipelineDir": str(pipe), "domainsPath": "x", "label": "alpha"},
            {"repoRoot": "/r/beta", "pipelineDir": str(pipe), "domainsPath": "x", "label": "beta"},
        ]))
        saved = os.environ.get("FEATUREFORGE_PROJECTS")
        os.environ["FEATUREFORGE_PROJECTS"] = str(reg)
        self.addCleanup(lambda: os.environ.__setitem__("FEATUREFORGE_PROJECTS", saved) if saved else os.environ.pop("FEATUREFORGE_PROJECTS", None))
        self.client = appmod.create_app(self.root).test_client()
        self.slug_a = store.create_feature("Alpha", "x\nrepo: alpha", self.root)
        self.slug_b = store.create_feature("Beta", "x\nrepo: beta", self.root)
        store.write_file(self.slug_a, "checklist.md",
                         "# Checklist: Alpha\n\n- [ ] FF-1 a <!-- task: t-a filed: 2026-11-14T04:00:00Z deps: -->\n",
                         self.root)
        store.write_file(self.slug_b, "checklist.md",
                         "# Checklist: Beta\n\n- [ ] FF-2 b <!-- task: t-b filed: 2026-11-14T04:00:00Z deps: -->\n",
                         self.root)

    def _timing_rows(self):
        log = self.root / ".timing.jsonl"
        if not log.is_file():
            return []
        return [json.loads(line) for line in log.read_text().splitlines() if line.strip()]

    def test_board_load_ticks_never_opened_feature_and_writes_one_timing_row(self):
        """GET /api/views/board must tick every feature, not only the one the client opens."""
        timing_before = len(self._timing_rows())
        r = self.client.get("/api/views/board")
        self.assertEqual(r.status_code, 200)
        cols = r.get_json()["columns"]
        done_cards = {c["id"] for c in cols.get("Done", [])}
        self.assertIn("FF-1", done_cards, "Feature A (never opened) should be ticked after board load")
        timing_after = len(self._timing_rows())
        self.assertEqual(timing_after, timing_before + 1,
                         ".timing.jsonl should gain exactly one row for the one merged item")

    def test_library_load_ticks_never_opened_feature(self):
        """GET /api/views/repos (library roll-up) must also tick every feature."""
        r = self.client.get("/api/views/repos")
        self.assertEqual(r.status_code, 200)
        groups = {g["repo"]: g for g in r.get_json()}
        alpha = groups.get("alpha", {})
        alpha_slugs = {f["slug"] for f in alpha.get("features", [])}
        self.assertIn(self.slug_a, alpha_slugs)
        checklist = {x["id"]: x for x in
                     self.client.get(f"/api/features/{self.slug_a}/checklist").get_json()}
        self.assertTrue(checklist["FF-1"]["ticked"],
                        "Feature A must be ticked after library load even though nobody opened it")

    def test_sync_all_endpoint_returns_slug_to_ticked_mapping(self):
        """POST /api/sync-all returns {slug: [ticked-keys]} for every feature."""
        r = self.client.post("/api/sync-all")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertIsInstance(body, dict)
        self.assertIn(self.slug_a, body)
        self.assertIn(self.slug_b, body)
        self.assertIn("FF-1", body[self.slug_a])

    def test_second_sync_all_is_idempotent_no_extra_timing_rows(self):
        """A second POST /api/sync-all adds no new .timing.jsonl rows (already-ticked items stay unticked)."""
        self.client.post("/api/sync-all")
        timing_after_first = len(self._timing_rows())
        self.assertGreater(timing_after_first, 0, "First sync-all should tick the merged item and write a row")
        self.client.post("/api/sync-all")
        timing_after_second = len(self._timing_rows())
        self.assertEqual(timing_after_second, timing_after_first,
                         "Already-ticked items must not produce another timing row")


if __name__ == "__main__":
    unittest.main()
