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
        self.assertEqual(s["FF-3"], {"state": "review", "status": "review"})
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
        self.assertEqual(status.sync(self.slug, self.root), {"ticked": [], "states": {}})
        store.write_file(self.slug, "checklist.md", CHECKLIST, self.root)
        store.write_file(self.slug, "request.md", "# Thing\n\nno repo", self.root)
        self.assertEqual(status.sync(self.slug, self.root), {"ticked": [], "states": {}})
        self.assertFalse(self.items()["FF-2"]["ticked"])

    def test_a_history_copy_is_kept_when_it_writes(self):
        status.sync(self.slug, self.root)
        self.assertTrue(list((self.root / self.slug / ".history").iterdir()))


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


if __name__ == "__main__":
    unittest.main()
