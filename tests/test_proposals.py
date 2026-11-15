"""Tests for server/core/proposals.py: dismissal_key determinism, load from
missing dir, append + append grows the file by one line, and the cross-repo
dedup case (same title, different why, different repos -> distinct keys and
both appear in load_dismissals).
"""
import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.core import proposals

SAMPLE_NOW = datetime(2026, 6, 15, 12, 30, 0, tzinfo=timezone.utc)


class ProposalsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name

    def test_dismissal_key_is_sha256_of_title_newline_why(self):
        expected = hashlib.sha256(b"hello\nworld").hexdigest()
        self.assertEqual(proposals.dismissal_key("hello", "world"), expected)

    def test_dismissal_key_is_deterministic(self):
        self.assertEqual(
            proposals.dismissal_key("a", "b"),
            proposals.dismissal_key("a", "b"),
        )

    def test_dismissal_key_distinguishes_title_vs_why(self):
        # Same words swapped -> different hash.
        self.assertNotEqual(
            proposals.dismissal_key("title", "why"),
            proposals.dismissal_key("why", "title"),
        )

    def test_load_dismissals_on_missing_dir_returns_empty_set(self):
        self.assertEqual(proposals.load_dismissals("/nonexistent/dir/xyz"), set())

    def test_load_dismissals_on_empty_dir_returns_empty_set(self):
        self.assertEqual(proposals.load_dismissals(self.dir), set())

    def test_append_creates_one_json_line_with_all_five_fields(self):
        proposals.append_dismissal(self.dir, "r", "1", "T", "W", SAMPLE_NOW)
        path = Path(self.dir) / "dismissals.jsonl"
        self.assertTrue(path.is_file())
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln]
        self.assertEqual(len(lines), 1)
        obj = json.loads(lines[0])  # noqa: F821 (json is stdlib, linter quirk)
        self.assertEqual(obj, {
            "repo": "r",
            "id": "1",
            "key": proposals.dismissal_key("T", "W"),
            "title": "T",
            "dismissedAt": SAMPLE_NOW.isoformat(),
        })

    def test_second_append_grows_file_by_one_line(self):
        proposals.append_dismissal(self.dir, "r", "1", "T1", "W1", SAMPLE_NOW)
        proposals.append_dismissal(self.dir, "r", "2", "T2", "W2", SAMPLE_NOW)
        path = Path(self.dir) / "dismissals.jsonl"
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln]
        self.assertEqual(len(lines), 2)

    def test_load_returns_all_five_fields(self):
        proposals.append_dismissal(self.dir, "repo-a", "id-7", "Keep it", "saves time", SAMPLE_NOW)
        keys = proposals.load_dismissals(self.dir)
        self.assertEqual(keys, {("repo-a", "id-7", proposals.dismissal_key("Keep it", "saves time"))})

    def test_cross_repo_same_title_different_why_both_appear(self):
        """Two proposals with identical title but different why in different
        repos produce distinct keys and both appear in load_dismissals.

        This is the case the contract calls out: a proposal whose title is
        identical across two repos (e.g. "Add rate limiter") but whose why
        differs.  The key includes both fields, so the two dismissals are
        distinct -- neither masks the other.
        """
        proposals.append_dismissal(self.dir, "auth-service", "42", "Add rate limiter", "prevent abuse", SAMPLE_NOW)
        proposals.append_dismissal(self.dir, "search-service", "9", "Add rate limiter", "save tokens", SAMPLE_NOW)
        keys = proposals.load_dismissals(self.dir)
        self.assertEqual(len(keys), 2)
        # Each (repo, id, key) is unique.
        for repo, rid, key in keys:
            self.assertEqual(key, proposals.dismissal_key("Add rate limiter",
                                                          "prevent abuse" if repo == "auth-service" else "save tokens"))
        # And the keys themselves differ.
        distinct_keys = {k for _, _, k in keys}
        self.assertEqual(len(distinct_keys), 2)

    def test_dedup_same_repo_id_key_returns_once(self):
        """Appending the same (repo, id, title, why) twice yields one entry
        in the loaded set, because the tuple (repo, id, key) deduplicates."""
        proposals.append_dismissal(self.dir, "r", "1", "T", "W", SAMPLE_NOW)
        proposals.append_dismissal(self.dir, "r", "1", "T", "W", SAMPLE_NOW)
        self.assertEqual(len(proposals.load_dismissals(self.dir)), 1)


if __name__ == "__main__":
    unittest.main()
