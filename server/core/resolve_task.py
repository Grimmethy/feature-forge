"""Resolve a stored task ID to its full form.

When a checklist item stores a truncated or partial task ID, this module can
recover the full ID by matching against the pipeline's queue states and
archives. Used as a fallback by status.find_task when an exact lookup fails.

Returns {"resolved": str, "candidates": [str]} where:
- resolved: the full ID if found (exact match, unique prefix, or title match)
            or the stored_id if unresolved
- candidates: list of possible matches (empty if exact match found)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import status

QUEUE_STATES = status.QUEUE_STATES


def resolveTaskId(pipeline_dir: str | Path, stored_id: str) -> dict[str, Any]:
    """Resolve a stored task ID to its full form.

    Tries, in order:
    1. Exact match in any queue state
    2. Unique prefix match across all queue states and archives
    3. Title match (fuzzy)

    Returns {"resolved": str, "candidates": [str]}.
    """
    pipeline_path = Path(pipeline_dir)
    
    # 1. Exact match
    for state in QUEUE_STATES:
        state_dir = pipeline_path / "queue" / state
        if state_dir.is_dir():
            for task_file in state_dir.glob("*.json"):
                if task_file.stem == stored_id:
                    return {"resolved": task_file.stem, "candidates": []}
    
    # Also check archived
    for archived_dir in pipeline_path.glob("done/_archived*"):
        if archived_dir.is_dir():
            for task_file in archived_dir.glob("*.json"):
                if task_file.stem == stored_id:
                    return {"resolved": task_file.stem, "candidates": []}
    
    # 2. Prefix match
    candidates = []
    for state in QUEUE_STATES:
        state_dir = pipeline_path / "queue" / state
        if state_dir.is_dir():
            for task_file in state_dir.glob("*.json"):
                if task_file.stem.startswith(stored_id) and task_file.stem != stored_id:
                    candidates.append(task_file.stem)
    
    for archived_dir in pipeline_path.glob("done/_archived*"):
        if archived_dir.is_dir():
            for task_file in archived_dir.glob("*.json"):
                if task_file.stem.startswith(stored_id) and task_file.stem != stored_id:
                    if task_file.stem not in candidates:
                        candidates.append(task_file.stem)
    
    if len(candidates) == 1:
        return {"resolved": candidates[0], "candidates": candidates}
    
    # 3. Title match (read each task file and check title field)
    for state in QUEUE_STATES:
        state_dir = pipeline_path / "queue" / state
        if state_dir.is_dir():
            for task_file in state_dir.glob("*.json"):
                if task_file.stem in [c for c in candidates]:
                    continue  # skip already matched
                try:
                    record = json.loads(task_file.read_text(encoding="utf-8"))
                    title = str(record.get("title") or "")
                    if stored_id.lower() in title.lower():
                        candidates.append(task_file.stem)
                except (OSError, ValueError):
                    pass
    
    for archived_dir in pipeline_path.glob("done/_archived*"):
        if archived_dir.is_dir():
            for task_file in archived_dir.glob("*.json"):
                if task_file.stem in [c for c in candidates]:
                    continue  # skip already matched
                try:
                    record = json.loads(task_file.read_text(encoding="utf-8"))
                    title = str(record.get("title") or "")
                    if stored_id.lower() in title.lower():
                        candidates.append(task_file.stem)
                except (OSError, ValueError):
                    pass
    
    if len(candidates) == 1:
        return {"resolved": candidates[0], "candidates": candidates}
    
    if candidates:
        return {"resolved": stored_id, "candidates": candidates}
    
    # Unresolved
    return {"resolved": stored_id, "candidates": []}
