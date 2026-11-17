"""Unit tests for feature_forge.proposal_overlap.find_overlaps.

The overlap module (HUB0038 1/5) is on disk at feature_forge/proposal_overlap.py.
Verified against that module:
- piece dicts read the keys: id, title, files, functions (plus optional description/body)
- title overlap is word-set Jaccard similarity over lowercased words, minus stop words
- a filed piece is flagged when it shares a file path, shares a function name, or
  its title Jaccard similarity is >= threshold
- OVERLAP_THRESHOLD is a float; tests read it from the module and never hard-code it

FIXTURES: the 1f (claim-order audit) and 1g (rank badge, explanation and docs)
groups are SKIPPED with a stated reason. The repo holds only a checklist line naming
1f (features/pipeline-claims-tasks-by-feature-rank-.../checklist.md:16). The report
bodies for 1f and 1g are not in the repo, so no fixture content was invented.

Run: python3 -m unittest tests.test_proposal_overlap
"""

import unittest

from feature_forge.proposal_overlap import find_overlaps, OVERLAP_THRESHOLD


def _piece(pid, title="", files=(), functions=()):
    return {
        "id": pid,
        "title": title,
        "files": list(files),
        "functions": list(functions),
    }


def _title_pair(threshold, above):
    """Build two titles whose word-set Jaccard similarity sits just above
    (above=True, >= threshold) or just below (above=False, < threshold) threshold.
    Two titles of n words sharing k words have similarity k / (2n - k).
    """
    best = None
    for n in range(1, 80):
        for k in range(1, n + 1):
            sim = k / (2 * n - k)
            ok = sim >= threshold if above else sim < threshold
            if not ok:
                continue
            if best is None:
                best = (sim, n, k)
            elif above and sim < best[0]:
                best = (sim, n, k)
            elif not above and sim > best[0]:
                best = (sim, n, k)
    if best is None:
        raise AssertionError("no title pair found for threshold %r" % (threshold,))
    _, n, k = best
    shared = ["shared%d" % i for i in range(k)]
    a = shared + ["alpha%d" % i for i in range(n - k)]
    b = shared + ["beta%d" % i for i in range(n - k)]
    return " ".join(a), " ".join(b)


class FindOverlapsTests(unittest.TestCase):

    def test_shared_file_path_is_flagged(self):
        new = _piece("new", files=["feature_forge/proposal_overlap.py"])
        filed = [
            _piece("f1", files=["feature_forge/proposal_overlap.py"]),
            _piece("f2", files=["unrelated/other.py"]),
        ]
        result = find_overlaps(new, filed, threshold=OVERLAP_THRESHOLD)
        self.assertIn("f1", result)
        self.assertNotIn("f2", result)

    def test_shared_function_name_is_flagged(self):
        new = _piece("new", functions=["parse_rank"])
        filed = [
            _piece("f1", functions=["parse_rank"]),
            _piece("f2", functions=["render_badge"]),
        ]
        result = find_overlaps(new, filed, threshold=OVERLAP_THRESHOLD)
        self.assertIn("f1", result)
        self.assertNotIn("f2", result)

    def test_title_overlap_just_above_threshold_is_flagged(self):
        new_title, filed_title = _title_pair(OVERLAP_THRESHOLD, above=True)
        new = _piece("new", title=new_title)
        filed = [_piece("f1", title=filed_title)]
        self.assertIn("f1", find_overlaps(new, filed, threshold=OVERLAP_THRESHOLD))

    def test_title_overlap_just_below_threshold_is_not_flagged(self):
        new_title, filed_title = _title_pair(OVERLAP_THRESHOLD, above=False)
        new = _piece("new", title=new_title)
        filed = [_piece("f1", title=filed_title)]
        self.assertNotIn("f1", find_overlaps(new, filed, threshold=OVERLAP_THRESHOLD))

    def test_unrelated_piece_is_not_flagged(self):
        new = _piece(
            "new",
            title="tighten retry backoff for sync worker",
            files=["workers/sync.py"],
            functions=["retry_backoff"],
        )
        filed = [
            _piece(
                "f1",
                title="add dark mode toggle to settings page",
                files=["ui/settings.js"],
                functions=["toggleDarkMode"],
            ),
        ]
        self.assertEqual(find_overlaps(new, filed, threshold=OVERLAP_THRESHOLD), [])

    def test_return_is_list_of_filed_ids(self):
        new = _piece("new", files=["feature_forge/proposal_overlap.py"])
        filed = [
            _piece("f1", files=["feature_forge/proposal_overlap.py"]),
            _piece("f2", files=["unrelated/other.py"]),
        ]
        result = find_overlaps(new, filed, threshold=OVERLAP_THRESHOLD)
        self.assertIsInstance(result, list)
        self.assertTrue(all(isinstance(r, str) for r in result))
        filed_ids = {p["id"] for p in filed}
        self.assertTrue(set(result) <= filed_ids)


class ClaimOrderAuditFixtures(unittest.TestCase):
    """1f: claim-order audit and per-task rank reason."""

    @unittest.skip("1f report body not in the repo; only the checklist line title exists")
    def test_1f_claim_order_audit_overlap(self):
        pass


class RankBadgeExplanationDocsFixtures(unittest.TestCase):
    """1g: rank badge, explanation and docs."""

    @unittest.skip("1g report body not located in the repo")
    def test_1g_rank_badge_explanation_docs_overlap(self):
        pass


if __name__ == "__main__":
    unittest.main()
