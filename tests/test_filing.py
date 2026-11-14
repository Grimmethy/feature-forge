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
            if self.fail:
                return SimpleNamespace(returncode=1, stdout="", stderr="boom")
            n = len(self.calls)
            return SimpleNamespace(returncode=0, stdout=f"queued adhoc task: /p/alpha-pipeline/queue/adhoc/adhoc-task-{n}.json\n", stderr="")

        def fake_open(req, timeout=None):
            self.posts.append((req.full_url, json.loads(req.data.decode())))
            if self.post_fail:
                raise OSError("down")
            return io.BytesIO(b"{}")
        self.fail = self.post_fail = False
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
