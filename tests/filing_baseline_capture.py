"""Baseline capture for server/core/filing.py: runs lint, record_text and file_item over five fixed checklist items with
filing.runner and filing._urlopen replaced by fixed fakes and the clock pinned, and prints repr / sorted-json output.

Usage: python3 tests/filing_baseline_capture.py server      (prints the capture)
       python3 -m unittest tests.filing_baseline_capture    (runs the checks)

Everything is written under a tempfile.mkdtemp() directory that is removed afterwards; nothing lands in the repo.
The fixture shape follows the checklist fixtures in tests/test_filing.py (the original gate text was not available).
"""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

_REPO = Path(__file__).resolve().parents[1]


def _setup(argv):
    """Put the server path argument at sys.path[0]; fall back to the repo's server dir. The repo root is added too."""
    server = Path(argv[1]).resolve() if len(argv) > 1 and Path(argv[1]).is_dir() else _REPO / "server"
    sys.path.insert(0, str(_REPO))
    sys.path.insert(0, str(server))


_setup(sys.argv)
from server.core import filing, store  # noqa: E402

_real_gmtime = time.gmtime

PLAIN = "- [ ] FF-1 Build the core\n  Write core.py with tests.\n"
WITH_HEADER = "- [ ] FF-1 Build the core\n  ## Steps\n  Write core.py with tests.\n"
WITH_SUMMARY = "- [ ] FF-1 Build the core\n  Summary: a small core module.\n  Write core.py with tests.\n"
LINT_FLAGGED = "- [ ] FF-1 Watch things\n  Check the folder every 5 minutes.\n"
MINIMAL_BODY = "- [ ] FF-1 Tiny\n"

FIXTURES = (("plain", PLAIN), ("with_header", WITH_HEADER), ("with_summary", WITH_SUMMARY),
            ("lint_flagged", LINT_FLAGGED), ("minimal_body", MINIMAL_BODY))

DISMISSED = []   # [name, call, reason]


def _fake_run(cmd, **kw):
    return SimpleNamespace(returncode=0, stdout="queued adhoc task: /p/alpha-pipeline/queue/adhoc/adhoc-task-1.json\n", stderr="")


def _fake_open(req, timeout=None):
    return io.BytesIO(b"{}")


@contextlib.contextmanager
def _env(fixture_text):
    """Yield (slug, root) for a fresh feature holding the fixture, with the seams faked and the clock pinned."""
    tmp = Path(tempfile.mkdtemp())
    saved = os.environ.get("FEATUREFORGE_PROJECTS")
    try:
        root = tmp / "features"
        slug = store.create_feature("Thing", "build a thing\nrepo: alpha", root)
        store.write_file(slug, "checklist.md", "# Checklist: Thing\n\n" + fixture_text, root)
        store.write_file(slug, "plan.md", "# Plan\n\nBuild it in two steps.", root)
        reg = tmp / "projects.json"
        reg.write_text(json.dumps([{"repoRoot": "/r/alpha", "pipelineDir": "/p/alpha-pipeline",
                                    "domainsPath": "/p/alpha-pipeline/d.json", "label": "alpha"}]))
        os.environ["FEATUREFORGE_PROJECTS"] = str(reg)
        with mock.patch.object(filing, "runner", _fake_run), mock.patch.object(filing, "_urlopen", _fake_open), \
                mock.patch.object(filing.time, "gmtime", lambda *a: _real_gmtime(0)):
            yield slug, root
    finally:
        if saved is None:
            os.environ.pop("FEATUREFORGE_PROJECTS", None)
        else:
            os.environ["FEATUREFORGE_PROJECTS"] = saved
        shutil.rmtree(tmp, ignore_errors=True)


def _call(name, label, fn, out):
    try:
        return fn()
    except Exception as e:  # recorded, never stops later fixtures
        print(f"ERROR {name} {label} {e!r}", file=out)
        DISMISSED.append([name, label, repr(e)])
        return None


def capture_one(name, text, out):
    """Run lint, record_text and file_item for one fixture."""
    print(f"== {name}", file=out)
    results = {}
    with _env(text) as (slug, root):
        lint_res = _call(name, "lint", lambda: filing.lint(text), out)
        print("lint", repr(lint_res), file=out)
        rec = _call(name, "record_text", lambda: filing.record_text(slug, "FF-1", root), out)
        print("record_text", repr(rec), file=out)
        if not rec:
            DISMISSED.append([name, "record_text", "empty result"])
        filed = _call(name, "file_item", lambda: filing.file_item(slug, "FF-1", False, root, None), out)
        print("file_item", json.dumps(filed, sort_keys=True, default=str), file=out)
        results.update(lint=lint_res, record=rec, filed=filed)
    if lint_res:
        with _env(text) as (slug, root):
            acc = _call(name, "file_item(accept_lint=True)", lambda: filing.file_item(slug, "FF-1", True, root, None), out)
            print("file_item accept_lint", json.dumps(acc, sort_keys=True, default=str), file=out)
            results["filed_accepted"] = acc
    return results


def run_all(out=None):
    out = out or sys.stdout
    del DISMISSED[:]
    results = {name: capture_one(name, text, out) for name, text in FIXTURES}
    print(json.dumps(DISMISSED, sort_keys=True), file=out)
    return results


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.buf = io.StringIO()
        self.results = run_all(self.buf)

    def test_with_header_goes_through(self):
        r = self.results["with_header"]
        self.assertIsNotNone(r["filed"])
        self.assertEqual(r["filed"]["id"], "FF-1")
        self.assertIn("Build the core", r["record"])
        self.assertNotIn("with_header", [d[0] for d in DISMISSED])

    def test_lint_flagged_still_files_when_accepted(self):
        r = self.results["lint_flagged"]
        self.assertIsNotNone(r["filed_accepted"])
        self.assertEqual(r["filed_accepted"]["id"], "FF-1")

    def test_lint_flagged_dismissal_recorded(self):
        rows = [d for d in DISMISSED if d[0] == "lint_flagged"]
        self.assertEqual([d[1] for d in rows], ["file_item"])
        self.assertIn("polling language", rows[0][2])
        for name, _ in FIXTURES:
            self.assertIn(f"== {name}", self.buf.getvalue())


if __name__ == "__main__":
    if len(sys.argv) > 1 and Path(sys.argv[1]).is_dir():
        run_all()
    else:
        unittest.main()
