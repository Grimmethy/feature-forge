"""Drop guard for tagged pieces: a change to a checklist item must not drop or alter a piece that carries a
task:, filed: or merged: tag. Standard library only.

A piece block is one indented piece line ('- [ ] 3a Title' or '- [x] 3a Title <!-- merged: abc1234 -->') plus any
deeper-indented continuation lines beneath it. Callers pass each side of a change as a list of such block strings.
The guard is a pure function: no file I/O, no clock, no logging, no network.
"""
from __future__ import annotations

import re

from .checklist import ChecklistError

TAG_MARKERS = ("task:", "filed:", "merged:")

# Same label grammar as checklist.PIECE_LABEL_RE, applied to the text after the checkbox.
_PIECE_LABEL_RE = re.compile(r"^(\d+[a-z]*\d*)\s+(.+)$")
_CHECKBOX_RE = re.compile(r"^\s*- \[[ xX]\]\s+(.*)$")


def _first_line(block: str) -> str:
    return block.split("\n", 1)[0]


def _label(block: str) -> str:
    """The piece label (e.g. '4a'); falls back to the stripped first line when no label parses."""
    first = _first_line(block)
    m = _CHECKBOX_RE.match(first)
    text = m.group(1).strip() if m else first.strip()
    lm = _PIECE_LABEL_RE.match(text)
    return lm.group(1) if lm else first.strip()


def _is_tagged(block: str) -> bool:
    return any(marker in block for marker in TAG_MARKERS)


def _tagged_blocks(blocks) -> dict[str, str]:
    """Map piece label -> block text, for blocks containing a task:, filed: or merged: tag only."""
    tagged: dict[str, str] = {}
    for block in blocks:
        if _is_tagged(block):
            tagged[_label(block)] = block
    return tagged


def assert_tagged_pieces_kept(item_id: str, before_blocks, after_blocks) -> None:
    """Raise ChecklistError if a tagged piece block present before the change is missing or altered after it.

    Untagged blocks may change freely, and new blocks may be added. The error names the item id and the first
    offending piece label.
    """
    before = _tagged_blocks(before_blocks)
    after = _tagged_blocks(after_blocks)
    for label, text in before.items():
        if label not in after:
            raise ChecklistError(f"item {item_id}: tagged piece {label} was dropped")
        if after[label] != text:
            raise ChecklistError(f"item {item_id}: tagged piece {label} was altered")
