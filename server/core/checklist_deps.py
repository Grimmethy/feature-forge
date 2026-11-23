"""Normalize and validate checklist item dependency ids."""
import re


def normalize_deps(value):
    """Return a list of dependency id strings.

    None -> []; str is split on commas/whitespace; list entries are stripped
    and empties dropped. Any other type raises ValueError.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [p for p in re.split(r"[,\s]+", value.strip()) if p]
    if isinstance(value, list):
        out = []
        for entry in value:
            if not isinstance(entry, str):
                raise ValueError("deps must be a string or list of strings")
            entry = entry.strip()
            if entry:
                out.append(entry)
        return out
    raise ValueError("deps must be a string or list of strings")


def validate_deps(deps, existing_ids):
    """Raise ValueError('Unknown dependency: <ids>') if any dep is unknown."""
    known = set(existing_ids)
    unknown = [d for d in deps if d not in known]
    if unknown:
        raise ValueError("Unknown dependency: " + ", ".join(unknown))
