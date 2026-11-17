"""Filing a checklist item into Agent Manager as a real task. Standard library only.

A filed item becomes one adhoc task in the target repo's pipeline (queue-adhoc-task.js, run with that project's pipeline
environment). Before filing, the item text is linted for polling language (setInterval, 'every 5 minutes', cron, sleep
loops): the owner's rule is triggers over polls, so a hit is a warning that must be accepted explicitly. Every filed task
carries the standard trigger clause. Dependencies between items become the task's dependsOn, so an item can only be filed
once the items it waits for are filed. The item then carries 'task:' and 'filed:' in its checklist comment and is locked.
Premium is a per-item flag: set at filing, or changed later through the dashboard's premium-priority route.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from . import checklist, grill, parallel_files, store

AM_CORE = Path(os.environ.get("FEATUREFORGE_AM_CORE", "/media/model-cache/github/agent-manager"))
AM_URL = os.environ.get("FEATUREFORGE_AM_URL", "http://localhost:7420")
STANDARD_CLAUSE = ("Prefer a trigger over a poll or timer: wake on the event that changes the state (a file change, a task-state "
                   "event, a deadline trigger) and add no setInterval, no repeating timer and no sleep loop.")
PLAN_CAP = 3500
POLL_PATTERNS = (
    (r"\bset(Interval|Timeout)\b", "setInterval or setTimeout"),
    (r"\bpoll(s|ed|ing)?\b", "the word 'poll'"),
    (r"\bevery\s+\d+\s*(ms|milliseconds?|s|secs?|seconds?|m|mins?|minutes?|h|hours?)\b", "'every N <unit>'"),
    (r"\b(cron|crontab|periodic(ally)?|on a timer|timer loop|sleep loop|while true)\b", "a cron, timer or sleep loop"),
    (r"\bsleep\s*\(", "a sleep call"),
)
runner = subprocess.run           # tests replace this
_urlopen = urllib.request.urlopen


class FilingError(RuntimeError):
    pass


class NotRegisteredError(FilingError):
    """A repo name that matches no registered Agent Manager project. Carries only the repo name."""

    def __init__(self, repo: str):
        self.repo = repo
        super().__init__(f"{repo} is not a registered Agent Manager project (create it first)")


def projects_path() -> Path:
    return Path(os.environ.get("FEATUREFORGE_PROJECTS", str(AM_CORE / "projects.json")))


NEGATION = re.compile(r"\b(no|not|nothing|never|without|nor|instead of)\b|\bdon'?t\b", re.I)


def _negated(text: str, start: int) -> bool:
    """True when the match at `start` sits in a clause that negates it. A clause ends at . ; , ! ? or a newline."""
    clause_start = max((text.rfind(c, 0, start) for c in ".;,!?\n"), default=-1) + 1
    return NEGATION.search(text, clause_start, start) is not None


def lint(text: str) -> list[str]:
    """Warnings for polling language in text (an item's title and body). The standard clause is not counted.
    A match negated in its own clause ('do not add a new sleep loop') is not a warning; an unnegated match elsewhere still is."""
    text = text.replace(STANDARD_CLAUSE, "")
    warnings = []
    for pat, label in POLL_PATTERNS:
        if any(not _negated(text, m.start()) for m in re.finditer(pat, text, re.I)):
            warnings.append(label)
    return warnings


def project_for(repo_name: str) -> dict:
    """The Agent Manager project registered for a repo name (by label or by the repo folder name)."""
    try:
        projects = json.loads(projects_path().read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise FilingError(f"cannot read the project registry {projects_path()}: {e}")
    for p in projects:
        if repo_name in (p.get("label"), Path(p.get("repoRoot", "")).name):
            if not (p.get("repoRoot") and p.get("pipelineDir") and p.get("domainsPath")):
                raise FilingError(f"project {repo_name} is registered without a pipeline")
            return p
    raise NotRegisteredError(repo_name)


def _item(slug: str, item_id: str, root: Path | None):
    entries = checklist.parse(store.read_file(slug, "checklist.md", root))
    for it in checklist.items(entries):
        if it["id"] == item_id:
            return entries, it
    raise FilingError(f"no such item {item_id}")


def _plan_excerpt(slug: str, root) -> str:
    try:
        plan = store.read_file(slug, "plan.md", root).strip()
    except store.StoreError:
        plan = ""
    return plan[:PLAN_CAP] + ("\n[plan cut here]" if len(plan) > PLAN_CAP else "")


def record_text(slug: str, item_id: str, root: Path | None = None, piece_id: str | None = None) -> str:
    """The self-contained task text for an item, or for one of its pieces: the job, its place in the feature, the plan excerpt and the standard clause."""
    _, it = _item(slug, item_id, root)
    repo = grill.target_repo(slug, root)["name"]
    plan = _plan_excerpt(slug, root)
    if piece_id is not None:
        ps = checklist.pieces(it)
        piece = next((p for p in ps if p["id"] == piece_id), None)
        if piece is None:
            raise FilingError(f"no such piece {piece_id} in {item_id}")
        idx = ps.index(piece)
        context = "\n".join(checklist.plain_body(it)).strip()
        parts = [f"{item_id}/{piece_id} of feature '{slug}': {piece['title']}", f"Repo: {repo}.",
                 piece["body"] or "(no further detail in the checklist piece)",
                 f"This piece is part of {item_id} ({it['title']})" + (f": {context}" if context else ".")]
        after_meta = piece["meta"].get("after", "").strip()
        if after_meta:
            after_labels = [a for a in after_meta.split() if a]
            if after_labels == ["none"]:
                pass
            else:
                peers = []
                for label in after_labels:
                    peer = next((p for p in ps if p["id"] == label), None)
                    if peer:
                        peers.append(f"{label} ({peer['title']})")
                if peers:
                    parts.append(f"This piece comes after {', '.join(peers)}.")
        elif idx:
            parts.append(f"This piece comes after {ps[idx - 1]['id']} ({ps[idx - 1]['title']}), which is this task's dependsOn.")
        if plan:
            parts.append("Feature plan (for context; do only this piece):\n" + plan)
        parts.append(STANDARD_CLAUSE)
        return "\n\n".join(parts)
    deps = [d for d in re.split(r"[,\s]+", it["meta"].get("deps", "")) if d]
    body = "\n".join(it["body"]).strip()
    parts = [f"{item_id} of feature '{slug}': {it['title']}", f"Repo: {repo}.", body or "(no further detail in the checklist item)"]
    if deps:
        parts.append(f"This item waits for: {', '.join(deps)} (their tasks are this task's dependsOn).")
    if plan:
        parts.append("Feature plan (for context; do only this item):\n" + plan)
    parts.append(STANDARD_CLAUSE)
    return "\n\n".join(parts)


def _write_entries(slug: str, entries, root):
    store.write_file(slug, "checklist.md", checklist.render(entries), root)


def set_flag(slug: str, item_id: str, flag: str, value: bool, root: Path | None = None) -> dict:
    """Set premium or cloud on an item. A filed item's cloud lane is fixed when it was filed, so only premium changes after filing."""
    if flag not in ("premium", "cloud"):
        raise FilingError("flag must be premium or cloud")
    entries, it = _item(slug, item_id, root)
    if it["ticked"]:
        raise FilingError(f"{item_id} is done")
    filed = checklist.is_locked(it)
    if filed and flag == "cloud":
        raise FilingError(f"{item_id} is already filed; its lane was fixed when it was filed")
    if filed:
        tasks = [it["meta"]["task"]] if it["meta"].get("task") else [p["meta"]["task"] for p in checklist.pieces(it) if p["meta"].get("task") and not p["ticked"]]
        project = project_for(grill.target_repo(slug, root)["name"])
        for task in tasks:
            _post(f"/api/task-anywhere/{task}/premium-priority?project={project['repoRoot']}", {"enabled": bool(value)})
    it["meta"][flag] = "true" if value else "false"
    it["dirty"] = True
    _write_entries(slug, entries, root)
    return {"id": item_id, "flag": flag, "value": bool(value)}


def _post(path: str, body: dict) -> dict:
    req = urllib.request.Request(AM_URL + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with _urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode() or "{}")
    except Exception as e:
        raise FilingError(f"Agent Manager did not accept {path}: {e}")


def _queue_task(project: dict, title: str, text: str, raised_from: str, dep_tasks: list[str]) -> str:
    """Run the Agent Manager queue script in the project's pipeline environment; returns the new task id."""
    with tempfile.TemporaryDirectory() as tmp:
        pc = Path(tmp) / "pc.json"
        pc.write_text(json.dumps({"rawText": text, "raisedFrom": raised_from}), encoding="utf-8")
        cmd = ["node", str(AM_CORE / "src" / "queue-adhoc-task.js"), "--title", title, "--prompt-context-file", str(pc)]
        if dep_tasks:
            cmd += ["--depends-on", ",".join(dep_tasks)]
        env = dict(os.environ, AGENT_MANAGER_REPO_ROOT=project["repoRoot"], AGENT_MANAGER_PIPELINE_DIR=project["pipelineDir"],
                   AGENT_MANAGER_DOMAINS_PATH=project["domainsPath"])
        r = runner(cmd, capture_output=True, text=True, cwd=str(AM_CORE), env=env, timeout=120)
    if r.returncode != 0:
        raise FilingError("the task could not be queued: " + (r.stderr or r.stdout or "no output").strip()[:300])
    m = re.search(r"queued adhoc task:\s*(\S+\.json)", r.stdout)
    if not m:
        raise FilingError("the queue script printed no task file: " + r.stdout.strip()[:200])
    return Path(m.group(1)).stem


def _item_dep_tasks(by_id: dict, item_id: str, it: dict) -> list[str]:
    """The task ids an item waits for. A dependency with pieces counts through its LAST piece's task (pieces chain); one done by hand adds none."""
    out: list[str] = []
    for d in [d for d in re.split(r"[,\s]+", it["meta"].get("deps", "")) if d]:
        dep = by_id.get(d)
        if dep is None:
            raise FilingError(f"file {d} first: {item_id} waits for it")
        if dep["meta"].get("task"):
            out.append(dep["meta"]["task"])
            continue
        ps = checklist.pieces(dep)
        if ps:
            if any(not p["ticked"] and not p["meta"].get("task") for p in ps):
                raise FilingError(f"file {d} first: {item_id} waits for it")
            tasks = [p["meta"]["task"] for p in ps if p["meta"].get("task")]
            out.extend(tasks[-1:])
            continue
        if dep["ticked"] and dep["meta"].get("manual") == "true":
            continue                      # done by hand: nothing to wait for
        raise FilingError(f"file {d} first: {item_id} waits for it")
    return out


def _file_pieces(slug, entries, it, item_id, piece_id, accept_lint, root, project, dep_tasks) -> dict:
    ps = checklist.pieces(it)
    todo = [p for p in ps if not p["ticked"] and not p["meta"].get("task")]
    if piece_id is not None:
        target = next((p for p in ps if p["id"] == piece_id), None)
        if target is None:
            raise FilingError(f"no such piece {piece_id} in {item_id}")
        if target not in todo:
            raise FilingError(f"{piece_id} is already {'done' if target['ticked'] else 'filed as ' + target['meta']['task']}")
        earlier = [p for p in todo if ps.index(p) < ps.index(target)]
        if earlier:
            raise FilingError(f"file {earlier[0]['id']} first: {piece_id} comes after it")
        todo = [target]
    if not todo:
        raise FilingError(f"{item_id} has no unfiled pieces")
    warnings = sorted({w for p in todo for w in lint(p["title"] + "\n" + p["body"])})
    if warnings and not accept_lint:
        raise FilingError("polling language in this item (" + ", ".join(warnings) + "): reword it to use a trigger, or accept the warning")
    premium = it["meta"].get("premium") == "true"
    out = {"id": item_id, "pieces": [], "premium": premium, "warnings": warnings}
    _deps_map: dict[str, set[str]] = {}
    for _q in checklist.pieces(it):
        _after = _q["meta"].get("after", "").strip()
        if _after and _after != "none":
            _deps_map[_q["id"]] = {a for a in _after.split() if a}
    for p in todo:
        after_meta = p["meta"].get("after", "").strip()
        if after_meta:
            after_labels = [a for a in after_meta.split() if a]
            if after_labels == ["none"]:
                deps = list(dep_tasks)
            else:
                deps = []
                now = checklist.pieces(it)                              # re-read: pieces filed a moment ago carry their task ids now
                for label in after_labels:
                    peer = next((q for q in now if q["id"] == label), None)
                    if peer is None:
                        raise FilingError(f"piece {label} in {item_id}/{p['id']} refers to an unknown piece")
                    if not peer["meta"].get("task"):
                        raise FilingError(f"piece {label} in {item_id}/{p['id']} has no task yet: file it first")
                    deps.append(peer["meta"]["task"])
        else:
            now = checklist.pieces(it)                              # re-read: the pieces filed a moment ago carry their task ids now
            before = now[:[q["id"] for q in now].index(p["id"])]
            prev = next((q["meta"]["task"] for q in reversed(before) if q["meta"].get("task")), None)
            if prev:
                deps = [prev]                                       # pieces chain: each waits for the one before it
            elif before:
                deps = []                                           # earlier pieces were done by hand: nothing to wait for
            else:
                deps = list(dep_tasks)                              # the first piece waits for what the step waits for
        p_files = parallel_files.files_of("\n".join(p["body"]) if isinstance(p.get("body"), list) else (p["body"] or ""))
        for prev in todo[:todo.index(p)]:
            prev_files = parallel_files.files_of("\n".join(prev["body"]) if isinstance(prev.get("body"), list) else (prev["body"] or ""))
            if not p_files or not prev_files:
                continue
            if parallel_files.depends_transitively(p["id"], prev["id"], _deps_map):
                continue
            for shared in sorted(p_files & prev_files):
                warnings.append(f"{p['id']} and {prev['id']} both name {shared}; they can run in parallel and may conflict")
        try:
            task = _queue_task(project, f"{item_id}/{p['id']} {p['title']}", record_text(slug, item_id, root, p["id"]), f"feature-forge:{slug}/{item_id}/{p['id']}", deps)
        except FilingError as e:
            raise FilingError(f"{e} (filed so far: {', '.join(x['task'] for x in out['pieces']) or 'nothing'})")
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        checklist.update_piece(it, p["id"], {"task": task, "filed": stamp})
        it["meta"].setdefault("filed", stamp)                   # the first piece filed locks the item
        it["dirty"] = True
        _write_entries(slug, entries, root)                     # each task exists now: record it before anything else can fail
        entry = {"piece": p["id"], "task": task}
        if premium:
            try:
                _post(f"/api/task-anywhere/{task}/premium-priority?project={project['repoRoot']}", {"enabled": True, "by": "operator-ui"})
            except FilingError as e:
                entry["premiumError"] = str(e)
        out["pieces"].append(entry)
    out["task"] = out["pieces"][-1]["task"]
    return out


def file_item(slug: str, item_id: str, accept_lint: bool = False, root: Path | None = None, piece: str | None = None) -> dict:
    """File an item as Agent Manager tasks. An item without pieces is one task; an item with pieces files each unfiled piece as its own task,
    in order, each waiting for the one before (or just one piece when `piece` names it). Returns {id, task, premium, warnings} (+ pieces)."""
    entries, it = _item(slug, item_id, root)
    if it["ticked"]:
        raise FilingError(f"{item_id} is already done")
    has_pieces = bool(checklist.pieces(it))
    if checklist.is_locked(it) and not has_pieces:
        raise FilingError(f"{item_id} is already filed as {it['meta'].get('task')}")
    if piece is not None and not has_pieces:
        raise FilingError(f"{item_id} has no pieces")
    repo = grill.target_repo(slug, root)["name"]
    if not repo:
        raise FilingError("choose the repo for this feature first")
    project = project_for(repo)
    by_id = {i["id"]: i for i in checklist.items(entries)}
    dep_tasks = _item_dep_tasks(by_id, item_id, it)
    if has_pieces:
        return _file_pieces(slug, entries, it, item_id, piece, accept_lint, root, project, dep_tasks)
    warnings = lint(it["title"] + "\n" + "\n".join(it["body"]))
    if warnings and not accept_lint:
        raise FilingError("polling language in this item (" + ", ".join(warnings) + "): reword it to use a trigger, or accept the warning")
    task = _queue_task(project, f"{item_id} {it['title']}", record_text(slug, item_id, root), f"feature-forge:{slug}/{item_id}", dep_tasks)
    premium = it["meta"].get("premium") == "true"
    it["meta"]["task"] = task
    it["meta"]["filed"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    it["dirty"] = True
    _write_entries(slug, entries, root)                  # the task exists now: record it before anything else can fail
    out = {"id": item_id, "task": task, "premium": premium, "warnings": warnings}
    if premium:
        try:
            _post(f"/api/task-anywhere/{task}/premium-priority?project={project['repoRoot']}", {"enabled": True, "by": "operator-ui"})
        except FilingError as e:
            out["premiumError"] = str(e)
    return out
