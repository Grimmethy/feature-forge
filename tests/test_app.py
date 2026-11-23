"""Tests for server/app.py: every route through Flask's test client on a temp features folder.
Plain unittest. They are skipped (not failed) where flask or markdown is not installed, for example a bare system python."""
import sys
import tempfile
import unittest
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))
try:
    from server.app import create_app
except ImportError:
    create_app = None


@unittest.skipIf(create_app is None, "flask and markdown are not installed")
class AppTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.client = create_app(self.root).test_client()

    def make_alpha(self):
        self.assertEqual(self.client.post("/api/features", json={"title": "Alpha Thing", "request": "build alpha"}).status_code, 201)
        return "alpha-thing"

    def test_health(self):
        self.assertEqual(self.client.get("/api/health").get_json(), {"ok": True})

    def test_index_serves_the_page(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content_type.startswith("text/html"))
        self.assertIn(b"Feature Forge", r.data)

    def test_markdown_is_a_declared_dependency(self):
        self.assertIn("markdown", (repo_root / "requirements.txt").read_text(encoding="utf-8").split())

    def test_create_and_list(self):
        alpha = self.make_alpha()
        (row,) = self.client.get("/api/features").get_json()
        self.assertEqual((row["slug"], row["title"], row["status"]), (alpha, "Alpha Thing", "Grilling"))

    def test_blank_title_is_400(self):
        self.assertEqual(self.client.post("/api/features", json={"title": "  "}).status_code, 400)
        self.assertEqual(self.client.post("/api/features", data="not json").status_code, 400)

    def test_file_round_trip_and_history(self):
        alpha = self.make_alpha()
        url = f"/api/features/{alpha}/file?path=plan.md"
        self.assertEqual(self.client.put(url, json={"text": "new plan"}).status_code, 200)
        self.assertEqual(self.client.get(url).get_json()["text"], "new plan")
        self.assertEqual(len(list((self.root / alpha / ".history").iterdir())), 1)

    def test_put_needs_a_text_string(self):
        alpha = self.make_alpha()
        self.assertEqual(self.client.put(f"/api/features/{alpha}/file?path=plan.md", json={"text": 5}).status_code, 400)

    def test_bad_paths_are_400(self):
        alpha = self.make_alpha()
        for bad in ["../x.md", "plan.txt", "/etc/passwd.md"]:
            with self.subTest(path=bad):
                self.assertEqual(self.client.get(f"/api/features/{alpha}/file?path={bad}").status_code, 400)

    def test_unknown_feature_and_file_are_404(self):
        alpha = self.make_alpha()
        self.assertEqual(self.client.get("/api/features/nope/tree").status_code, 404)
        self.assertEqual(self.client.get(f"/api/features/{alpha}/file?path=nofile.md").status_code, 404)

    def test_tree_lists_markdown_without_history(self):
        alpha = self.make_alpha()
        self.client.put(f"/api/features/{alpha}/file?path=plan.md", json={"text": "v2"})
        paths = [t["path"] for t in self.client.get(f"/api/features/{alpha}/tree").get_json()]
        self.assertIn("plan.md", paths)
        self.assertFalse(any(p.startswith(".") for p in paths))

    def test_render_rewrites_relative_md_links_only(self):
        alpha = self.make_alpha()
        text = "see [req](request.md), [ext](https://example.org/a.md) and [up](../../x.md)\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
        self.client.put(f"/api/features/{alpha}/file?path=plan.md", json={"text": text})
        html = self.client.get(f"/api/features/{alpha}/render?path=plan.md").get_json()["html"]
        self.assertIn('data-md="request.md"', html)
        self.assertIn('href="https://example.org/a.md"', html)
        self.assertNotIn('data-md="../', html)
        self.assertIn("<table>", html)

    def test_search_is_case_insensitive_and_skips_history(self):
        alpha = self.make_alpha()
        self.client.put(f"/api/features/{alpha}/file?path=plan.md", json={"text": "a Unique-NEEDLE here"})
        hits = self.client.get("/api/search?q=unique-needle").get_json()
        self.assertEqual([(h["slug"], h["path"]) for h in hits], [(alpha, "plan.md")])
        self.assertIn("unique-needle", hits[0]["snippet"].lower())
        self.assertEqual(self.client.get("/api/search?q=").get_json(), [])
        self.assertEqual(self.client.get("/api/search?q=zzzqqq").get_json(), [])

    def test_duplicate_title_returns_409_with_exact_json(self):
        self.make_alpha()
        r = self.client.post("/api/features", json={"title": "Alpha Thing", "request": "duplicate"})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.get_json(), {"error": 'A feature titled "Alpha Thing" already exists.'})
        self.assertEqual(len(list(self.root.iterdir())), 1)

    def test_case_variant_title_returns_409(self):
        self.make_alpha()
        r = self.client.post("/api/features", json={"title": "alpha thing", "request": "lowercase"})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.get_json(), {"error": 'A feature titled "alpha thing" already exists.'})
        self.assertEqual(len(list(self.root.iterdir())), 1)

    def test_whitespace_variant_title_returns_409(self):
        self.make_alpha()
        r = self.client.post("/api/features", json={"title": "Alpha  Thing", "request": "extra space"})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.get_json(), {"error": 'A feature titled "Alpha  Thing" already exists.'})
        self.assertEqual(len(list(self.root.iterdir())), 1)

    def test_concurrent_identical_titles_one_201_one_409(self):
        import threading
        results = []
        def post():
            results.append(self.client.post("/api/features", json={"title": "Concurrent Thing", "request": "thread"}).status_code)
        threads = [threading.Thread(target=post) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(results), [201, 409])
        self.assertEqual(len(list(self.root.iterdir())), 1)


if __name__ == "__main__":
    unittest.main()
