"""Tests for item grills and checklist-diff proposals in server/core/grill.py: the item seed, node validation, extracting the
newest proposal from a conversation, and the protocol text. Plain unittest, standard library only; the chat plugin is a fake."""
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.core import grill, store

CHECKLIST = """# Checklist: Thing

- [x] FF-1 Scaffold <!-- task: adhoc-1 premium: true deps: filed: 2026-11-13 manual: true -->
- [ ] FF-2 Build the core <!-- premium: true deps: FF-1 -->
  Write server/core/core.py with tests.
  Acceptance: tests pass.
- [ ] FF-3 Wire the routes <!-- deps: FF-2 -->
"""
BLOCK = '```checklist-diff\n{"ops": [{"op": "add", "title": "Docs"}]}\n```'


class FakeChat:
    def __init__(self, transcript=None):
        self.calls, self.transcript = [], transcript or []

    def __call__(self, req, timeout=None):
        body = json.loads(req.data.decode()) if req.data else None
        path = "/" + req.full_url.split("://", 1)[1].split("/", 1)[1]
        self.calls.append((req.get_method(), path, body))
        if path == "/api/chat/new":
            return io.BytesIO(json.dumps({"id": "chat-1-abc"}).encode())
        if req.get_method() == "GET":
            return io.BytesIO(json.dumps({"transcript": self.transcript}).encode())
        return io.BytesIO(b"{}")


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.slug = store.create_feature("Thing", "build a thing", self.root)
        store.write_file(self.slug, "checklist.md", CHECKLIST, self.root)
        self.proto = Path(tmp.name) / "p.md"
        self.proto.write_text("PROTOCOL", encoding="utf-8")
        self.fake = FakeChat()
        saved = grill._urlopen
        grill._urlopen = self.fake
        self.addCleanup(lambda: setattr(grill, "_urlopen", saved))


class ItemSeedTests(Base):
    def seed(self, node):
        return grill.build_seed(self.slug, self.root, Path(self.root) / "norepos", self.proto, node=node)

    def test_an_item_seed_carries_the_item_its_neighbours_and_the_job(self):
        seed = self.seed("FF-2")
        self.assertIn("checklist item FF-2: Build the core", seed)
        self.assertIn("It waits for: FF-1. Waiting for it: FF-3.", seed)
        self.assertIn("Write server/core/core.py with tests.", seed)
        self.assertIn("propose splitting it into smaller tasks", seed)
        self.assertIn("Filed: no", seed)

    def test_a_filed_item_is_described_as_locked(self):
        self.assertIn("locked", self.seed("FF-1"))

    def test_the_feature_seed_has_no_item_section(self):
        self.assertNotIn("This session is about checklist item", self.seed("feature"))

    def test_an_unknown_item_is_refused(self):
        with self.assertRaisesRegex(grill.GrillError, "no such item FF-9"):
            self.seed("FF-9")


class StartAndStreamTests(Base):
    def test_start_refuses_an_unknown_item_before_any_chat_call(self):
        with self.assertRaisesRegex(grill.GrillError, "no such item"):
            grill.start(self.slug, "FF-9", root=self.root)
        self.assertEqual(self.fake.calls, [])

    def test_start_records_the_item_node(self):
        self.assertEqual(grill.start(self.slug, "FF-3", root=self.root)["node"], "FF-3")

    def test_the_first_turn_of_an_item_session_sends_the_item_seed(self):
        grill.start(self.slug, "FF-2", root=self.root)
        sent = []
        grill._urlopen = lambda req, timeout=None: (sent.append(json.loads(req.data.decode())) or io.BytesIO(b"data: {}\n\n"))
        list(grill.stream_turn(self.slug, "chat-1-abc", None, self.root, Path(self.root) / "norepos"))
        self.assertIn("checklist item FF-2", sent[0]["message"])


class ProposalTests(Base):
    def test_extract_the_only_block(self):
        self.assertEqual(grill.extract_proposal("here you go\n" + BLOCK), {"ops": [{"op": "add", "title": "Docs"}]})

    def test_the_last_block_wins(self):
        newer = BLOCK.replace("Docs", "Newer")
        self.assertEqual(grill.extract_proposal(BLOCK + "\ntext\n" + newer)["ops"][0]["title"], "Newer")

    def test_bad_blocks_are_errors(self):
        for text, msg in [("no block here", "no checklist-diff block"),
                          ("```checklist-diff\n{not json}\n```", "not valid JSON"),
                          ("```checklist-diff\n[1,2]\n```", "no ops"),
                          ('```checklist-diff\n{"ops": []}\n```', "no ops"),
                          ('```json\n{"ops": [{"op": "add"}]}\n```', "no checklist-diff block")]:
            with self.subTest(text=text):
                with self.assertRaisesRegex(grill.GrillError, msg):
                    grill.extract_proposal(text)

    def test_the_newest_proposal_in_a_conversation_is_used(self):
        grill.start(self.slug, "feature", root=self.root)
        self.fake.transcript = [
            {"role": "assistant", "text": BLOCK.replace("Docs", "Old")},
            {"role": "user", "text": "no, change it"},
            {"role": "assistant", "text": BLOCK.replace("Docs", "New") + "\nThat's the plan."},
            {"role": "user", "text": "thanks"},
            {"marker": True, "role": "assistant", "text": BLOCK.replace("Docs", "Marker")},
        ]
        self.assertEqual(grill.proposal_from_session(self.slug, "chat-1-abc", self.root)["ops"][0]["title"], "New")

    def test_no_proposal_yet_and_unknown_sessions(self):
        grill.start(self.slug, "feature", root=self.root)
        self.fake.transcript = [{"role": "assistant", "text": "Q1 - what?"}]
        with self.assertRaisesRegex(grill.GrillError, "no checklist-diff proposal"):
            grill.proposal_from_session(self.slug, "chat-1-abc", self.root)
        with self.assertRaisesRegex(grill.GrillError, "no such grill session"):
            grill.proposal_from_session(self.slug, "chat-9-zzz", self.root)

    def test_the_protocol_documents_the_block_and_the_rules(self):
        text = grill.PROTOCOL_PATH.read_text(encoding="utf-8")
        for needle in ("```checklist-diff", '"op": "split"', "smaller tasks", "instead of a timer", "Filed items"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
