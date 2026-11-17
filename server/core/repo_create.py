"""Creating a new repo for a feature, the steps the owner confirms with the Create repo button. Standard library only.

plan(name) lists the steps without doing anything. create(name) does them in order and stops at the first failure:
 1. git init in <repos root>/<name> (skipped when it is already a repo) with a README and a first commit,
 2. a private GitHub repository <owner>/<name> through the gh CLI, with the first commit pushed (skipped when 'origin' exists),
 3. the Agent Manager registry entry (pool: true) in projects.json, after a dated backup of that file (skipped when listed),
 4. the repo's pipeline folder with its task-domains.json and queue folders (skipped when it exists).
Every external command goes through the replaceable runner, so tests never touch git, GitHub or the real registry.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from . import filing, grill

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,60}$")
QUEUE_DIRS = ("adhoc", "pending", "drafting", "review", "approved", "blocked", "needs-clarification", "awaiting-confirm", "coordinating", "done")
runner = subprocess.run           # tests replace this
_list_dir = os.listdir            # tests replace this (directory listing seam for unregistered_repos)
_unreg_cache = {}                 # root path -> ((root_mtime_ns, projects_mtime_ns), sorted names)


class RepoCreateError(RuntimeError):
    pass


def gh_owner() -> str:
    return os.environ.get("FEATUREFORGE_GH_OWNER", "Grimmethy")


def _check(name: str) -> str:
    if not isinstance(name, str) or not NAME_RE.match(name) or name.endswith(".git"):
        raise RepoCreateError("a repo name is letters, digits, dots, dashes and underscores, starting with a letter or digit")
    return name


def _paths(name: str, repos: Path | None) -> dict:
    base = Path(repos) if repos is not None else grill.repos_root()
    return {"repo": base / name, "pipeline": base / f"{name}-pipeline"}


def _registered(name: str) -> bool:
    try:
        return any(name in (p.get("label"), Path(p.get("repoRoot", "")).name) for p in json.loads(filing.projects_path().read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return False


def _registered_names() -> set:
    """Every label and repo folder name in projects.json."""
    try:
        projects = json.loads(filing.projects_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()        # no readable projects.json means nothing is registered (same as _registered), not a 500
    names = set()
    for p in projects:
        for v in (p.get("label"), Path(p.get("repoRoot", "")).name):
            if v:
                names.add(v)
    return names


def unregistered_repos(root) -> list[str]:
    """Sorted names under root that are not registered and do not match grill.SKIP_REPO.
    Memoised on the mtime_ns of root and projects.json, so an unchanged pair skips the listing.
    The key covers root's own entries and projects.json only, not the contents of nested directories."""
    key = str(root)
    stat_key = (os.stat(root).st_mtime_ns, os.stat(filing.projects_path()).st_mtime_ns)
    cached = _unreg_cache.get(key)
    if cached is not None and cached[0] == stat_key:
        return list(cached[1])
    registered = _registered_names()
    result = sorted(n for n in _list_dir(root) if n not in registered and not grill.SKIP_REPO.search(n))
    _unreg_cache[key] = (stat_key, result)
    return list(result)


def plan(name: str, repos: Path | None = None) -> list[dict]:
    """The steps create() would take, each with what it will do and whether it is already done."""
    _check(name)
    p = _paths(name, repos)
    has_origin = (p["repo"] / ".git").is_dir() and runner(["git", "-C", str(p["repo"]), "remote", "get-url", "origin"], capture_output=True, text=True).returncode == 0
    return [
        {"id": "git", "text": f"git init {p['repo']} with a README and a first commit", "done": (p["repo"] / ".git").is_dir()},
        {"id": "github", "text": f"create the private GitHub repo {gh_owner()}/{name} and push the first commit", "done": has_origin},
        {"id": "register", "text": f"add {name} to the Agent Manager project registry (pool: true) after a backup of {filing.projects_path()}", "done": _registered(name)},
        {"id": "pipeline", "text": f"create the pipeline folder {p['pipeline']} with its task-domains.json and queue folders", "done": (p["pipeline"] / "task-domains.json").is_file()},
    ]


def _run(cmd: list[str], what: str) -> str:
    r = runner(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RepoCreateError(f"{what} failed: " + (r.stderr or r.stdout or "no output").strip()[:300])
    return r.stdout


def _do_git(name: str, p: dict) -> None:
    repo = p["repo"]
    repo.mkdir(parents=True, exist_ok=True)
    _run(["git", "init", "-q", "-b", "main", str(repo)], "git init")
    readme = repo / "README.md"
    if not readme.exists():
        readme.write_text(f"# {name}\n\nCreated by Feature Forge.\n", encoding="utf-8")
    _run(["git", "-C", str(repo), "add", "README.md"], "git add")
    _run(["git", "-C", str(repo), "commit", "-q", "-m", "Initial commit"], "git commit")


def _do_github(name: str, p: dict) -> None:
    _run(["gh", "repo", "create", f"{gh_owner()}/{name}", "--private", "--source", str(p["repo"]), "--remote", "origin", "--push"], "creating the GitHub repo")


def _do_register(name: str, p: dict) -> None:
    path = filing.projects_path()
    try:
        projects = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise RepoCreateError(f"cannot read the project registry {path}: {e}")
    shutil.copy2(path, path.with_name(path.name + ".bak-" + time.strftime("%Y%m%d-%H%M%S") + "-before-" + name))
    projects.append({"repoRoot": str(p["repo"]), "pipelineDir": str(p["pipeline"]), "domainsPath": str(p["pipeline"] / "task-domains.json"),
                     "label": name, "pool": True})
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(projects, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _do_pipeline(name: str, p: dict) -> None:
    template = filing.AM_CORE / "task-domains.json"
    if not template.is_file():
        raise RepoCreateError(f"no task-domains.json template at {template}")
    for q in QUEUE_DIRS:
        (p["pipeline"] / "queue" / q).mkdir(parents=True, exist_ok=True)
    shutil.copy2(template, p["pipeline"] / "task-domains.json")


STEPS = {"git": _do_git, "github": _do_github, "register": _do_register, "pipeline": _do_pipeline}


def create(name: str, repos: Path | None = None) -> list[dict]:
    """Run every step that is not already done. Returns the steps with 'result' (done, skipped) and stops with RepoCreateError on a failure."""
    steps = plan(name, repos)
    p = _paths(name, repos)
    for s in steps:
        if s["done"]:
            s["result"] = "skipped (already done)"
            continue
        STEPS[s["id"]](name, p)
        s["result"] = "done"
    return steps
