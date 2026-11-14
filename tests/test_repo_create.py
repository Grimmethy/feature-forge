"""Tests for server/core/repo_create.py with a fake command runner and temp folders: the plan, each step, skipping what is done,
stopping on a failure, the registry backup and the name check. Plain unittest, standard library only."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.core import filing, repo_create


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.repos = self.tmp / "repos"
        self.repos.mkdir()
        self.reg = self.tmp / "projects.json"
        self.reg.write_text(json.dumps([{"repoRoot": "/r/old", "pipelineDir": "/p/old", "domainsPath": "/p/old/d.json", "label": "old"}]))
        self.core = self.tmp / "am"
        self.core.mkdir()
        (self.core / "task-domains.json").write_text('{"default": {}}')
        self.calls, self.fail_on = [], None

        def run(cmd, **kw):
            self.calls.append(cmd)
            if self.fail_on and self.fail_on in cmd:
                return SimpleNamespace(returncode=1, stdout="", stderr="boom")
            if cmd[:2] == ["git", "init"]:
                (Path(cmd[-1]) / ".git").mkdir(parents=True, exist_ok=True)
            if cmd[:2] == ["gh", "repo"]:
                self.origin = True
            if "get-url" in cmd:
                return SimpleNamespace(returncode=0 if getattr(self, "origin", False) else 1, stdout="", stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        saved = (repo_create.runner, filing.AM_CORE, os.environ.get("FEATUREFORGE_PROJECTS"))
        repo_create.runner, filing.AM_CORE = run, self.core
        os.environ["FEATUREFORGE_PROJECTS"] = str(self.reg)

        def restore():
            repo_create.runner, filing.AM_CORE = saved[0], saved[1]
            if saved[2] is None:
                os.environ.pop("FEATUREFORGE_PROJECTS", None)
            else:
                os.environ["FEATUREFORGE_PROJECTS"] = saved[2]
        self.addCleanup(restore)

    def registry(self):
        return json.loads(self.reg.read_text())


class PlanTests(Base):
    def test_plan_lists_four_steps_and_does_nothing(self):
        steps = repo_create.plan("brand-new", self.repos)
        self.assertEqual([s["id"] for s in steps], ["git", "github", "register", "pipeline"])
        self.assertFalse(any(s["done"] for s in steps))
        self.assertIn("Grimmethy/brand-new", steps[1]["text"])
        self.assertEqual(self.calls, [])
        self.assertEqual(len(self.registry()), 1)
        self.assertFalse((self.repos / "brand-new").exists())

    def test_bad_names_are_refused(self):
        for bad in ("", "../x", "a b", "-lead", "x" * 80, "a/b", "name.git", None, 5):
            with self.subTest(name=bad):
                with self.assertRaises(repo_create.RepoCreateError):
                    repo_create.plan(bad, self.repos)


class CreateTests(Base):
    def test_every_step_runs_in_order(self):
        steps = repo_create.create("brand-new", self.repos)
        self.assertEqual([s["result"] for s in steps], ["done"] * 4)
        cmds = [" ".join(c[:3]) for c in self.calls if "get-url" not in c]
        self.assertEqual([c.split()[0] for c in cmds], ["git", "git", "git", "gh"])
        self.assertTrue((self.repos / "brand-new" / "README.md").is_file())
        gh = [c for c in self.calls if c[0] == "gh"][0]
        self.assertEqual(gh[:4], ["gh", "repo", "create", "Grimmethy/brand-new"])
        self.assertIn("--private", gh)

    def test_the_registry_entry_has_a_pipeline_and_pool_true_and_the_old_entries_survive(self):
        repo_create.create("brand-new", self.repos)
        reg = self.registry()
        self.assertEqual([p["label"] for p in reg], ["old", "brand-new"])
        new = reg[1]
        self.assertEqual((new["pool"], new["repoRoot"], new["pipelineDir"]), (True, str(self.repos / "brand-new"), str(self.repos / "brand-new-pipeline")))
        self.assertTrue((self.repos / "brand-new-pipeline" / "task-domains.json").is_file())
        self.assertTrue((self.repos / "brand-new-pipeline" / "queue" / "adhoc").is_dir())

    def test_the_registry_is_backed_up_before_it_changes(self):
        before = self.reg.read_text()
        repo_create.create("brand-new", self.repos)
        baks = list(self.tmp.glob("projects.json.bak-*-before-brand-new"))
        self.assertEqual(len(baks), 1)
        self.assertEqual(baks[0].read_text(), before)

    def test_steps_already_done_are_skipped_and_a_second_run_changes_nothing(self):
        repo_create.create("brand-new", self.repos)
        self.calls.clear()
        steps = repo_create.create("brand-new", self.repos)
        self.assertTrue(all(s["result"].startswith("skipped") for s in steps))
        self.assertEqual([c for c in self.calls if "get-url" not in c], [])
        self.assertEqual(len(self.registry()), 2)

    def test_a_failure_stops_the_run_and_later_steps_do_not_happen(self):
        self.fail_on = "gh"
        with self.assertRaisesRegex(repo_create.RepoCreateError, "creating the GitHub repo failed: boom"):
            repo_create.create("brand-new", self.repos)
        self.assertEqual(len(self.registry()), 1)
        self.assertFalse((self.repos / "brand-new-pipeline").exists())

    def test_an_unreadable_registry_stops_the_run_and_is_left_untouched(self):
        self.reg.write_text("not json")
        with self.assertRaisesRegex(repo_create.RepoCreateError, "cannot read the project registry"):
            repo_create.create("brand-new", self.repos)
        self.assertEqual(self.reg.read_text(), "not json")


if __name__ == "__main__":
    unittest.main()
