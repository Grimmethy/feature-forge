'''Baseline unittest module for the record_text output in server/core/filing.py.

Covers HUB0027-04. The baselines may be updated intentionally: when a change to filing.py alters the record_text output on purpose, regenerate the literals below and state the reason in that change.

The literals were regenerated from the unchanged filing.py because the HUB0031-01 capture was not in this checkout.
'''
import json
import os
import tempfile
import unittest
from pathlib import Path

from server.core import filing, store

PLAIN = "- [ ] FF-1 Build the core\n  Write core.py with tests.\n"
WITH_HEADER = "- [ ] FF-1 Build the core\n  ## Steps\n  Write core.py with tests.\n"
WITH_SUMMARY = "- [ ] FF-1 Build the core\n  Summary: a small core module.\n  Write core.py with tests.\n"
LINT_FLAGGED = "- [ ] FF-1 Watch things\n  Check the folder every 5 minutes.\n"
MINIMAL_BODY = "- [ ] FF-1 Tiny\n"

# BEGIN EXPECTED LITERALS
EXPECTED_PLAIN = "FF-1 of feature 'thing': Build the core\n\nRepo: alpha.\n\nWrite core.py with tests.\n\nFeature plan (for context; do only this item):\n# Plan\n\nBuild it in two steps.\n\nPrefer a trigger over a poll or timer: wake on the event that changes the state (a file change, a task-state event, a deadline trigger) and add no setInterval, no repeating timer and no sleep loop."
EXPECTED_WITH_HEADER = "FF-1 of feature 'thing': Build the core\n\nRepo: alpha.\n\n## Steps\nWrite core.py with tests.\n\nFeature plan (for context; do only this item):\n# Plan\n\nBuild it in two steps.\n\nPrefer a trigger over a poll or timer: wake on the event that changes the state (a file change, a task-state event, a deadline trigger) and add no setInterval, no repeating timer and no sleep loop."
EXPECTED_WITH_SUMMARY = "FF-1 of feature 'thing': Build the core\n\nRepo: alpha.\n\nSummary: a small core module.\nWrite core.py with tests.\n\nFeature plan (for context; do only this item):\n# Plan\n\nBuild it in two steps.\n\nPrefer a trigger over a poll or timer: wake on the event that changes the state (a file change, a task-state event, a deadline trigger) and add no setInterval, no repeating timer and no sleep loop."
EXPECTED_LINT_FLAGGED = "FF-1 of feature 'thing': Watch things\n\nRepo: alpha.\n\nCheck the folder every 5 minutes.\n\nFeature plan (for context; do only this item):\n# Plan\n\nBuild it in two steps.\n\nPrefer a trigger over a poll or timer: wake on the event that changes the state (a file change, a task-state event, a deadline trigger) and add no setInterval, no repeating timer and no sleep loop."
EXPECTED_MINIMAL_BODY = "FF-1 of feature 'thing': Tiny\n\nRepo: alpha.\n\n(no further detail in the checklist item)\n\nFeature plan (for context; do only this item):\n# Plan\n\nBuild it in two steps.\n\nPrefer a trigger over a poll or timer: wake on the event that changes the state (a file change, a task-state event, a deadline trigger) and add no setInterval, no repeating timer and no sleep loop."
# END EXPECTED LITERALS


def fake_runner(*args, **kwargs):
    raise AssertionError("filing.runner must not be called by record_text")


def fake_urlopen(*args, **kwargs):
    raise AssertionError("filing._urlopen must not be called by record_text")


def _restore_env(value):
    if value is None:
        os.environ.pop("FEATUREFORGE_PROJECTS", None)
    else:
        os.environ["FEATUREFORGE_PROJECTS"] = value


class FilingBaselineTests(unittest.TestCase):
    def setUp(self):
        saved_runner = filing.runner
        saved_urlopen = filing._urlopen
        saved_projects = os.environ.get("FEATUREFORGE_PROJECTS")
        self.addCleanup(setattr, filing, "runner", saved_runner)
        self.addCleanup(setattr, filing, "_urlopen", saved_urlopen)
        self.addCleanup(_restore_env, saved_projects)
        filing.runner = fake_runner
        filing._urlopen = fake_urlopen

    def _record(self, tmp, fixture_text):
        root = Path(tmp) / "features"
        registry = Path(tmp) / "projects.json"
        registry.write_text(json.dumps([{"repoRoot": "/r/alpha", "pipelineDir": "/p/alpha-pipeline",
                                        "domainsPath": "/p/alpha-pipeline/d.json", "label": "alpha"}]))
        os.environ["FEATUREFORGE_PROJECTS"] = str(registry)
        slug = store.create_feature("Thing", "build a thing\nrepo: alpha", root)
        store.write_file(slug, "checklist.md", "# Checklist: Thing\n\n" + fixture_text, root)
        store.write_file(slug, "plan.md", "# Plan\n\nBuild it in two steps.", root)
        return filing.record_text(slug, "FF-1", root=root)

    def test_plain(self):
        with tempfile.TemporaryDirectory() as tmp:
            got = self._record(tmp, PLAIN)
        self.assertEqual(got, EXPECTED_PLAIN)

    def test_with_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            got = self._record(tmp, WITH_HEADER)
        self.assertEqual(got, EXPECTED_WITH_HEADER)

    def test_with_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            got = self._record(tmp, WITH_SUMMARY)
        self.assertEqual(got, EXPECTED_WITH_SUMMARY)

    def test_lint_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            got = self._record(tmp, LINT_FLAGGED)
        self.assertEqual(got, EXPECTED_LINT_FLAGGED)

    def test_minimal_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            got = self._record(tmp, MINIMAL_BODY)
        self.assertEqual(got, EXPECTED_MINIMAL_BODY)


if __name__ == "__main__":
    unittest.main()
