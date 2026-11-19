"""Tests that the repo picker (repo_create.unregistered_repos) lists agent-manager-pipeline-ops but skips scratch folders. Plain unittest, standard library only."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.core import filing, repo_create

SCRATCH = [
    "agent-manager-pipeline-ops-pipeline",
    "X-manual",
    "X-BACKUP",
    "X-hub-p3",
    "X-wake-others",
    "X-test-tmp",
]


class RepoPickerSkipTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = self.tmp / "projects"
        self.root.mkdir()
        self.reg = self.tmp / "projects.json"
        self.reg.write_text(json.dumps([]))
        patcher = mock.patch.object(filing, "projects_path", return_value=self.reg)
        patcher.start()
        self.addCleanup(patcher.stop)
        repo_create._unreg_cache.clear()
        self.addCleanup(repo_create._unreg_cache.clear)
        for name in ["agent-manager-pipeline-ops"] + SCRATCH:
            (self.root / name).mkdir()

    def test_lists_pipeline_ops_repo(self):
        result = repo_create.unregistered_repos(str(self.root))
        self.assertIn("agent-manager-pipeline-ops", result)

    def test_excludes_scratch_names(self):
        result = repo_create.unregistered_repos(str(self.root))
        for name in SCRATCH:
            with self.subTest(name=name):
                self.assertNotIn(name, result)

    def test_only_real_repo_remains(self):
        result = repo_create.unregistered_repos(str(self.root))
        self.assertEqual(result, ["agent-manager-pipeline-ops"])


if __name__ == "__main__":
    unittest.main()
