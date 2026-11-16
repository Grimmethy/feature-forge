import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from progress import computeProgress  # noqa: E402


class MergeFirstTests(unittest.TestCase):
    def test_merged_blocked_piece_is_ticked_not_excluded(self):
        r = computeProgress([{"id": "A", "group": "g", "state": "blocked", "mergeRef": "abc"}])
        self.assertEqual(r["ticked"], 1)
        self.assertEqual(r["excluded"], [])
        self.assertEqual(r["counted"], 1)

    def test_merged_archived_piece_is_ticked_not_excluded(self):
        r = computeProgress([{"id": "A", "group": "g", "state": "archived", "mergeRef": "abc"}])
        self.assertEqual(r["ticked"], 1)
        self.assertEqual(r["excluded"], [])

    def test_empty_mergeref_is_absent(self):
        r = computeProgress([{"id": "A", "group": "g", "state": "blocked", "mergeRef": ""}])
        self.assertEqual(r["ticked"], 0)
        self.assertEqual(r["excluded"], [{"id": "A", "reason": "blocked"}])

    def test_duplicate_ids_are_not_deduplicated(self):
        r = computeProgress([
            {"id": "X", "group": "g", "state": "blocked"},
            {"id": "X", "group": "g", "state": "blocked"},
        ])
        self.assertEqual(len(r["excluded"]), 2)

    def test_state_precedence(self):
        r = computeProgress([{"id": "A", "group": "g", "state": "archived"}])
        self.assertEqual(r["excluded"][0]["reason"], "archived")
        r = computeProgress([{"id": "B", "group": "g", "state": "blocked"}])
        self.assertEqual(r["excluded"][0]["reason"], "blocked")
        r = computeProgress([{"id": "C", "group": "g", "state": "needs-clarification"}])
        self.assertEqual(r["excluded"][0]["reason"], "needs-clarification")

    def test_mixed_input_invariants(self):
        pieces = [
            {"id": "1", "group": "g", "state": "pending"},
            {"id": "2", "group": "g", "state": "blocked"},
            {"id": "3", "group": "g", "state": "done", "mergeRef": "m"},
            {"id": "4", "group": "g", "state": "archived"},
            {"id": "5", "group": "g", "state": "needs-clarification", "mergeRef": "m"},
        ]
        r = computeProgress(pieces)
        self.assertEqual(r["total"], len(pieces))
        self.assertEqual(r["total"], r["counted"] + len(r["excluded"]))
        self.assertEqual(r["ticked"], 2)


if __name__ == "__main__":
    unittest.main()
