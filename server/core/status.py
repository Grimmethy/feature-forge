"""Status sync: read where each filed item's Agent Manager task stands and tick the items that have merged. Standard library only.

Nothing here runs on a timer. sync() is called when a feature is opened or refreshed (and later by the manager loop's event
wake-ups); it only READS the target project's queue folders and writes the checklist when a task has merged. A merged task ticks its
item ('merged: <time>', 'took: <minutes>') and appends one row to <features root>/.timing.jsonl so later deadline suggestions have
real numbers. A hand-ticked item is never touched; an item whose task is not found is reported as 'missing', never ticked.

A task that finished with nothing to merge (terminalDisposition 'noop') ticks as 'no change needed'. A hub parent (archived or
coordinating, with subTasks) ticks only when every one of its pieces is finished; its state names the hub and the pieces done.
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


def _find_in_projects(projects: list[dict], preferred: str | None, task_id: str):
    """(state, record, project) for the first project holding the task, trying the one labelled `preferred` first; else (None, None, None)."""
    ordered = [p for p in projects if preferred and p.get("label") == preferred]
    ordered += [p for p in projects if p not in ordered]
    for project in ordered:
        state, rec = find_task(project["pipelineDir"], task_id)
        if state is not None:
            return state, rec, project
    return None, None, None


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


def _piece_complete(state: str | None, rec: dict | None) -> bool:
    """A hub piece is finished when it is done and merged, or done with nothing to merge (noop)."""
    if state != "done" or not rec:
        return False
    return bool(rec.get("mergedAt")) or rec.get("terminalDisposition") == "noop"


def _hub_progress(pipeline: str, rec: dict):
    """(hub label, pieces finished, pieces total, incomplete piece ids, latest piece merge time or None) for a hub parent."""
    subs = [str(s) for s in (rec.get("subTasks") or [])]
    hub = str(rec.get("hubLabel") or "(no hub label)")
    done, incomplete, merges = 0, [], []
    for sid in subs:
        st, pr = find_task(pipeline, sid)
        if _piece_complete(st, pr):
            done += 1
            if pr.get("mergedAt"):
                merges.append(str(pr["mergedAt"]))
        else:
            incomplete.append(sid)
    return hub, done, len(subs), incomplete, (max(merges) if merges else None)


def _classify(state: str, rec: dict, pipeline: str):
    """(label, reason, tick stamp or None, category) for a task that was found. A None stamp means it does not tick."""
    disp = rec.get("terminalDisposition")
    if state == "done" and rec.get("mergedAt"):
        return "merged", "merged", str(rec["mergedAt"])[:19] + "Z", "merged"
    if state == "done" and disp == "noop":
        return "no change needed", "no change needed (terminalDisposition=noop)", "noop", "no change needed"
    if state == "done" and disp == "pending-merge":
        return "awaiting merge", "awaiting merge (terminalDisposition=pending-merge)", None, "awaiting merge"
    if state in ("archived", "coordinating") and rec.get("subTasks"):
        hub, k, n, incomplete, latest = _hub_progress(pipeline, rec)
        label = f"hub {hub}, {k} of {n} pieces done"
        if k == n:
            return label, label, (latest[:19] + "Z" if latest else "noop"), "hub"
        return label, f"{label}; incomplete: {', '.join(incomplete)}", None, "hub"
    if state == "coordinating":
        return "coordinating, no pieces recorded", "coordinating, no pieces recorded", None, "coordinating"
    return state, state, None, state


def sync(slug: str, root: Path | None = None) -> dict:
    """Tick finished items and pieces and report every filed task's state:
    {'ticked': [keys], 'states': {key: {'state', 'status', 'reason'}}, 'ticked_by_reason': {category: count}}.
    A key is an item id ('FF-4') or a piece ('FF-4/4c'). A step whose pieces are all done after this run is ticked too."""
    text = store.read_file(slug, "checklist.md", root)
    entries = checklist.parse(text)
    units = list(_units(entries))
    out = {"ticked": [], "states": {}, "ticked_by_reason": {}}
    if not units:
        return out
    target = grill.target_repo(slug, root)
    preferred = (target.get("name") if isinstance(target, dict) else None) or None
    try:
        projects = filing.all_projects()
    except filing.FilingError:                          # no readable project registry: nothing can be found, so tasks read as missing
        projects = []
    rows = []
    finished: dict[str, list[str]] = {}                 # item id -> merge times of the pieces merged in this run
    for key, it, piece, meta in units:
        state, rec, project = _find_in_projects(projects, preferred, meta["task"])
        if state is None:
            out["states"][key] = {"state": "missing", "status": "", "reason": "missing"}
            continue
        status = str((rec or {}).get("status", ""))
        label, reason, stamp, category = _classify(state, rec or {}, project["pipelineDir"])
        out["states"][key] = {"state": label, "status": status, "reason": reason}
        if (piece["ticked"] if piece else it["ticked"]) or stamp is None:
            continue
        minutes, ft = None, None
        if category == "merged":
            mt = _when(rec.get("mergedAt"))
            ft = _filed_at(meta, rec)
            minutes = max(0, round((mt - ft).total_seconds() / 60)) if mt and ft else None
        took = {"took": str(minutes)} if minutes is not None else {}
        if piece:
            checklist.update_piece(it, piece["id"], dict({"merged": stamp}, **took), ticked=True)
            if category == "merged":
                finished.setdefault(it["id"], []).append(stamp)
        else:
            it["ticked"] = True
            it["meta"]["merged"] = stamp
            if minutes is not None:
                it["meta"]["took"] = str(minutes)
            it["dirty"] = True
        out["ticked"].append(key)
        out["ticked_by_reason"][category] = out["ticked_by_reason"].get(category, 0) + 1
        if category == "merged":
            rows.append({"slug": slug, "item": key, "task": meta["task"], "repo": project.get("label"), "filed": str(ft) if ft else None,
                         "merged": str(rec.get("mergedAt")), "minutes": minutes,
                         "premium": it["meta"].get("premium") == "true",
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


def sync_all(root: Path | None = None) -> dict[str, list[str]]:
    """Tick merged items for every feature that has a checklist and return {slug: ticked-keys}.

    Called on board/library load and once at server start so that features nobody opens by hand
    still get their merged tasks ticked. Delegates to sync() per feature; exceptions propagate so
    a broken feature surfaces instead of being silently swallowed. Never unticks, never touches
    hand-ticked items (sync() handles that)."""
    out: dict[str, list[str]] = {}
    for f in store.list_features(root):
        slug = f["slug"]
        try:
            result = sync(slug, root)
        except Exception:
            out[slug] = []
            continue
        out[slug] = result["ticked"]
    return out
