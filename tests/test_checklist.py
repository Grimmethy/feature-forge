"""Tests for server/core/checklist.py: parsing and rendering, the four operations, locks on filed items, ids, cycles
and the all-or-nothing write. Plain unittest, standard library only."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.core import checklist as cl, store

FIXTURE = """# Checklist: Fixture

- [x] FF-1 Scaffold <!-- task: adhoc-1 premium: true cloud: false deps: filed: 2026-11-13 manual: true merged: abc1234 -->
- [ ] FF-2 Second <!-- premium: true cloud: false deps: FF-1 -->
  Full text of the second item.
  Acceptance: it works.
- [ ] FF-3 Third <!-- deps: FF-2 -->
- [ ] FF-4 Fourth <!-- deps: FF-3 -->
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

    def by_id(self):
        return {i["id"]: i for i in cl.items(cl.parse(self.text()))}

    def apply(self, *ops, only=None):
        return cl.apply(self.slug, {"ops": list(ops)}, only, self.root)

    def refused(self, *ops):
        with self.assertRaises(cl.ChecklistError) as ctx:
            self.apply(*ops)
        return str(ctx.exception)


class ParseRenderTests(Base):
    def test_round_trip_is_byte_identical(self):
        self.assertEqual(cl.render(cl.parse(FIXTURE)), FIXTURE)

    def test_the_real_checklist_round_trips(self):
        real = (Path(__file__).resolve().parents[1] / "features" / "feature-forge" / "checklist.md").read_text(encoding="utf-8")
        self.assertEqual(cl.render(cl.parse(real)), real)

    def test_body_lines_belong_to_their_item(self):
        two = cl.items(cl.parse(FIXTURE))[1]
        self.assertEqual(two["body"], ["Full text of the second item.", "Acceptance: it works."])

    def test_locked_means_filed(self):
        items = {i["id"]: i for i in cl.items(cl.parse(FIXTURE))}
        self.assertTrue(cl.is_locked(items["FF-1"]))
        self.assertFalse(cl.is_locked(items["FF-2"]))


PIECES = """# Checklist: Pieces

- [ ] FF-1 Parent <!-- deps: -->
  Some plain text about the parent.
  - [x] 1a First piece <!-- merged: abc1234 -->
  - [ ] 1b Second piece <!-- needs: owner decision -->
  - [X] 1c Third piece, no comment
  More plain text after the pieces.
- [ ] FF-2 Child <!-- deps: FF-1 -->
  not a piece: - [x] inside a sentence
"""


class PieceTests(unittest.TestCase):
    def item(self, text=PIECES, n=0):
        return cl.items(cl.parse(text))[n]

    def test_pieces_are_read_in_order_with_ticks_titles_and_comments(self):
        ps = cl.pieces(self.item())
        self.assertEqual([p["title"] for p in ps], ["First piece", "Second piece", "Third piece, no comment"])
        self.assertEqual([p["id"] for p in ps], ["1a", "1b", "1c"])
        self.assertEqual([p["ticked"] for p in ps], [True, False, True])
        self.assertEqual(ps[0]["meta"], {"merged": "abc1234"})
        self.assertEqual(ps[1]["meta"], {"needs": "owner decision"})
        self.assertEqual(ps[2]["meta"], {})

    def test_plain_body_keeps_only_the_other_lines(self):
        self.assertEqual(cl.plain_body(self.item()), ["Some plain text about the parent.", "More plain text after the pieces."])

    def test_a_pieces_own_text_belongs_to_the_piece_not_the_plain_body(self):
        text = "# C\n\n- [ ] FF-1 P <!-- deps: -->\n  Intro.\n  - [ ] 1a One\n    detail line one\n    detail line two\n  - [x] 1b Two <!-- merged: abc1234 -->\n  Outro.\n"
        it = self.item(text)
        self.assertEqual([(p["id"], p["body"]) for p in cl.pieces(it)], [("1a", "detail line one\ndetail line two"), ("1b", "")])
        self.assertEqual(cl.plain_body(it), ["Intro.", "Outro."])
        self.assertEqual(cl.render(cl.parse(text)), text)

    def test_a_sentence_containing_a_checkbox_is_not_a_piece(self):
        child = self.item(n=1)
        self.assertEqual(cl.pieces(child), [])
        self.assertEqual(cl.plain_body(child), ["not a piece: - [x] inside a sentence"])

    def test_a_piece_without_a_label_has_an_empty_id_and_keeps_its_whole_text(self):
        item = cl.items(cl.parse("# C\n\n- [ ] FF-1 P <!-- deps: -->\n  - [ ] Third piece alone\n  - [x] 12b2 Odd label\n  - [ ] fixes the lowercase case\n  - [ ] 7 Plain number\n"))[0]
        self.assertEqual([(p["id"], p["title"]) for p in cl.pieces(item)],
                         [("", "Third piece alone"), ("12b2", "Odd label"), ("", "fixes the lowercase case"), ("7", "Plain number")])

    def test_an_item_with_no_body_has_no_pieces(self):
        self.assertEqual(cl.pieces(cl.items(cl.parse(FIXTURE))[2]), [])

    def test_pieces_do_not_change_the_item_list_or_the_round_trip(self):
        self.assertEqual([i["id"] for i in cl.items(cl.parse(PIECES))], ["FF-1", "FF-2"])
        self.assertEqual(cl.render(cl.parse(PIECES)), PIECES)

    def test_editing_an_item_keeps_a_change_ops_body_exactly(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        slug = store.create_feature("P", "x", root)
        store.write_file(slug, "checklist.md", PIECES, root)
        cl.apply(slug, {"ops": [{"op": "change", "id": "FF-2", "title": "Child renamed"}]}, None, root)
        text = store.read_file(slug, "checklist.md", root)
        self.assertIn("  - [x] 1a First piece <!-- merged: abc1234 -->", text)
        self.assertEqual(len(cl.pieces(cl.items(cl.parse(text))[0])), 3)


class PieceOpTests(Base):
    def pieces_of(self, item_id):
        return cl.pieces(self.by_id()[item_id])

    def test_add_with_pieces_labels_them_from_the_new_item_number(self):
        self.apply({"op": "add", "title": "Fifth", "body": "why", "deps": ["FF-4"],
                    "pieces": ["First task", {"title": "Second task", "body": "Edit core.py.\nAcceptance: tests pass."}]})
        ps = self.pieces_of("FF-5")
        self.assertEqual([(p["id"], p["title"], p["ticked"]) for p in ps], [("5a", "First task", False), ("5b", "Second task", False)])
        self.assertEqual(ps[1]["body"], "Edit core.py.\nAcceptance: tests pass.")
        self.assertEqual(ps[0]["body"], "")
        self.assertEqual(cl.plain_body(self.by_id()["FF-5"]), ["why"])
        self.assertIn("  - [ ] 5b Second task\n    Edit core.py.\n    Acceptance: tests pass.", self.text())

    def test_the_rendered_result_round_trips_and_is_stable(self):
        self.apply({"op": "add", "title": "Fifth", "pieces": [{"title": "A", "body": "text"}, "B"]})
        text = self.text()
        self.assertEqual(cl.render(cl.parse(text)), text)

    def test_change_appends_pieces_with_the_next_free_labels_and_leaves_existing_ones(self):
        self.apply({"op": "add", "title": "Fifth", "pieces": ["A", "B"]})
        before = [dict(p) for p in self.pieces_of("FF-5")]
        self.apply({"op": "change", "id": "FF-5", "pieces": [{"title": "C", "body": "later"}]})
        ps = self.pieces_of("FF-5")
        self.assertEqual([p["id"] for p in ps], ["5a", "5b", "5c"])
        self.assertEqual(ps[:2], before)
        self.assertEqual(ps[2]["body"], "later")

    def test_labels_skip_taken_ones(self):
        store.write_file(self.slug, "checklist.md", FIXTURE + "  - [x] 4a Old <!-- merged: abc1234 -->\n  - [ ] 4c Odd\n", self.root)
        self.apply({"op": "change", "id": "FF-4", "pieces": ["New one", "New two"]})
        self.assertEqual([p["id"] for p in self.pieces_of("FF-4")], ["4a", "4c", "4b", "4d"])

    def test_a_filed_item_can_gain_pieces_and_is_marked_changed(self):
        self.apply({"op": "change", "id": "FF-1", "pieces": ["Late task"]})
        it = self.by_id()["FF-1"]
        self.assertEqual([p["id"] for p in cl.pieces(it)], ["1a"])
        self.assertTrue(it["meta"]["changed"])
        self.assertEqual(it["meta"]["task"], "adhoc-1")

    def test_split_parts_can_carry_pieces(self):
        self.apply({"op": "split", "id": "FF-3", "into": [{"title": "Part one", "pieces": ["x"]}, {"title": "Part two"}]})
        self.assertEqual([p["id"] for p in self.pieces_of("FF-5")], ["5a"])
        self.assertEqual(self.pieces_of("FF-6"), [])

    def test_bad_pieces_are_refused_and_nothing_is_written(self):
        for bad in ([], "title", [{"body": "no title"}], [""], ["a --> b"], [{"title": "ok", "body": "x --> y"}], [{"title": "ok", "body": "z" * 2001}],
                    [5], ["x"] * 27):
            with self.subTest(pieces=bad if len(str(bad)) < 40 else "long"):
                self.refused({"op": "add", "title": "T", "pieces": bad})
        self.assertEqual(self.text(), FIXTURE)

    def test_26_pieces_fit_and_the_next_one_does_not(self):
        self.apply({"op": "add", "title": "Big", "pieces": [f"p{n}" for n in range(26)]})
        self.assertEqual(len(self.pieces_of("FF-5")), 26)
        self.assertIn("at most 26", self.refused({"op": "change", "id": "FF-5", "pieces": ["one too many"]}))


class UpdatePieceTests(unittest.TestCase):
    TEXT = "# C\n\n- [ ] FF-1 P <!-- deps: -->\n  Intro.\n  - [ ] 1a One\n    own text\n  - [x] 1b Two <!-- merged: abc1234 -->\n  Outro.\n"

    def run_update(self, *a, **k):
        entries = cl.parse(self.TEXT)
        item = cl.items(entries)[0]
        ok = cl.update_piece(item, *a, **k)
        return ok, item, cl.render(entries)

    def test_meta_is_merged_into_the_pieces_comment(self):
        ok, item, text = self.run_update("1b", meta={"took": "7"})
        self.assertTrue(ok)
        self.assertIn("  - [x] 1b Two <!-- merged: abc1234 took: 7 -->", text)

    def test_a_piece_with_no_comment_gets_one_and_keeps_its_own_text(self):
        ok, item, text = self.run_update("1a", meta={"task": "t-1", "filed": "2026-11-14T01:00:00Z"})
        self.assertIn("  - [ ] 1a One <!-- task: t-1 filed: 2026-11-14T01:00:00Z -->\n    own text\n", text)
        self.assertEqual(cl.pieces(item)[0]["body"], "own text")

    def test_ticking_sets_the_box_and_nothing_else(self):
        ok, item, text = self.run_update("1a", ticked=True)
        self.assertIn("  - [x] 1a One\n    own text\n", text)
        ok, item, text = self.run_update("1b", ticked=False)
        self.assertIn("  - [ ] 1b Two <!-- merged: abc1234 -->", text)

    def test_only_the_named_piece_and_no_other_line_changes(self):
        ok, item, text = self.run_update("1a", meta={"task": "t-1"})
        self.assertEqual(text.replace(" <!-- task: t-1 -->", ""), self.TEXT)

    def test_an_unknown_piece_changes_nothing(self):
        ok, item, text = self.run_update("1z", meta={"task": "t"})
        self.assertFalse(ok)
        self.assertEqual(text, self.TEXT)

    def test_an_unlabelled_piece_cannot_be_addressed(self):
        entries = cl.parse("# C\n\n- [ ] FF-1 P <!-- deps: -->\n  - [ ] fixes things\n")
        self.assertFalse(cl.update_piece(cl.items(entries)[0], "", meta={"task": "t"}))


class AddTests(Base):
    def test_add_gets_the_next_id_and_keeps_the_rest_untouched(self):
        self.apply({"op": "add", "title": "Fifth", "body": "line one\nline two", "deps": ["FF-4"], "premium": True})
        text = self.text()
        self.assertIn("- [ ] FF-5 Fifth <!-- premium: true deps: FF-4 -->\n  line one\n  line two", text)
        self.assertTrue(text.startswith(FIXTURE.rstrip("\n")))

    def test_add_validation(self):
        for bad in [{"title": ""}, {"title": "x" * 200}, {"title": "a --> b"}, {"title": "ok", "deps": ["FF-99"]},
                    {"title": "ok", "deps": ["nope"]}, {"title": "ok", "body": "x --> y"}]:
            with self.subTest(op=bad):
                self.refused(dict(bad, op="add"))
        self.assertEqual(self.text(), FIXTURE)


class ChangeTests(Base):
    def test_change_title_body_and_deps_of_an_unfiled_item(self):
        self.apply({"op": "change", "id": "FF-3", "title": "Third, better", "body": "new body", "deps": ["FF-1"]})
        it = self.by_id()["FF-3"]
        self.assertEqual((it["title"], it["body"], it["meta"]["deps"]), ("Third, better", ["new body"], "FF-1"))
        self.assertNotIn("changed", it["meta"])

    def test_changing_one_key_leaves_the_others(self):
        self.apply({"op": "change", "id": "FF-2", "title": "Second, renamed"})
        it = self.by_id()["FF-2"]
        self.assertEqual(it["body"], ["Full text of the second item.", "Acceptance: it works."])
        self.assertEqual(it["meta"]["deps"], "FF-1")

    def test_a_filed_item_can_change_but_is_marked_and_keeps_its_task(self):
        self.apply({"op": "change", "id": "FF-1", "title": "Scaffold v2"})
        it = self.by_id()["FF-1"]
        self.assertEqual(it["title"], "Scaffold v2")
        self.assertTrue(it["meta"]["changed"])
        self.assertEqual((it["meta"]["task"], it["meta"]["filed"], it["meta"]["merged"]), ("adhoc-1", "2026-11-13", "abc1234"))
        self.assertTrue(it["ticked"])

    def test_unknown_item_and_cycles_are_refused(self):
        self.assertIn("no such item", self.refused({"op": "change", "id": "FF-9", "title": "x"}))
        self.assertIn("circular", self.refused({"op": "change", "id": "FF-2", "deps": ["FF-4"]}))
        self.assertIn("itself", self.refused({"op": "change", "id": "FF-3", "deps": ["FF-3"]}))


class RemoveTests(Base):
    def test_remove_repoints_dependents_to_the_removed_items_own_deps(self):
        self.apply({"op": "remove", "id": "FF-3"})
        items = self.by_id()
        self.assertNotIn("FF-3", items)
        self.assertEqual(items["FF-4"]["meta"]["deps"], "FF-2")

    def test_a_filed_item_cannot_be_removed(self):
        self.assertIn("filed", self.refused({"op": "remove", "id": "FF-1"}))


class SplitTests(Base):
    def split(self, item_id="FF-3", parts=None, **kw):
        parts = parts or [{"title": "Third a"}, {"title": "Third b", "body": "b body"}]
        return self.apply(dict({"op": "split", "id": item_id, "into": parts}, **kw))

    def test_split_chains_the_parts_and_repoints_dependents(self):
        self.split()
        items = self.by_id()
        self.assertNotIn("FF-3", items)
        self.assertEqual((items["FF-5"]["title"], items["FF-5"]["meta"]["deps"]), ("Third a", "FF-2"))
        self.assertEqual((items["FF-6"]["title"], items["FF-6"]["meta"]["deps"]), ("Third b", "FF-5"))
        self.assertEqual(items["FF-4"]["meta"]["deps"], "FF-6")

    def test_parts_sit_where_the_old_item_was(self):
        self.split()
        ids = [i["id"] for i in cl.items(cl.parse(self.text()))]
        self.assertEqual(ids, ["FF-1", "FF-2", "FF-5", "FF-6", "FF-4"])

    def test_the_highest_id_is_never_reused(self):
        self.split("FF-4", [{"title": "A"}, {"title": "B"}])
        ids = [i["id"] for i in cl.items(cl.parse(self.text()))]
        self.assertEqual(ids, ["FF-1", "FF-2", "FF-3", "FF-5", "FF-6"])

    def test_parts_inherit_premium_and_cloud_flags(self):
        self.split("FF-2", [{"title": "A"}, {"title": "B", "premium": False}])
        items = self.by_id()
        self.assertEqual((items["FF-5"]["meta"]["premium"], items["FF-5"]["meta"]["cloud"]), ("true", "false"))
        self.assertEqual(items["FF-6"]["meta"]["premium"], "false")

    def test_split_refusals(self):
        self.assertIn("filed", self.refused({"op": "split", "id": "FF-1", "into": [{"title": "a"}, {"title": "b"}]}))
        self.assertIn("at least two", self.refused({"op": "split", "id": "FF-3", "into": [{"title": "a"}]}))
        self.assertIn("being split", self.refused({"op": "split", "id": "FF-3", "into": [{"title": "a"}, {"title": "b", "deps": ["FF-3"]}]}))
        self.assertEqual(self.text(), FIXTURE)


class ApplyTests(Base):
    def test_all_or_nothing(self):
        msg = self.refused({"op": "add", "title": "good"}, {"op": "change", "id": "FF-99", "title": "bad"})
        self.assertIn("op 1", msg)
        self.assertEqual(self.text(), FIXTURE)

    def test_only_selected_ops_are_applied(self):
        r = self.apply({"op": "add", "title": "one"}, {"op": "add", "title": "two"}, only=[1])
        self.assertEqual([x["ok"] for x in r["results"]], [None, True])
        self.assertEqual([i["title"] for i in cl.items(cl.parse(self.text()))][-1], "two")
        self.assertNotIn("one", self.text().split("FF-4")[1])

    def test_nothing_selected_and_empty_proposals_are_errors(self):
        with self.assertRaisesRegex(cl.ChecklistError, "nothing selected"):
            self.apply({"op": "add", "title": "x"}, only=[])
        with self.assertRaisesRegex(cl.ChecklistError, "no ops"):
            cl.apply(self.slug, {"ops": []}, None, self.root)
        with self.assertRaisesRegex(cl.ChecklistError, "no ops"):
            cl.preview(self.slug, {}, self.root)

    def test_a_proposal_that_is_not_an_object_is_an_error_not_a_crash(self):
        for bad in ["text", ["ops"], 5, None, True]:
            with self.subTest(proposal=bad):
                with self.assertRaisesRegex(cl.ChecklistError, "no ops"):
                    cl.preview(self.slug, bad, self.root)
                with self.assertRaisesRegex(cl.ChecklistError, "no ops"):
                    cl.apply(self.slug, bad, None, self.root)

    def test_unknown_op_is_refused(self):
        self.assertIn("unknown op", self.refused({"op": "explode"}))

    def test_a_history_copy_is_kept(self):
        self.apply({"op": "add", "title": "x"})
        self.assertEqual(len(list((self.root / self.slug / ".history").iterdir())), 1)

    def test_preview_reports_each_op_without_writing(self):
        r = cl.preview(self.slug, {"ops": [{"op": "add", "title": "x"}, {"op": "remove", "id": "FF-1"}]}, self.root)
        self.assertEqual([x["ok"] for x in r], [True, False])
        self.assertEqual(self.text(), FIXTURE)

    def test_the_store_still_reads_the_result(self):
        self.apply({"op": "add", "title": "x", "deps": ["FF-4"]})
        items = store.parse_checklist(self.slug, self.root)
        self.assertEqual([i["id"] for i in items], ["FF-1", "FF-2", "FF-3", "FF-4", "FF-5"])
        self.assertEqual(store.derive_status(items), "Building")


if __name__ == "__main__":
    unittest.main()
