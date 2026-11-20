"""Tests for server/core/status.py: finding a task in a project's queue folders, ticking merged items, the timing log and the
cases that must not tick. Plain unittest, standard library only."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.core import checklist, status, store

CHECKLIST = """# Checklist: Thing

- [x] FF-1 By hand <!-- manual: true merged: abc1234 -->
- [ ] FF-2 Merged one <!-- task: t-merged premium: true filed: 2026-11-14T04:00:00Z deps: -->
- [ ] FF-3 Still building <!-- task: t-review filed: 2026-11-14T04:00:00Z deps: -->
- [ ] FF-4 Gone <!-- task: t-gone filed: 2026-11-14T04:00:00Z deps: -->
- [ ] FF-5 Done without a merge <!-- task: t-nomerge filed: 2026-11-14T04:00:00Z deps: -->
- [ ] FF-6 Archived <!-- task: t-arch filed: 2026-11-14T04:00:00Z deps: -->
- [ ] FF-7 Old date only <!-- task: t-old filed: 2026-11-13 deps: -->
- [ ] FF-8 Not filed <!-- deps: -->
"""


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = self.tmp / "features"
        self.pipe = self.tmp / "pipe"
        for s in ("done", "review", "done/_archived_no_action"):
            (self.pipe / "queue" / s).mkdir(parents=True)
        self.put("done", "t-merged", {"status": "done", "mergedAt": "2026-11-14T05:37:30.123456+00:00"})
        self.put("review", "t-review", {"status": "review"})
        self.put("done", "t-nomerge", {"status": "done"})
        self.put("done/_archived_no_action", "t-arch", {"status": "done", "mergedAt": "2026-11-14T05:00:00+00:00"})
        self.put("done", "t-old", {"status": "done", "mergedAt": "2026-11-14T05:00:00+00:00",
                                   "history": [{"stage": "approved", "at": "2026-11-14T04:00:00"}, {"stage": "merged", "at": "2026-11-14T05:00:00"}]})
        reg = self.tmp / "projects.json"
        reg.write_text(json.dumps([{"repoRoot": "/r/alpha", "pipelineDir": str(self.pipe), "domainsPath": "x", "label": "alpha"}]))
        saved = os.environ.get("FEATUREFORGE_PROJECTS")
        os.environ["FEATUREFORGE_PROJECTS"] = str(reg)
        self.addCleanup(lambda: os.environ.__setitem__("FEATUREFORGE_PROJECTS", saved) if saved else os.environ.pop("FEATUREFORGE_PROJECTS", None))
        self.slug = store.create_feature("Thing", "x\nrepo: alpha", self.root)
        store.write_file(self.slug, "checklist.md", CHECKLIST, self.root)

    def put(self, state, tid, rec):
        (self.pipe / "queue" / state / f"{tid}.json").write_text(json.dumps(rec))

    def items(self):
        return {i["id"]: i for i in checklist.items(checklist.parse(store.read_file(self.slug, "checklist.md", self.root)))}


class SyncTests(Base):
    def test_a_merged_task_ticks_its_item_with_the_time_and_minutes(self):
        r = status.sync(self.slug, self.root)
        self.assertEqual(r["ticked"], ["FF-2", "FF-7"])
        it = self.items()["FF-2"]
        self.assertTrue(it["ticked"])
        self.assertEqual((it["meta"]["merged"], it["meta"]["took"]), ("2026-11-14T05:37:30Z", "98"))

    def test_an_old_date_only_filing_falls_back_to_the_records_first_history_time(self):
        status.sync(self.slug, self.root)
        self.assertEqual(self.items()["FF-7"]["meta"]["took"], "60")

    def test_states_are_reported_for_every_filed_item(self):
        s = status.sync(self.slug, self.root)["states"]
        self.assertEqual(s["FF-2"]["state"], "merged")
        self.assertEqual(s["FF-3"], {"state": "review", "status": "review", "reason": "review"})
        self.assertEqual(s["FF-4"]["state"], "missing")
        self.assertEqual(s["FF-5"]["state"], "done")
        self.assertEqual(s["FF-6"]["state"], "archived")
        self.assertNotIn("FF-8", s)
        self.assertNotIn("FF-1", s)

    def test_nothing_else_is_ticked(self):
        status.sync(self.slug, self.root)
        items = self.items()
        for i in ("FF-3", "FF-4", "FF-5", "FF-6", "FF-8"):
            self.assertFalse(items[i]["ticked"], i)
        self.assertEqual(items["FF-1"]["meta"], {"manual": "true", "merged": "abc1234"})

    def test_a_second_sync_changes_nothing_and_logs_nothing_more(self):
        status.sync(self.slug, self.root)
        before = store.read_file(self.slug, "checklist.md", self.root)
        log = (self.root / ".timing.jsonl").read_text()
        self.assertEqual(status.sync(self.slug, self.root)["ticked"], [])
        self.assertEqual(store.read_file(self.slug, "checklist.md", self.root), before)
        self.assertEqual((self.root / ".timing.jsonl").read_text(), log)

    def test_the_timing_log_has_one_row_per_ticked_item(self):
        status.sync(self.slug, self.root)
        rows = [json.loads(l) for l in (self.root / ".timing.jsonl").read_text().splitlines()]
        self.assertEqual([r["item"] for r in rows], ["FF-2", "FF-7"])
        self.assertEqual((rows[0]["minutes"], rows[0]["premium"], rows[0]["repo"], rows[0]["task"]), (98, True, "alpha", "t-merged"))

    def test_no_filed_items_or_no_repo_do_nothing(self):
        store.write_file(self.slug, "checklist.md", "# Checklist: x\n\n- [ ] FF-1 a <!-- deps: -->\n", self.root)
        self.assertEqual(status.sync(self.slug, self.root), {"ticked": [], "states": {}, "ticked_by_reason": {}})
        store.write_file(self.slug, "checklist.md", CHECKLIST, self.root)
        store.write_file(self.slug, "request.md", "# Thing\n\nno repo", self.root)
        from unittest import mock
        with mock.patch.object(status.filing, "all_projects", return_value=[]):      # no project holds any task
            r = status.sync(self.slug, self.root)
        self.assertEqual((r["ticked"], r["ticked_by_reason"]), ([], {}))
        self.assertTrue(all(s["state"] == "missing" for s in r["states"].values()))
        self.assertFalse(self.items()["FF-2"]["ticked"])

    def test_a_history_copy_is_kept_when_it_writes(self):
        status.sync(self.slug, self.root)
        self.assertTrue(list((self.root / self.slug / ".history").iterdir()))


PIECES_TEXT = """# Checklist: Thing

- [ ] FF-1 Step <!-- premium: true filed: 2026-11-14T04:00:00Z deps: -->
  Context.
  - [ ] 1a First <!-- task: tp-a filed: 2026-11-14T04:00:00Z -->
    own text of the first
  - [ ] 1b Second <!-- task: tp-b filed: 2026-11-14T04:30:00Z -->
  - [ ] 1c Third <!-- task: tp-c filed: 2026-11-14T05:00:00Z -->
- [ ] FF-2 Unfiled pieces <!-- deps: -->
  - [x] 2a By hand <!-- merged: abc1234 -->
  - [ ] 2b Not filed
"""


class PieceSyncTests(Base):
    def setUp(self):
        super().setUp()
        store.write_file(self.slug, "checklist.md", PIECES_TEXT, self.root)
        self.put("done", "tp-a", {"status": "done", "mergedAt": "2026-11-14T04:20:00+00:00"})
        self.put("review", "tp-b", {"status": "review"})
        self.put("review", "tp-c", {"status": "review"})

    def piece(self, item, pid):
        return {p["id"]: p for p in checklist.pieces(self.items()[item])}[pid]

    def merge_all(self):
        (self.pipe / "queue" / "review" / "tp-b.json").rename(self.pipe / "queue" / "done" / "tp-b.json")
        (self.pipe / "queue" / "review" / "tp-c.json").rename(self.pipe / "queue" / "done" / "tp-c.json")
        self.put("done", "tp-b", {"status": "done", "mergedAt": "2026-11-14T05:10:00+00:00"})
        self.put("done", "tp-c", {"status": "done", "mergedAt": "2026-11-14T06:00:00+00:00"})

    def test_a_merged_pieces_task_ticks_the_piece_with_time_and_minutes_and_keeps_its_text(self):
        r = status.sync(self.slug, self.root)
        self.assertEqual(r["ticked"], ["FF-1/1a"])
        a = self.piece("FF-1", "1a")
        self.assertTrue(a["ticked"])
        self.assertEqual((a["meta"]["merged"], a["meta"]["took"], a["meta"]["task"]), ("2026-11-14T04:20:00Z", "20", "tp-a"))
        self.assertEqual(a["body"], "own text of the first")
        self.assertFalse(self.items()["FF-1"]["ticked"])

    def test_states_are_keyed_by_the_piece(self):
        s = status.sync(self.slug, self.root)["states"]
        self.assertEqual(s["FF-1/1a"]["state"], "merged")
        self.assertEqual(s["FF-1/1b"], {"state": "review", "status": "review", "reason": "review"})
        self.assertNotIn("FF-1", s)                                  # the step itself has no task
        self.assertNotIn("FF-2/2b", s)                               # an unfiled piece has none either

    def test_pieces_that_are_not_merged_stay_open(self):
        status.sync(self.slug, self.root)
        self.assertFalse(self.piece("FF-1", "1b")["ticked"])
        self.assertFalse(self.piece("FF-1", "1c")["ticked"])
        self.assertNotIn("merged", self.piece("FF-1", "1b")["meta"])

    def test_the_step_is_ticked_when_its_last_piece_merges(self):
        status.sync(self.slug, self.root)
        self.merge_all()
        r = status.sync(self.slug, self.root)
        self.assertEqual(r["ticked"], ["FF-1/1b", "FF-1/1c", "FF-1"])
        it = self.items()["FF-1"]
        self.assertTrue(it["ticked"])
        self.assertEqual(it["meta"]["merged"], "2026-11-14T06:00:00Z")           # the latest piece merge

    def test_the_step_is_not_ticked_while_a_piece_is_open(self):
        (self.pipe / "queue" / "review" / "tp-b.json").rename(self.pipe / "queue" / "done" / "tp-b.json")
        self.put("done", "tp-b", {"status": "done", "mergedAt": "2026-11-14T05:10:00+00:00"})
        status.sync(self.slug, self.root)
        self.assertFalse(self.items()["FF-1"]["ticked"])

    def test_one_timing_row_per_piece_and_none_for_the_step(self):
        status.sync(self.slug, self.root)
        self.merge_all()
        status.sync(self.slug, self.root)
        rows = [json.loads(l) for l in (self.root / ".timing.jsonl").read_text().splitlines()]
        self.assertEqual([r["item"] for r in rows], ["FF-1/1a", "FF-1/1b", "FF-1/1c"])
        self.assertEqual([r["minutes"] for r in rows], [20, 40, 60])
        self.assertTrue(all(r["premium"] for r in rows))                         # the step's premium flag

    def test_a_second_sync_changes_nothing(self):
        status.sync(self.slug, self.root)
        self.merge_all()
        status.sync(self.slug, self.root)
        before, log = store.read_file(self.slug, "checklist.md", self.root), (self.root / ".timing.jsonl").read_text()
        self.assertEqual(status.sync(self.slug, self.root)["ticked"], [])
        self.assertEqual((store.read_file(self.slug, "checklist.md", self.root), (self.root / ".timing.jsonl").read_text()), (before, log))

    def test_hand_ticked_and_unfiled_pieces_are_left_alone(self):
        status.sync(self.slug, self.root)
        self.assertEqual(self.piece("FF-2", "2a")["meta"], {"merged": "abc1234"})
        self.assertFalse(self.items()["FF-2"]["ticked"])

    def test_a_vanished_piece_task_is_reported_missing_and_nothing_is_ticked(self):
        (self.pipe / "queue" / "review" / "tp-b.json").unlink()
        s = status.sync(self.slug, self.root)["states"]
        self.assertEqual(s["FF-1/1b"]["state"], "missing")
        self.assertFalse(self.piece("FF-1", "1b")["ticked"])

    def test_a_piece_finished_without_a_merge_is_not_ticked(self):
        (self.pipe / "queue" / "review" / "tp-b.json").unlink()
        self.put("done", "tp-b", {"status": "done"})
        r = status.sync(self.slug, self.root)
        self.assertEqual(r["states"]["FF-1/1b"]["state"], "done")
        self.assertNotIn("FF-1/1b", r["ticked"])

    def test_the_checklist_round_trips_after_a_piece_sync(self):
        status.sync(self.slug, self.root)
        text = store.read_file(self.slug, "checklist.md", self.root)
        self.assertEqual(checklist.render(checklist.parse(text)), text)


class FindTaskTests(Base):
    def test_finds_a_drafting_task_in_an_instance_folder(self):
        d = self.pipe / "queue" / "drafting" / "inst1"
        d.mkdir(parents=True)
        (d / "t-draft.json").write_text(json.dumps({"status": "drafting"}))
        self.assertEqual(status.find_task(str(self.pipe), "t-draft")[0], "drafting")

    def test_a_dated_archive_is_searched(self):
        d = self.pipe / "queue" / "done" / "_archived" / "2026-10"
        d.mkdir(parents=True)
        (d / "t-dated.json").write_text(json.dumps({"status": "done"}))
        self.assertEqual(status.find_task(str(self.pipe), "t-dated")[0], "archived")

    def test_unknown_is_none(self):
        self.assertEqual(status.find_task(str(self.pipe), "nope"), (None, None))


HUB_TEXT = """# Checklist: Thing

- [ ] FF-1 Parent <!-- task: th-parent filed: 2026-11-14T04:00:00Z deps: -->
- [ ] FF-2 Noop task <!-- task: th-noop filed: 2026-11-14T04:00:00Z deps: -->
- [ ] FF-3 Pending task <!-- task: th-pend filed: 2026-11-14T04:00:00Z deps: -->
- [ ] FF-4 Coordinating parent <!-- task: th-coord filed: 2026-11-14T04:00:00Z deps: -->
"""


class HubTests(Base):
    """Fixture records for the noop, pending-merge, archived-hub and coordinating-parent dispositions.
    The field names (terminalDisposition, subTasks, hubLabel) follow the task text and are not yet confirmed against live records."""

    def setUp(self):
        super().setUp()
        (self.pipe / "queue" / "coordinating").mkdir(parents=True, exist_ok=True)
        store.write_file(self.slug, "checklist.md", HUB_TEXT, self.root)
        self.put("done/_archived_no_action", "th-parent", {"status": "done", "hubLabel": "HUB0396",
                 "subTasks": ["th-p1", "th-p2"]})
        self.put("done", "th-p1", {"status": "done", "terminalDisposition": "noop"})
        self.put("done", "th-p2", {"status": "done", "mergedAt": "2026-11-14T05:00:00+00:00"})
        self.put("done", "th-noop", {"status": "done", "terminalDisposition": "noop"})
        self.put("done", "th-pend", {"status": "done", "terminalDisposition": "pending-merge"})
        self.put("coordinating", "th-coord", {"status": "coordinating", "hubLabel": "HUB0401", "subTasks": []})

    def test_hub_noop_piece_still_ticks(self):
        r = status.sync(self.slug, self.root)
        self.assertIn("FF-1", r["ticked"])
        it = self.items()["FF-1"]
        self.assertTrue(it["ticked"])
        self.assertEqual(it["meta"]["merged"], "2026-11-14T05:00:00Z")
        self.assertIn("HUB0396", r["states"]["FF-1"]["reason"])
        self.assertEqual(r["states"]["FF-1"]["state"], "hub HUB0396, 2 of 2 pieces done")

    def test_hub_with_a_pending_merge_piece_does_not_tick(self):
        self.put("done", "th-p2", {"status": "done", "terminalDisposition": "pending-merge"})
        r = status.sync(self.slug, self.root)
        self.assertNotIn("FF-1", r["ticked"])
        self.assertFalse(self.items()["FF-1"]["ticked"])
        self.assertIn("th-p2", r["states"]["FF-1"]["reason"])

    def test_hub_with_a_missing_piece_names_it_and_does_not_tick(self):
        (self.pipe / "queue" / "done" / "th-p1.json").unlink()
        r = status.sync(self.slug, self.root)
        self.assertNotIn("FF-1", r["ticked"])
        self.assertIn("th-p1", r["states"]["FF-1"]["reason"])

    def test_hub_with_one_open_piece_shows_progress_and_does_not_tick(self):
        self.put("done", "th-p1", {"status": "review"})
        self.put("done/_archived_no_action", "th-parent", {"status": "done", "hubLabel": "HUB0396",
                 "subTasks": ["th-p1", "th-p2", "th-p3"]})
        self.put("done", "th-p3", {"status": "done", "mergedAt": "2026-11-14T05:00:00+00:00"})
        (self.pipe / "queue" / "done" / "th-p1.json").unlink()
        self.put("review", "th-p1", {"status": "review"})
        r = status.sync(self.slug, self.root)
        self.assertEqual(r["states"]["FF-1"]["state"], "hub HUB0396, 2 of 3 pieces done")
        self.assertNotIn("FF-1", r["ticked"])

    def test_noop_task_ticks_as_no_change_needed(self):
        r = status.sync(self.slug, self.root)
        self.assertIn("FF-2", r["ticked"])
        it = self.items()["FF-2"]
        self.assertEqual(it["meta"]["merged"], "noop")
        self.assertEqual(r["states"]["FF-2"]["state"], "no change needed")
        self.assertIn("no change needed", r["states"]["FF-2"]["reason"])

    def test_pending_merge_task_is_labelled_awaiting_merge_and_not_ticked(self):
        r = status.sync(self.slug, self.root)
        self.assertEqual(r["states"]["FF-3"]["state"], "awaiting merge")
        self.assertNotIn("FF-3", r["ticked"])
        self.assertFalse(self.items()["FF-3"]["ticked"])

    def test_coordinating_parent_with_empty_subtasks_is_labelled_and_not_ticked(self):
        r = status.sync(self.slug, self.root)
        self.assertEqual(r["states"]["FF-4"]["state"], "coordinating, no pieces recorded")
        self.assertNotIn("FF-4", r["ticked"])
        self.assertFalse(self.items()["FF-4"]["ticked"])

    def test_ticked_by_reason_counts_each_tick(self):
        r = status.sync(self.slug, self.root)
        self.assertEqual(sum(r["ticked_by_reason"].values()), len(r["ticked"]))
        self.assertEqual(r["ticked_by_reason"].get("hub"), 1)
        self.assertEqual(r["ticked_by_reason"].get("no change needed"), 1)


if __name__ == "__main__":
    unittest.main()
