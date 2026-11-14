"""Tests for the grill and repo routes in server/app.py through Flask's test client.
Plain unittest. Skipped (not failed) where flask or markdown is not installed. The chat plugin is a fake
(grill._urlopen is replaced) and the repos folder is a temp folder, so nothing real is touched."""
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))
try:
    from server import app as appmod
    from server.core import grill, store
except ImportError:
    appmod = None


class FakeChat:
    def __init__(self):
        self.calls, self.transcript, self.fail = [], [], False

    def __call__(self, req, timeout=None):
        if self.fail:
            raise urllib.error.URLError("connection refused")
        body = json.loads(req.data.decode()) if req.data else None
        path = "/" + req.full_url.split("://", 1)[1].split("/", 1)[1]
        self.calls.append((req.get_method(), path, body))
        if path == "/api/chat/new":
            return io.BytesIO(json.dumps({"id": "chat-1-abc"}).encode())
        if path.endswith("/message"):
            return io.BytesIO(b'data: {"type": "chunk", "text": "Q1 - repo?"}\n\ndata: {"type": "done"}\n\n')
        if req.get_method() == "GET":
            return io.BytesIO(json.dumps({"transcript": self.transcript}).encode())
        return io.BytesIO(b"{}")


@unittest.skipIf(appmod is None, "flask and markdown are not installed")
class GrillRouteTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "features"
        self.root.mkdir()
        self.repos = Path(tmp.name) / "repos"
        self.repos.mkdir()
        (self.repos / "alpha" / ".git").mkdir(parents=True)
        (self.repos / "alpha" / "README.md").write_text("# Alpha\n\nMakes alphas.\n", encoding="utf-8")
        patcher = mock.patch.dict(os.environ, {"FEATUREFORGE_REPOS_ROOT": str(self.repos)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.fake = FakeChat()
        saved = grill._urlopen
        grill._urlopen = self.fake
        self.addCleanup(lambda: setattr(grill, "_urlopen", saved))
        self.client = appmod.create_app(self.root).test_client()
        self.slug = store.create_feature("Thing", "build a thing", self.root)

    def begin_session(self):
        return self.client.post("/api/grill/start", json={"feature": self.slug}).get_json()["id"]

    # ---- repos ----
    def test_repos_lists_the_existing_repositories(self):
        rows = self.client.get("/api/repos").get_json()
        self.assertEqual([(r["name"], r["summary"]) for r in rows], [("alpha", "Makes alphas.")])

    def test_repo_starts_empty_then_records_the_owners_choice(self):
        self.assertEqual(self.client.get(f"/api/features/{self.slug}/repo").get_json()["name"], "")
        r = self.client.post(f"/api/features/{self.slug}/repo", json={"name": "alpha"}).get_json()
        self.assertEqual((r["name"], r["exists"]), ("alpha", True))
        self.assertIn("repo: alpha", store.read_file(self.slug, "request.md", self.root))

    def test_changing_the_repo_replaces_the_line_instead_of_adding_one(self):
        self.client.post(f"/api/features/{self.slug}/repo", json={"name": "alpha"})
        r = self.client.post(f"/api/features/{self.slug}/repo", json={"name": "brand-new"}).get_json()
        self.assertEqual((r["name"], r["exists"]), ("brand-new", False))
        text = store.read_file(self.slug, "request.md", self.root)
        self.assertEqual(text.count("repo:"), 1)
        self.assertIn("build a thing", text)

    def test_bad_repo_names_and_unknown_features(self):
        for bad in ["", "a/b", "..", "x y", "-x", "a" * 90]:
            with self.subTest(name=bad):
                self.assertEqual(self.client.post(f"/api/features/{self.slug}/repo", json={"name": bad}).status_code, 400)
        self.assertEqual(self.client.post("/api/features/nope/repo", json={"name": "alpha"}).status_code, 404)
        self.assertEqual(self.client.get("/api/features/nope/repo").status_code, 404)

    def test_set_repo_line_keeps_the_heading_first(self):
        self.assertEqual(appmod._set_repo_line("# T\n\nbody", "x"), "# T\n\nrepo: x\n\nbody")
        self.assertEqual(appmod._set_repo_line("no heading", "x"), "\nrepo: x\nno heading")

    # ---- grill ----
    def test_start_creates_a_read_only_session(self):
        store.write_file(self.slug, "checklist.md", "# Checklist: Thing\n\n- [ ] FF-3 Third item\n", self.root)
        r = self.client.post("/api/grill/start", json={"feature": self.slug, "node": "FF-3"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual((r.get_json()["id"], r.get_json()["node"]), ("chat-1-abc", "FF-3"))
        self.assertEqual(self.fake.calls[0][2], {"provider": "claude", "readOnly": True})
        self.assertEqual([s["id"] for s in self.client.get(f"/api/grill/{self.slug}/sessions").get_json()], ["chat-1-abc"])

    def test_start_for_an_unknown_checklist_item_is_404_before_any_chat_call(self):
        r = self.client.post("/api/grill/start", json={"feature": self.slug, "node": "FF-9"})
        self.assertEqual(r.status_code, 404)
        self.assertIn("no such item", r.get_json()["error"])
        self.assertEqual(self.fake.calls, [])

    def test_start_errors(self):
        self.assertEqual(self.client.post("/api/grill/start", json={"feature": "nope"}).status_code, 404)
        self.assertEqual(self.client.post("/api/grill/start", json={}).status_code, 400)
        self.fake.fail = True
        r = self.client.post("/api/grill/start", json={"feature": self.slug})
        self.assertEqual(r.status_code, 502)
        self.assertIn("chat plugin unavailable", r.get_json()["error"])

    def test_begin_streams_the_first_round_and_sends_the_seed(self):
        sid = self.begin_session()
        r = self.client.post(f"/api/grill/{self.slug}/{sid}/begin")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content_type.startswith("text/event-stream"))
        self.assertIn(b"Q1 - repo?", r.data)
        sent = [c for c in self.fake.calls if c[1].endswith("/message")][0][2]["message"]
        self.assertIn("Feature Forge grill session", sent)
        self.assertIn("alpha", sent)

    def test_message_relays_the_owners_words_and_refuses_an_empty_one(self):
        sid = self.begin_session()
        self.assertEqual(self.client.post(f"/api/grill/{self.slug}/{sid}/message", json={"message": "  "}).status_code, 400)
        r = self.client.post(f"/api/grill/{self.slug}/{sid}/message", json={"message": "yes, alpha"})
        self.assertIn(b"Q1 - repo?", r.data)
        self.assertEqual([c for c in self.fake.calls if c[1].endswith("/message")][-1][2], {"message": "yes, alpha"})

    def test_unknown_session_is_404_and_a_dead_plugin_mid_turn_is_an_error_event(self):
        self.assertEqual(self.client.post(f"/api/grill/{self.slug}/chat-9-zzz/begin").status_code, 404)
        sid = self.begin_session()
        self.fake.fail = True
        r = self.client.post(f"/api/grill/{self.slug}/{sid}/message", json={"message": "hi"})
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'"type": "error"', r.data)

    def test_save_appends_to_interview_and_nothing_to_save_is_400(self):
        sid = self.begin_session()
        r = self.client.post(f"/api/grill/{self.slug}/{sid}/save")
        self.assertEqual((r.status_code, r.get_json()["error"]), (400, "nothing to save yet"))
        self.fake.transcript = [{"role": "user", "text": "SEED"}, {"role": "assistant", "text": "Q1 - repo?"},
                                {"role": "user", "text": "alpha please"}]
        r = self.client.post(f"/api/grill/{self.slug}/{sid}/save")
        self.assertEqual((r.status_code, r.get_json()["path"]), (200, "interview.md"))
        self.assertIn("alpha please", store.read_file(self.slug, "interview.md", self.root))

    def test_end_stamps_the_session(self):
        sid = self.begin_session()
        self.assertIn("ended", self.client.post(f"/api/grill/{self.slug}/{sid}/end").get_json())

    def test_bad_session_id_is_400(self):
        self.assertEqual(self.client.post(f"/api/grill/{self.slug}/a.b/end").status_code, 400)


if __name__ == "__main__":
    unittest.main()
