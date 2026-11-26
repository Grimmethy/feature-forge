"""Tests for checklist writer preserving full task IDs (HUB0085 · 1/3).

The writer in server/core/checklist.py must store the full task ID without
truncation. These tests verify that short, long, and special-character IDs
are preserved exactly as provided.
"""
import unittest
from server.core import checklist


class TestChecklistWriterFullId(unittest.TestCase):
    """Verify the checklist writer never truncates task IDs."""

    def test_short_id_preserved(self):
        """Short IDs (<=10 chars) must be stored unchanged."""
        item = checklist._new_item([], {"title": "Test item", "body": []})
        item["meta"]["task"] = "FF-1"
        item["dirty"] = True
        entries = [item]
        rendered = checklist.render(entries)
        self.assertIn("task: FF-1", rendered)
        self.assertNotIn("task: FF-1...", rendered)

    def test_long_id_preserved(self):
        """Long IDs (>10 chars) must be stored in full, no truncation."""
        long_id = "adhoc-ff-1-this-is-a-very-long-task-id-12345"
        item = checklist._new_item([], {"title": "Test item", "body": []})
        item["meta"]["task"] = long_id
        item["dirty"] = True
        entries = [item]
        rendered = checklist.render(entries)
        self.assertIn(f"task: {long_id}", rendered)
        self.assertNotIn("...", rendered)

    def test_special_chars_preserved(self):
        """IDs with special characters must be stored exactly."""
        special_id = "TASK-12345!@#$%"
        item = checklist._new_item([], {"title": "Test item", "body": []})
        item["meta"]["task"] = special_id
        item["dirty"] = True
        entries = [item]
        rendered = checklist.render(entries)
        self.assertIn(f"task: {special_id}", rendered)
        self.assertNotIn("task: TASK-12345...", rendered)


if __name__ == "__main__":
    unittest.main()
