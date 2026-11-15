"""Static checks of web/index.html: the repo chooser and grill panel are wired to the routes, and the page stays free of
timers and blocking dialogs. Standard library only, so it runs under a bare python3; the node parse check needs node on PATH. The real-browser test is
tests/browser_grill_panel.mjs."""
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

PAGE = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(encoding="utf-8")
SCRIPT = PAGE.split("<script>")[-1].split("</script>")[0]


def inline_scripts(html):
    """Bodies of every <script> block without a src= attribute, in document order."""
    found = re.findall(r"<script\b([^>]*)>(.*?)</script>", html, re.S | re.I)
    return [body for attrs, body in found if "src=" not in attrs.lower()]


def node_check(body):
    """Run `node --check` on one script body; returns (returncode, stderr)."""
    tmp = tempfile.mkdtemp(prefix="page-script-")
    try:
        path = os.path.join(tmp, "page-script.js")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
        proc = subprocess.run(["node", "--check", path], capture_output=True, text=True)
        return proc.returncode, proc.stderr
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


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

    def test_the_view_buttons_are_wired_to_the_view_routes(self):
        for ident in ("bBoard", "bRepos", "bGraph"):
            self.assertIn(f'id="{ident}"', PAGE)
        for needle in ("/api/views/board", "/api/views/repos", "/api/features/${cur}/graph.svg", "data-col", "data-repo", "(no repo yet)"):
            with self.subTest(needle=needle):
                self.assertIn(needle, SCRIPT)

    def test_the_create_repo_button_shows_the_steps_before_doing_anything(self):
        for needle in ("/api/repos/plan?name=", "/api/repos/create", "confirm:true", "Create now", "rcplan", "rcgo", "repoCreateBox", "does not exist yet"):
            with self.subTest(needle=needle):
                self.assertIn(needle, SCRIPT)
        self.assertLess(SCRIPT.index("/api/repos/plan?name="), SCRIPT.index("/api/repos/create"))

    def test_create_now_cannot_be_pressed_twice_and_done_steps_are_marked(self):
        self.assertIn("$('rcgo').disabled=true", SCRIPT)                 # disabled while the request runs
        self.assertIn("$('rcgo').disabled=false", SCRIPT)                # and usable again after an error
        self.assertIn("(already done)", SCRIPT)

    def test_sub_pieces_are_drawn_under_each_checklist_row(self):
        for needle in ("piecesHtml", "data-piece", "i.pieceDone", "i.pieceTotal", "pieces</span>", "tag merged", "tag need", "needs: "):
            with self.subTest(needle=needle):
                self.assertIn(needle, SCRIPT)

    def test_piece_text_is_escaped(self):
        body = SCRIPT[SCRIPT.index("function piecesHtml"):SCRIPT.index("function checklistHtml")]
        for needle in ("esc(p.id)", "esc(p.title)", "esc(m.merged)", "esc(m.needs)"):
            with self.subTest(needle=needle):
                self.assertIn(needle, body)

    def test_pieces_can_be_filed_and_show_their_tasks(self):
        for needle in ("i.pieceUnfiled>0", "r.pieces.map", "The Agent Manager task for this piece", "taskStates[i.id+'/'+p.id]"):
            with self.subTest(needle=needle):
                self.assertIn(needle, SCRIPT)

    def test_a_refused_op_cannot_be_ticked(self):
        self.assertIn("r.ok?'checked':'disabled'", SCRIPT)

    def test_buttons_are_hidden_outside_a_feature(self):
        self.assertRegex(SCRIPT, r"function showButtons\(on\)\{\['bRepo','bGrill'")


class ParsePageTests(unittest.TestCase):
    def require_node(self):
        if shutil.which("node") is None:
            self.fail("node is required to check the page script")

    def test_every_inline_script_parses(self):
        self.require_node()
        blocks = inline_scripts(PAGE)
        self.assertGreater(len(blocks), 0, "no inline script found; check failed vacuously")
        for i, body in enumerate(blocks):
            with self.subTest(block=i):
                code, err = node_check(body)
                self.assertEqual(code, 0, f"inline script {i} does not parse:\n{err}")

    def test_a_broken_first_inline_script_is_caught(self):
        self.require_node()
        html = ('<script>function (</script>'
                '<script>var ok = 1;</script>'
                '<script src="x.js">not read</script>')
        blocks = inline_scripts(html)
        self.assertEqual(len(blocks), 2)
        self.assertNotEqual(node_check(blocks[0])[0], 0)
        self.assertEqual(node_check(blocks[1])[0], 0)

    def test_the_proposals_view_button_is_present(self):
        self.assertIn('id="bProposals"', PAGE)


if __name__ == "__main__":
    unittest.main()
