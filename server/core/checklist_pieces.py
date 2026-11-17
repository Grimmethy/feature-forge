"""Piece-block split / join helpers for checklist item bodies.

Syntax source: ``server/core/checklist.py`` -- ``PIECE_RE`` and
``PIECE_LABEL_RE``.  A piece line in an item body looks like::

    - [ ] 4a Some title <!-- key: value -->

where ``PIECE_RE`` is ``r"^- \\[( |x|X)\\] (.+?)\\s*(?:<!--(.*?)-->)?\\s*$"``
and ``PIECE_LABEL_RE`` is ``r"^(\\d+[a-z]*\\d*)\\s+(.+)$"``.

A piece block is the piece line plus every following line (including the
piece's own indented body text) up to, but not including, the next piece
line (or end of body).  Trailing non-piece text after the last piece is
kept as part of the last block's raw string so that
``join_item_body(*split_item_body(b)) == b`` holds exactly.
"""

from __future__ import annotations

import re

# Mirror the regexes from server/core/checklist.py (verified there).
_PIECE_RE = re.compile(r"^- \[( |x|X)\] (.+?)\s*(?:<!--(.*?)-->)?\s*$")
_PIECE_LABEL_RE = re.compile(r"^(\d+[a-z]*\d*)\s+(.+)$")


def split_item_body(body: str) -> tuple[str, list[str]]:
    """Split an item body into ``(lead_text, piece_blocks)``.

    * ``lead_text`` is everything before the first piece line (possibly
      empty or just whitespace).
    * ``piece_blocks`` is a list of raw strings; each starts with a piece
      line (``- [ ] ...`` or ``- [x] ...``) and extends to the line just
      before the next piece line, or to the end of ``body``.

    A body with no piece lines returns ``(body, [])``.  The split is
    byte-exact: ``"".join(lead + "".join(blocks)) == body``.
    """
    # Use splitlines(keepends=True) so every line keeps its original
    # separator (\n or \r\n).  Concatenation then reproduces the body
    # byte-for-byte -- no separator is ever lost between or within blocks.
    lines = body.splitlines(keepends=True)
    lead_parts: list[str] = []
    blocks: list[str] = []
    cur: list[str] | None = None

    for line in lines:
        if _PIECE_RE.match(line):
            if cur is not None:
                blocks.append("".join(cur))
            cur = [line]
        elif cur is not None:
            cur.append(line)
        else:
            lead_parts.append(line)

    if cur is not None:
        blocks.append("".join(cur))

    lead_text = "".join(lead_parts)
    return lead_text, blocks


def join_item_body(lead_text: str, piece_blocks: list[str]) -> str:
    """Reassemble a body from its split parts.

    ``join_item_body(*split_item_body(b)) == b`` for any body ``b``.
    """
    return lead_text + "".join(piece_blocks)


def next_piece_label(blocks: list[str]) -> str:
    """Return the next piece label after the highest one in ``blocks``.

    The label is the leading token of each block's first line (the piece
    line), parsed by ``PIECE_LABEL_RE``.  The "next" label is obtained by
    incrementing the last letter of the highest label (e.g. ``1g`` ->
    ``1h``).  If a label has no letter, the trailing digit group is
    incremented by one.  Raises ``ValueError`` when no label is parseable
    or when the label ends in ``z`` (no wrap-around rule is defined by
    the source syntax).
    """
    highest: str | None = None

    for block in blocks:
        first_line = block.split("\n", 1)[0]
        m = _PIECE_RE.match(first_line)
        if not m:
            continue
        label_m = _PIECE_LABEL_RE.match(m.group(2).strip())
        if not label_m:
            continue
        label = label_m.group(1)
        if highest is None or _label_cmp(label, highest) > 0:
            highest = label

    if highest is None:
        raise ValueError("no parseable piece label in blocks")

    return _increment_label(highest)


def _label_cmp(a: str, b: str) -> int:
    """Compare two labels lexicographically by (digits, letters, digits)."""
    pa = _parse_label_tokens(a)
    pb = _parse_label_tokens(b)
    for ta, tb in zip(pa, pb):
        if ta < tb:
            return -1
        if ta > tb:
            return 1
    return len(pa) - len(pb)


def _parse_label_tokens(label: str) -> list[tuple[str, str]]:
    """Split a label into (kind, value) runs: 'd' for digit group, 'l' for letter group."""
    tokens: list[tuple[str, str]] = []
    i = 0
    n = len(label)
    while i < n:
        if label[i].isdigit():
            j = i
            while j < n and label[j].isdigit():
                j += 1
            tokens.append(("d", label[i:j]))
            i = j
        else:
            j = i
            while j < n and label[j].isalpha():
                j += 1
            tokens.append(("l", label[i:j]))
            i = j
    return tokens


def _increment_label(label: str) -> str:
    """Increment the last letter of ``label``; if none, increment the last digit group."""
    tokens = _parse_label_tokens(label)
    # Find the last letter token.
    last_letter_idx = -1
    for i, (kind, _) in enumerate(tokens):
        if kind == "l":
            last_letter_idx = i

    if last_letter_idx >= 0:
        kind, val = tokens[last_letter_idx]
        if val[-1] == "z":
            raise ValueError(f"label ending in 'z' has no successor: {label}")
        new_val = val[:-1] + chr(ord(val[-1]) + 1)
        tokens[last_letter_idx] = (kind, new_val)
    else:
        # No letter: increment the last digit group.
        last_d_idx = max(i for i, (k, _) in enumerate(tokens) if k == "d")
        kind, val = tokens[last_d_idx]
        new_val = str(int(val) + 1)
        tokens[last_d_idx] = (kind, new_val)

    return "".join(v for _, v in tokens)
