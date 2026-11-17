"""Tests for server/core/filing.py: the polling lint, the task text, filing an item through a fake queue script and a fake
dashboard, the dependency order, and the premium and cloud flags. Plain unittest, standard library only."""
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.core import checklist, filing, grill, store

CHECKLIST = """# Checklist: Thing

- [x] FF-1 Scaffold <!-- manual: true merged: abc1234 -->
- [ ] FF-2 Build the core <!-- premium: true deps: FF-1 -->
  Write core.py with tests.
- [ ] FF-3 Wire it <!-- deps: FF-2 -->
- [ ] FF-4 Watch things <!-- deps: FF-1 -->
  Check the folder every 5 minutes.
"""


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = self.tmp / "features"
        self.slug = store.create_feature("Thing", "build a thing\nrepo: alpha", self.root)
        store.write_file(self.slug, "checklist.md", CHECKLIST, self.root)
        store.write_file(self.slug, "plan.md", "# Plan\n\nBuild it in two steps.", self.root)
        reg = self.tmp / "projects.json"
        reg.write_text(json.dumps([{"repoRoot": "/r/alpha", "pipelineDir": "/p/alpha-pipeline", "domainsPath": "/p/alpha-pipeline/d.json", "label": "alpha"}]))
        self.calls, self.posts = [], []

        def fake_run(cmd, **kw):
            self.calls.append((cmd, kw))
            n = len(self.calls)
            if self.fail or n == self.fail_on_call:
                return SimpleNamespace(returncode=1, stdout="", stderr="boom")
            return SimpleNamespace(returncode=0, stdout=f"queued adhoc task: /p/alpha-pipeline/queue/adhoc/adhoc-task-{n}.json\n", stderr="")

        def fake_open(req, timeout=None):
            self.posts.append((req.full_url, json.loads(req.data.decode())))
            if self.post_fail:
                raise OSError("down")
            return io.BytesIO(b"{}")
        self.fail = self.post_fail = False
        self.fail_on_call = None
        saved = (filing.runner, filing._urlopen, os.environ.get("FEATUREFORGE_PROJECTS"))
        filing.runner, filing._urlopen = fake_run, fake_open
        os.environ["FEATUREFORGE_PROJECTS"] = str(reg)

        def restore():
            filing.runner, filing._urlopen = saved[0], saved[1]
            if saved[2] is None:
                os.environ.pop("FEATUREFORGE_PROJECTS", None)
            else:
                os.environ["FEATUREFORGE_PROJECTS"] = saved[2]
        self.addCleanup(restore)

    def items(self):
        return {i["id"]: i for i in checklist.items(checklist.parse(store.read_file(self.slug, "checklist.md", self.root)))}

    def file(self, item, **kw):
        return filing.file_item(self.slug, item, root=self.root, **kw)


class LintTests(unittest.TestCase):
    def test_polling_language_is_found(self):
        for text in ("use setInterval to refresh", "poll the queue", "check every 5 minutes", "run from cron", "while True: sleep(1)", "sleep(3)"):
            with self.subTest(text=text):
                self.assertTrue(filing.lint(text), text)

    def test_trigger_language_is_clean(self):
        self.assertEqual(filing.lint("wake on the task-state event and write the file"), [])

    def test_the_standard_clause_does_not_trip_the_lint(self):
        self.assertEqual(filing.lint("do the thing. " + filing.STANDARD_CLAUSE), [])

    def test_a_negated_polling_word_is_not_flagged(self):
        for text in ("do not add a new sleep loop", "add no new timer", "never poll the queue", "without cron", "instead of a sleep loop, wake on the event"):
            with self.subTest(text=text):
                self.assertEqual(filing.lint(text), [])

    def test_negated_no_poll_is_not_flagged(self):
        self.assertEqual(filing.lint("add no poll to the worker"), [])

    def test_negated_nothing_polls_is_not_flagged(self):
        self.assertEqual(filing.lint("nothing polls the queue"), [])

    def test_negated_not_poll_is_not_flagged(self):
        self.assertEqual(filing.lint("do not poll the queue"), [])

    def test_negated_never_poll_is_not_flagged(self):
        self.assertEqual(filing.lint("never poll the queue"), [])

    def test_negated_without_polling_is_not_flagged(self):
        self.assertEqual(filing.lint("without polling, wake on the event"), [])

    def test_negated_does_not_poll_is_not_flagged(self):
        self.assertEqual(filing.lint("the worker does not poll the queue"), [])

    def test_double_negation_not_never_poll(self):
        # Double-negation edge case: "do not never poll the queue" contains two
        # negation words ("not", "never") before "poll". The current implementation
        # only checks for the FIRST negation word in the clause, so it treats the
        # clause as negated and suppresses the warning -- even though a strict
        # reading of double negation would imply the opposite. This test pins the
        # current behavior so the edge case is explicit and ready for a decision
        # on whether to handle it.
        self.assertEqual(filing.lint("do not never poll the queue"), [])

    def test_negated_no_polling_is_not_flagged(self):
        self.assertEqual(filing.lint("no polling, the file is read on demand"), [])

    def test_negated_instead_of_polling_is_not_flagged(self):
        self.assertEqual(filing.lint("wake on events instead of polling the queue"), [])

    def test_affirmative_polls_every_5_seconds_warns(self):
        self.assertTrue(filing.lint("polls the file every 5 seconds"))

    def test_affirmative_worker_polls_the_queue_warns(self):
        self.assertTrue(filing.lint("the worker polls the queue"))

    def test_affirmative_polls_then_sleeps_warns(self):
        self.assertTrue(filing.lint("it polls and then sleeps"))

    def test_negation_in_an_earlier_clause_does_not_exempt_a_later_poll(self):
        self.assertTrue(filing.lint("Nothing else changes; the worker polls the queue"))

    def test_an_unnegated_match_still_warns_beside_a_negated_one(self):
        self.assertTrue(filing.lint("do not add a sleep loop, but poll every 5 minutes"))
        self.assertTrue(filing.lint("run a cron job"))
        self.assertTrue(filing.lint("poll every 5 minutes"))


class RecordTextTests(Base):
    def test_text_has_the_job_the_deps_the_plan_and_the_clause(self):
        t = filing.record_text(self.slug, "FF-2", self.root)
        for needle in ("FF-2 of feature 'thing': Build the core", "Repo: alpha.", "Write core.py with tests.", "waits for: FF-1",
                       "Build it in two steps.", filing.STANDARD_CLAUSE):
            with self.subTest(needle=needle):
                self.assertIn(needle, t)

    def test_a_long_plan_is_cut(self):
        store.write_file(self.slug, "plan.md", "x" * 9000, self.root)
        t = filing.record_text(self.slug, "FF-2", self.root)
        self.assertIn("[plan cut here]", t)
        self.assertLess(len(t), 5200)


class FileItemTests(Base):
    def test_filing_runs_the_queue_script_in_the_target_pipeline_and_stamps_the_item(self):
        r = self.file("FF-2")
        cmd, kw = self.calls[0]
        self.assertTrue(cmd[1].endswith("queue-adhoc-task.js"))
        self.assertEqual(cmd[cmd.index("--title") + 1], "FF-2 Build the core")
        self.assertNotIn("--depends-on", cmd)                    # FF-1 was done by hand: nothing to wait for
        self.assertEqual(kw["env"]["AGENT_MANAGER_PIPELINE_DIR"], "/p/alpha-pipeline")
        self.assertEqual(kw["env"]["AGENT_MANAGER_REPO_ROOT"], "/r/alpha")
        it = self.items()["FF-2"]
        self.assertEqual(it["meta"]["task"], "adhoc-task-1")
        self.assertTrue(it["meta"]["filed"])
        self.assertTrue(checklist.is_locked(it))
        self.assertEqual(r["task"], "adhoc-task-1")

    def test_the_prompt_context_file_holds_the_task_text(self):
        seen = {}
        orig = filing.runner

        def spy(cmd, **kw):
            seen["pc"] = json.loads(Path(cmd[cmd.index("--prompt-context-file") + 1]).read_text())
            return orig(cmd, **kw)
        filing.runner = spy
        self.file("FF-2")
        self.assertIn(filing.STANDARD_CLAUSE, seen["pc"]["rawText"])
        self.assertEqual(seen["pc"]["raisedFrom"], "feature-forge:thing/FF-2")

    def test_premium_is_set_through_the_dashboard_after_filing(self):
        r = self.file("FF-2")
        self.assertTrue(r["premium"])
        url, body = self.posts[0]
        self.assertIn("/api/task-anywhere/adhoc-task-1/premium-priority?project=/r/alpha", url)
        self.assertEqual(body["enabled"], True)

    def test_a_dashboard_failure_keeps_the_filing_and_reports_it(self):
        self.post_fail = True
        r = self.file("FF-2")
        self.assertIn("premiumError", r)
        self.assertEqual(self.items()["FF-2"]["meta"]["task"], "adhoc-task-1")

    def test_an_item_can_only_be_filed_after_the_items_it_waits_for(self):
        with self.assertRaisesRegex(filing.FilingError, "file FF-2 first"):
            self.file("FF-3")
        self.assertEqual(self.calls, [])
        self.file("FF-2")
        self.file("FF-3")
        cmd = self.calls[1][0]
        self.assertEqual(cmd[cmd.index("--depends-on") + 1], "adhoc-task-1")

    def test_polling_language_needs_an_explicit_accept(self):
        with self.assertRaisesRegex(filing.FilingError, "polling language"):
            self.file("FF-4")
        self.assertEqual(self.calls, [])
        r = self.file("FF-4", accept_lint=True)
        self.assertEqual(r["warnings"], ["'every N <unit>'"])
        self.assertEqual(len(self.calls), 1)

    def test_refusals_leave_the_checklist_untouched(self):
        before = store.read_file(self.slug, "checklist.md", self.root)
        self.file("FF-2")
        for item, msg in (("FF-2", "already filed"), ("FF-1", "already done"), ("FF-9", "no such item")):
            with self.subTest(item=item):
                with self.assertRaisesRegex(filing.FilingError, msg):
                    self.file(item)
        self.fail = True
        with self.assertRaisesRegex(filing.FilingError, "could not be queued: boom"):
            self.file("FF-3")
        self.assertNotIn("FF-3 Wire it <!-- task", store.read_file(self.slug, "checklist.md", self.root))
        self.assertNotEqual(before, store.read_file(self.slug, "checklist.md", self.root))

    def test_no_repo_or_unregistered_repo_is_refused(self):
        store.write_file(self.slug, "request.md", "# Thing\n\nno repo here", self.root)
        with self.assertRaisesRegex(filing.FilingError, "choose the repo"):
            self.file("FF-2")
        store.write_file(self.slug, "request.md", "# Thing\n\nrepo: gamma", self.root)
        with self.assertRaisesRegex(filing.FilingError, "not a registered"):
            self.file("FF-2")


PIECES_CHECKLIST = """# Checklist: Thing

- [x] FF-1 By hand <!-- manual: true -->
- [ ] FF-2 Step with pieces <!-- premium: true deps: FF-1 -->
  Context line about the step.
  - [ ] 2a First piece
    Do the first thing in core.py.
  - [ ] 2b Second piece
    Do the second thing in app.py.
  - [ ] 2c Third piece
- [ ] FF-3 After the step <!-- deps: FF-2 -->
"""


class PieceFilingTests(Base):
    def setUp(self):
        super().setUp()
        store.write_file(self.slug, "checklist.md", PIECES_CHECKLIST, self.root)

    def pieces(self, item="FF-2"):
        return {p["id"]: p for p in checklist.pieces(self.items()[item])}

    def deps_of(self, call):
        cmd = call[0]
        return cmd[cmd.index("--depends-on") + 1] if "--depends-on" in cmd else None

    def test_an_item_with_pieces_files_one_task_per_piece_in_a_chain(self):
        r = self.file("FF-2")
        self.assertEqual([x["piece"] for x in r["pieces"]], ["2a", "2b", "2c"])
        self.assertEqual(r["task"], "adhoc-task-3")
        self.assertEqual([self.deps_of(c) for c in self.calls], [None, "adhoc-task-1", "adhoc-task-2"])       # FF-1 was done by hand
        self.assertEqual([c[0][c[0].index("--title") + 1] for c in self.calls], ["FF-2/2a First piece", "FF-2/2b Second piece", "FF-2/2c Third piece"])

    def test_each_piece_line_is_stamped_and_the_item_is_locked_without_an_item_task(self):
        self.file("FF-2")
        ps = self.pieces()
        self.assertEqual([ps[k]["meta"]["task"] for k in "2a 2b 2c".split()], ["adhoc-task-1", "adhoc-task-2", "adhoc-task-3"])
        self.assertTrue(all(p["meta"]["filed"].endswith("Z") for p in ps.values()))
        it = self.items()["FF-2"]
        self.assertNotIn("task", it["meta"])
        self.assertTrue(checklist.is_locked(it))
        self.assertEqual(ps["2a"]["body"], "Do the first thing in core.py.")                       # the piece text survived the stamp

    def test_the_task_text_is_the_pieces_own_text_with_the_step_for_context(self):
        seen = []
        orig = filing.runner

        def spy(cmd, **kw):
            seen.append(json.loads(Path(cmd[cmd.index("--prompt-context-file") + 1]).read_text())["rawText"])
            return orig(cmd, **kw)
        filing.runner = spy
        self.file("FF-2")
        self.assertIn("Do the first thing in core.py.", seen[0])
        self.assertIn("part of FF-2 (Step with pieces): Context line about the step.", seen[0])
        self.assertNotIn("Do the second thing", seen[0])
        self.assertIn("comes after 2a (First piece)", seen[1])
        self.assertIn("(no further detail in the checklist piece)", seen[2])
        self.assertTrue(all(filing.STANDARD_CLAUSE in t for t in seen))

    def test_the_steps_premium_flag_reaches_every_piece_task(self):
        r = self.file("FF-2")
        self.assertTrue(r["premium"])
        self.assertEqual(len(self.posts), 3)
        self.assertEqual(sorted(u.split("/api/task-anywhere/")[1].split("/")[0] for u, _ in self.posts), ["adhoc-task-1", "adhoc-task-2", "adhoc-task-3"])

    def test_one_piece_can_be_filed_alone_but_only_in_order(self):
        with self.assertRaisesRegex(filing.FilingError, "file 2a first"):
            self.file("FF-2", piece="2b")
        self.assertEqual(self.calls, [])
        self.assertEqual([x["piece"] for x in self.file("FF-2", piece="2a")["pieces"]], ["2a"])
        self.file("FF-2", piece="2b")
        self.assertEqual(self.deps_of(self.calls[1]), "adhoc-task-1")
        with self.assertRaisesRegex(filing.FilingError, "2a is already filed as adhoc-task-1"):
            self.file("FF-2", piece="2a")

    def test_filing_again_files_only_what_is_left_and_chains_to_the_last_filed_piece(self):
        self.file("FF-2", piece="2a")
        r = self.file("FF-2")
        self.assertEqual([x["piece"] for x in r["pieces"]], ["2b", "2c"])
        self.assertEqual(self.deps_of(self.calls[1]), "adhoc-task-1")
        with self.assertRaisesRegex(filing.FilingError, "no unfiled pieces"):
            self.file("FF-2")

    def test_a_piece_added_to_a_filed_item_can_be_filed(self):
        self.file("FF-2")
        checklist.apply(self.slug, {"ops": [{"op": "change", "id": "FF-2", "pieces": ["Late piece"]}]}, None, self.root)
        r = self.file("FF-2")
        self.assertEqual([x["piece"] for x in r["pieces"]], ["2d"])
        self.assertEqual(self.deps_of(self.calls[-1]), "adhoc-task-3")

    def test_a_step_waiting_on_a_step_with_pieces_waits_for_its_last_piece(self):
        with self.assertRaisesRegex(filing.FilingError, "file FF-2 first"):
            self.file("FF-3")
        self.file("FF-2")
        self.calls.clear()
        self.file("FF-3")
        self.assertEqual(self.deps_of(self.calls[0]), "adhoc-task-3")

    def test_pieces_done_by_hand_add_no_dependency(self):
        store.write_file(self.slug, "checklist.md", PIECES_CHECKLIST.replace("- [ ] 2a First piece", "- [x] 2a First piece <!-- merged: abc1234 -->"), self.root)
        r = self.file("FF-2")
        self.assertEqual([x["piece"] for x in r["pieces"]], ["2b", "2c"])
        self.assertIsNone(self.deps_of(self.calls[0]))
        self.assertEqual(self.deps_of(self.calls[1]), "adhoc-task-1")

    def test_a_done_earlier_piece_means_the_step_dependencies_are_met_too(self):
        text = ("# Checklist: Thing\n\n- [ ] FF-1 Base <!-- task: t-base filed: 2026-11-14T00:00:00Z deps: -->\n"
                "- [ ] FF-2 Step <!-- deps: FF-1 -->\n  - [x] 2a Done <!-- merged: abc1234 -->\n  - [ ] 2b Next\n    text\n")
        store.write_file(self.slug, "checklist.md", text, self.root)
        self.file("FF-2")
        self.assertIsNone(self.deps_of(self.calls[0]))
        store.write_file(self.slug, "checklist.md", text.replace("- [x] 2a Done <!-- merged: abc1234 -->", "- [ ] 2a Done"), self.root)
        self.calls.clear()
        self.file("FF-2")
        self.assertEqual(self.deps_of(self.calls[0]), "t-base")                  # the first piece of a fresh step waits for what the step waits for

    def test_polling_language_in_a_piece_is_refused_before_anything_is_queued(self):
        store.write_file(self.slug, "checklist.md", PIECES_CHECKLIST.replace("Do the second thing in app.py.", "Check it every 5 minutes."), self.root)
        with self.assertRaisesRegex(filing.FilingError, "polling language"):
            self.file("FF-2")
        self.assertEqual(self.calls, [])
        self.assertEqual(len(self.file("FF-2", accept_lint=True)["pieces"]), 3)

    def test_a_failure_midway_keeps_what_was_filed_and_says_so(self):
        self.fail_on_call = 2
        with self.assertRaisesRegex(filing.FilingError, r"could not be queued: boom \(filed so far: adhoc-task-1\)"):
            self.file("FF-2")
        ps = self.pieces()
        self.assertEqual(ps["2a"]["meta"]["task"], "adhoc-task-1")
        self.assertNotIn("task", ps["2b"]["meta"])
        self.fail_on_call = None
        self.assertEqual([x["piece"] for x in self.file("FF-2")["pieces"]], ["2b", "2c"])

    def test_piece_arguments_are_checked(self):
        with self.assertRaisesRegex(filing.FilingError, "no such piece 2z"):
            self.file("FF-2", piece="2z")
        with self.assertRaisesRegex(filing.FilingError, "FF-3 has no pieces"):
            self.file("FF-3", piece="3a")
        with self.assertRaisesRegex(filing.FilingError, "no such piece"):
            filing.record_text(self.slug, "FF-2", self.root, "9z")

    def test_premium_on_a_filed_step_changes_every_unfinished_piece_task(self):
        self.file("FF-2")
        self.posts.clear()
        filing.set_flag(self.slug, "FF-2", "premium", False, self.root)
        self.assertEqual(len(self.posts), 3)
        self.assertTrue(all(body == {"enabled": False} for _, body in self.posts))
        self.assertEqual(self.items()["FF-2"]["meta"]["premium"], "false")

    def test_independent_pieces_with_after_none_get_no_inter_piece_deps(self):
        text = ("# Checklist: Thing\n\n- [ ] FF-1 Base <!-- task: t-base filed: 2026-11-14T00:00:00Z -->\n"
                "- [ ] FF-2 Step <!-- deps: FF-1 -->\n"
                "  - [ ] 2a First <!-- after: none -->\n"
                "    Do the first thing.\n"
                "  - [ ] 2b Second <!-- after: none -->\n"
                "    Do the second thing.\n"
                "  - [ ] 2c Third <!-- after: none -->\n"
                "    Do the third thing.\n")
        store.write_file(self.slug, "checklist.md", text, self.root)
        r = self.file("FF-2")
        self.assertEqual([x["piece"] for x in r["pieces"]], ["2a", "2b", "2c"])
        self.assertEqual([self.deps_of(c) for c in self.calls], ["t-base", "t-base", "t-base"])

    def test_after_with_a_piece_label_cites_that_piece_only(self):
        text = ("# Checklist: Thing\n\n- [ ] FF-1 Base <!-- task: t-base filed: 2026-11-14T00:00:00Z -->\n"
                "- [ ] FF-2 Step <!-- deps: FF-1 -->\n"
                "  - [ ] 2a First <!-- after: none -->\n"
                "    Do the first thing.\n"
                "  - [ ] 2b Second <!-- after: 2a -->\n"
                "    Do the second thing.\n"
                "  - [ ] 2c Third <!-- after: 2a -->\n"
                "    Do the third thing.\n")
        store.write_file(self.slug, "checklist.md", text, self.root)
        self.file("FF-2")
        self.assertEqual(self.deps_of(self.calls[0]), "t-base")
        self.assertEqual(self.deps_of(self.calls[1]), "adhoc-task-1")
        self.assertEqual(self.deps_of(self.calls[2]), "adhoc-task-1")

    def test_after_with_multiple_labels_cites_all_of_them(self):
        text = ("# Checklist: Thing\n\n- [ ] FF-1 Base <!-- task: t-base filed: 2026-11-14T00:00:00Z -->\n"
                "- [ ] FF-2 Step <!-- deps: FF-1 -->\n"
                "  - [ ] 2a First\n"
                "    Do the first thing.\n"
                "  - [ ] 2b Second\n"
                "    Do the second thing.\n"
                "  - [ ] 2c Third <!-- after: 2a 2b -->\n"
                "    Do the third thing.\n")
        store.write_file(self.slug, "checklist.md", text, self.root)
        self.file("FF-2")
        self.assertEqual(self.deps_of(self.calls[0]), "t-base")
        self.assertEqual(self.deps_of(self.calls[1]), "adhoc-task-1")
        self.assertEqual(self.deps_of(self.calls[2]), "adhoc-task-1,adhoc-task-2")

    def test_after_referencing_an_unfiled_piece_raises(self):
        text = ("# Checklist: Thing\n\n- [ ] FF-1 Base <!-- task: t-base filed: 2026-11-14T00:00:00Z -->\n"
                "- [ ] FF-2 Step <!-- deps: FF-1 -->\n"
                "  - [ ] 2a First <!-- after: 2b -->\n"
                "    Do the first thing.\n"
                "  - [ ] 2b Second\n"
                "    Do the second thing.\n")
        store.write_file(self.slug, "checklist.md", text, self.root)
        with self.assertRaisesRegex(filing.FilingError, "piece 2b in FF-2/2a has no task yet"):
            self.file("FF-2")
        self.assertEqual(self.calls, [])

    def test_after_referencing_an_unknown_piece_raises(self):
        text = ("# Checklist: Thing\n\n- [ ] FF-1 Base <!-- task: t-base filed: 2026-11-14T00:00:00Z -->\n"
                "- [ ] FF-2 Step <!-- deps: FF-1 -->\n"
                "  - [ ] 2a First <!-- after: 9z -->\n"
                "    Do the first thing.\n")
        store.write_file(self.slug, "checklist.md", text, self.root)
        with self.assertRaisesRegex(filing.FilingError, "piece 9z in FF-2/2a refers to an unknown piece"):
            self.file("FF-2")
        self.assertEqual(self.calls, [])

    def test_no_after_keeps_the_chain(self):
        r = self.file("FF-2")
        self.assertEqual([x["piece"] for x in r["pieces"]], ["2a", "2b", "2c"])
        self.assertEqual([self.deps_of(c) for c in self.calls], [None, "adhoc-task-1", "adhoc-task-2"])

    def test_task_text_shows_declared_after_peers(self):
        text = ("# Checklist: Thing\n\n- [ ] FF-1 Base <!-- task: t-base filed: 2026-11-14T00:00:00Z -->\n"
                "- [ ] FF-2 Step <!-- deps: FF-1 -->\n"
                "  - [ ] 2a First\n"
                "    Do the first thing.\n"
                "  - [ ] 2b Second <!-- after: 2a -->\n"
                "    Do the second thing.\n")
        store.write_file(self.slug, "checklist.md", text, self.root)
        seen = []
        orig = filing.runner
        def spy(cmd, **kw):
            seen.append(json.loads(Path(cmd[cmd.index("--prompt-context-file") + 1]).read_text())["rawText"])
            return orig(cmd, **kw)
        filing.runner = spy
        self.file("FF-2")
        self.assertNotIn("comes after", seen[0])
        self.assertIn("comes after 2a (First)", seen[1])
        filing.runner = orig

    def test_after_round_trips_through_checklist_parse_and_render(self):
        text = ("# Checklist: Thing\n\n- [ ] FF-2 Step\n"
                "  - [ ] 2a First <!-- after: 2b none -->\n"
                "    Do the first thing.\n"
                "  - [ ] 2b Second <!-- after: none -->\n"
                "    Do the second thing.\n")
        entries = checklist.parse(text)
        rendered = checklist.render(entries)
        self.assertIn("after: 2b none", rendered)
        self.assertIn("after: none", rendered)
        reparsed = checklist.parse(rendered)
        ps = checklist.pieces(checklist.items(reparsed)[0])
        self.assertEqual(ps[0]["meta"]["after"], "2b none")
        self.assertEqual(ps[1]["meta"]["after"], "none")


class FlagTests(Base):
    def flag(self, item, flag, value):
        return filing.set_flag(self.slug, item, flag, value, self.root)

    def test_flags_change_on_an_unfiled_item_and_nothing_is_posted(self):
        self.flag("FF-3", "premium", True)
        self.flag("FF-3", "cloud", True)
        m = self.items()["FF-3"]["meta"]
        self.assertEqual((m["premium"], m["cloud"], m["deps"]), ("true", "true", "FF-2"))
        self.flag("FF-3", "premium", False)
        self.assertEqual(self.items()["FF-3"]["meta"]["premium"], "false")
        self.assertEqual(self.posts, [])

    def test_premium_on_a_filed_item_goes_through_the_dashboard(self):
        self.file("FF-2")
        self.posts.clear()
        self.flag("FF-2", "premium", False)
        self.assertEqual(self.posts[0][1], {"enabled": False})
        self.assertEqual(self.items()["FF-2"]["meta"]["premium"], "false")
        self.assertNotIn("changed", self.items()["FF-2"]["meta"])

    def test_a_dashboard_failure_leaves_the_flag_unchanged(self):
        self.file("FF-2")
        self.post_fail = True
        with self.assertRaises(filing.FilingError):
            self.flag("FF-2", "premium", False)
        self.assertEqual(self.items()["FF-2"]["meta"]["premium"], "true")

    def test_cloud_is_fixed_once_filed_and_done_items_are_refused(self):
        self.file("FF-2")
        with self.assertRaisesRegex(filing.FilingError, "lane was fixed"):
            self.flag("FF-2", "cloud", True)
        with self.assertRaisesRegex(filing.FilingError, "is done"):
            self.flag("FF-1", "premium", True)
        with self.assertRaisesRegex(filing.FilingError, "premium or cloud"):
            self.flag("FF-3", "weird", True)


class RegistryTests(Base):
    def test_a_project_is_found_by_label_or_folder_name(self):
        self.assertEqual(filing.project_for("alpha")["pipelineDir"], "/p/alpha-pipeline")
        reg = self.tmp / "p2.json"
        reg.write_text(json.dumps([{"repoRoot": "/r/beta", "pipelineDir": "/p/b", "domainsPath": "/p/b/d.json", "label": "other"}]))
        os.environ["FEATUREFORGE_PROJECTS"] = str(reg)
        self.assertEqual(filing.project_for("beta")["pipelineDir"], "/p/b")

    def test_a_missing_registry_is_an_error(self):
        os.environ["FEATUREFORGE_PROJECTS"] = str(self.tmp / "nope.json")
        with self.assertRaisesRegex(filing.FilingError, "cannot read the project registry"):
            filing.project_for("alpha")


if __name__ == "__main__":
    unittest.main()
