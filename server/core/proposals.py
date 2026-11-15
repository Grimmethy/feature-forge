"""Helpers for the Dismiss feature on proposals.

The scout writes one <repoName>.json per repo under REPOSCOUT_PROPOSALS_DIR
(default ~/.local/state/pipeline-ops/reposcout/proposals/).  Each file holds
a list of proposals; the owner can dismiss a proposal and the dismissal is
recorded in <proposals dir>/dismissals.jsonl -- one JSON object per line --
so the scout's per-repo glob (which would read a *.json file) never picks it
up.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Iterable, Set, Tuple

DismissalKey = Tuple[str, str, str]  # (repo, id, key)


def dismissal_key(title: str, why: str) -> str:
    """Return the sha256 hex digest of `title + '\\n' + why`.

    Deterministic: the same (title, why) always produces the same key, so two
    dismissals of the same proposal in the same (repo, id) deduplicate at the
    key level.  The *full* dedup key used by load_dismissals is the tuple
    (repo, id, key) -- the sha256 alone is only a hint within a single
    proposal.
    """
    return hashlib.sha256((title + "\n" + why).encode("utf-8")).hexdigest()


def load_dismissals(dir: str) -> Set[DismissalKey]:
    """Read <dir>/dismissals.jsonl and return the set of (repo, id, key) tuples.

    Returns an empty set if the file is missing or the directory does not
    exist.  Blank lines are skipped; malformed lines raise ValueError so a
    corrupt log is never silently accepted.
    """
    path = os.path.join(dir, "dismissals.jsonl")
    if not os.path.exists(path):
        return set()
    keys: Set[DismissalKey] = set()
    with open(path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            keys.add((obj["repo"], obj["id"], obj["key"]))
    return keys


def append_dismissal(
    dir: str,
    repo: str,
    id: str,
    title: str,
    why: str,
    now: datetime,
) -> None:
    """Append one JSON line to <dir>/dismissals.jsonl recording the dismissal.

    Creates the directory if it does not exist.  Each call appends exactly
    one line; the file is never overwritten.  The record contains repo, id,
    key (sha256 of title+\\n+why), title and dismissedAt (ISO 8601).
    """
    os.makedirs(dir, exist_ok=True)
    path = os.path.join(dir, "dismissals.jsonl")
    key = dismissal_key(title, why)
    record = {
        "repo": repo,
        "id": id,
        "key": key,
        "title": title,
        "dismissedAt": now.isoformat(),
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
