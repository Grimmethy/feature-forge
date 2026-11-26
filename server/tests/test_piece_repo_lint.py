"""Tests for core.piece_repo_lint (unittest, stdlib only)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import piece_repo_lint  # noqa: E402


def _resolver_to(target):
    return lambda piece, feature_repo: target


class LintPieceRepoMismatchTest(unittest.TestCase):
    def test_matching_repo_returns_empty(self):
        pieces = [{"id": "1a", "title": "t", "body": "Repo: alpha\ndo it"}]
        self.assertEqual(
            piece_repo_lint.lint_piece_repo_mismatch(pieces, "alpha", _resolver_to("alpha")), [])

    def test_mismatched_repo_returns_one_string_with_piece_id(self):
        pieces = [{"id": "2b", "title": "t", "body": "Repo: beta\ndo it"}]
        out = piece_repo_lint.lint_piece_repo_mismatch(pieces, "alpha", _resolver_to("alpha"))
        self.assertEqual(len(out), 1)
        self.assertIn("2b", out[0])
        self.assertIn("beta", out[0])
        self.assertIn("alpha", out[0])

    def test_piece_without_repo_line_returns_empty(self):
        pieces = [{"id": "3c", "title": "t", "body": ["do it", "no repo here"]}]
        self.assertEqual(
            piece_repo_lint.lint_piece_repo_mismatch(pieces, "alpha", _resolver_to("beta")), [])

    def test_multiple_pieces_keyed_by_their_own_ids(self):
        pieces = [
            {"id": "1a", "title": "t", "body": "Repo: alpha"},
            {"id": "1b", "title": "t", "body": "Repo: beta"},
            {"id": "1c", "title": "t", "body": "no repo"},
            {"id": "1d", "title": "t", "body": ["Repo: gamma."]},
        ]
        out = piece_repo_lint.lint_piece_repo_mismatch(pieces, "alpha", _resolver_to("alpha"))
        self.assertEqual(len(out), 2)
        self.assertIn("piece 1b:", out[0])
        self.assertIn("piece 1d:", out[1])
        self.assertNotIn("1a", " ".join(out))
        self.assertNotIn("1c", " ".join(out))

    def test_resolver_receives_piece_and_feature_repo(self):
        seen = []

        def resolver(piece, feature_repo):
            seen.append((piece["id"], feature_repo))
            return "alpha"

        pieces = [{"id": "9z", "title": "t", "body": "Repo: beta"}]
        piece_repo_lint.lint_piece_repo_mismatch(pieces, "feat", resolver)
        self.assertEqual(seen, [("9z", "feat")])

    def test_inputs_are_not_mutated(self):
        pieces = [{"id": "1a", "title": "t", "body": ["Repo: beta"]}]
        snapshot = [dict(p, body=list(p["body"])) for p in pieces]
        piece_repo_lint.lint_piece_repo_mismatch(pieces, "alpha", _resolver_to("alpha"))
        self.assertEqual(pieces, snapshot)


class PieceRepoParsingTest(unittest.TestCase):
    """FF-1: pieces() sets a repo key from a Repo: line, accepting trailing text."""

    def _parse_pieces(self, body_lines):
        """Build a fake item dict and call checklist.pieces() via the lint helper."""
        from core import checklist
        item = {"body": body_lines}
        return checklist.pieces(item)

    def test_bare_repo_line(self):
        """A piece with a bare Repo: line gets repo == 'foo'."""
        pieces = self._parse_pieces(["- [ ] 1a Title", "Repo: foo"])
        self.assertEqual(len(pieces), 1)
        self.assertEqual(pieces[0]["repo"], "foo")

    def test_repo_line_with_trailing_text(self):
        """Repo: name (extra text) resolves to the first token; trailing text still flagged by lint."""
        pieces = self._parse_pieces(["- [ ] 1b Title", "Repo: agent-manager-pipeline-ops (src/x.js)"])
        self.assertEqual(len(pieces), 1)
        self.assertEqual(pieces[0]["repo"], "agent-manager-pipeline-ops")
        # Lint should still warn about trailing text (repo differs from feature repo)
        warnings = piece_repo_lint.lint_piece_repo_mismatch(
            pieces, "other-repo", _resolver_to("other-repo")
        )
        self.assertEqual(len(warnings), 1)
        self.assertIn("agent-manager-pipeline-ops", warnings[0])

    def test_no_repo_line_inherits(self):
        """A piece with no Repo: line has repo == None (caller inherits)."""
        pieces = self._parse_pieces(["- [ ] 1c Title", "just body text"])
        self.assertEqual(len(pieces), 1)
        self.assertIsNone(pieces[0]["repo"])

    def test_indented_body_with_repo_line(self):
        """A Repo: line followed by indented body parses correctly."""
        pieces = self._parse_pieces([
            "- [ ] 1d Title",
            "Repo: repo-d",
            "  indented line 1",
            "  indented line 2",
        ])
        self.assertEqual(len(pieces), 1)
        self.assertEqual(pieces[0]["repo"], "repo-d")
        # Repo: line is included in body for parsing
        self.assertIn("Repo: repo-d", pieces[0]["body"])
        self.assertIn("indented line 1", pieces[0]["body"])
        self.assertIn("indented line 2", pieces[0]["body"])


if __name__ == "__main__":
    unittest.main()
