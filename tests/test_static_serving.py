"""Tests for the generic static route in server/app.py.
A file added under web/ after the app is created must be served without a restart,
and the route must not escape web/ or list directories. Plain unittest; skipped where flask is missing."""
import sys
import tempfile
import unittest
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))
try:
    from server.app import create_app, WEB_DIR
except ImportError:
    create_app = None
    WEB_DIR = None

PROBE_NAME = "_probe_static_serving.js"
PROBE_BODY = "// probe\n"


@unittest.skipIf(create_app is None, "flask and markdown are not installed")
class StaticServingTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.client = create_app(Path(tmp.name)).test_client()
        # Created AFTER the app, so serving it proves no restart is needed.
        self.probe = Path(WEB_DIR) / PROBE_NAME
        self.addCleanup(lambda: self.probe.unlink(missing_ok=True))
        self.probe.write_text(PROBE_BODY, encoding="utf-8")

    def test_new_file_served_after_app_creation(self):
        r = self.client.get("/" + PROBE_NAME)
        self.addCleanup(r.close)
        self.assertEqual(r.status_code, 200)
        self.assertRegex(r.content_type, r"^(text|application)/javascript")
        self.assertEqual(r.data, PROBE_BODY.encode("utf-8"))

    def test_dotdot_returns_404(self):
        for path in ("/../server/app.py", "/%2e%2e/server/app.py", "/..%2fserver%2fapp.py"):
            with self.subTest(path=path):
                r = self.client.get(path)
                self.assertEqual(r.status_code, 404)
                self.assertNotIn(b"create_app", r.data)

    def test_absolute_path_returns_404(self):
        for path in ("//etc/passwd", "/%2Fetc/passwd"):
            with self.subTest(path=path):
                r = self.client.get(path)
                self.assertEqual(r.status_code, 404)
                self.assertNotIn(b"root:", r.data)

    def test_directory_request_has_no_listing(self):
        for path in ("/tests", "/tests/"):
            with self.subTest(path=path):
                r = self.client.get(path)
                self.assertNotEqual(r.status_code, 200)
                self.assertNotIn(b"feature-counts.js", r.data)
                self.assertNotIn(b"Directory listing", r.data)

    def test_api_features_still_json(self):
        r = self.client.get("/api/features")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content_type.startswith("application/json"))
        self.assertIsNotNone(r.get_json())

    def test_index_still_served(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content_type.startswith("text/html"))


if __name__ == "__main__":
    unittest.main()
