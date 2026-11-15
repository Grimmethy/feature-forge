"""Feature store: plain Markdown files under features/<slug>/ (files are the product).

Layout per feature: request.md, plan.md, interview.md, checklist.md; overwritten files are copied to
.history/<name>.<timestamp> first. Checklist line format:

    - [ ] FF-3 Title <!-- key: value key: value -->

Recognised comment keys: task, premium, cloud, deps, filed, manual (any other key is kept as written).
Status: Grilling (no items), Planned (items, none filed), Filed (some filed), Building (some ticked but not all),
Done (all ticked). Progress is (ticked, total).
"""
from __future__ import annotations

import re
import shutil
import time
from pathlib import Path

FILES = ("request.md", "plan.md", "interview.md", "checklist.md")
STATUSES = ("Grilling", "Planned", "Filed", "Building", "Done")
DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "features"

ITEM_RE = re.compile(r"^- \[( |x|X)\] (FF-\d+) (.*?)\s*(?:<!--(.*?)-->)?\s*$")


class StoreError(RuntimeError):
    pass


def _root(root: Path | None) -> Path:
    return Path(root) if root is not None else DEFAULT_ROOT


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "feature"


def feature_dir(slug: str, root: Path | None = None) -> Path:
    if not slug or slug != slugify(slug):
        raise StoreError("bad feature slug")
    d = _root(root) / slug
    if not d.is_dir():
        raise StoreError("no such feature")
    return d


def _safe_path(slug: str, rel: str, root: Path | None) -> Path:
    base = feature_dir(slug, root).resolve()
    if not rel or Path(rel).is_absolute() or not rel.endswith(".md"):
        raise StoreError("path must be a relative .md file")
    p = (base / rel).resolve()
    if base != p and base not in p.parents:
        raise StoreError("path escapes the feature folder")
    return p


def read_file(slug: str, rel: str, root: Path | None = None) -> str:
    p = _safe_path(slug, rel, root)
    if not p.is_file():
        raise StoreError("no such file")
    return p.read_text(encoding="utf-8")


def write_file(slug: str, rel: str, text: str, root: Path | None = None) -> None:
    p = _safe_path(slug, rel, root)
    if p.is_file():
        hist = feature_dir(slug, root) / ".history"
        hist.mkdir(exist_ok=True)
        shutil.copy2(p, hist / f"{p.name}.{time.strftime('%Y%m%dT%H%M%S')}")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def create_feature(title: str, request_text: str, root: Path | None = None) -> str:
    title = (title or "").strip()
    if not title:
        raise StoreError("title is required")
    base, slug, n = _root(root), slugify(title), 1
    while (base / slug).exists():
        n += 1
        slug = f"{slugify(title)}-{n}"
    d = base / slug
    d.mkdir(parents=True)
    d.joinpath("request.md").write_text(f"# {title}\n\n{(request_text or '').strip()}\n", encoding="utf-8")
    d.joinpath("plan.md").write_text(f"# Plan: {title}\n\n_Not started._\n", encoding="utf-8")
    d.joinpath("interview.md").write_text(f"# Interview: {title}\n\n_Not started._\n", encoding="utf-8")
    d.joinpath("checklist.md").write_text(f"# Checklist: {title}\n\n", encoding="utf-8")
    return slug


def _parse_meta(comment: str | None) -> dict:
    """'task: abc premium: true deps:' -> {'task': 'abc', 'premium': 'true', 'deps': ''}. A token ending in ':' starts a key."""
    meta: dict[str, str] = {}
    key = None
    for tok in (comment or "").split():
        if tok.endswith(":"):
            key = tok[:-1]
            meta[key] = ""
        elif key is not None:
            meta[key] = (meta[key] + " " + tok).strip()
    return meta


def parse_checklist_text(text: str) -> list[dict]:
    items = []
    for line in text.splitlines():
        m = ITEM_RE.match(line.rstrip())
        if m:
            items.append({"id": m.group(2), "title": m.group(3).strip(), "ticked": m.group(1) != " ",
                          "meta": _parse_meta(m.group(4))})
    return items


def parse_checklist(slug: str, root: Path | None = None) -> list[dict]:
    try:
        return parse_checklist_text(read_file(slug, "checklist.md", root))
    except StoreError:
        return []


def _grill_gate(feature_dir: Path, slug: str) -> bool:
    """True when request.md carries 'grill: required' and grill_done(slug) is still False."""
    try:
        text = (feature_dir / "request.md").read_text(encoding="utf-8")
    except FileNotFoundError:
        return False
    if not any(line.strip() == "grill: required" for line in text.splitlines()):
        return False
    from .grill import grill_done  # lazy import: grill.py is owned by subtask 1/6
    return not grill_done(slug)


def derive_status(items: list[dict], slug: str | None = None, feature_dir: Path | None = None) -> str:
    if slug is not None and feature_dir is not None and _grill_gate(feature_dir, slug):
        return "Grilling"
    if not items:
        return "Grilling"
    if all(i["ticked"] for i in items):
        return "Done"
    if any(i["ticked"] for i in items):
        return "Building"
    if any(i["meta"].get("task") or i["meta"].get("filed") for i in items):
        return "Filed"
    return "Planned"


def progress(items: list[dict]) -> tuple[int, int]:
    return sum(1 for i in items if i["ticked"]), len(items)


def _heading(slug: str, rel: str, prefix: str, root: Path | None) -> str:
    try:
        m = re.search(rf"^#\s+{prefix}(.+)$", read_file(slug, rel, root), re.M)
    except StoreError:
        return ""
    return m.group(1).strip() if m else ""


def _request_info(slug: str, root: Path | None) -> tuple[str, str]:
    """(title, repo). Title: the plan or checklist heading, then request.md's heading, then the slug."""
    title = (_heading(slug, "plan.md", r"Plan:\s*", root) or _heading(slug, "checklist.md", r"Checklist:\s*", root)
             or _heading(slug, "request.md", "", root) or slug)
    try:
        repo = re.search(r"^repo:\s*(\S+)\s*$", read_file(slug, "request.md", root), re.M | re.I)
    except StoreError:
        repo = None
    return title, (repo.group(1) if repo else "")


def list_features(root: Path | None = None) -> list[dict]:
    base = _root(root)
    if not base.is_dir():
        return []
    out = []
    for d in sorted(p for p in base.iterdir() if p.is_dir() and not p.name.startswith(".")):
        items = parse_checklist(d.name, root)
        title, repo = _request_info(d.name, root)
        done, total = progress(items)
        updated = max((f.stat().st_mtime for f in d.glob("*.md")), default=d.stat().st_mtime)
        out.append({"slug": d.name, "title": title, "status": derive_status(items, slug=d.name, feature_dir=d), "ticked": done,
                    "total": total, "repo": repo, "updated": updated})
    return out
