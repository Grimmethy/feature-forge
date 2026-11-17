"""Tests for repo_create.unregistered_repos: lists repo folders under the projects root that are not registered, skips pipeline/manual and similar folders, and memoises on the root's mtime. Plain unittest, standard library only."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.core import filing, repo_create


class UnregisteredReposTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = self.tmp / "projects"
        self.root.mkdir()
        self.reg = self.tmp / "projects.json"
        self.reg.write_text(json.dumps([{"repoRoot": "/r/registered-repo", "pipelineDir": "/p/x", "domainsPath": "/p/x/d.json", "label": "registered-repo"}]))
        patcher = mock.patch.object(filing, "projects_path", return_value=self.reg)
        patcher.start()
        self.addCleanup(patcher.stop)
        repo_create._unreg_cache.clear()
        self.addCleanup(repo_create._unreg_cache.clear)
        for name in ["new-repo", "registered-repo", "foo-pipeline", "foo-manual"]:
            (self.root / name).mkdir()

    def test_lists_unregistered_repo(self):
        result = repo_create.unregistered_repos(str(self.root))
        self.assertIsInstance(result, list)
        self.assertIn("new-repo", result)

    def test_omits_registered_repo(self):
        result = repo_create.unregistered_repos(str(self.root))
        self.assertNotIn("registered-repo", result)

    def test_ignores_pipeline_and_manual(self):
        result = repo_create.unregistered_repos(str(self.root))
        self.assertNotIn("foo-pipeline", result)
        self.assertNotIn("foo-manual", result)

    def test_keeps_pipeline_ops_repo_and_excludes_its_pipeline_dir(self):
        (self.root / "agent-manager-pipeline-ops").mkdir()
        (self.root / "agent-manager-pipeline-ops-pipeline").mkdir()
        result = repo_create.unregistered_repos(str(self.root))
        self.assertIn("agent-manager-pipeline-ops", result)
        self.assertNotIn("agent-manager-pipeline-ops-pipeline", result)

    def test_result_is_sorted(self):
        result = repo_create.unregistered_repos(str(self.root))
        self.assertEqual(result, sorted(result))
        self.assertEqual(result, ["new-repo"])

    def test_unchanged_stats_does_not_relist(self):
        with mock.patch.object(repo_create, "_list_dir", wraps=os.listdir) as lister:
            first = repo_create.unregistered_repos(str(self.root))
            second = repo_create.unregistered_repos(str(self.root))
            self.assertEqual(first, second)
            self.assertEqual(lister.call_count, 1)

    def test_mtime_bump_relists(self):
        with mock.patch.object(repo_create, "_list_dir", wraps=os.listdir) as lister:
            repo_create.unregistered_repos(str(self.root))
            self.assertEqual(lister.call_count, 1)
            st = os.stat(self.root)
            os.utime(self.root, (st.st_atime, st.st_mtime + 10))
            result = repo_create.unregistered_repos(str(self.root))
            self.assertEqual(lister.call_count, 2)
            self.assertEqual(result, ["new-repo"])


if __name__ == "__main__":
    unittest.main()
