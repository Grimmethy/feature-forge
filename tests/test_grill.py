"""Tests for server/core/grill.py: repo index and target repo, the seed, read-only chat sessions, streaming and saving.
Plain unittest and standard library only; the chat plugin is a fake (grill._urlopen is replaced)."""
import io
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.core import grill, store


class FakeChat:
    """Records every request and answers by path, like the chat plugin would."""
    def __init__(self, transcript=None, fail=False):
        self.calls, self.transcript, self.fail = [], transcript or [], fail

    def __call__(self, req, timeout=None):
        if self.fail:
            raise urllib.error.URLError("connection refused")
        body = json.loads(req.data.decode()) if req.data else None
        path = req.full_url.split("://", 1)[1].split("/", 1)[1]
        self.calls.append((req.get_method(), "/" + path, body))
        if path == "api/chat/new":
            return io.BytesIO(json.dumps({"id": "chat-1-abc"}).encode())
        if path.endswith("/message"):
            return io.BytesIO(b'data: {"type": "chunk", "text": "Q1 - repo?"}\n\ndata: {"type": "done"}\n\n')
        if req.get_method() == "GET":
            return io.BytesIO(json.dumps({"transcript": self.transcript}).encode())
        return io.BytesIO(b"{}")


class GrillTestBase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "features"
        self.root.mkdir()
        self.repos = Path(tmp.name) / "repos"
        self.repos.mkdir()
        self.proto = Path(tmp.name) / "protocol.md"
        self.proto.write_text("PROTOCOL TEXT: ask the whole frontier", encoding="utf-8")
        self.fake = FakeChat()
        self._saved = grill._urlopen
        grill._urlopen = self.fake
        self.addCleanup(lambda: setattr(grill, "_urlopen", self._saved))

    def make_repo(self, name, readme=None, context=None, git_dir=True):
        d = self.repos / name
        d.mkdir()
        if git_dir:
            (d / ".git").mkdir()
        if readme:
            (d / "README.md").write_text(readme, encoding="utf-8")
        if context:
            (d / "CONTEXT.md").write_text(context, encoding="utf-8")
        return d

    def feature(self, request="build a thing"):
        return store.create_feature("Thing", request, self.root)


class RepoTests(GrillTestBase):
    def test_repo_index_lists_git_repos_with_a_summary_and_skips_the_rest(self):
        self.make_repo("alpha", readme="# Alpha\n\nA tool for making alphas.\n")
        self.make_repo("beta", context="# Beta\n\nBeta context line.\n", readme="# Beta\n\nIgnored readme line.\n")
        self.make_repo("alpha-pipeline")
        self.make_repo("plain-folder", git_dir=False)
        names = {r["name"]: r for r in grill.repo_index(self.repos)}
        self.assertEqual(set(names), {"alpha", "beta"})
        self.assertEqual(names["alpha"]["summary"], "A tool for making alphas.")
        self.assertEqual(names["beta"]["summary"], "Beta context line.")

    def test_repo_index_of_a_missing_folder_is_empty(self):
        self.assertEqual(grill.repo_index(self.repos / "nowhere"), [])

    def test_target_repo_none_existing_and_new(self):
        none = self.feature()
        self.assertEqual(grill.target_repo(none, self.root, self.repos)["name"], "")
        self.make_repo("alpha")
        store.write_file(none, "request.md", "# Thing\n\nrepo: alpha\nbuild it", self.root)
        t = grill.target_repo(none, self.root, self.repos)
        self.assertTrue(t["exists"] and t["path"] == str(self.repos / "alpha"))
        store.write_file(none, "request.md", "# Thing\n\nrepo: brand-new\n", self.root)
        t = grill.target_repo(none, self.root, self.repos)
        self.assertEqual((t["name"], t["exists"]), ("brand-new", False))


class SeedTests(GrillTestBase):
    def test_no_repo_chosen_asks_for_the_repo_first_and_lists_repos(self):
        self.make_repo("alpha", readme="# Alpha\n\nMakes alphas.\n")
        seed = grill.build_seed(self.feature(), self.root, self.repos, self.proto)
        self.assertIn("PROTOCOL TEXT", seed)
        self.assertIn("READ-ONLY", seed)
        self.assertIn("No target repo is chosen yet", seed)
        self.assertIn("Question 1 of your first round MUST be the repo", seed)
        self.assertIn("`alpha`: Makes alphas.", seed)
        self.assertIn("build a thing", seed)

    def test_existing_repo_brings_its_docs_tree_and_path(self):
        d = self.make_repo("alpha", context="# Alpha context\n\nNEVER-WRITE-RULE here\n")
        (d / "src").mkdir()
        (d / "src" / "main.py").write_text("x = 1", encoding="utf-8")
        slug = self.feature("repo: alpha\nbuild a thing")
        seed = grill.build_seed(slug, self.root, self.repos, self.proto)
        self.assertIn(str(d), seed)
        self.assertIn("NEVER-WRITE-RULE", seed)
        self.assertIn("src/main.py", seed)
        self.assertNotIn("No target repo is chosen yet", seed)
        self.assertNotIn("MUST be the repo", seed)

    def test_a_new_repo_name_is_called_new(self):
        self.make_repo("alpha", readme="# A\n\nx\n")
        slug = self.feature("repo: brand-new\nbuild a thing")
        seed = grill.build_seed(slug, self.root, self.repos, self.proto)
        self.assertIn("NEW repo `brand-new`", seed)

    def test_long_context_files_are_truncated(self):
        d = self.make_repo("alpha", context="x" * (grill.FILE_CAP * 2))
        slug = self.feature("repo: alpha\n")
        seed = grill.build_seed(slug, self.root, self.repos, self.proto)
        self.assertIn("[...truncated...]", seed)
        self.assertLess(len(seed), grill.CONTEXT_CAP + 6000)


class SessionTests(GrillTestBase):
    def test_start_opens_a_read_only_claude_session_and_saves_meta(self):
        slug = self.feature()
        meta = grill.start(slug, root=self.root)
        self.assertEqual(self.fake.calls[0], ("POST", "/api/chat/new", {"provider": "claude", "readOnly": True}))
        self.assertEqual(self.fake.calls[1], ("POST", "/api/chat/chat-1-abc/swap", {"provider": "claude", "account": "claude-main"}))
        self.assertEqual((meta["id"], meta["feature"], meta["node"]), ("chat-1-abc", slug, "feature"))
        self.assertEqual(grill.load_meta(slug, "chat-1-abc", self.root)["id"], "chat-1-abc")
        self.assertEqual([m["id"] for m in grill.list_sessions(slug, self.root)], ["chat-1-abc"])

    def test_start_for_an_unknown_feature_is_refused_before_any_chat_call(self):
        with self.assertRaises(store.StoreError):
            grill.start("nope", root=self.root)
        self.assertEqual(self.fake.calls, [])

    def test_chat_plugin_down_is_a_grill_error(self):
        slug = self.feature()
        grill._urlopen = FakeChat(fail=True)
        with self.assertRaisesRegex(grill.GrillError, "chat plugin unavailable"):
            grill.start(slug, root=self.root)

    def test_first_turn_sends_the_seed_and_later_turns_the_message(self):
        slug = self.feature()
        grill.start(slug, root=self.root)
        lines = list(grill.stream_turn(slug, "chat-1-abc", None, self.root, self.repos))
        self.assertTrue(any("Q1 - repo?" in ln for ln in lines))
        sent = [c for c in self.fake.calls if c[1].endswith("/message")][0][2]["message"]
        self.assertIn("Feature Forge grill session", sent)
        self.assertTrue(grill.load_meta(slug, "chat-1-abc", self.root)["seeded"])
        list(grill.stream_turn(slug, "chat-1-abc", "yes, repo alpha", self.root))
        self.assertEqual([c for c in self.fake.calls if c[1].endswith("/message")][1][2], {"message": "yes, repo alpha"})

    def test_a_dead_chat_plugin_mid_turn_becomes_an_error_event(self):
        slug = self.feature()
        grill.start(slug, root=self.root)
        grill._urlopen = FakeChat(fail=True)
        (line,) = [ln for ln in grill.stream_turn(slug, "chat-1-abc", "hi", self.root) if ln.strip()]
        self.assertEqual(json.loads(line[len("data: "):])["type"], "error")

    def test_bad_session_ids_are_rejected(self):
        slug = self.feature()
        for bad in ("", "../x", "a/b"):
            with self.subTest(sid=bad):
                with self.assertRaisesRegex(grill.GrillError, "bad session id"):
                    grill.load_meta(slug, bad, self.root)
        with self.assertRaisesRegex(grill.GrillError, "no such grill session"):
            grill.load_meta(slug, "chat-9-zzz", self.root)


class SaveTests(GrillTestBase):
    def entries(self):
        return [
            {"role": "user", "text": "THE SEED PROMPT"},
            {"role": "assistant", "text": "Q1 - repo?\nCONTEXT-LOG: noise\n-> alpha"},
            {"role": "user", "text": "yes, alpha"},
            {"marker": True, "role": "assistant", "text": "swapped"},
            {"role": "assistant", "text": "Q2 - tests?"},
        ]

    def test_format_drops_the_seed_markers_and_bookkeeping_and_keeps_the_owners_words(self):
        text = grill.format_transcript(self.entries())
        self.assertNotIn("THE SEED PROMPT", text)
        self.assertNotIn("CONTEXT-LOG", text)
        self.assertNotIn("swapped", text)
        self.assertIn("**Owner:**\n\nyes, alpha", text)
        self.assertEqual(text.count("**Grill:**"), 2)

    def test_save_appends_a_session_block_without_the_placeholder(self):
        slug = self.feature()
        grill.start(slug, root=self.root)
        self.fake.transcript = self.entries()
        r = grill.save_to_interview(slug, "chat-1-abc", self.root)
        self.assertEqual(r["path"], "interview.md")
        text = store.read_file(slug, "interview.md", self.root)
        self.assertNotIn("_Not started._", text)
        self.assertIn("## Session", text)
        self.assertIn("yes, alpha", text)
        self.assertTrue(grill.load_meta(slug, "chat-1-abc", self.root)["saved"])
        grill.save_to_interview(slug, "chat-1-abc", self.root)
        self.assertEqual(store.read_file(slug, "interview.md", self.root).count("## Session"), 2)

    def test_nothing_to_save_is_an_error(self):
        slug = self.feature()
        grill.start(slug, root=self.root)
        with self.assertRaisesRegex(grill.GrillError, "nothing to save yet"):
            grill.save_to_interview(slug, "chat-1-abc", self.root)

    def test_end_closes_the_chat_and_stamps_the_meta(self):
        slug = self.feature()
        grill.start(slug, root=self.root)
        meta = grill.end(slug, "chat-1-abc", self.root)
        self.assertIn("ended", meta)
        self.assertIn(("POST", "/api/chat/chat-1-abc/close", {}), self.fake.calls)

    def test_end_still_stamps_when_the_chat_plugin_is_down(self):
        slug = self.feature()
        grill.start(slug, root=self.root)
        grill._urlopen = FakeChat(fail=True)
        self.assertIn("ended", grill.end(slug, "chat-1-abc", self.root))


if __name__ == "__main__":
    unittest.main()
