"""Status sync: read where each filed item's Agent Manager task stands and tick the items that have merged. Standard library only.

Nothing here runs on a timer. sync() is called when a feature is opened or refreshed (and later by the manager loop's event
wake-ups); it only READS the target project's queue folders and writes the checklist when a task has merged. A merged task ticks its
item ('merged: <time>', 'took: <minutes>') and appends one row to <features root>/.timing.jsonl so later deadline suggestions have
real numbers. A hand-ticked item is never touched; an item whose task is not found is reported as 'missing', never ticked.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from . import checklist, filing, grill, store

QUEUE_STATES = ("adhoc", "pending", "drafting", "review", "approved", "blocked", "needs-clarification", "awaiting-confirm",
                "coordinating", "done")


def find_task(pipeline_dir: str, task_id: str) -> tuple[str | None, dict | None]:
    """The queue state and record of a task, or (None, None). Looks in every live state, then the done archives."""
    q = Path(pipeline_dir) / "queue"
    spots = [(s, q / s / f"{task_id}.json") for s in QUEUE_STATES if s != "drafting"]
    spots += [("archived", p) for p in (q / "done" / "_archived_no_action" / f"{task_id}.json",)]
    arch = q / "done" / "_archived"
    if arch.is_dir():
        spots += [("archived", d / f"{task_id}.json") for d in sorted(arch.iterdir()) if d.is_dir()]
    drafting = q / "drafting"
    if drafting.is_dir():
        spots += [("drafting", p) for p in drafting.rglob(f"{task_id}.json")]
    for state, p in spots:
        if p.is_file():
            try:
                return state, json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return state, {}
    return None, None


def _when(text: str | None):
    try:
        t = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)      # queue history times carry no zone: they are UTC


def _filed_at(item_meta: dict, record: dict):
    t = _when(item_meta.get("filed"))
    if t is not None and "T" in str(item_meta.get("filed")):
        return t
    stamps = [_when(h.get("at")) for h in record.get("history", []) if isinstance(h, dict)]
    stamps = [s for s in stamps if s is not None]
    return min(stamps) if stamps else t


def _units(entries):
    """(key, item, piece or None, meta) for every filed task: an item's own task, and each piece's task (key 'FF-4/4c')."""
    for it in checklist.items(entries):
        if it["meta"].get("task"):
            yield it["id"], it, None, it["meta"]
        for p in checklist.pieces(it):
            if p["meta"].get("task"):
                yield f"{it['id']}/{p['id']}", it, p, p["meta"]


def sync(slug: str, root: Path | None = None) -> dict:
    """Tick merged items and pieces and report every filed task's state: {'ticked': [keys], 'states': {key: {'state', 'status'}}}.
    A key is an item id ('FF-4') or a piece ('FF-4/4c'). A step whose pieces are all done after this run is ticked too."""
    text = store.read_file(slug, "checklist.md", root)
    entries = checklist.parse(text)
    units = list(_units(entries))
    out = {"ticked": [], "states": {}}
    if not units:
        return out
    repo = grill.target_repo(slug, root)["name"]
    if not repo:
        return out
    pipeline = filing.project_for(repo)["pipelineDir"]
    rows = []
    finished: dict[str, list[str]] = {}                 # item id -> merge times of the pieces ticked in this run
    for key, it, piece, meta in units:
        state, rec = find_task(pipeline, meta["task"])
        if state is None:
            out["states"][key] = {"state": "missing", "status": ""}
            continue
        status = str((rec or {}).get("status", ""))
        merged = (rec or {}).get("mergedAt")
        label = "merged" if state == "done" and merged else state
        out["states"][key] = {"state": label, "status": status}
        if (piece["ticked"] if piece else it["ticked"]) or label != "merged":
            continue
        mt = _when(merged)
        ft = _filed_at(meta, rec or {})
        minutes = max(0, round((mt - ft).total_seconds() / 60)) if mt and ft else None
        stamp = str(merged)[:19] + "Z"
        if piece:
            checklist.update_piece(it, piece["id"], dict({"merged": stamp}, **({"took": str(minutes)} if minutes is not None else {})), ticked=True)
            finished.setdefault(it["id"], []).append(stamp)
        else:
            it["ticked"] = True
            it["meta"]["merged"] = stamp
            if minutes is not None:
                it["meta"]["took"] = str(minutes)
            it["dirty"] = True
        out["ticked"].append(key)
        rows.append({"slug": slug, "item": key, "task": meta["task"], "repo": repo, "filed": str(ft) if ft else None,
                     "merged": str(merged), "minutes": minutes, "premium": it["meta"].get("premium") == "true",
                     "cloud": it["meta"].get("cloud") == "true"})
    for it in checklist.items(entries):                 # the last piece of a step merged: the step is done
        if it["id"] in finished and not it["ticked"] and all(p["ticked"] for p in checklist.pieces(it)):
            it["ticked"] = True
            it["meta"]["merged"] = max(finished[it["id"]])
            it["dirty"] = True
            out["ticked"].append(it["id"])
    if out["ticked"]:
        store.write_file(slug, "checklist.md", checklist.render(entries), root)
        log = (Path(root) if root is not None else store.DEFAULT_ROOT) / ".timing.jsonl"
        with log.open("a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
    return out
