"""Tests for the checklist and proposal routes in server/app.py through Flask's test client, and the FF-2 hand-tick in the real
checklist. Plain unittest; skipped where flask or markdown is not installed. The chat plugin is a fake (grill._urlopen)."""
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))
try:
    from server import app as appmod
    from server.core import checklist, grill, store
except ImportError:
    appmod = None

CHECKLIST = """# Checklist: Thing

- [x] FF-1 Scaffold <!-- task: adhoc-1 premium: true deps: filed: 2026-11-13 -->
- [ ] FF-2 Build <!-- deps: FF-1 -->
  Body of build.
- [ ] FF-3 Wire <!-- deps: FF-2 -->
"""
BLOCK = '```checklist-diff\n{"ops": [{"op": "add", "title": "Docs", "deps": ["FF-3"]}, {"op": "remove", "id": "FF-1"}]}\n```'


class FakeChat:
    def __init__(self):
        self.transcript, self.fail = [], False

    def __call__(self, req, timeout=None):
        path = "/" + req.full_url.split("://", 1)[1].split("/", 1)[1]
        if path == "/api/chat/new":
            return io.BytesIO(json.dumps({"id": "chat-1-abc"}).encode())
        if req.get_method() == "GET":
            return io.BytesIO(json.dumps({"transcript": self.transcript}).encode())
        return io.BytesIO(b"{}")


@unittest.skipIf(appmod is None, "flask and markdown are not installed")
class ChecklistRouteTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.fake = FakeChat()
        saved = grill._urlopen
        grill._urlopen = self.fake
        self.addCleanup(lambda: setattr(grill, "_urlopen", saved))
        self.client = appmod.create_app(self.root).test_client()
        self.slug = store.create_feature("Thing", "x", self.root)
        store.write_file(self.slug, "checklist.md", CHECKLIST, self.root)

    def url(self, tail):
        return f"/api/features/{self.slug}/checklist{tail}"

    def text(self):
        return store.read_file(self.slug, "checklist.md", self.root)

    def test_get_lists_items_with_lock_deps_and_body(self):
        rows = {r["id"]: r for r in self.client.get(self.url("")).get_json()}
        self.assertEqual(list(rows), ["FF-1", "FF-2", "FF-3"])
        self.assertTrue(rows["FF-1"]["locked"] and rows["FF-1"]["ticked"])
        self.assertFalse(rows["FF-2"]["locked"])
        self.assertEqual((rows["FF-2"]["deps"], rows["FF-2"]["body"]), (["FF-1"], "Body of build."))
        self.assertEqual(rows["FF-3"]["meta"]["deps"], "FF-2")

    def test_unknown_feature_is_404(self):
        self.assertEqual(self.client.get("/api/features/nope/checklist").status_code, 404)
        self.assertEqual(self.client.post("/api/features/nope/checklist/preview", json={"proposal": {"ops": [{"op": "add", "title": "x"}]}}).status_code, 404)

    def test_preview_reports_each_op_and_writes_nothing(self):
        r = self.client.post(self.url("/preview"), json={"proposal": {"ops": [{"op": "add", "title": "x"}, {"op": "remove", "id": "FF-1"}]}})
        self.assertEqual([x["ok"] for x in r.get_json()["results"]], [True, False])
        self.assertEqual(self.text(), CHECKLIST)

    def test_apply_writes_the_selected_ops(self):
        r = self.client.post(self.url("/apply"), json={"proposal": {"ops": [{"op": "add", "title": "One"}, {"op": "add", "title": "Two"}]}, "only": [1]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual([x["ok"] for x in r.get_json()["results"]], [None, True])
        self.assertIn("FF-4 Two", self.text())
        self.assertNotIn("One", self.text())

    def test_apply_is_all_or_nothing_and_a_refusal_is_400(self):
        r = self.client.post(self.url("/apply"), json={"proposal": {"ops": [{"op": "add", "title": "ok"}, {"op": "remove", "id": "FF-1"}]}})
        self.assertEqual(r.status_code, 400)
        self.assertIn("filed", r.get_json()["error"])
        self.assertEqual(self.text(), CHECKLIST)

    def test_bad_bodies_are_400(self):
        for body in [{}, {"proposal": {}}, {"proposal": {"ops": []}}, {"proposal": "x"}]:
            with self.subTest(body=body):
                self.assertEqual(self.client.post(self.url("/preview"), json=body).status_code, 400)
        ok = {"ops": [{"op": "add", "title": "x"}]}
        for only in ["1", [True], [1.5], {"a": 1}, 5, True]:
            with self.subTest(only=only):
                self.assertEqual(self.client.post(self.url("/apply"), json={"proposal": ok, "only": only}).status_code, 400)
        self.assertEqual(self.text(), CHECKLIST)

    def test_proposal_route_extracts_the_newest_block_and_previews_it(self):
        sid = self.client.post("/api/grill/start", json={"feature": self.slug}).get_json()["id"]
        self.fake.transcript = [{"role": "assistant", "text": BLOCK.replace("Docs", "Old")}, {"role": "user", "text": "ok"},
                                {"role": "assistant", "text": "plan:\n" + BLOCK}]
        r = self.client.post(f"/api/grill/{self.slug}/{sid}/proposal")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["proposal"]["ops"][0]["title"], "Docs")
        self.assertEqual([x["ok"] for x in body["preview"]], [True, False])
        self.assertEqual(self.text(), CHECKLIST)

    def test_proposal_route_errors(self):
        sid = self.client.post("/api/grill/start", json={"feature": self.slug}).get_json()["id"]
        self.fake.transcript = [{"role": "assistant", "text": "Q1 - what?"}]
        r = self.client.post(f"/api/grill/{self.slug}/{sid}/proposal")
        self.assertEqual(r.status_code, 400)
        self.assertIn("no checklist-diff proposal", r.get_json()["error"])
        self.assertEqual(self.client.post(f"/api/grill/{self.slug}/chat-9-zzz/proposal").status_code, 404)

    def test_the_real_checklist_has_ff2_hand_ticked_with_its_merge(self):
        items = {i["id"]: i for i in checklist.items(checklist.parse(
            (repo_root / "features" / "feature-forge" / "checklist.md").read_text(encoding="utf-8")))}
        self.assertTrue(items["FF-2"]["ticked"])
        self.assertEqual((items["FF-2"]["meta"]["manual"], items["FF-2"]["meta"]["merged"]), ("true", "de08292"))
        self.assertFalse(items["FF-3"]["ticked"])


if __name__ == "__main__":
    unittest.main()
