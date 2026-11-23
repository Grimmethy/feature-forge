"""Feature store: plain Markdown files under features/<slug>/ (files are the product).

Layout per feature: request.md, plan.md, interview.md, checklist.md; overwritten files are copied to
.history/<name>.<timestamp> first. Checklist line format:

    - [ ] FF-3 Title <!-- key: value key: value -->

Recognised comment keys: task, premium, cloud, deps, filed, manual (any other key is kept as written).
Status: Grilling (no items), Planned (items, none filed), Filed (some filed), Building (some ticked but not all),
Done (all ticked). Progress is (ticked, total).
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
from pathlib import Path

FILES = ("request.md", "plan.md", "interview.md", "checklist.md")
STATUSES = ("Grilling", "Planned", "Filed", "Building", "Done")
DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "features"

ITEM_RE = re.compile(r"^- \[( |x|X)\] (FF-\d+) (.*?)\s*(?:<!--(.*?)-->)?\s*$")


class StoreError(RuntimeError):
    pass


class DuplicateFeatureError(StoreError):
    """Raised when a feature with the same normalized title or slug already exists."""

    def __init__(self, message: str, title: str = ""):
        super().__init__(message)
        self.title = (title or "").strip()


def _normalize_title(title: str) -> str:
    """Trim, collapse whitespace, lowercase."""
    return re.sub(r"\s+", " ", (title or "").strip()).lower()


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
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=f".{p.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def create_feature(title: str, request_text: str, root: Path | None = None, tags=None) -> str:
    title = (title or "").strip()
    if not title:
        raise StoreError("title is required")
    base = _root(root)
    slug = slugify(title)
    norm = _normalize_title(title)

    # Check for duplicates: same slug OR same normalized heading in request.md
    if base.is_dir():
        for candidate in base.iterdir():
            if not candidate.is_dir() or candidate.name.startswith("."):
                continue
            # Slug collision
            if candidate.name == slug:
                raise DuplicateFeatureError(f"duplicate feature slug: {slug}", title=title)
            # Normalized heading collision
            req = candidate / "request.md"
            if req.is_file():
                try:
                    head_match = re.search(r"^# (.+)$", req.read_text(encoding="utf-8"), re.M)
                    if head_match and _normalize_title(head_match.group(1)) == norm:
                        raise DuplicateFeatureError(f"duplicate feature title: {title}", title=title)
                except DuplicateFeatureError:
                    raise
                except Exception:
                    pass

    base.mkdir(parents=True, exist_ok=True)  # ensure parent collection exists
    d = base / slug
    d.mkdir()  # non-recursive; FileExistsError → duplicate
    created_dir = True
    try:
        body = (request_text or "").strip()
        tags_line = ""
        if tags:
            clean = normalise_tags(tags)
            if clean:
                tags_line = "tags: " + ", ".join(clean) + "\n"
        d.joinpath("request.md").write_text(f"# {title}\n{tags_line}\n{body}\n", encoding="utf-8")
        d.joinpath("plan.md").write_text(f"# Plan: {title}\n\n_Not started._\n", encoding="utf-8")
        d.joinpath("interview.md").write_text(f"# Interview: {title}\n\n_Not started._\n", encoding="utf-8")
        d.joinpath("checklist.md").write_text(f"# Checklist: {title}\n\n", encoding="utf-8")
    except BaseException:
        if created_dir and d.is_dir():
            shutil.rmtree(d)
        raise
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


def derive_status(items: list[dict]) -> str:
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


TAGS_RE = re.compile(r"^\s*tags\s*:\s*(.*)$", re.I)


def _parse_tags(text: str) -> list[str]:
    """First 'tags:' line -> lowercased, trimmed, de-duplicated tags in first-seen order. [] when absent."""
    for line in text.splitlines():
        m = TAGS_RE.match(line)
        if m:
            tags: list[str] = []
            for part in m.group(1).split(","):
                t = part.strip().lower()
                if t and t not in tags:
                    tags.append(t)
            return tags
    return []


_TAG_ALLOWED_RE = re.compile(r"^[a-z0-9/_-]+$")


def normalise_tags(tags):
    """Lowercase, trim, drop empty, dedupe (first-seen order kept).

    Raise ValueError naming every tag whose characters fall outside
    [a-z 0-9 - / _].  Empty-after-trim entries are silently dropped,
    matching _parse_tags behaviour.  Preserves first-seen order."""
    cleaned, bad = [], []
    for raw in tags or []:
        t = str(raw).strip().lower()
        if not t:
            continue
        if t in cleaned:
            continue
        if _TAG_ALLOWED_RE.match(t):
            cleaned.append(t)
        else:
            bad.append(t)
    if bad:
        raise ValueError(f"invalid tag(s): {', '.join(sorted(bad))}")
    return cleaned


def set_tags(slug, tags, root=None):
    """Rewrite only the 'tags:' line of request.md.

    Validates and normalises *tags* before any I/O. Replaces an
    existing 'tags:' line in place (removing it when the list is
    empty), or inserts one after 'repo:' if present, otherwise after
    the '# ' heading. Writes through write_file so .history/ is kept."""
    clean = normalise_tags(tags)
    fdir = feature_dir(slug, root)
    path = fdir / "request.md"
    raw = path.read_text(encoding="utf-8")
    lines = raw.splitlines(keepends=True)
    idx = next((i for i, l in enumerate(lines) if l.startswith("tags:")), None)
    if idx is not None:
        if clean:
            eol = "\n" if lines[idx].endswith("\n") else ""
            lines[idx] = "tags: " + ", ".join(clean) + eol
        else:
            del lines[idx]
    elif clean:
        pos = next((i for i, l in enumerate(lines) if l.startswith("repo:")), None)
        if pos is None:
            pos = next((i for i, l in enumerate(lines) if l.startswith("# ")), None)
        if pos is None:
            raise StoreError(
                f"request.md has no 'repo:' or '# ' heading to anchor tags"
            )
        if not lines[pos].endswith("\n"):
            lines[pos] += "\n"
        lines.insert(pos + 1, "tags: " + ", ".join(clean) + "\n")
    else:
        return
    new_text = "".join(lines)
    if new_text == raw:
        return
    write_file(slug, "request.md", new_text, root=root)


def _request_tags(slug: str, root: Path | None) -> list[str]:
    try:
        return _parse_tags(read_file(slug, "request.md", root))
    except StoreError:
        return []


def all_tags(root: Path | None = None) -> list[dict]:
    """Sorted [{tag, count}]. A feature tagged a/b/c counts once toward a, a/b and a/b/c."""
    counts: dict[str, int] = {}
    for f in list_features(root):
        seen: set[str] = set()
        for t in f["tags"]:
            parts = t.split("/")
            for i in range(1, len(parts) + 1):
                seen.add("/".join(parts[:i]))
        for t in seen:
            counts[t] = counts.get(t, 0) + 1
    return [{"tag": t, "count": counts[t]} for t in sorted(counts)]


def tag_matches(feature_tags: list[str], selected: list[str]) -> bool:
    """True when every selected tag equals a feature tag or is a '/'-prefix of one."""
    for s in selected:
        if not any(f == s or f.startswith(s + "/") for f in feature_tags):
            return False
    return True


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
        out.append({"slug": d.name, "title": title, "status": derive_status(items), "ticked": done,
                    "total": total, "repo": repo, "updated": updated,
                    "tags": _request_tags(d.name, root)})
    return out
