"""Lint a piece's own ``Repo: X`` text against the file target it would be filed to.

Pure function only: no I/O, no timers or threads, no globals, no model calls, and the
inputs are not mutated.

Resolver contract: ``resolver(piece, feature_repo) -> str`` returns the repo name the piece
would actually be filed to. ``piece`` is the same object that appears in ``pieces`` and
``feature_repo`` is the feature's repo name. The resolver is called once per piece that
declares a repo, and it must itself be pure.

Rule: a piece with no ``Repo:`` line (or repo marker) emits nothing. A piece with one emits
exactly one warning when its declared repo differs from the resolver's target.

Piece shape: a dict with ``id`` and ``body`` (a string, or a list of lines). ``title`` is
optional. The declared repo is parsed with ``piece_repo.parse_piece_repo``.

Warnings are plain strings that contain the piece id, so callers can key them by piece.
"""
from __future__ import annotations

from .piece_repo import parse_piece_repo


def _piece_text(piece) -> str:
    body = piece.get("body") or ""
    if isinstance(body, list):
        body = "\n".join(body)
    title = piece.get("title") or ""
    return f"{title}\n{body}"


def lint_piece_repo_mismatch(pieces, feature_repo, resolver) -> list[str]:
    """Return one warning string per piece whose ``Repo: X`` differs from its file target.

    Pieces with no ``Repo:`` line produce nothing. The result is in input order.
    """
    warnings: list[str] = []
    for piece in pieces:
        declared = parse_piece_repo(_piece_text(piece))
        if declared is None:
            continue
        target = resolver(piece, feature_repo)
        if declared != target:
            warnings.append(
                f"piece {piece['id']}: Repo '{declared}' differs from file target '{target}'"
            )
    return warnings
