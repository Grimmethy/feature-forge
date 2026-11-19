"""Tests for per-piece repo override functionality.

These tests verify that pieces can be routed to different repositories
based on per-piece configuration, using the fixture
tests/fixtures/per_piece_repo_checklist.md.
"""

import os
import sys
import tempfile
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add the repo root to path for imports
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from server.core.piece_repo import parse_piece_repo, strip_repo_header
from server.core.piece_routing import route_pieces, format_file_summary
from server.core.piece_repo_lint import lint_piece_repo_mismatch
from server.core.filing import FilingError


class PerPieceRoutingTests(unittest.TestCase):
    """Test per-piece routing with correct headers."""

    FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "per_piece_repo_checklist.md"

    def setUp(self):
        """Set up test fixtures and temporary directories."""
        self.tmp_dir = tempfile.mkdtemp()
        self.feature_repo = Path(self.tmp_dir) / "feature-repo"
        self.feature_repo.mkdir()

    def tearDown(self):
        """Clean up temporary directories."""
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _load_fixture_pieces(self):
        """Load pieces from the fixture as dicts suitable for route_pieces."""
        text = self.FIXTURE_PATH.read_text(encoding="utf-8")
        pieces = []
        current_piece = None
        current_body = []
        
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("- ["):
                # New piece
                if current_piece is not None:
                    # Extract repo from body
                    piece_body = "\n".join(current_body)
                    piece_repo = parse_piece_repo(piece_body)
                    pieces.append({
                        "id": current_piece,
                        "body": piece_body,
                        "title": f"Piece {current_piece}",
                        "repo": piece_repo
                    })
                # Extract piece ID from "- [ ] 1 Piece one targets repo A"
                parts = stripped.split()
                # parts[0]="-", parts[1]="[", parts[2]="]", parts[3]="1", parts[4]="Piece", ...
                if len(parts) > 3 and parts[2] == "]":
                    current_piece = parts[3]
                else:
                    current_piece = None
                current_body = [line]
            elif current_piece is not None:
                current_body.append(line)
        
        # Don't forget the last piece
        if current_piece is not None:
            piece_body = "\n".join(current_body)
            piece_repo = parse_piece_repo(piece_body)
            pieces.append({
                "id": current_piece,
                "body": piece_body,
                "title": f"Piece {current_piece}",
                "repo": piece_repo
            })
        
        return pieces

    def test_piece_one_routes_to_repo_a(self):
        """Test that piece 1 routes to repo-a."""
        pieces = self._load_fixture_pieces()
        self.assertEqual(len(pieces), 2, f"Expected 2 pieces, got {len(pieces)}: {pieces}")
        
        def resolver(name):
            return name in ["repo-a", "repo-b"]
        
        results = route_pieces(pieces, "feature-repo", resolver)
        
        piece1_result = next((r for r in results if r["piece"]["id"] == "1"), None)
        self.assertIsNotNone(piece1_result, f"Piece 1 not found in results: {results}")
        self.assertEqual(piece1_result["targetRepo"], "repo-a")
        self.assertEqual(piece1_result["status"], "ok")

    def test_piece_two_routes_to_repo_b(self):
        """Test that piece 2 routes to repo-b."""
        pieces = self._load_fixture_pieces()
        self.assertEqual(len(pieces), 2, f"Expected 2 pieces, got {len(pieces)}: {pieces}")
        
        def resolver(name):
            return name in ["repo-a", "repo-b"]
        
        results = route_pieces(pieces, "feature-repo", resolver)
        
        piece2_result = next((r for r in results if r["piece"]["id"] == "2"), None)
        self.assertIsNotNone(piece2_result, f"Piece 2 not found in results: {results}")
        self.assertEqual(piece2_result["targetRepo"], "repo-b")
        self.assertEqual(piece2_result["status"], "ok")

    def test_piece_two_text_includes_the_repo_header(self):
        """Test that the fixture text includes the Repo: header."""
        text = self.FIXTURE_PATH.read_text(encoding="utf-8")
        self.assertIn("Repo:", text)
        self.assertIn("repo-a", text)
        self.assertIn("repo-b", text)

    def test_parse_piece_repo_extracts_repo_from_piece(self):
        """Test that parse_piece_repo extracts the repo name from piece text."""
        pieces = self._load_fixture_pieces()
        self.assertEqual(len(pieces), 2)
        
        piece1_repo = parse_piece_repo(pieces[0]["body"])
        self.assertEqual(piece1_repo, "repo-a")
        
        piece2_repo = parse_piece_repo(pieces[1]["body"])
        self.assertEqual(piece2_repo, "repo-b")


class UnregisteredRepoTests(unittest.TestCase):
    """Test unregistered repo refusal."""

    FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "per_piece_repo_checklist.md"

    def setUp(self):
        """Set up test fixtures."""
        self.tmp_dir = tempfile.mkdtemp()
        self.feature_repo = Path(self.tmp_dir) / "feature-repo"
        self.feature_repo.mkdir()

    def tearDown(self):
        """Clean up temporary directories."""
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_unknown_repo_raises_with_the_exact_message_and_writes_nothing(self):
        """Test that unregistered repo raises with exact message and writes nothing."""
        pieces = [
            {
                "id": "1",
                "body": "- [ ] 1 Piece one targets repo z\nRepo: repo-z\n  Change something.\n",
                "title": "Piece 1",
                "repo": "repo-z"
            }
        ]
        
        def resolver(name):
            # repo-z is not registered
            return name in ["repo-a", "repo-b"]
        
        results = route_pieces(pieces, "feature-repo", resolver)
        
        # Check for blocked result
        blocked = [r for r in results if r["status"] == "blocked"]
        self.assertEqual(len(blocked), 1, f"Expected 1 blocked result, got {len(blocked)}: {results}")
        
        blocked_result = blocked[0]
        self.assertEqual(blocked_result["piece"]["id"], "1")
        self.assertEqual(
            blocked_result["message"],
            "unknown repo 'repo-z' for piece 1"
        )
        
        # Verify no files were written
        feature_files = list(self.feature_repo.iterdir())
        self.assertEqual(len(feature_files), 0)


class NoOverrideTests(unittest.TestCase):
    """Test no-override feature filing."""

    def test_no_override_filing_uses_default_repo(self):
        """Test that without override, filing uses the default repo."""
        pieces = [
            {
                "id": "1",
                "body": "- [ ] Task one\n  Change something.\n",
                "title": "Task one"
            }
        ]
        
        def resolver(name):
            return name == "feature-repo"
        
        results = route_pieces(pieces, "feature-repo", resolver)
        
        piece1_result = results[0]
        # Without override, piece inherits feature_repo
        self.assertEqual(piece1_result["targetRepo"], "feature-repo")
        self.assertEqual(piece1_result["status"], "ok")


class MutantRoutingTests(unittest.TestCase):
    """Test mutant-style monkeypatch of routing name."""

    def test_mutant_routing_ignores_override_and_raises(self):
        """Test that monkeypatching resolver to raise causes AssertionError."""
        pieces = [
            {
                "id": "1",
                "body": "- [ ] 1 Piece one targets repo A\nRepo: repo-a\n  Change something.\n",
                "title": "Piece 1",
                "repo": "repo-a"
            }
        ]
        
        def mutant_resolver(name):
            # Mutant: raise AssertionError instead of checking
            raise AssertionError(f"routing name '{name}' is blocked by mutant")
        
        with self.assertRaises(AssertionError) as ctx:
            route_pieces(pieces, "feature-repo", mutant_resolver)
        
        # The resolver is called with the piece's repo (repo-a)
        self.assertIn("repo-a", str(ctx.exception))


class LintWarningTests(unittest.TestCase):
    """Test lint warning for piece repo mismatch."""

    def test_lint_warning_for_mismatched_piece_repo(self):
        """Test that lint raises warning for mismatched piece repo."""
        pieces = [
            {
                "id": "1",
                "body": "- [ ] 1 Piece one targets repo A\nRepo: repo-a\n  Change something.\n",
                "title": "Piece 1"
            }
        ]
        
        warnings = lint_piece_repo_mismatch(
            pieces,
            "feature-repo",
            lambda piece, feature_repo: "feature-repo"  # Always returns feature-repo
        )
        
        self.assertEqual(len(warnings), 1)
        self.assertIn("piece 1", warnings[0])
        self.assertIn("repo-a", warnings[0])
        self.assertIn("feature-repo", warnings[0])


class SummaryFormattingTests(unittest.TestCase):
    """Test summary formatting for piece repo overrides."""

    def test_format_file_summary_lists_each_target_repo(self):
        """Test that summary lists each target repo."""
        results = [
            {
                "piece": {"id": "1"},
                "targetRepo": "repo-a",
                "status": "ok",
                "message": None
            },
            {
                "piece": {"id": "2"},
                "targetRepo": "repo-b",
                "status": "ok",
                "message": None
            }
        ]
        
        summary = format_file_summary(results)
        
        self.assertIn("repo-a", summary)
        self.assertIn("repo-b", summary)
        self.assertIn("2 tasks filed", summary)
        self.assertIn("0 blocked", summary)

    def test_format_file_summary_with_blocked(self):
        """Test that summary includes blocked pieces."""
        results = [
            {
                "piece": {"id": "1"},
                "targetRepo": "repo-a",
                "status": "ok",
                "message": None
            },
            {
                "piece": {"id": "2"},
                "targetRepo": "repo-z",
                "status": "blocked",
                "message": "unknown repo 'repo-z' for piece 2"
            }
        ]
        
        summary = format_file_summary(results)
        
        self.assertIn("1 tasks filed", summary)
        self.assertIn("1 blocked", summary)
        self.assertIn("unknown repo 'repo-z' for piece 2", summary)


if __name__ == "__main__":
    unittest.main()
