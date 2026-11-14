"""Tests for the filing routes in server/app.py through Flask's test client, with the queue script and the dashboard faked.
Plain unittest; skipped where flask or markdown is not installed."""
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from server import app as appmod
    from server.core import filing, store
except ImportError:
    appmod = None

CHECKLIST = """# Checklist: Thing

- [ ] FF-1 Build the core <!-- premium: true deps: -->
  Write core.py.
- [ ] FF-2 Watch the folder <!-- deps: FF-1 -->
  Check it every 5 minutes.
- [x] FF-3 Done already <!-- manual: true -->
"""


@unittest.skipIf(appmod is None, "flask and markdown are not installed")
class FilingRouteTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = self.tmp / "features"
        reg = self.tmp / "projects.json"
        reg.write_text(json.dumps([{"repoRoot": "/r/alpha", "pipelineDir": "/p/a", "domainsPath": "/p/a/d.json", "label": "alpha"}]))
        self.calls, self.posts, self.down = [], [], False

        def run(cmd, **kw):
            self.calls.append(cmd)
            return SimpleNamespace(returncode=0, stdout=f"queued adhoc task: /p/a/queue/adhoc/adhoc-t{len(self.calls)}.json\n", stderr="")

        def opener(req, timeout=None):
            self.posts.append((req.full_url, json.loads(req.data.decode())))
            if self.down:
                raise OSError("down")
            return io.BytesIO(b"{}")
        saved = (filing.runner, filing._urlopen, os.environ.get("FEATUREFORGE_PROJECTS"))
        filing.runner, filing._urlopen = run, opener
        os.environ["FEATUREFORGE_PROJECTS"] = str(reg)

        def restore():
            filing.runner, filing._urlopen = saved[0], saved[1]
            if saved[2] is None:
                os.environ.pop("FEATUREFORGE_PROJECTS", None)
            else:
                os.environ["FEATUREFORGE_PROJECTS"] = saved[2]
        self.addCleanup(restore)
        self.client = appmod.create_app(self.root).test_client()
        self.slug = store.create_feature("Thing", "x\nrepo: alpha", self.root)
        store.write_file(self.slug, "checklist.md", CHECKLIST, self.root)

    def url(self, item, tail):
        return f"/api/features/{self.slug}/checklist/{item}/{tail}"

    def test_the_rows_carry_polling_warnings(self):
        rows = {r["id"]: r for r in self.client.get(f"/api/features/{self.slug}/checklist").get_json()}
        self.assertEqual(rows["FF-1"]["lint"], [])
        self.assertEqual(rows["FF-2"]["lint"], ["'every N <unit>'"])

    def test_file_files_the_item_and_returns_the_task(self):
        r = self.client.post(self.url("FF-1", "file"), json={})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["task"], "adhoc-t1")
        self.assertTrue(r.get_json()["premium"])
        rows = {x["id"]: x for x in self.client.get(f"/api/features/{self.slug}/checklist").get_json()}
        self.assertTrue(rows["FF-1"]["locked"])
        self.assertEqual(rows["FF-1"]["meta"]["task"], "adhoc-t1")

    def test_polling_language_is_a_400_until_accepted(self):
        self.client.post(self.url("FF-1", "file"), json={})
        r = self.client.post(self.url("FF-2", "file"), json={})
        self.assertEqual(r.status_code, 400)
        self.assertIn("polling language", r.get_json()["error"])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.client.post(self.url("FF-2", "file"), json={"acceptLint": True}).status_code, 200)

    def test_refusals_have_the_right_codes(self):
        self.assertEqual(self.client.post(self.url("FF-9", "file"), json={}).status_code, 404)
        self.assertEqual(self.client.post(self.url("FF-2", "file"), json={}).status_code, 400)          # FF-1 not filed yet
        self.assertEqual(self.client.post(self.url("FF-3", "file"), json={}).status_code, 400)          # already done
        self.assertEqual(self.client.post(self.url("FF-1", "file"), json={"acceptLint": "yes"}).status_code, 400)
        self.assertEqual(self.client.post("/api/features/nope/checklist/FF-1/file", json={}).status_code, 404)
        self.assertEqual(self.calls, [])

    def test_a_step_with_pieces_files_each_piece_and_the_rows_say_what_is_left(self):
        store.write_file(self.slug, "checklist.md", "# Checklist: Thing\n\n- [ ] FF-1 Step <!-- deps: -->\n  Context.\n  - [ ] 1a One\n    text one\n  - [ ] 1b Two\n    text two\n", self.root)
        rows = {r["id"]: r for r in self.client.get(f"/api/features/{self.slug}/checklist").get_json()}
        self.assertEqual((rows["FF-1"]["pieceTotal"], rows["FF-1"]["pieceUnfiled"]), (2, 2))
        r = self.client.post(self.url("FF-1", "file"), json={"piece": "1a"})
        self.assertEqual([x["piece"] for x in r.get_json()["pieces"]], ["1a"])
        rows = {r["id"]: r for r in self.client.get(f"/api/features/{self.slug}/checklist").get_json()}
        self.assertEqual((rows["FF-1"]["pieceUnfiled"], rows["FF-1"]["locked"]), (1, True))
        self.assertEqual(rows["FF-1"]["pieces"][0]["meta"]["task"], "adhoc-t1")
        r = self.client.post(self.url("FF-1", "file"), json={})
        self.assertEqual([x["piece"] for x in r.get_json()["pieces"]], ["1b"])
        self.assertEqual(self.client.post(self.url("FF-1", "file"), json={}).status_code, 400)             # nothing left to file

    def test_the_piece_argument_must_be_a_label(self):
        for bad in (5, ["1a"], {"a": 1}, True):
            with self.subTest(piece=bad):
                r = self.client.post(self.url("FF-1", "file"), json={"piece": bad})
                self.assertEqual(r.status_code, 400)
                self.assertIn("piece must be a piece label", r.get_json()["error"])
        self.assertEqual(self.client.post(self.url("FF-1", "file"), json={"piece": "1a"}).status_code, 400)    # FF-1 has no pieces
        self.assertEqual(self.calls, [])

    def test_flag_changes_the_item(self):
        r = self.client.post(self.url("FF-2", "flag"), json={"flag": "cloud", "value": True})
        self.assertEqual(r.get_json(), {"id": "FF-2", "flag": "cloud", "value": True})
        rows = {x["id"]: x for x in self.client.get(f"/api/features/{self.slug}/checklist").get_json()}
        self.assertEqual(rows["FF-2"]["meta"]["cloud"], "true")

    def test_flag_validation(self):
        for body in ({}, {"flag": "premium"}, {"flag": "premium", "value": "true"}, {"flag": "weird", "value": True}):
            with self.subTest(body=body):
                self.assertEqual(self.client.post(self.url("FF-1", "flag"), json=body).status_code, 400)
        self.assertEqual(self.client.post(self.url("FF-9", "flag"), json={"flag": "premium", "value": True}).status_code, 404)

    def test_a_dashboard_that_is_down_is_a_502_for_a_filed_premium_change(self):
        self.client.post(self.url("FF-1", "file"), json={})
        self.down = True
        r = self.client.post(self.url("FF-1", "flag"), json={"flag": "premium", "value": False})
        self.assertEqual(r.status_code, 502)


if __name__ == "__main__":
    unittest.main()
