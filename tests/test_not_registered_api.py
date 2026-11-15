"""Tests for the not-registered API behaviour: the 409 handler, POST /api/repos/create on an existing repo,
GET /api/repos 'registered' flags and GET /api/repos/unregistered. The command runner and the registry are faked
in a temp dir. Plain unittest; skipped where flask or markdown is not installed."""
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
    from server.core import filing, repo_create
except ImportError:
    appmod = None


def _items(body):
    """A list response, or a dict wrapping one under a common key."""
    if isinstance(body, list):
        return body
    for key in ("repos", "items", "names"):
        if isinstance(body.get(key), list):
            return body[key]
    raise AssertionError(f"no list in response: {body!r}")


@unittest.skipIf(appmod is None, "flask and markdown are not installed")
class NotRegisteredApiTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        t = Path(tmp.name)
        self.repos = t / "repos"
        self.repos.mkdir()
        # a registered repo (with a git dir and origin), an existing but unregistered repo, and a new one
        for name in ("registered-repo", "existing-repo"):
            (self.repos / name / ".git").mkdir(parents=True)
        (self.repos / "new-repo").mkdir()
        self.reg = t / "projects.json"
        self.reg.write_text(json.dumps([{
            "repoRoot": str(self.repos / "registered-repo"),
            "pipelineDir": str(t / "registered-repo-pipeline"),
            "domainsPath": str(t / "registered-repo-pipeline" / "task-domains.json"),
            "label": "registered-repo",
        }]))
        core = t / "am"
        core.mkdir()
        (core / "task-domains.json").write_text("{}")
        self.calls = []

        def run(cmd, **kw):
            self.calls.append(cmd)
            if cmd[:2] == ["git", "init"]:
                (Path(cmd[-1]) / ".git").mkdir(parents=True, exist_ok=True)
            # 'git remote get-url origin' succeeds, so an existing repo counts as having an origin
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        saved = (repo_create.runner, filing.AM_CORE, os.environ.get("FEATUREFORGE_PROJECTS"),
                 os.environ.get("FEATUREFORGE_REPOS_ROOT"))
        repo_create.runner, filing.AM_CORE = run, core
        os.environ["FEATUREFORGE_PROJECTS"] = str(self.reg)
        os.environ["FEATUREFORGE_REPOS_ROOT"] = str(self.repos)
        repo_create._unreg_cache.clear()

        def restore():
            repo_create.runner, filing.AM_CORE = saved[0], saved[1]
            for k, v in (("FEATUREFORGE_PROJECTS", saved[2]), ("FEATUREFORGE_REPOS_ROOT", saved[3])):
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
            repo_create._unreg_cache.clear()
        self.addCleanup(restore)

        self.app = appmod.create_app(t / "features")
        # a test-only route that raises the not-registered error, so the 409 handler is exercised directly
        def _raise_unregistered():
            raise filing.NotRegisteredError("new-repo")
        self.app.add_url_rule("/_test/unregistered", "_test_unregistered", _raise_unregistered)
        self.client = self.app.test_client()

    def test_filing_an_unregistered_repo_is_409_with_the_plan(self):
        r = self.client.get("/_test/unregistered")
        self.assertEqual(r.status_code, 409)
        body = r.get_json()
        self.assertEqual(body["code"], "not-registered")
        self.assertEqual(body["repo"], "new-repo")
        self.assertIn("error", body)
        self.assertEqual(body["steps"], repo_create.plan("new-repo"))
        self.assertEqual([s["id"] for s in body["steps"]], ["git", "github", "register", "pipeline"])

    def test_create_on_an_existing_repo_runs_only_register_and_pipeline(self):
        original = self.reg.read_text()
        r = self.client.post("/api/repos/create", json={"name": "existing-repo", "confirm": True})
        self.assertEqual(r.status_code, 200)
        steps = {s["id"]: s["result"] for s in r.get_json()["steps"]}
        self.assertEqual(steps["git"], "skipped (already done)")
        self.assertEqual(steps["github"], "skipped (already done)")
        self.assertEqual(steps["register"], "done")
        self.assertEqual(steps["pipeline"], "done")
        self.assertFalse(any(c[0] == "gh" for c in self.calls))
        # the backup of projects.json is taken before the registry is rewritten: it holds the original text
        backups = list(self.reg.parent.glob("projects.json.bak-*-before-existing-repo"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), original)
        labels = [p["label"] for p in json.loads(self.reg.read_text())]
        self.assertIn("existing-repo", labels)

    def test_get_repos_marks_registered_with_a_boolean(self):
        r = self.client.get("/api/repos")
        self.assertEqual(r.status_code, 200)
        entries = _items(r.get_json())
        by_name = {}
        for e in entries:
            name = e.get("name") or e.get("label")
            self.assertIsInstance(e.get("registered"), bool, f"'registered' not a boolean in {e!r}")
            by_name[name] = e["registered"]
        # every listed repo is flagged by whether it is in the registry; only 'registered-repo' is registered
        self.assertIn("registered-repo", by_name)
        for name, flag in by_name.items():
            self.assertIs(flag, name == "registered-repo", f"wrong 'registered' flag for {name!r}")

    def test_get_unregistered_lists_only_unregistered_names(self):
        r = self.client.get("/api/repos/unregistered")
        self.assertEqual(r.status_code, 200)
        names = set(_items(r.get_json()) if not isinstance(r.get_json(), list) else r.get_json())
        self.assertEqual(names, {"new-repo", "existing-repo"})
        self.assertNotIn("registered-repo", names)


if __name__ == "__main__":
    unittest.main()
