import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

from progress import computeProgress  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "mixed-states-checklist.json")


class MixedStatesFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(FIXTURE, encoding="utf-8") as fh:
            cls.data = json.load(fh)
        cls.result = computeProgress(cls.data["pieces"])

    def test_merged_then_archived_piece_is_ticked_not_excluded(self):
        p3 = [p for p in self.data["pieces"] if p["id"] == "p3"]
        self.assertEqual(len(p3), 1)
        self.assertEqual(p3[0]["state"], "archived")
        self.assertIn("mergeRef", p3[0])
        self.assertNotIn("p3", [e["id"] for e in self.result["excluded"]])
        self.assertEqual(self.result["ticked"], self.data["expected"]["ticked"])

    def test_result_matches_expected(self):
        exp = self.data["expected"]
        self.assertEqual(self.result["total"], exp["total"])
        self.assertEqual(self.result["counted"], exp["counted"])
        self.assertEqual(self.result["ticked"], exp["ticked"])
        self.assertEqual(self.result["excluded"], exp["excluded"])

    def test_fixture_shape_and_values(self):
        valid_states = {"pending", "drafting", "review", "blocked", "done", "merged",
                        "archived", "needs-clarification", "awaiting-confirm",
                        "coordinating", "approved", "adhoc"}
        valid_reasons = {"blocked", "archived", "needs-clarification"}
        pieces = self.data["pieces"]
        self.assertEqual(len(pieces), 6)
        self.assertEqual(len({p["group"] for p in pieces}), 2)
        for p in pieces:
            self.assertLessEqual(set(p), {"id", "group", "state", "mergeRef"})
            self.assertIn(p["state"], valid_states)
        for e in self.data["expected"]["excluded"]:
            self.assertIn(e["reason"], valid_reasons)


if __name__ == "__main__":
    unittest.main()
