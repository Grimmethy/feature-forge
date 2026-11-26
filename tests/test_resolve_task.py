"""Tests for server/core/resolve_task.py: resolveTaskId fallback resolution.

Covers exact match, unique prefix, ambiguous prefix, and no-match cases.
Plain unittest, standard library only.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.core import resolve_task


class ResolveTaskIdTests(unittest.TestCase):
    """Test resolveTaskId with various scenarios."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.pipe = self.tmp / "pipe"
        # Create queue structure
        for state in resolve_task.QUEUE_STATES:
            (self.pipe / "queue" / state).mkdir(parents=True, exist_ok=True)
        # Create archived directories
        (self.pipe / "done" / "_archived_no_action").mkdir(parents=True, exist_ok=True)
        (self.pipe / "done" / "_archived" / "2026-11").mkdir(parents=True, exist_ok=True)

    def _put_task(self, state, task_id, record=None):
        """Helper to write a task JSON file."""
        if record is None:
            record = {"status": state}
        path = self.pipe / "queue" / state / f"{task_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record))

    def _put_archived_task(self, state, task_id, record=None):
        """Helper to write a task JSON file in archived directory."""
        if record is None:
            record = {"status": state}
        path = self.pipe / "done" / state / f"{task_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record))

    def test_exact_match_returns_resolved_with_empty_candidates(self):
        """When the stored_id exactly matches a task file, return it with no candidates."""
        self._put_task("pending", "HUB1234")
        result = resolve_task.resolveTaskId(str(self.pipe), "HUB1234")
        self.assertEqual(result["resolved"], "HUB1234")
        self.assertEqual(result["candidates"], [])

    def test_unique_prefix_match_returns_full_id(self):
        """When only one task starts with stored_id, return the full ID."""
        self._put_task("pending", "HUB1234_full")
        self._put_task("review", "HUB9999_other")
        result = resolve_task.resolveTaskId(str(self.pipe), "HUB1234")
        self.assertEqual(result["resolved"], "HUB1234_full")
        self.assertEqual(result["candidates"], ["HUB1234_full"])

    def test_ambiguous_prefix_returns_unresolved_with_candidates(self):
        """When multiple tasks start with stored_id, return unresolved with candidates."""
        self._put_task("pending", "HUB1234_a")
        self._put_task("review", "HUB1234_b")
        result = resolve_task.resolveTaskId(str(self.pipe), "HUB1234")
        self.assertEqual(result["resolved"], "HUB1234")  # unchanged
        self.assertEqual(sorted(result["candidates"]), ["HUB1234_a", "HUB1234_b"])

    def test_no_match_returns_unresolved_with_empty_candidates(self):
        """When no task matches, return stored_id unchanged with no candidates."""
        self._put_task("pending", "HUB9999")
        result = resolve_task.resolveTaskId(str(self.pipe), "HUB0000")
        self.assertEqual(result["resolved"], "HUB0000")
        self.assertEqual(result["candidates"], [])

    def test_exact_match_in_archived(self):
        """Exact match should be found in archived directories."""
        self._put_archived_task("_archived_no_action", "HUB5678")
        result = resolve_task.resolveTaskId(str(self.pipe), "HUB5678")
        self.assertEqual(result["resolved"], "HUB5678")
        self.assertEqual(result["candidates"], [])

    def test_prefix_match_across_archived(self):
        """Prefix match should search across live and archived directories."""
        self._put_task("pending", "HUB1111_live")
        self._put_archived_task("_archived/2026-11", "HUB2222_arch")
        result = resolve_task.resolveTaskId(str(self.pipe), "HUB1111")
        self.assertEqual(result["resolved"], "HUB1111_live")
        self.assertEqual(result["candidates"], ["HUB1111_live"])

    def test_title_match_fallback(self):
        """When no prefix match, try title field match in JSON records."""
        self._put_task("pending", "HUB9999", {"title": "HUB3333_special_task"})
        self._put_task("review", "HUB8888", {"title": "HUB4444_other_task"})
        result = resolve_task.resolveTaskId(str(self.pipe), "HUB3333")
        self.assertEqual(result["resolved"], "HUB9999")  # resolved to the matching task
        self.assertEqual(result["candidates"], ["HUB9999"])

    def test_empty_pipeline_dir(self):
        """Empty pipeline directory returns unresolved."""
        result = resolve_task.resolveTaskId(str(self.pipe), "HUB9999")
        self.assertEqual(result["resolved"], "HUB9999")
        self.assertEqual(result["candidates"], [])


if __name__ == "__main__":
    unittest.main()
