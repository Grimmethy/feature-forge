"""Tests for the checklist items add route (POST /api/features/<slug>/checklist/items) in server/app.py
through Flask's test client. Plain unittest; skipped where flask or markdown is not installed.
Each test gets its own temp feature directory so no real checklist file is touched."""
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))
_skip_reason = "flask and markdown are not installed"
try:
    from server import app as appmod
    from server.core import checklist, grill, store
except ImportError as _e:
    _missing = getattr(_e, "name", None)
    if _missing in ("flask", "markdown") or (_missing and _missing.startswith("flask.")):
        appmod = None
        _skip_reason = f"{_missing} is not installed"
    else:
        raise


EMPTY_CHECKLIST = "# Checklist: Thing\n"


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


@unittest.skipIf(appmod is None, _skip_reason)
class ChecklistItemsRouteTests(unittest.TestCase):
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
        store.write_file(self.slug, "checklist.md", EMPTY_CHECKLIST, self.root)

    def url(self):
        return f"/api/features/{self.slug}/checklist/items"

    def text(self):
        return store.read_file(self.slug, "checklist.md", self.root)

    def test_valid_post_returns_201_with_id_and_stores_item(self):
        r = self.client.post(self.url(), json={"title": "FF-4 New", "body": "done"})
        self.assertEqual(r.status_code, 201, r.get_json())
        self.assertIn("id", r.get_json())
        self.assertIn("FF-4 New", self.text())
        self.assertIn("done", self.text())

    def test_premium_and_deps_are_stored_as_named_fields(self):
        store.write_file(self.slug, "checklist.md",
                         "# Checklist: Thing\n\n- [ ] FF-1 Existing <!-- deps: -->\n", self.root)
        r = self.client.post(self.url(), json={
            "title": "FF-4 Premium",
            "body": "x",
            "premium": True,
            "deps": ["FF-1"],
        })
        self.assertEqual(r.status_code, 201, r.get_json())
        new_id = r.get_json()["id"]
        self.assertIn("premium: true", self.text())
        self.assertIn("deps: FF-1", self.text())
        entries = checklist.parse(self.text())
        new_item = next(e for e in checklist.items(entries) if e["id"] == new_id)
        self.assertTrue(new_item["meta"]["premium"])
        self.assertEqual(new_item["meta"]["deps"], "FF-1")

    def test_bad_premium_returns_400_and_names_premium(self):
        r = self.client.post(self.url(), json={"title": "FF-4 Bad", "premium": "maybe"})
        self.assertEqual(r.status_code, 400)
        body = r.get_json()
        self.assertIn("error", body)
        self.assertIn("premium", body["error"])

    def test_unknown_feature_returns_404_with_error_message(self):
        r = self.client.post("/api/features/nope/checklist/items", json={"title": "FF-4 Bad"})
        self.assertEqual(r.status_code, 404)
        body = r.get_json()
        self.assertIn("error", body)
        self.assertTrue(body["error"], "error body should not be empty")

    def test_blank_title_returns_400(self):
        r = self.client.post(self.url(), json={"title": "  "})
        self.assertEqual(r.status_code, 400)
        body = r.get_json()
        self.assertIn("error", body)
        self.assertIn("title", body["error"])


if __name__ == "__main__":
    unittest.main()
