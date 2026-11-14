"""Throwaway server for tests/browser_filing_panel.mjs: the real app with the queue script and the dashboard faked, so filing
touches nothing. Usage: python tests/browser_filing_server.py <features folder> <port>. A registry with the repo 'alpha' is written
next to the features folder."""
import io
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.app import create_app
from server.core import filing

root, port = Path(sys.argv[1]), int(sys.argv[2])
reg = root.parent / "projects.json"
pipe = root.parent / "pipe"
(pipe / "queue" / "review").mkdir(parents=True)
reg.write_text(json.dumps([{"repoRoot": "/r/alpha", "pipelineDir": str(pipe), "domainsPath": str(pipe / "d.json"), "label": "alpha"}]))
os.environ["FEATUREFORGE_PROJECTS"] = str(reg)
n = [0]


def run(cmd, **kw):
    n[0] += 1
    (pipe / "queue" / "review" / f"adhoc-fake-{n[0]}.json").write_text(json.dumps({"status": "review"}))      # the filed task sits in review
    return SimpleNamespace(returncode=0, stdout=f"queued adhoc task: /p/a/queue/adhoc/adhoc-fake-{n[0]}.json\n", stderr="")


filing.runner = run

# repo creation: git, gh and the registry are faked too (the repos folder and registry are temp ones next to the features folder)
from server.core import repo_create
repos = root.parent / "repos"
repos.mkdir(exist_ok=True)
os.environ["FEATUREFORGE_REPOS_ROOT"] = str(repos)
made = set()


def repo_run(cmd, **kw):
    if cmd[:2] == ["git", "init"]:
        (Path(cmd[-1]) / ".git").mkdir(parents=True, exist_ok=True)
    if cmd[:2] == ["gh", "repo"]:
        made.add(cmd[3])
    if "get-url" in cmd:
        return SimpleNamespace(returncode=0 if made else 1, stdout="", stderr="")
    return SimpleNamespace(returncode=0, stdout="", stderr="")


repo_create.runner = repo_run
filing._urlopen = lambda req, timeout=None: io.BytesIO(b"{}")
create_app(root).run(host="127.0.0.1", port=port)
