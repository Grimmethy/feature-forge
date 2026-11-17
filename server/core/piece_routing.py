"""Route parsed feature pieces to their target repos, and summarize the result.

Pure functions only: no I/O, no filesystem or network access, and no imports
from filing or checklist.

Resolver contract: ``resolver(name) -> bool``. A truthy return means the repo
name is known to the caller's registry/picker. The caller passes the resolver
in; this module never looks up the registry itself.

Target rule: a piece with a set, non-empty ``repo`` targets that repo, and a
piece without one inherits ``feature_repo``. A set but unknown piece repo is
blocked and never falls back to ``feature_repo``.

Feature-repo edge case: an inherited ``feature_repo`` goes through the resolver
like any other target. If the feature repo is unknown, every piece that
inherits it is blocked with the same message format.
"""


def _get(obj, name):
    """Read ``name`` from a dict key or an attribute, whichever the piece uses."""
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def route_pieces(pieces, feature_repo, resolver):
    """Return one result dict per piece, in input order.

    Each dict has the keys ``piece``, ``targetRepo``, ``status`` and ``message``.
    ``status`` is ``"ok"`` (message None) or ``"blocked"`` (message set to
    ``"unknown repo '<target>' for piece <id>"``).
    """
    results = []
    for piece in pieces:
        piece_repo = _get(piece, "repo")
        target = piece_repo if piece_repo else feature_repo
        if resolver(target):
            results.append({
                "piece": piece,
                "targetRepo": target,
                "status": "ok",
                "message": None,
            })
        else:
            piece_id = _get(piece, "id")
            results.append({
                "piece": piece,
                "targetRepo": target,
                "status": "blocked",
                "message": f"unknown repo '{target}' for piece {piece_id}",
            })
    return results


def format_file_summary(results):
    """Summarize routing results as text.

    The first line reads ``N tasks filed: 4 to repo-a, 5 to repo-b, 0 blocked``,
    with repos sorted by name. With no ok results it reads
    ``0 tasks filed: <blocked> blocked``. Each blocked result adds one line
    holding its message.
    """
    ok = [r for r in results if r["status"] == "ok"]
    blocked = [r for r in results if r["status"] == "blocked"]

    if ok:
        counts = {}
        for r in ok:
            counts[r["targetRepo"]] = counts.get(r["targetRepo"], 0) + 1
        clauses = ", ".join(f"{counts[repo]} to {repo}" for repo in sorted(counts))
        first = f"{len(ok)} tasks filed: {clauses}, {len(blocked)} blocked"
    else:
        first = f"0 tasks filed: {len(blocked)} blocked"

    lines = [first] + [r["message"] for r in blocked]
    return "\n".join(lines)
