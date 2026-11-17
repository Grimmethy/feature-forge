"""Contract tests for src/progress.py computeProgress.

Run with: python3 -I src/progress.test.py -v
"""
import os
import sys
import unittest

# Isolated mode (-I) drops the script directory from sys.path, so add it
# explicitly so that `progress` resolves to src/progress.py.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from progress import computeProgress  # noqa: E402


class ComputeProgressContractTests(unittest.TestCase):
    # Protects merge-precedence ordering: mergeRef is checked before state,
    # so a blocked piece with a merge record is counted and ticked, never excluded.
    def test_merged_blocked_piece_is_ticked_not_excluded(self):
        pieces = [{"id": "a", "group": "g", "state": "blocked", "mergeRef": "m1"}]
        result = computeProgress(pieces)
        excluded_ids = [entry["id"] for entry in result["excluded"]]
        self.assertNotIn("a", excluded_ids)
        self.assertEqual(result["ticked"], 1)
        self.assertEqual(result["counted"], 1)

    def test_archived_without_merge_ref_reports_archived(self):
        pieces = [{"id": "b", "group": "g", "state": "archived"}]
        result = computeProgress(pieces)
        self.assertEqual(result["excluded"], [{"id": "b", "reason": "archived"}])
        self.assertEqual(result["total"], len(pieces))

    def test_duplicate_ids_are_both_excluded(self):
        pieces = [
            {"id": "c", "group": "g", "state": "blocked"},
            {"id": "c", "group": "g", "state": "blocked"},
        ]
        result = computeProgress(pieces)
        self.assertEqual(len(result["excluded"]), 2)
        self.assertEqual([entry["id"] for entry in result["excluded"]], ["c", "c"])

    def test_total_is_zero_for_empty_input(self):
        result = computeProgress([])
        self.assertEqual(result["total"], 0)

    def test_total_equals_length_for_non_empty_input(self):
        pieces = [
            {"id": "d", "group": "g", "state": "pending"},
            {"id": "e", "group": "g", "state": "blocked"},
        ]
        result = computeProgress(pieces)
        self.assertEqual(result["total"], len(pieces))


if __name__ == "__main__":
    unittest.main()
