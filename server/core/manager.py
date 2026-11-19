"""The feature manager's decisions: keep filed feature tasks from being forgotten or lost. Standard library only.

It is a WATCHER. For each filed, unticked task (an item's own task, or a sub-piece's task, keyed 'FF-4/4c') it looks at where the Agent Manager task stands and picks one outcome from a
closed list; it never carries, verifies, merges, discards or archives anything (those loops already exist elsewhere):
  ok           the task is moving: nothing to do
  tick         the task merged: tick the item (status.sync)
  bump         the task sits unclaimed (adhoc or pending) past UNCLAIMED_MIN minutes: set premium once ('bumped:' stamp, never twice;
               for a piece only that piece's task is raised and only its line is stamped)
  refile       the task vanished from every queue folder: file the item (or just that piece) again
  flag         anything else that needs an owner's eye (blocked, needs clarification, done but never merged, archived, overdue):
               one line in features/<slug>/notes.md
One item per tick. Modes: off, dry-run (the default: only the ledger says what it would do) and on. Every decision is written to
<features root>/.manager-ledger.jsonl BEFORE it is acted on; the same decision for the same task is not repeated within 24 hours, so
a stuck item cannot spin it. A marker file <features root>/.manager-disabled turns it off. Deadlines are proposed only once at least
10 merged items have timing rows (twice the median minutes). Nothing here polls: tick() is called by an event wake-up.
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import checklist, filing, grill, status, store

UNCLAIMED_MIN = 30
STALLED_MIN = 120
MIN_SAMPLES = 10
DEDUP_HOURS = 24
UNCLAIMED = ("adhoc", "pending")
MOVING = ("drafting", "review", "approved", "coordinating")
STALLED = ("blocked", "needs-clarification", "awaiting-confirm")


def mode() -> str:
    m = os.environ.get("FEATUREFORGE_MANAGER_MODE", "dry-run").strip().lower()
    return m if m in ("off", "dry-run", "on") else "dry-run"


def _root(root: Path | None) -> Path:
    return Path(root) if root is not None else store.DEFAULT_ROOT


def deadline_minutes(root: Path | None = None) -> int | None:
    """Twice the median minutes of merged items, once there are MIN_SAMPLES rows; None before that."""
    log = _root(root) / ".timing.jsonl"
    try:
        rows = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines() if l.strip()]
    except OSError:
        return None
    minutes = [r["minutes"] for r in rows if isinstance(r.get("minutes"), (int, float))]
    return round(2 * statistics.median(minutes)) if len(minutes) >= MIN_SAMPLES else None


def decide(label: str | None, record: dict | None, age_min: float | None, item_meta: dict, deadline: int | None) -> dict:
    """The outcome for one item: {'outcome', 'reason'}. Pure: no I/O."""
    if label is None:
        return {"outcome": "refile", "reason": "the task is in no queue folder"}
    if label == "done":
        if (record or {}).get("mergedAt"):
            return {"outcome": "tick", "reason": "the task merged"}
        return {"outcome": "flag", "reason": "the task is done but has no merge time (finished without a merge)"}
    if label == "archived":
        return {"outcome": "flag", "reason": "the task was archived"}
    if label in UNCLAIMED and age_min is not None and age_min > UNCLAIMED_MIN and item_meta.get("premium") != "true" and not item_meta.get("bumped"):
        return {"outcome": "bump", "reason": f"unclaimed for {round(age_min)} minutes"}
    if label in STALLED and age_min is not None and age_min > STALLED_MIN:
        return {"outcome": "flag", "reason": f"{label} for {round(age_min)} minutes"}
    if deadline is not None and age_min is not None and age_min > deadline:
        return {"outcome": "flag", "reason": f"past the {deadline}-minute deadline (twice the median of merged items), now {label}"}
    return {"outcome": "ok", "reason": label}


def _ledger(root: Path | None) -> Path:
    return _root(root) / ".manager-ledger.jsonl"


def _recent(root: Path | None, now: datetime) -> set:
    seen = set()
    try:
        for line in _ledger(root).read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r.get("kind") == "intent" and datetime.fromisoformat(r["at"]) > now - timedelta(hours=DEDUP_HOURS):
                seen.add((r["slug"], r["item"], r["task"], r["outcome"]))
    except (OSError, ValueError, KeyError):
        pass
    return seen


def _append(root: Path | None, row: dict) -> None:
    _root(root).mkdir(parents=True, exist_ok=True)
    with _ledger(root).open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def _note(slug: str, item_id: str, text: str, root: Path | None, now: datetime) -> None:
    p = _root(root) / slug / "notes.md"
    head = "" if p.exists() else "# Manager notes\n\n"
    with p.open("a", encoding="utf-8") as f:
        f.write(f"{head}- {now.strftime('%Y-%m-%dT%H:%M:%SZ')} {item_id}: {text}\n")


def _act(outcome: str, slug: str, key: str, reason: str, root: Path | None, now: datetime) -> str:
    """Do one decision. `key` is an item id ('FF-4') or a piece ('FF-4/4c')."""
    item_id, _, piece_id = key.partition("/")
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    if outcome == "tick":
        status.sync(slug, root)
        return "ticked via status sync"
    if outcome == "bump":
        entries = checklist.parse(store.read_file(slug, "checklist.md", root))
        it = next(i for i in checklist.items(entries) if i["id"] == item_id)
        if piece_id:                                           # one piece: only its own task is raised, and only its line is stamped
            task = next(p["meta"]["task"] for p in checklist.pieces(it) if p["id"] == piece_id)
            project = filing.project_for(grill.target_repo(slug, root)["name"])
            filing._post(f"/api/task-anywhere/{task}/premium-priority?project={project['repoRoot']}", {"enabled": True, "by": "operator-ui"})
            checklist.update_piece(it, piece_id, {"bumped": stamp})
        else:
            filing.set_flag(slug, item_id, "premium", True, root)
            entries = checklist.parse(store.read_file(slug, "checklist.md", root))
            it = next(i for i in checklist.items(entries) if i["id"] == item_id)
            it["meta"]["bumped"] = stamp
            it["dirty"] = True
        store.write_file(slug, "checklist.md", checklist.render(entries), root)
        return "premium set"
    if outcome == "refile":
        entries = checklist.parse(store.read_file(slug, "checklist.md", root))
        it = next(i for i in checklist.items(entries) if i["id"] == item_id)
        if piece_id:
            checklist.update_piece(it, piece_id, drop=("task", "filed"))
        else:
            it["meta"].pop("task", None)
            it["meta"].pop("filed", None)
            it["dirty"] = True
        store.write_file(slug, "checklist.md", checklist.render(entries), root)
        r = filing.file_item(slug, item_id, accept_lint=True, root=root, piece=piece_id or None)
        _note(slug, key, f"task vanished, filed again as {r['task']}", root, now)
        return f"filed again as {r['task']}"
    _note(slug, key, reason, root, now)
    return "note written"


def candidates(root: Path | None = None) -> list[dict]:
    """Every filed, unticked task with where it stands, oldest filing first: an item's own task and each piece's task (item 'FF-4/4c')."""
    out = []
    for f in store.list_features(root):
        slug = f["slug"]
        try:
            repo = grill.target_repo(slug, root)["name"]
            if not repo:
                continue
            pipeline = filing.project_for(repo)["pipelineDir"]
            entries = checklist.parse(store.read_file(slug, "checklist.md", root))
        except (store.StoreError, filing.FilingError):
            continue
        for it in checklist.items(entries):
            if it["ticked"]:
                continue
            units = [(it["id"], it["meta"])] if it["meta"].get("task") else []
            units += [(f"{it['id']}/{p['id']}", dict(p["meta"], premium=it["meta"].get("premium", ""))) for p in checklist.pieces(it)
                      if not p["ticked"] and p["meta"].get("task")]
            for key, meta in units:
                label, rec = status.find_task(pipeline, meta["task"])
                out.append({"slug": slug, "item": key, "task": meta["task"], "label": label, "record": rec, "meta": meta,
                            "filed": status._filed_at(meta, rec or {})})
    return sorted(out, key=lambda c: (c["filed"] is None, c["filed"] or datetime.max.replace(tzinfo=timezone.utc)))


def tick(root: Path | None = None, now: datetime | None = None, run_mode: str | None = None) -> dict:
    """One decision for one item. Returns {'result': 'idle'|'off'|'handled', ...}."""
    now = now or datetime.now(timezone.utc)
    m = run_mode or mode()
    if m == "off" or (_root(root) / ".manager-disabled").exists():
        return {"result": "off"}
    seen = _recent(root, now)
    deadline = deadline_minutes(root)
    for c in candidates(root):
        age = (now - c["filed"]).total_seconds() / 60 if c["filed"] else None
        d = decide(c["label"], c["record"], age, c["meta"], deadline)
        if d["outcome"] == "ok" or (c["slug"], c["item"], c["task"], d["outcome"]) in seen:
            continue
        row = {"slug": c["slug"], "item": c["item"], "task": c["task"], "outcome": d["outcome"], "reason": d["reason"], "mode": m}
        _append(root, dict(row, kind="intent", at=now.isoformat()))                 # write-ahead: the decision is on record before it is acted on
        if m == "dry-run":
            done = "dry-run: nothing done"
        else:
            try:
                done = _act(d["outcome"], c["slug"], c["item"], d["reason"], root, now)
            except (store.StoreError, filing.FilingError, checklist.ChecklistError) as e:
                done = f"error: {e}"                                              # on record, and not retried for DEDUP_HOURS
        _append(root, dict(row, kind="result", at=now.isoformat(), done=done))
        return dict(row, result="handled", done=done)
    return {"result": "idle"}


QUEUES = ("adhoc", "pending", "blocked", "needs-clarification", "done")


def watch_paths(root: Path | None = None) -> list[str]:
    """Files and folders the manager reads: each checklist.md, the queue folders of each filed target repo, the disabled marker. Pure read."""
    r = _root(root)
    paths = {str(r / ".manager-disabled")}
    for f in store.list_features(root):
        slug = f["slug"]
        paths.add(str(r / slug / "checklist.md"))
        try:
            repo = grill.target_repo(slug, root)["name"]
            if not repo:
                continue
            pipeline = Path(filing.project_for(repo)["pipelineDir"])
        except (store.StoreError, filing.FilingError):
            continue
        paths.update(str(pipeline / "queue" / q) for q in QUEUES)
    return sorted(paths)


def next_due(root: Path | None = None, now: datetime | None = None) -> str | None:
    """Earliest future ISO time a filed unticked task crosses a threshold decide() acts on; None if none. Pure read."""
    now = now or datetime.now(timezone.utc)
    deadline = deadline_minutes(root)
    best = None
    for c in candidates(root):
        if c["filed"] is None:
            continue
        mins = []
        if c["label"] in UNCLAIMED and c["meta"].get("premium") != "true" and not c["meta"].get("bumped"):
            mins.append(UNCLAIMED_MIN)
        if c["label"] in STALLED:
            mins.append(STALLED_MIN)
        if deadline is not None and c["label"] is not None and c["label"] not in ("done", "archived"):
            mins.append(deadline)
        for m in mins:
            t = c["filed"] + timedelta(minutes=m)
            if t > now and (best is None or t < best):
                best = t
    return best.strftime("%Y-%m-%dT%H:%M:%SZ") if best else None


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m server.core.manager")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--tick", action="store_true")
    g.add_argument("--watch-paths", action="store_true")
    g.add_argument("--next-due", action="store_true")
    ap.add_argument("root", nargs="?")
    a = ap.parse_args(argv)
    root = Path(a.root) if a.root else None
    try:
        if a.watch_paths:
            out = watch_paths(root)
        elif a.next_due:
            out = next_due(root)
        else:
            out = tick(root)
    except Exception as e:  # the CLI always exits 0; the error goes in the JSON
        out = {"error": str(e)}
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
