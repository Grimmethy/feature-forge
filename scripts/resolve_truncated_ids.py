#!/usr/bin/env python3
"""One-off script to list checklist items whose stored task ID required fallback resolution.

Iterates over all items in features/feature-forge/checklist.md, attempts to resolve each
stored task ID using resolveTaskId, and prints items where resolution required fallback
(not an exact match) along with the resolved full ID.

This script is read-only and does not modify the checklist.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add the repo root to the path so we can import server.core
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from server.core import checklist
from server.core.resolve_task import resolveTaskId


def main() -> None:
    checklist_path = repo_root / "features" / "feature-forge" / "checklist.md"
    
    # Find pipeline directory: accept as argument, or look in standard locations
    if len(sys.argv) > 1:
        pipeline_dir = Path(sys.argv[1])
    else:
        # Look in standard locations
        standard_locations = [
            repo_root / "pipeline",
            Path.home() / ".config" / "pipeline-ops",
            Path("/media/model-cache/github/agent-manager"),
        ]
        pipeline_dir = None
        for loc in standard_locations:
            if loc.is_dir():
                pipeline_dir = loc
                break
        
        if pipeline_dir is None:
            print("ERROR: No pipeline directory found. Pass as first argument.", file=sys.stderr)
            print("Searched:", [str(l) for l in standard_locations], file=sys.stderr)
            sys.exit(1)

    if not checklist_path.is_file():
        print(f"ERROR: checklist not found at {checklist_path}", file=sys.stderr)
        sys.exit(1)

    text = checklist_path.read_text(encoding="utf-8")
    entries = checklist.parse(text)
    items = checklist.items(entries)

    resolved_count = 0

    for item in items:
        task_id = item["meta"].get("task")
        if not task_id:
            continue

        result = resolveTaskId(pipeline_dir, task_id)
        resolved = result["resolved"]

        # If resolved differs from stored, fallback was needed
        if resolved != task_id:
            resolved_count += 1
            print(f"[{item['id']}] {item['title']}")
            print(f"  stored:  {task_id}")
            print(f"  resolved: {resolved}")
            if result["candidates"]:
                print(f"  candidates: {result['candidates']}")
            print()

    print(f"Total items requiring fallback resolution: {resolved_count}")


if __name__ == "__main__":
    main()
