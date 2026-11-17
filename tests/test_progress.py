"""Tests for src/progress.py: computeProgress over the mixed-states checklist fixture.
Plain unittest, standard library only."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.progress import computeProgress

FIXTURE_PATH = ROOT / "tests" / "fixtures" / "mixed-states-checklist.json"
EXCLUDE_REASONS = {"blocked", "archived", "needs-clarification"}


class ProgressTest(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        self.pieces = self.fixture["pieces"]
        self.expected = self.fixture["expected"]
        self.result = computeProgress(self.pieces)
        self.excluded_list = self.result["excluded"]
        self.excluded = {e["id"]: e["reason"] for e in self.excluded_list}

    def counted_ids(self):
        # counted and ticked are integer counts; a piece is counted unless it is excluded.
        return {p["id"] for p in self.pieces} - set(self.excluded)

    def test_merged_then_archived_is_ticked_and_counted(self):
        merged_archived = [p["id"] for p in self.pieces
                           if p["state"] == "archived" and p.get("mergeRef")]
        self.assertEqual(len(merged_archived), 1)
        pid = merged_archived[0]
        self.assertIn(pid, self.counted_ids())
        self.assertNotIn(pid, self.excluded)
        ticked_expected = len([p for p in self.pieces if p.get("mergeRef")])
        self.assertEqual(self.result["ticked"], ticked_expected)
        self.assertEqual(self.result["ticked"], self.expected["ticked"])

    def test_total_equals_piece_count(self):
        self.assertEqual(self.result["total"], len(self.pieces))
        self.assertEqual(self.result["total"], self.expected["total"])

    def test_group_headers_sum_to_card(self):
        header_total = header_counted = header_ticked = 0
        for group in self.fixture["groups"]:
            subset = [p for p in self.pieces if p["group"] == group]
            subset_ids = {p["id"] for p in subset}
            r = computeProgress(subset)
            self.assertEqual(r["total"], len(subset))
            group_excluded = {e["id"] for e in self.excluded_list if e["id"] in subset_ids}
            self.assertEqual({e["id"] for e in r["excluded"]}, group_excluded)
            header_total += r["total"]
            header_counted += len(subset) - len(r["excluded"])
            header_ticked += r["ticked"]
        self.assertEqual(header_total, self.result["total"])
        self.assertEqual(header_counted, self.expected["counted"])
        self.assertEqual(header_ticked, self.result["ticked"])

    def test_blocked_and_archived_without_merge_not_counted(self):
        for p in self.pieces:
            if p["state"] == "blocked" or (p["state"] == "archived" and not p.get("mergeRef")):
                self.assertNotIn(p["id"], self.counted_ids())
                self.assertIn(p["id"], self.excluded)

    def test_every_excluded_piece_listed_with_reason(self):
        # no piece is dropped silently and no id is listed twice
        self.assertEqual(len(self.excluded_list), len(self.excluded))
        not_counted = {p["id"] for p in self.pieces} - self.counted_ids()
        self.assertEqual(set(self.excluded), not_counted)
        for pid, reason in self.excluded.items():
            self.assertIn(reason, EXCLUDE_REASONS)
        expected = {e["id"]: e["reason"] for e in self.expected["excluded"]}
        self.assertEqual(self.excluded, expected)
        self.assertEqual(len(self.counted_ids()), self.expected["counted"])


if __name__ == "__main__":
    unittest.main()
