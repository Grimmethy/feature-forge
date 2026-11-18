"""Tests for the piece-level checklist ops: {"op": "remove", "id", "piece"} and {"op": "supersede", "id", "piece", "reason"}.
They close ONE unfiled piece (and the step, when every piece is then done); a piece with a task:, filed: or merged: tag is never touched.
Plain unittest, standard library only."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.core import checklist as cl, store

FIXTURE = """# Checklist: Fixture

- [ ] FF-4 Filing <!-- deps: -->
  - [x] 4a Core <!-- merged: f02d0e5 -->
  - [x] 4b Routes <!-- merged: 762078b -->
  - [ ] 4c Cloud lane <!-- needs: owner decision -->
    own text of 4c
- [ ] FF-5 Mixed <!-- deps: FF-4 -->
  - [x] 5a Done <!-- merged: abc1234 -->
  - [ ] 5b Open
  - [ ] 5c Filed <!-- task: adhoc-9 filed: 2026-11-13 -->
- [ ] FF-6 Filed step <!-- task: adhoc-6 filed: 2026-11-13 -->
  - [x] 6a Done <!-- merged: abc1234 -->
  - [ ] 6b Open
- [ ] FF-7 Single
"""


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.slug = store.create_feature("Fixture", "x", self.root)
        store.write_file(self.slug, "checklist.md", FIXTURE, self.root)

    def text(self):
        return store.read_file(self.slug, "checklist.md", self.root)

    def item(self, item_id):
        return {i["id"]: i for i in cl.items(cl.parse(self.text()))}[item_id]

    def apply(self, *ops):
        return cl.apply(self.slug, {"ops": list(ops)}, None, self.root)

    def refused(self, *ops):
        before = self.text()
        with self.assertRaises(cl.ChecklistError) as ctx:
            self.apply(*ops)
        self.assertEqual(self.text(), before, "a refused op must not write the file")
        return str(ctx.exception)


class DropPieceTests(Base):
    def test_drops_an_untagged_piece_and_ticks_the_step_when_every_other_piece_is_done(self):
        res = self.apply({"op": "remove", "id": "FF-4", "piece": "4c"})
        self.assertIn("drop piece 4c of FF-4", res["results"][0]["summary"])
        self.assertIn("FF-4 ticked", res["results"][0]["summary"])
        it = self.item("FF-4")
        self.assertEqual([p["id"] for p in cl.pieces(it)], ["4a", "4b"])
        self.assertTrue(it["ticked"])
        self.assertEqual(it["meta"].get("manual"), "true")
        self.assertNotIn("own text of 4c", self.text())
        self.assertIn("- [x] 4a Core <!-- merged: f02d0e5 -->", self.text())

    def test_the_step_stays_open_while_another_piece_is_open(self):
        self.apply({"op": "remove", "id": "FF-6", "piece": "6b"})
        self.assertTrue(self.item("FF-6")["ticked"])
        self.apply({"op": "remove", "id": "FF-5", "piece": "5b"})
        it = self.item("FF-5")
        self.assertFalse(it["ticked"])
        self.assertEqual([p["id"] for p in cl.pieces(it)], ["5a", "5c"])

    def test_a_piece_with_a_task_filed_or_merged_tag_is_refused(self):
        self.assertIn("tagged piece 5c was dropped", self.refused({"op": "remove", "id": "FF-5", "piece": "5c"}))
        self.assertIn("tagged piece 4a was dropped", self.refused({"op": "remove", "id": "FF-4", "piece": "4a"}))

    def test_an_unknown_piece_or_item_is_refused_and_so_is_a_missing_piece_label(self):
        self.assertIn("has no piece '4z'", self.refused({"op": "remove", "id": "FF-4", "piece": "4z"}))
        self.assertIn("no such item FF-99", self.refused({"op": "remove", "id": "FF-99", "piece": "4c"}))
        self.assertIn("has no piece ''", self.refused({"op": "remove", "id": "FF-4", "piece": ""}))

    def test_the_last_piece_dropped_leaves_the_step_unticked(self):
        text = "# C\n\n- [ ] FF-1 One <!-- deps: -->\n  - [ ] 1a Only\n"
        store.write_file(self.slug, "checklist.md", text, self.root)
        self.apply({"op": "remove", "id": "FF-1", "piece": "1a"})
        self.assertFalse(self.item("FF-1")["ticked"])
        self.assertEqual(cl.pieces(self.item("FF-1")), [])

    def test_a_filed_step_may_lose_an_untagged_piece_and_is_marked_changed(self):
        self.apply({"op": "remove", "id": "FF-6", "piece": "6b"})
        self.assertIn("changed", self.item("FF-6")["meta"])
        self.assertEqual(self.item("FF-6")["meta"]["task"], "adhoc-6")

    def test_removing_a_whole_step_is_unchanged(self):
        self.apply({"op": "remove", "id": "FF-7"})
        self.assertNotIn("FF-7", self.text())
        self.assertIn("is filed and cannot be removed", self.refused({"op": "remove", "id": "FF-6"}))

    def test_the_result_round_trips_byte_for_byte(self):
        self.apply({"op": "remove", "id": "FF-4", "piece": "4c"})
        self.assertEqual(cl.render(cl.parse(self.text())), self.text())


class SupersedePieceTests(Base):
    def test_ticks_the_piece_by_hand_with_the_reason_and_ticks_the_step(self):
        res = self.apply({"op": "supersede", "id": "FF-4", "piece": "4c", "reason": "superseded by the cloud agent pool"})
        self.assertIn("supersede piece 4c of FF-4", res["results"][0]["summary"])
        it = self.item("FF-4")
        piece = [p for p in cl.pieces(it) if p["id"] == "4c"][0]
        self.assertTrue(piece["ticked"])
        self.assertEqual(piece["meta"], {"manual": "true", "superseded": "superseded by the cloud agent pool", "needs": "owner decision"})
        self.assertTrue(it["ticked"])
        self.assertIn("own text of 4c", self.text())

    def test_the_step_stays_open_while_another_piece_is_open(self):
        self.apply({"op": "supersede", "id": "FF-6", "piece": "6b", "reason": "not needed"})
        self.assertTrue(self.item("FF-6")["ticked"])
        self.apply({"op": "supersede", "id": "FF-5", "piece": "5b", "reason": "not needed"})
        self.assertFalse(self.item("FF-5")["ticked"])

    def test_a_reason_is_required_and_must_be_plain_text(self):
        for reason in (None, "", "   ", "x" * 121, "has <!-- mark", "ends --> here", "a word: with a colon"):
            with self.subTest(reason=reason):
                self.assertIn("reason", self.refused({"op": "supersede", "id": "FF-4", "piece": "4c", "reason": reason}))

    def test_a_tagged_or_ticked_or_unknown_piece_is_refused(self):
        self.assertIn("tagged piece 5c was altered", self.refused({"op": "supersede", "id": "FF-5", "piece": "5c", "reason": "no"}))
        self.assertIn("already ticked", self.refused({"op": "supersede", "id": "FF-4", "piece": "4a", "reason": "no"}))
        self.assertIn("has no piece '4z'", self.refused({"op": "supersede", "id": "FF-4", "piece": "4z", "reason": "no"}))

    def test_preview_reports_the_op_without_writing(self):
        before = self.text()
        res = cl.preview(self.slug, {"ops": [{"op": "supersede", "id": "FF-4", "piece": "4c", "reason": "done elsewhere"}]}, self.root)
        self.assertEqual([r["ok"] for r in res], [True])
        self.assertEqual(self.text(), before)

    def test_a_later_status_sync_keeps_the_hand_ticked_step_and_piece(self):
        from server.core import status
        self.apply({"op": "supersede", "id": "FF-4", "piece": "4c", "reason": "done elsewhere"})
        after = self.text()
        status.sync(self.slug, self.root)
        self.assertEqual(self.text(), after)


class ProtocolTextTests(unittest.TestCase):
    def test_the_grill_protocol_names_both_piece_ops(self):
        doc = (Path(__file__).resolve().parents[1] / "Docs" / "GRILL_PROTOCOL.md").read_text(encoding="utf-8")
        self.assertIn('"op": "remove", "id": "FF-4", "piece": "4c"', doc)
        self.assertIn('"op": "supersede"', doc)


if __name__ == "__main__":
    unittest.main()
