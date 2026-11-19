"""Tests for server/core/manager.py: the pure decision table, then ticks over a temp project queue with a fake queue script and
dashboard: modes, the write-ahead ledger, no repeats, each action. Plain unittest, standard library only."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.core import checklist, filing, manager, store

NOW = datetime(2026, 11, 14, 12, 0, 0, tzinfo=timezone.utc)


class DecideTests(unittest.TestCase):
    def d(self, label, rec=None, age=5, meta=None, deadline=None):
        return manager.decide(label, rec, age, meta or {}, deadline)["outcome"]

    def test_the_closed_outcomes(self):
        self.assertEqual(self.d(None), "refile")
        self.assertEqual(self.d("done", {"mergedAt": "x"}), "tick")
        self.assertEqual(self.d("done", {}), "flag")
        self.assertEqual(self.d("archived"), "flag")
        self.assertEqual(self.d("review"), "ok")
        self.assertEqual(self.d("approved", age=9999), "ok")

    def test_bump_only_when_unclaimed_long_enough_not_premium_and_not_bumped_before(self):
        self.assertEqual(self.d("pending", age=31), "bump")
        self.assertEqual(self.d("adhoc", age=31), "bump")
        self.assertEqual(self.d("pending", age=29), "ok")
        self.assertEqual(self.d("pending", age=999, meta={"premium": "true"}), "ok")
        self.assertEqual(self.d("pending", age=999, meta={"bumped": "2026-11-14T00:00:00Z"}), "ok")
        self.assertEqual(self.d("pending", age=None), "ok")

    def test_stalled_states_are_flagged_after_two_hours(self):
        for label in ("blocked", "needs-clarification", "awaiting-confirm"):
            self.assertEqual(self.d(label, age=121), "flag", label)
            self.assertEqual(self.d(label, age=119), "ok", label)

    def test_a_deadline_flags_a_moving_task_that_runs_over(self):
        self.assertEqual(self.d("review", age=61, deadline=60), "flag")
        self.assertEqual(self.d("review", age=59, deadline=60), "ok")
        self.assertEqual(self.d("review", age=999, deadline=None), "ok")


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = self.tmp / "features"
        self.pipe = self.tmp / "pipe"
        for s in ("adhoc", "pending", "review", "blocked", "done"):
            (self.pipe / "queue" / s).mkdir(parents=True)
        reg = self.tmp / "projects.json"
        reg.write_text(json.dumps([{"repoRoot": "/r/alpha", "pipelineDir": str(self.pipe), "domainsPath": "x", "label": "alpha"}]))
        self.posts, self.calls = [], []

        def run(cmd, **kw):
            self.calls.append(cmd)
            return SimpleNamespace(returncode=0, stdout="queued adhoc task: /q/adhoc/t-new.json\n", stderr="")

        def opener(req, timeout=None):
            self.posts.append(req.full_url)
            return io.BytesIO(b"{}")
        saved = (filing.runner, filing._urlopen, os.environ.get("FEATUREFORGE_PROJECTS"), os.environ.get("FEATUREFORGE_MANAGER_MODE"))
        filing.runner, filing._urlopen = run, opener
        os.environ["FEATUREFORGE_PROJECTS"] = str(reg)
        os.environ.pop("FEATUREFORGE_MANAGER_MODE", None)

        def restore():
            filing.runner, filing._urlopen = saved[0], saved[1]
            for k, v in (("FEATUREFORGE_PROJECTS", saved[2]), ("FEATUREFORGE_MANAGER_MODE", saved[3])):
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self.addCleanup(restore)
        self.slug = store.create_feature("Thing", "x\nrepo: alpha", self.root)
        filed = (NOW - timedelta(minutes=150)).strftime("%Y-%m-%dT%H:%M:%SZ")
        store.write_file(self.slug, "checklist.md", f"# Checklist: Thing\n\n- [ ] FF-1 One <!-- task: t-pend filed: {filed} deps: -->\n", self.root)

    def put(self, state, tid, rec):
        (self.pipe / "queue" / state / f"{tid}.json").write_text(json.dumps(rec))

    def items(self):
        return {i["id"]: i for i in checklist.items(checklist.parse(store.read_file(self.slug, "checklist.md", self.root)))}

    def ledger(self):
        p = self.root / ".manager-ledger.jsonl"
        return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []

    def tick(self, mode=None):
        return manager.tick(self.root, NOW, mode)


class TickTests(Base):
    def test_idle_when_the_task_is_moving(self):
        self.put("review", "t-pend", {"status": "review"})
        self.assertEqual(self.tick("on")["result"], "idle")
        self.assertEqual(self.ledger(), [])

    def test_dry_run_is_the_default_and_only_writes_the_ledger(self):
        self.put("pending", "t-pend", {"status": "pending"})
        r = self.tick()
        self.assertEqual((r["result"], r["outcome"], r["done"]), ("handled", "bump", "dry-run: nothing done"))
        self.assertEqual([x["kind"] for x in self.ledger()], ["intent", "result"])
        self.assertEqual(self.posts, [])
        self.assertNotIn("premium", self.items()["FF-1"]["meta"])

    def test_the_intent_is_written_before_the_action_runs(self):
        self.put("pending", "t-pend", {"status": "pending"})
        seen = []
        orig = filing.set_flag

        def spy(*a, **k):
            seen.append([x["kind"] for x in self.ledger()])
            return orig(*a, **k)
        filing.set_flag = spy
        self.addCleanup(lambda: setattr(filing, "set_flag", orig))
        self.tick("on")
        self.assertEqual(seen, [["intent"]])

    def test_on_bumps_an_unclaimed_task_to_premium_once(self):
        self.put("pending", "t-pend", {"status": "pending"})
        r = self.tick("on")
        self.assertEqual(r["outcome"], "bump")
        meta = self.items()["FF-1"]["meta"]
        self.assertEqual(meta["premium"], "true")
        self.assertEqual(meta["bumped"], "2026-11-14T12:00:00Z")
        self.assertIn("t-pend/premium-priority", self.posts[0])
        self.assertEqual(self.tick("on", )["result"], "idle")             # premium now, and never bumped twice

    def test_the_same_decision_is_not_repeated_within_a_day(self):
        self.put("blocked", "t-pend", {"status": "blocked"})
        self.assertEqual(self.tick("dry-run")["outcome"], "flag")
        self.assertEqual(self.tick("dry-run")["result"], "idle")
        later = manager.tick(self.root, NOW + timedelta(hours=25), "dry-run")
        self.assertEqual(later["outcome"], "flag")

    def test_flag_writes_a_note(self):
        self.put("blocked", "t-pend", {"status": "blocked"})
        self.tick("on")
        text = (self.root / self.slug / "notes.md").read_text()
        self.assertIn("FF-1: blocked for 150 minutes", text)
        self.assertTrue(text.startswith("# Manager notes"))

    def test_a_vanished_task_is_filed_again(self):
        r = self.tick("on")
        self.assertEqual((r["outcome"], r["done"]), ("refile", "filed again as t-new"))
        self.assertEqual(self.items()["FF-1"]["meta"]["task"], "t-new")
        self.assertIn("filed again as t-new", (self.root / self.slug / "notes.md").read_text())

    def test_a_merged_task_is_ticked(self):
        self.put("done", "t-pend", {"status": "done", "mergedAt": "2026-11-14T11:30:00+00:00"})
        r = self.tick("on")
        self.assertEqual(r["outcome"], "tick")
        self.assertTrue(self.items()["FF-1"]["ticked"])

    def test_a_failing_action_is_recorded_not_raised(self):
        self.put("pending", "t-pend", {"status": "pending"})

        def down(req, timeout=None):
            raise OSError("down")
        filing._urlopen = down
        r = self.tick("on")
        self.assertTrue(r["done"].startswith("error: "))
        self.assertEqual(self.ledger()[-1]["kind"], "result")

    def test_off_mode_and_the_marker_file_stop_everything(self):
        self.assertEqual(self.tick("off"), {"result": "off"})
        (self.root / ".manager-disabled").write_text("")
        self.assertEqual(self.tick("on"), {"result": "off"})
        self.assertEqual(self.ledger(), [])

    def test_the_mode_comes_from_the_environment_and_unknown_values_fall_back_to_dry_run(self):
        self.assertEqual(manager.mode(), "dry-run")
        os.environ["FEATUREFORGE_MANAGER_MODE"] = "on"
        self.assertEqual(manager.mode(), "on")
        os.environ["FEATUREFORGE_MANAGER_MODE"] = "banana"
        self.assertEqual(manager.mode(), "dry-run")

    def test_one_item_per_tick_oldest_filing_first(self):
        old = (NOW - timedelta(minutes=200)).strftime("%Y-%m-%dT%H:%M:%SZ")
        new = (NOW - timedelta(minutes=130)).strftime("%Y-%m-%dT%H:%M:%SZ")
        store.write_file(self.slug, "checklist.md", f"# Checklist: Thing\n\n- [ ] FF-1 A <!-- task: t-a filed: {new} deps: -->\n- [ ] FF-2 B <!-- task: t-b filed: {old} deps: -->\n", self.root)
        self.put("blocked", "t-a", {"status": "blocked"})
        self.put("blocked", "t-b", {"status": "blocked"})
        self.assertEqual(self.tick("dry-run")["item"], "FF-2")
        self.assertEqual(self.tick("dry-run")["item"], "FF-1")
        self.assertEqual(self.tick("dry-run")["result"], "idle")

    def test_unregistered_or_repo_less_features_are_skipped(self):
        store.write_file(self.slug, "request.md", "# Thing\n\nrepo: gamma", self.root)
        self.assertEqual(self.tick("on")["result"], "idle")


class PieceManagerTests(Base):
    def setUp(self):
        super().setUp()
        filed = (NOW - timedelta(minutes=150)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.write_pieces(filed)

    def write_pieces(self, filed, premium=""):
        store.write_file(self.slug, "checklist.md",
                         f"# Checklist: Thing\n\n- [ ] FF-1 Step <!-- {premium}filed: {filed} deps: -->\n  Context.\n"
                         f"  - [ ] 1a First <!-- task: p-a filed: {filed} -->\n    text a\n"
                         f"  - [ ] 1b Second <!-- task: p-b filed: {filed} -->\n", self.root)

    def piece(self, pid):
        return {p["id"]: p for p in checklist.pieces(self.items()["FF-1"])}[pid]

    def test_a_pieces_task_is_watched_under_its_own_key(self):
        self.put("blocked", "p-a", {"status": "blocked"})
        self.put("review", "p-b", {"status": "review"})
        r = self.tick("dry-run")
        self.assertEqual((r["item"], r["outcome"]), ("FF-1/1a", "flag"))
        self.assertEqual(self.ledger()[0]["item"], "FF-1/1a")
        self.assertEqual(self.tick("dry-run")["result"], "idle")                 # 1b is moving, 1a was already decided

    def test_bumping_one_piece_raises_only_its_own_task_and_stamps_only_its_line(self):
        self.put("pending", "p-a", {"status": "pending"})
        self.put("review", "p-b", {"status": "review"})
        r = self.tick("on")
        self.assertEqual((r["item"], r["outcome"], r["done"]), ("FF-1/1a", "bump", "premium set"))
        self.assertEqual(len(self.posts), 1)
        self.assertIn("p-a/premium-priority", self.posts[0])
        self.assertEqual(self.piece("1a")["meta"]["bumped"], "2026-11-14T12:00:00Z")
        self.assertNotIn("bumped", self.piece("1b")["meta"])
        self.assertNotIn("premium", self.items()["FF-1"]["meta"])                # the step's own flag is not touched
        self.assertEqual(self.piece("1a")["body"], "text a")
        self.assertEqual(self.tick("on")["result"], "idle")                      # never bumped twice

    def test_a_step_that_is_already_premium_is_not_bumped_through_its_pieces(self):
        self.write_pieces((NOW - timedelta(minutes=150)).strftime("%Y-%m-%dT%H:%M:%SZ"), premium="premium: true ")
        self.put("pending", "p-a", {"status": "pending"})
        self.put("review", "p-b", {"status": "review"})
        self.assertEqual(self.tick("on")["result"], "idle")

    def test_a_merged_piece_is_ticked_through_the_status_sync(self):
        self.put("done", "p-a", {"status": "done", "mergedAt": "2026-11-14T11:30:00+00:00"})
        self.put("review", "p-b", {"status": "review"})
        r = self.tick("on")
        self.assertEqual((r["item"], r["outcome"]), ("FF-1/1a", "tick"))
        self.assertTrue(self.piece("1a")["ticked"])
        self.assertFalse(self.items()["FF-1"]["ticked"])

    def test_a_vanished_piece_task_is_filed_again_for_that_piece_only(self):
        self.put("review", "p-b", {"status": "review"})
        r = self.tick("on")
        self.assertEqual((r["item"], r["outcome"], r["done"]), ("FF-1/1a", "refile", "filed again as t-new"))
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.piece("1a")["meta"]["task"], "t-new")
        self.assertEqual(self.piece("1b")["meta"]["task"], "p-b")
        self.assertIn("FF-1/1a: task vanished, filed again as t-new", (self.root / self.slug / "notes.md").read_text())

    def test_refiling_one_piece_does_not_file_the_pieces_that_were_never_filed(self):
        filed = (NOW - timedelta(minutes=150)).strftime("%Y-%m-%dT%H:%M:%SZ")
        store.write_file(self.slug, "checklist.md", f"# Checklist: Thing\n\n- [ ] FF-1 Step <!-- filed: {filed} deps: -->\n"
                         f"  - [ ] 1a First <!-- task: p-a filed: {filed} -->\n  - [ ] 1b Second\n", self.root)
        self.tick("on")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.piece("1a")["meta"]["task"], "t-new")
        self.assertNotIn("task", self.piece("1b")["meta"])

    def test_notes_name_the_piece(self):
        self.put("blocked", "p-a", {"status": "blocked"})
        self.put("review", "p-b", {"status": "review"})
        self.tick("on")
        self.assertIn("FF-1/1a: blocked for 150 minutes", (self.root / self.slug / "notes.md").read_text())

    def test_ticked_pieces_are_not_candidates(self):
        self.put("review", "p-b", {"status": "review"})
        text = store.read_file(self.slug, "checklist.md", self.root).replace("- [ ] 1a First", "- [x] 1a First")
        store.write_file(self.slug, "checklist.md", text, self.root)
        self.assertEqual([c["item"] for c in manager.candidates(self.root)], ["FF-1/1b"])

    def test_items_and_pieces_are_ordered_together_oldest_first(self):
        old = (NOW - timedelta(minutes=300)).strftime("%Y-%m-%dT%H:%M:%SZ")
        mid = (NOW - timedelta(minutes=200)).strftime("%Y-%m-%dT%H:%M:%SZ")
        new = (NOW - timedelta(minutes=150)).strftime("%Y-%m-%dT%H:%M:%SZ")
        store.write_file(self.slug, "checklist.md",
                         f"# Checklist: Thing\n\n- [ ] FF-1 Step <!-- filed: {new} deps: -->\n  - [ ] 1a A <!-- task: p-a filed: {new} -->\n"
                         f"- [ ] FF-2 Plain <!-- task: t-plain filed: {old} deps: -->\n  - [ ] 2a B <!-- task: p-b filed: {mid} -->\n", self.root)
        self.assertEqual([c["item"] for c in manager.candidates(self.root)], ["FF-2", "FF-2/2a", "FF-1/1a"])


class DeadlineTests(Base):
    def test_no_deadline_before_ten_samples_then_twice_the_median(self):
        self.assertIsNone(manager.deadline_minutes(self.root))
        log = self.root / ".timing.jsonl"
        log.write_text("".join(json.dumps({"minutes": m}) + "\n" for m in (10, 20, 30, 40, 50, 60, 70, 80, 90)))
        self.assertIsNone(manager.deadline_minutes(self.root))
        log.write_text("".join(json.dumps({"minutes": m}) + "\n" for m in (10, 20, 30, 40, 50, 60, 70, 80, 90, 100)))
        self.assertEqual(manager.deadline_minutes(self.root), 110)


class WatchAndDueTests(Base):
    def set_filed(self, minutes_ago, ticked=False, with_task=True):
        filed = (NOW - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
        box = "x" if ticked else " "
        task = "task: t-pend " if with_task else ""
        store.write_file(self.slug, "checklist.md", f"# Checklist: Thing\n\n- [{box}] FF-1 One <!-- {task}filed: {filed} deps: -->\n", self.root)

    def snapshot(self):
        return sorted((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in self.tmp.rglob("*") if p.is_file())

    def run_cli(self, *args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = manager.main(list(args))
        return code, buf.getvalue()

    def test_watch_paths_lists_checklists_queues_and_marker(self):
        paths = manager.watch_paths(self.root)
        self.assertIn(str(self.root / self.slug / "checklist.md"), paths)
        for q in ("adhoc", "pending", "blocked", "needs-clarification", "done"):
            self.assertIn(str(self.pipe / "queue" / q), paths)
        self.assertIn(str(self.root / ".manager-disabled"), paths)
        self.assertEqual(paths, sorted(set(paths)))

    def test_watch_paths_writes_nothing(self):
        before = self.snapshot()
        manager.watch_paths(self.root)
        self.assertEqual(before, self.snapshot())

    def test_next_due_future_threshold(self):
        self.set_filed(10)
        self.put("pending", "t-pend", {"status": "pending"})
        self.assertEqual(manager.next_due(self.root, NOW), "2026-11-14T12:20:00Z")

    def test_next_due_earliest_wins(self):
        self.set_filed(10)
        self.put("pending", "t-pend", {"status": "pending"})
        (self.root / ".timing.jsonl").write_text("".join(json.dumps({"minutes": 10}) + "\n" for _ in range(10)))
        self.assertEqual(manager.next_due(self.root, NOW), "2026-11-14T12:10:00Z")

    def test_next_due_null_when_no_tasks(self):
        self.set_filed(10, with_task=False)
        self.assertIsNone(manager.next_due(self.root, NOW))

    def test_next_due_null_when_all_ticked(self):
        self.set_filed(10, ticked=True)
        self.put("pending", "t-pend", {"status": "pending"})
        self.assertIsNone(manager.next_due(self.root, NOW))

    def test_next_due_all_past_is_null(self):
        self.set_filed(150)
        self.put("pending", "t-pend", {"status": "pending"})
        self.assertIsNone(manager.next_due(self.root, NOW))

    def test_next_due_past_threshold_skipped(self):
        self.set_filed(50)
        self.put("blocked", "t-pend", {"status": "blocked"})
        self.assertEqual(manager.next_due(self.root, NOW), "2026-11-14T13:10:00Z")
        (self.root / ".timing.jsonl").write_text("".join(json.dumps({"minutes": 20}) + "\n" for _ in range(10)))   # deadline 40: already past
        self.assertEqual(manager.next_due(self.root, NOW), "2026-11-14T13:10:00Z")

    def test_next_due_writes_nothing(self):
        self.set_filed(10)
        self.put("pending", "t-pend", {"status": "pending"})
        before = self.snapshot()
        manager.next_due(self.root, NOW)
        self.assertEqual(before, self.snapshot())

    def test_cli_tick_one_json_line_exit_0(self):
        code, out = self.run_cli("--tick", str(self.root))
        self.assertEqual(code, 0)
        self.assertEqual(out.count("\n"), 1)
        self.assertTrue(out.endswith("\n"))
        self.assertIn(json.loads(out)["result"], ("handled", "idle", "off"))

    def test_cli_watch_paths_one_json_line(self):
        code, out = self.run_cli("--watch-paths", str(self.root))
        self.assertEqual(code, 0)
        self.assertEqual(out.count("\n"), 1)
        self.assertEqual(json.loads(out), manager.watch_paths(self.root))

    def test_cli_next_due_one_json_line(self):
        filed = (datetime.now(timezone.utc) - timedelta(minutes=10)).replace(microsecond=0)
        store.write_file(self.slug, "checklist.md", f"# Checklist: Thing\n\n- [ ] FF-1 One <!-- task: t-pend filed: {filed.strftime('%Y-%m-%dT%H:%M:%SZ')} deps: -->\n", self.root)
        self.put("pending", "t-pend", {"status": "pending"})
        code, out = self.run_cli("--next-due", str(self.root))
        self.assertEqual(code, 0)
        self.assertEqual(out.count("\n"), 1)
        self.assertEqual(json.loads(out), (filed + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ"))

    def test_cli_next_due_null_prints_null(self):
        self.set_filed(10, with_task=False)
        code, out = self.run_cli("--next-due", str(self.root))
        self.assertEqual((code, out), (0, "null\n"))

    def test_cli_tick_error_exit_0_with_error_key(self):
        with mock.patch.object(manager, "tick", side_effect=RuntimeError("boom")):
            code, out = self.run_cli("--tick", str(self.root))
        self.assertEqual(code, 0)
        self.assertEqual(out.count("\n"), 1)
        self.assertIn("boom", json.loads(out)["error"])


if __name__ == "__main__":
    unittest.main()
