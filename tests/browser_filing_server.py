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
reg.write_text(json.dumps([{"repoRoot": "/r/alpha", "pipelineDir": "/p/a", "domainsPath": "/p/a/d.json", "label": "alpha"}]))
os.environ["FEATUREFORGE_PROJECTS"] = str(reg)
n = [0]


def run(cmd, **kw):
    n[0] += 1
    return SimpleNamespace(returncode=0, stdout=f"queued adhoc task: /p/a/queue/adhoc/adhoc-fake-{n[0]}.json\n", stderr="")


filing.runner = run
filing._urlopen = lambda req, timeout=None: io.BytesIO(b"{}")
create_app(root).run(host="127.0.0.1", port=port)
