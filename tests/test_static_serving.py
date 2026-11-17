"""Static file serving from web/: .js/.css served, traversal and dotfiles 404, index.html at /."""
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

try:
    from server.app import WEB_DIR, create_app
except ImportError:  # flask or markdown not installed
    create_app = None


class _LocalAssets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script" and a.get("src"):
            self.refs.append(a["src"])
        if tag == "link" and a.get("href"):
            self.refs.append(a["href"])


@unittest.skipIf(create_app is None, "flask and markdown are not installed")
class StaticServingTest(unittest.TestCase):
    def setUp(self):
        self.client = create_app(Path(__file__).parent).test_client()

    def test_js_served_byte_equal(self):
        r = self.client.get("/feature-counts.js")
        self.assertEqual(r.status_code, 200)
        self.assertIn("javascript", r.headers["Content-Type"])
        self.assertEqual(r.get_data(), (WEB_DIR / "feature-counts.js").read_bytes())

    def test_traversal_and_dotfiles_404(self):
        for path in ("/../server/app.py", "/..%2Fserver%2Fapp.py", "/.env", "/.git/config"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_index_unchanged(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_data(), (WEB_DIR / "index.html").read_bytes())

    def test_all_local_assets_in_index_served(self):
        parser = _LocalAssets()
        parser.feed((WEB_DIR / "index.html").read_text(encoding="utf-8"))
        local = []
        for ref in parser.refs:
            if ref.startswith(("http://", "https://", "//", "data:")):
                continue
            local.append(urlsplit(ref).path.lstrip("/"))
        self.assertIn("feature-counts.js", local)
        for name in local:
            with self.subTest(asset=name):
                self.assertEqual(self.client.get("/" + name).status_code, 200)


if __name__ == "__main__":
    unittest.main()
