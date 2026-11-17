"""Parse per-piece repo overrides from feature checklist piece text.

Pure functions only: no I/O, and no imports from filing or checklist.

A piece-level override is a line starting with ``Repo: <name>`` (a trailing
period, as written by filing.py, is tolerated) or an HTML marker
``<!-- repo: name -->``.

Assumption: a feature-header ``Repo:`` line is one that appears before the
first piece line (``- [``) or markdown heading (``#``). Only those header
lines are removed by ``strip_repo_header``; later ``Repo:`` lines are kept.
"""
import re

_REPO_LINE_RE = re.compile(r"^Repo:[ \t]*(\S+?)\.?[ \t]*$")
_REPO_MARKER_RE = re.compile(r"<!--\s*repo:\s*([^\s>]+?)\s*-->", re.IGNORECASE)
_PIECE_START_RE = re.compile(r"^\s*(- \[|#)")


def is_repo_header_line(line: str) -> bool:
    """Return True if ``line`` is a ``Repo: <name>`` line."""
    return _REPO_LINE_RE.match(line.rstrip("\r\n")) is not None


def parse_piece_repo(piece_text: str) -> str | None:
    """Return the repo name from the first ``Repo:`` line or repo marker, else None."""
    for line in piece_text.splitlines():
        m = _REPO_LINE_RE.match(line) or _REPO_MARKER_RE.search(line)
        if m:
            return m.group(1)
    return None


def strip_repo_header(piece_text: str) -> str:
    """Remove feature-header ``Repo:`` lines, i.e. those before the first piece line or heading.

    Lines after the first piece line or ``#`` heading are left unchanged.
    """
    out = []
    in_header = True
    for line in piece_text.splitlines(keepends=True):
        if in_header and _PIECE_START_RE.match(line):
            in_header = False
        if in_header and is_repo_header_line(line):
            continue
        out.append(line)
    return "".join(out)
