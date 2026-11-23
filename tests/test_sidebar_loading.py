"""Static checks: the sidebar list holds a loading line before /api/features answers, and a failure shows an error with a Retry button."""
import re
import unittest
from pathlib import Path

PAGE = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(encoding="utf-8")
SCRIPT = PAGE.split("<script>")[-1].split("</script>")[0]


class SidebarLoadingTests(unittest.TestCase):
    def test_list_holds_a_loading_line_in_the_static_markup(self):
        m = re.search(r'<div id="list">(.*?)</div></div>', PAGE, re.S)
        self.assertIsNotNone(m, "no #list container")
        self.assertIn('id="feature-list-status"', m.group(1))
        self.assertIn("Loading features...", m.group(1))

    def test_failure_shows_error_and_click_only_retry(self):
        self.assertIn("Could not load features.", SCRIPT)
        self.assertIn("bListRetry", SCRIPT)
        self.assertIn("Retry", SCRIPT)
        self.assertIn("$('bListRetry').onclick", SCRIPT)

    def test_render_replaces_the_status_line(self):
        body = SCRIPT[SCRIPT.index("function renderList"):SCRIPT.index("async function loadLibrary")]
        self.assertIn("$('list').innerHTML=", body)


if __name__ == "__main__":
    unittest.main()
