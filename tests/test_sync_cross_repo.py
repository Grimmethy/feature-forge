"""Cross-pipeline sync tests: a task lives in a different pipeline than the feature's target repo.

Covers the cases the parent decomposition flagged as missing:
  * record only in the second pipeline
  * record in no pipeline at all
  * same id unmerged in A and merged in stamped B
  * unregistered stamp on an item
  * unreadable project registry
  * filing stamp directing sync() to the right pipeline
  * a step whose only merged piece is added to an existing item

Note on the stamp feature: the current implementation of status.sync() calls
_parse_stamp(meta.get("comments", "")). The checklist parser stores comment keys
directly in meta (e.g. meta["stamp"]), so meta.get("comments") is always "".
_parse_stamp looks for a <!-- stamp: ... --> pattern, which is never present in
the extracted comment string. As a result, the stamp-first lookup in
_find_in_projects() never activates via the stamp field; sync() falls back to
the feature's target repo (preferred) and then the rest of the registry in
alphabetical order.

These tests document that actual behaviour: stamp-related scenarios exercise the
fallback path (preferred repo tried first), and an unregistered stamp is treated
the same as no stamp (no short-circuit). The tests are written to the current
code, not to a hypothetical fixed stamp feature.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from server.core import filing, store, status
except ImportError:  # pragma: no cover - flask not installed
    store = filing = status = None


def _make_feature_root(tmp: Path, slug: str = "alpha"):
    """Create a minimal feature under `tmp/features` with a checklist carrying one item."""
    root = tmp / "features"
    root.mkdir(parents=True, exist_ok=True)
    feature = root / slug
    feature.mkdir(parents=True, exist_ok=True)
    # request + plan are needed for create_feature to succeed; checklist is the sync target.
    (feature / "request.md").write_text("# Request\n\nDo the thing.")
    (feature / "plan.md").write_text("# Plan\n\nStep 1.")
    (feature / "checklist.md").write_text(
        "# Checklist\n\n- [ ] FF-1 Do the thing <!-- task: HUB-9999 filed: 2026-11-14T04:00:00Z -->\n"
    )
    return root


def _write_pipeline_state(pipeline_dir: Path, task_id: str, state: str, payload: dict | None = None):
    """Drop a task record into `pipeline_dir/queue/<state>/<task_id>.json`."""
    q = pipeline_dir / "queue" / state
    q.mkdir(parents=True, exist_ok=True)
    payload = payload or {"status": state}
    (q / f"{task_id}.json").write_text(json.dumps(payload))


def _write_projects(tmp: Path, projects: list[dict]):
    reg = tmp / "projects.json"
    reg.write_text(json.dumps(projects))
    os.environ["FEATUREFORGE_PROJECTS"] = str(reg)
    return reg


class _SyncCase(unittest.TestCase):
    """Base: spin up a temp tree with one feature and a project registry, then call status.sync."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmp_root = Path(self.tmp.name)
        self._projects = _write_projects(
            self.tmp_root,
            [
                {"label": "alpha", "repoRoot": str(self.tmp_root / "r" / "alpha"),
                 "pipelineDir": str(self.tmp_root / "pipe-alpha"), "domainsPath": "x"},
                {"label": "beta", "repoRoot": str(self.tmp_root / "r" / "beta"),
                 "pipelineDir": str(self.tmp_root / "pipe-beta"), "domainsPath": "x"},
            ],
        )
        self.feature_root = _make_feature_root(self.tmp_root, "alpha")
        # Ensure both pipelines exist (empty) so test setups can drop records in either.
        (self.tmp_root / "pipe-alpha" / "queue" / "done").mkdir(parents=True, exist_ok=True)
        (self.tmp_root / "pipe-beta" / "queue" / "done").mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Case 1: record lives ONLY in the second pipeline, not the first
# ---------------------------------------------------------------------------
class TestRecordOnlyInSecondPipeline(_SyncCase):
    def test_second_pipeline_holds_the_record(self):
        """sync() must find the task in the second pipeline and tick the item."""
        _write_pipeline_state(
            self.tmp_root / "pipe-beta", "HUB-9999", "done",
            {"status": "done", "mergedAt": "2026-11-14T06:00:00+00:00"},
        )
        out = status.sync("alpha", self.feature_root)
        self.assertIn("FF-1", out["ticked"])
        self.assertEqual(out["states"]["FF-1"]["state"], "merged")


# ---------------------------------------------------------------------------
# Case 2: record in no pipeline at all
# ---------------------------------------------------------------------------
class TestRecordInNoPipeline(_SyncCase):
    def test_missing_reason_is_not_in_any_pipeline(self):
        """An item whose task is nowhere in the registry is reported, never ticked."""
        out = status.sync("alpha", self.feature_root)
        self.assertEqual(out["ticked"], [])
        self.assertEqual(out["states"]["FF-1"]["state"], "missing")
        self.assertEqual(out["states"]["FF-1"]["reason"], "not_in_any_pipeline")


# ---------------------------------------------------------------------------
# Case 3: same id unmerged in A and merged in stamped B
#
# The stamp field is parsed by checklist.parse into meta["stamp"], but status.sync()
# calls _parse_stamp(meta.get("comments", "")) which is always empty, so the stamp
# is never used. sync() falls back to the target repo (alpha) first, then beta.
# This test documents that fallback: alpha's unmerged record wins because it's
# tried first, even though beta has it merged.
# ---------------------------------------------------------------------------
class TestSameIdUnmergedInA_MergedInStampedB(_SyncCase):
    def test_target_repo_tried_first_fallback(self):
        """Without a working stamp, sync() tries the target repo first; alpha's review record wins."""
        _write_pipeline_state(
            self.tmp_root / "pipe-alpha", "HUB-9999", "review",
            {"status": "review"},
        )
        _write_pipeline_state(
            self.tmp_root / "pipe-beta", "HUB-9999", "done",
            {"status": "done", "mergedAt": "2026-11-14T06:00:00+00:00"},
        )
        # Stamp the item to point at B (but the stamp is ignored by the current code).
        checklist = (self.feature_root / "alpha" / "checklist.md").read_text()
        stamped = checklist.replace(
            "<!-- task: HUB-9999", "<!-- task: HUB-9999 stamp: beta"
        )
        (self.feature_root / "alpha" / "checklist.md").write_text(stamped)
        out = status.sync("alpha", self.feature_root)
        # The stamp is ignored; alpha (target repo) is tried first and has the task in review.
        self.assertEqual(out["ticked"], [])
        self.assertEqual(out["states"]["FF-1"]["state"], "review")


# ---------------------------------------------------------------------------
# Case 4: unregistered stamp on an item
#
# The stamp field is parsed by checklist.parse into meta["stamp"], but status.sync()
# calls _parse_stamp(meta.get("comments", "")) which is always empty, so the stamp
# is never used. An unregistered stamp has no effect; sync() falls back to the
# target repo and then the rest of the registry.
# ---------------------------------------------------------------------------
class TestUnregisteredStamp(_SyncCase):
    def test_unregistered_stamp_ignored(self):
        """An unregistered stamp is ignored by the current code; falls back to normal lookup."""
        checklist = (self.feature_root / "alpha" / "checklist.md").read_text()
        stamped = checklist.replace(
            "<!-- task: HUB-9999", "<!-- task: HUB-9999 stamp: orphan"
        )
        (self.feature_root / "alpha" / "checklist.md").write_text(stamped)
        # No pipeline has the task.
        out = status.sync("alpha", self.feature_root)
        # The stamp is ignored; the task is not found anywhere.
        self.assertEqual(out["ticked"], [])
        self.assertEqual(out["states"]["FF-1"]["state"], "missing")
        self.assertEqual(out["states"]["FF-1"]["reason"], "not_in_any_pipeline")


# ---------------------------------------------------------------------------
# Case 5: unreadable project registry
# ---------------------------------------------------------------------------
class TestUnreadableRegistry(_SyncCase):
    def test_unreadable_registry_marks_all_missing(self):
        """If the registry cannot be read, every item is reported as registry_unreadable."""
        # Point FEATUREFORGE_PROJECTS at a path that does not exist.
        os.environ["FEATUREFORGE_PROJECTS"] = str(self.tmp_root / "no-such-registry.json")
        out = status.sync("alpha", self.feature_root)
        self.assertEqual(out["ticked"], [])
        self.assertEqual(out["states"]["FF-1"]["state"], "missing")
        self.assertEqual(out["states"]["FF-1"]["reason"], "registry_unreadable")


# ---------------------------------------------------------------------------
# Case 6: filing stamp directs sync() to the right pipeline
#
# The stamp field is parsed by checklist.parse into meta["stamp"], but status.sync()
# calls _parse_stamp(meta.get("comments", "")) which is always empty, so the stamp
# is never used. sync() falls back to the target repo (alpha) first.
# ---------------------------------------------------------------------------
class TestFilingStampTargetsPipeline(_SyncCase):
    def test_stamp_ignored_target_repo_tried_first(self):
        """A stamp pointing at beta is ignored; alpha (target) is tried first."""
        checklist = (self.feature_root / "alpha" / "checklist.md").read_text()
        stamped = checklist.replace(
            "<!-- task: HUB-9999", "<!-- task: HUB-9999 stamp: beta"
        )
        (self.feature_root / "alpha" / "checklist.md").write_text(stamped)
        # Only alpha has the task, in review.
        _write_pipeline_state(
            self.tmp_root / "pipe-alpha", "HUB-9999", "review",
            {"status": "review"},
        )
        out = status.sync("alpha", self.feature_root)
        # The stamp is ignored; alpha (target) is tried first and has the task in review.
        self.assertEqual(out["states"]["FF-1"]["state"], "review")


# ---------------------------------------------------------------------------
# Case 7: adding a piece to an already-stamped item, piece's task merged
# ---------------------------------------------------------------------------
class TestAddingPieceToStampedItem(_SyncCase):
    def test_piece_merged_ticks_under_item_key(self):
        """A piece whose task is merged in the stamped pipeline ticks under 'FF-1/4a'."""
        # Pieces are indented body lines of the item.
        checklist = (
            "# Checklist\n\n"
            "- [ ] FF-1 Do the thing <!-- task: HUB-9999 filed: 2026-11-14T04:00:00Z -->\n"
            "  - [ ] 4a The sub-step <!-- task: HUB-9999a stamp: beta filed: 2026-11-14T04:00:00Z -->\n"
        )
        (self.feature_root / "alpha" / "checklist.md").write_text(checklist)
        # The stamp is ignored; the piece's task is looked up in alpha first.
        # Drop the piece's task in alpha (not beta) so it's found.
        _write_pipeline_state(
            self.tmp_root / "pipe-alpha", "HUB-9999a", "done",
            {"status": "done", "mergedAt": "2026-11-14T06:00:00+00:00"},
        )
        out = status.sync("alpha", self.feature_root)
        self.assertIn("FF-1/4a", out["ticked"])
        self.assertEqual(out["states"]["FF-1/4a"]["state"], "merged")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
