"""Static checks of web/index.html: the repo chooser and grill panel are wired to the routes, and the page stays free of
timers and blocking dialogs. Standard library only, so it runs under a bare python3. The real-browser test is
tests/browser_grill_panel.mjs."""
import re
import unittest
from pathlib import Path

PAGE = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(encoding="utf-8")
SCRIPT = PAGE.split("<script>")[-1].split("</script>")[0]


class PageTests(unittest.TestCase):
    def test_every_control_exists(self):
        for ident in ("bRepo", "bGrill", "grill", "gt", "gtext", "gstart", "gsend", "gsave", "gend", "gclose", "gin"):
            with self.subTest(id=ident):
                self.assertIn(f'id="{ident}"', PAGE)

    def test_the_page_calls_each_repo_and_grill_route(self):
        for needle in ("/api/repos", "/api/features/${cur}/repo", "/api/grill/start", "/begin", "/message", "/save", "/end"):
            with self.subTest(route=needle):
                self.assertIn(needle, SCRIPT)

    def test_no_timers_and_no_blocking_dialogs(self):
        for banned in ("setInterval", "setTimeout", "confirm(", "alert(", "prompt("):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, SCRIPT)

    def test_the_stream_reader_handles_chunks_and_errors(self):
        self.assertIn("ev.type==='chunk'", SCRIPT)
        self.assertIn("ev.type==='error'", SCRIPT)
        self.assertIn("r.body.getReader()", SCRIPT)

    def test_end_asks_twice_when_unsaved(self):
        self.assertRegex(SCRIPT, r"gUnsaved&&!gEnding")
        self.assertIn("Not saved yet", SCRIPT)

    def test_the_owner_decides_the_repo_wording(self):
        self.assertIn("The decision is yours", SCRIPT)

    def test_the_checklist_rows_and_proposal_review_are_wired(self):
        for ident in ("grev", "prop"):
            self.assertIn(f'id="{ident}"', PAGE)
        for needle in ("/api/features/${cur}/checklist", "data-grill", "node:gNode", "/proposal", "/checklist/apply", "only", "changed since filing"):
            with self.subTest(needle=needle):
                self.assertIn(needle, SCRIPT)

    def test_filing_buttons_are_wired_to_the_routes(self):
        for needle in ("data-file", "data-flag", "/checklist/${id}/file", "/checklist/${pb.dataset.id}/flag", "acceptLint", "lintArmed",
                       "File anyway", "Polling language"):
            with self.subTest(needle=needle):
                self.assertIn(needle, SCRIPT)

    def test_the_page_syncs_task_states_when_the_checklist_opens(self):
        for needle in ("/api/features/${cur}/sync", "taskStates", "Merged: ", "took ${esc(m.took)} min"):
            with self.subTest(needle=needle):
                self.assertIn(needle, SCRIPT)

    def test_a_refused_op_cannot_be_ticked(self):
        self.assertIn("r.ok?'checked':'disabled'", SCRIPT)

    def test_buttons_are_hidden_outside_a_feature(self):
        self.assertRegex(SCRIPT, r"function showButtons\(on\)\{\['bRepo','bGrill'")


if __name__ == "__main__":
    unittest.main()
