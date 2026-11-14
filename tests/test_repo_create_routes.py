"""Tests for the repo creation routes through Flask's test client, with the command runner and registry faked. Plain unittest;
skipped where flask or markdown is not installed."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from server import app as appmod
    from server.core import filing, grill, repo_create
except ImportError:
    appmod = None


@unittest.skipIf(appmod is None, "flask and markdown are not installed")
class RepoRouteTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        t = Path(tmp.name)
        self.repos = t / "repos"
        self.repos.mkdir()
        reg = t / "projects.json"
        reg.write_text("[]")
        core = t / "am"
        core.mkdir()
        (core / "task-domains.json").write_text("{}")
        self.calls = []

        def run(cmd, **kw):
            self.calls.append(cmd)
            if cmd[:2] == ["git", "init"]:
                (Path(cmd[-1]) / ".git").mkdir(parents=True, exist_ok=True)
            return SimpleNamespace(returncode=1 if "get-url" in cmd else 0, stdout="", stderr="")
        saved = (repo_create.runner, filing.AM_CORE, os.environ.get("FEATUREFORGE_PROJECTS"), os.environ.get("FEATUREFORGE_REPOS_ROOT"))
        repo_create.runner, filing.AM_CORE = run, core
        os.environ["FEATUREFORGE_PROJECTS"], os.environ["FEATUREFORGE_REPOS_ROOT"] = str(reg), str(self.repos)

        def restore():
            repo_create.runner, filing.AM_CORE = saved[0], saved[1]
            for k, v in (("FEATUREFORGE_PROJECTS", saved[2]), ("FEATUREFORGE_REPOS_ROOT", saved[3])):
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self.addCleanup(restore)
        self.client = appmod.create_app(t / "features").test_client()
        self.reg = reg

    def test_plan_shows_the_steps_and_changes_nothing(self):
        r = self.client.get("/api/repos/plan?name=brand-new")
        self.assertEqual([s["id"] for s in r.get_json()["steps"]], ["git", "github", "register", "pipeline"])
        self.assertFalse(any(c[0] == "gh" for c in self.calls))
        self.assertEqual(json.loads(self.reg.read_text()), [])

    def test_plan_of_a_bad_name_is_400(self):
        self.assertEqual(self.client.get("/api/repos/plan?name=../x").status_code, 400)
        self.assertEqual(self.client.get("/api/repos/plan").status_code, 400)

    def test_create_needs_the_explicit_confirm(self):
        for body in ({"name": "brand-new"}, {"name": "brand-new", "confirm": "yes"}, {"name": "brand-new", "confirm": False}):
            with self.subTest(body=body):
                self.assertEqual(self.client.post("/api/repos/create", json=body).status_code, 400)
        self.assertEqual(self.calls, [])

    def test_create_runs_the_steps(self):
        r = self.client.post("/api/repos/create", json={"name": "brand-new", "confirm": True})
        self.assertEqual(r.status_code, 200)
        self.assertEqual([s["result"] for s in r.get_json()["steps"]], ["done"] * 4)
        self.assertEqual([p["label"] for p in json.loads(self.reg.read_text())], ["brand-new"])

    def test_a_failed_step_is_a_400_with_the_reason(self):
        repo_create.runner = lambda cmd, **kw: SimpleNamespace(returncode=1, stdout="", stderr="no git")
        r = self.client.post("/api/repos/create", json={"name": "brand-new", "confirm": True})
        self.assertEqual(r.status_code, 400)
        self.assertIn("git init failed: no git", r.get_json()["error"])


if __name__ == "__main__":
    unittest.main()
