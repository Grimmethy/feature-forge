"""Pure progress computation for pipeline pieces.

No timers, waiting loops, or I/O. Input pieces have the shape
{id, group, state, mergeRef?}.
"""

_STATE_REASONS = ("archived", "blocked", "needs-clarification")


def _has_merge_ref(piece):
    """A mergeRef is present when it is neither None nor undefined.

    An empty string is treated as absent: it is not a real merge reference.
    """
    ref = piece.get("mergeRef")
    if ref is None:
        return False
    if isinstance(ref, str) and ref == "":
        return False
    return True


def computeProgress(pieces):
    """Return {counted, total, ticked, excluded}.

    - total is len(pieces).
    - ticked is a COUNT of pieces that were ticked (merged).
    - excluded is a list of {id, reason} for dismissed pieces, one entry per
      input piece, with no deduplication by id.
    - Precedence: mergeRef first (counted and ticked regardless of state),
      then state archived, blocked, needs-clarification.
    """
    counted = 0
    ticked = 0
    excluded = []
    for piece in pieces:
        if _has_merge_ref(piece):
            counted += 1
            ticked += 1
            continue
        state = piece.get("state")
        reason = None
        for candidate in _STATE_REASONS:
            if state == candidate:
                reason = candidate
                break
        if reason is not None:
            excluded.append({"id": piece.get("id"), "reason": reason})
        else:
            counted += 1
    return {
        "counted": counted,
        "total": len(pieces),
        "ticked": ticked,
        "excluded": excluded,
    }
