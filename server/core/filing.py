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

from . import checklist, grill, store

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


def projects_path() -> Path:
    return Path(os.environ.get("FEATUREFORGE_PROJECTS", str(AM_CORE / "projects.json")))


def lint(text: str) -> list[str]:
    """Warnings for polling language in text (an item's title and body). The standard clause is not counted."""
    text = text.replace(STANDARD_CLAUSE, "")
    return [label for pat, label in POLL_PATTERNS if re.search(pat, text, re.I)]


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
    raise FilingError(f"{repo_name} is not a registered Agent Manager project (create it first)")


def _item(slug: str, item_id: str, root: Path | None):
    entries = checklist.parse(store.read_file(slug, "checklist.md", root))
    for it in checklist.items(entries):
        if it["id"] == item_id:
            return entries, it
    raise FilingError(f"no such item {item_id}")


def record_text(slug: str, item_id: str, root: Path | None = None) -> str:
    """The self-contained task text for an item: the job, its place in the feature, the plan excerpt and the standard clause."""
    _, it = _item(slug, item_id, root)
    repo = grill.target_repo(slug, root)["name"]
    try:
        plan = store.read_file(slug, "plan.md", root).strip()
    except store.StoreError:
        plan = ""
    plan = plan[:PLAN_CAP] + ("\n[plan cut here]" if len(plan) > PLAN_CAP else "")
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
        task = it["meta"].get("task")
        project = project_for(grill.target_repo(slug, root)["name"])
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


def file_item(slug: str, item_id: str, accept_lint: bool = False, root: Path | None = None) -> dict:
    """File one item as an Agent Manager task. Returns {id, task, premium, warnings}."""
    entries, it = _item(slug, item_id, root)
    if checklist.is_locked(it):
        raise FilingError(f"{item_id} is already filed as {it['meta'].get('task')}")
    if it["ticked"]:
        raise FilingError(f"{item_id} is already done")
    repo = grill.target_repo(slug, root)["name"]
    if not repo:
        raise FilingError("choose the repo for this feature first")
    project = project_for(repo)
    by_id = {i["id"]: i for i in checklist.items(entries)}
    dep_tasks = []
    for d in [d for d in re.split(r"[,\s]+", it["meta"].get("deps", "")) if d]:
        dep = by_id.get(d)
        if dep is None or not dep["meta"].get("task"):
            if dep is not None and dep["ticked"] and dep["meta"].get("manual") == "true":
                continue                      # done by hand: nothing to wait for
            raise FilingError(f"file {d} first: {item_id} waits for it")
        dep_tasks.append(dep["meta"]["task"])
    warnings = lint(it["title"] + "\n" + "\n".join(it["body"]))
    if warnings and not accept_lint:
        raise FilingError("polling language in this item (" + ", ".join(warnings) + "): reword it to use a trigger, or accept the warning")
    text = record_text(slug, item_id, root)
    with tempfile.TemporaryDirectory() as tmp:
        pc = Path(tmp) / "pc.json"
        pc.write_text(json.dumps({"rawText": text, "raisedFrom": f"feature-forge:{slug}/{item_id}"}), encoding="utf-8")
        cmd = ["node", str(AM_CORE / "src" / "queue-adhoc-task.js"), "--title", f"{item_id} {it['title']}", "--prompt-context-file", str(pc)]
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
    task = Path(m.group(1)).stem
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
