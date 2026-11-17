import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from progress import computeProgress  # noqa: E402


class ComputeProgressReturnShapeTests(unittest.TestCase):
    def setUp(self):
        # Inline fixture (not the shared checklist fixture).
        self.pieces = [
            # A: merged then archived -> ticked, absent from excluded.
            {"id": "A", "group": "g1", "state": "archived", "mergeRef": "m1"},
            # B: done with no merge record -> counted, not ticked.
            {"id": "B", "group": "g1", "state": "done"},
            # C: archived with no merge record -> excluded with reason archived.
            {"id": "C", "group": "g2", "state": "archived"},
            # D and E: same state, different groups -> both counted independently.
            {"id": "D", "group": "g1", "state": "pending"},
            {"id": "E", "group": "g2", "state": "pending"},
        ]

    def test_full_return_shape_matches_hand_computed_value(self):
        result = computeProgress(self.pieces)
        expected = {
            "counted": 4,
            "total": 5,
            "ticked": 1,
            "excluded": [{"id": "C", "reason": "archived"}],
        }
        self.assertEqual(result, expected)

    def test_merged_archived_piece_is_ticked_and_not_excluded(self):
        result = computeProgress(self.pieces)
        excluded_ids = [entry["id"] for entry in result["excluded"]]
        self.assertNotIn("A", excluded_ids)
        self.assertEqual(result["ticked"], 1)

    def test_every_excluded_entry_has_valid_shape_and_reason(self):
        result = computeProgress(self.pieces)
        valid_reasons = {"blocked", "archived", "needs-clarification"}
        for entry in result["excluded"]:
            self.assertEqual(set(entry.keys()), {"id", "reason"})
            self.assertIn(entry["reason"], valid_reasons)


if __name__ == "__main__":
    unittest.main()
