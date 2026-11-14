"""Checklist diffs: apply a proposed change to a feature's checklist.md safely. Standard library only.

A proposal is {"ops": [...]} with operations:
  {"op": "add",    "title": ..., "body": ..., "deps": ["FF-2"], "premium": false, "pieces": ["title" | {"title", "body"}, ...]}
  {"op": "change", "id": "FF-3", "title": ..., "body": ..., "deps": [...], "pieces": [...]}   (only the keys given change; pieces are appended)
  {"op": "split",  "id": "FF-3", "into": [{"title": ..., "body": ..., "deps": [...]}, ...]}
  {"op": "remove", "id": "FF-3"}

Filed items are locked: they can be changed (the item then carries 'changed: <date>' so the page can say "changed since
filing"; its task id and filing stamp are never touched) but never split or removed. preview() says what each op would do;
apply() writes the file only when every selected op is valid (all or nothing) and keeps a history copy through the store.
A line is '- [ ] FF-3 Title <!-- key: value ... -->' optionally followed by indented body lines.
Pieces: an indented body line of the form '- [x] 3a Title <!-- merged: abc1234 -->' is a SUB-PIECE of the item (shown under it in the
page with its own tick and merge commit). Pieces are ordinary body lines, so the editor, the diff ops and byte-stable rendering keep working.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from . import store

META_ORDER = ("task", "premium", "cloud", "deps", "filed", "manual", "merged", "changed")
TITLE_CAP = 120
BODY_CAP = 6000
OPS = ("add", "change", "split", "remove")


class ChecklistError(RuntimeError):
    pass


# ---- parsing and rendering ---------------------------------------------------------------------------------------

def parse(text: str) -> list[dict]:
    """Entries in file order: {'kind': 'raw', 'line': ...} or {'kind': 'item', 'raw', 'ticked', 'id', 'title', 'meta', 'body', 'dirty'}."""
    entries: list[dict] = []
    for line in text.split("\n"):
        m = store.ITEM_RE.match(line.rstrip())
        if m:
            entries.append({"kind": "item", "raw": line, "ticked": m.group(1) != " ", "id": m.group(2),
                            "title": m.group(3).strip(), "meta": store._parse_meta(m.group(4)), "body": [], "dirty": False})
        elif entries and entries[-1]["kind"] == "item" and line.startswith("  ") and line.strip():
            entries[-1]["body"].append(line[2:])
        else:
            entries.append({"kind": "raw", "line": line})
    return entries


def _meta_text(meta: dict) -> str:
    keys = [k for k in META_ORDER if k in meta] + sorted(k for k in meta if k not in META_ORDER)
    return " ".join(f"{k}: {meta[k]}".rstrip() if meta[k] != "" else f"{k}:" for k in keys)


def render(entries: list[dict]) -> str:
    out: list[str] = []
    for e in entries:
        if e["kind"] == "raw":
            out.append(e["line"])
            continue
        if e["dirty"] or e["raw"] is None:
            box = "x" if e["ticked"] else " "
            tail = f" <!-- {_meta_text(e['meta'])} -->" if e["meta"] else ""
            out.append(f"- [{box}] {e['id']} {e['title']}{tail}")
        else:
            out.append(e["raw"].rstrip("\n"))
        out.extend("  " + b for b in e["body"])
    return "\n".join(out)


def items(entries: list[dict]) -> list[dict]:
    return [e for e in entries if e["kind"] == "item"]


def is_locked(item: dict) -> bool:
    return bool(item["meta"].get("task") or item["meta"].get("filed"))


def _deps(item: dict) -> list[str]:
    return [d for d in re.split(r"[,\s]+", item["meta"].get("deps", "")) if d]


PIECE_RE = re.compile(r"^- \[( |x|X)\] (.+?)\s*(?:<!--(.*?)-->)?\s*$")


PIECE_LABEL_RE = re.compile(r"^(\d+[a-z]*\d*)\s+(.+)$")        # a leading label like 4, 4a or 3b1 is the piece's id


def pieces(item: dict) -> list[dict]:
    """The sub-pieces of an item: [{'ticked', 'id', 'title', 'meta', 'body'}] from its '- [x] 4a title <!-- key: value -->' body lines, in order.
    Lines under a piece that are indented two more spaces are that piece's own text ('body'), the task text a worker will see."""
    out = []
    for line in item["body"]:
        m = PIECE_RE.match(line)
        if m:
            label = PIECE_LABEL_RE.match(m.group(2).strip())
            out.append({"ticked": m.group(1) != " ", "id": label.group(1) if label else "",
                        "title": label.group(2) if label else m.group(2).strip(), "meta": store._parse_meta(m.group(3)), "body": ""})
        elif out and line.startswith("  "):
            out[-1]["body"] = (out[-1]["body"] + "\n" + line[2:]).strip("\n")
    return out


def plain_body(item: dict) -> list[str]:
    """The item's body lines that are not sub-pieces or a piece's own text."""
    out, in_piece = [], False
    for line in item["body"]:
        if PIECE_RE.match(line):
            in_piece = True
        elif in_piece and line.startswith("  "):
            continue
        else:
            in_piece = False
            out.append(line)
    return out


def update_piece(item: dict, piece_id: str, meta: dict | None = None, ticked: bool | None = None, drop: tuple = ()) -> bool:
    """Rewrite one piece line of an item in place: merge `meta` into its comment, remove the `drop` keys and/or set its tick. Returns False when there is no such piece."""
    for n, line in enumerate(item["body"]):
        m = PIECE_RE.match(line)
        if not m:
            continue
        label = PIECE_LABEL_RE.match(m.group(2).strip())
        if not label or label.group(1) != piece_id:
            continue
        merged = store._parse_meta(m.group(3))
        merged.update(meta or {})
        for k in drop:
            merged.pop(k, None)
        box = "x" if (m.group(1) != " " if ticked is None else ticked) else " "
        item["body"][n] = f"- [{box}] {piece_id} {label.group(2)}" + (f" <!-- {_meta_text(merged)} -->" if merged else "")
        return True
    return False


PIECE_BODY_CAP = 2000
PIECE_LETTERS = "abcdefghijklmnopqrstuvwxyz"


def _piece_lines(item_id: str, specs, taken: set[str]) -> list[str]:
    """Body lines for new pieces labelled <item number><letter> (4a, 4b...), skipping labels already taken; each spec is a title or {title, body}."""
    if not isinstance(specs, list) or not specs:
        raise ChecklistError("pieces must be a non-empty list")
    num = item_id.split("-")[1]
    lines: list[str] = []
    free = (f"{num}{c}" for c in PIECE_LETTERS if f"{num}{c}" not in taken)
    for spec in specs:
        title, body = (spec, "") if isinstance(spec, str) else (spec.get("title"), spec.get("body", "")) if isinstance(spec, dict) else (None, "")
        label = next(free, None)
        if label is None:
            raise ChecklistError("an item can have at most 26 pieces")
        text = str(body or "").strip("\n")
        if len(text) > PIECE_BODY_CAP or "-->" in text or "<!--" in text:
            raise ChecklistError(f"a piece's text must be at most {PIECE_BODY_CAP} characters without comment marks")
        lines.append(f"- [ ] {label} {_clean_title(title)}")
        if text.strip():
            lines.extend("  " + b for b in text.split("\n") if b.strip())
    return lines


def next_id(entries: list[dict]) -> str:
    nums = [int(i["id"].split("-")[1]) for i in items(entries)]
    return f"FF-{max(nums, default=0) + 1}"


# ---- checks ------------------------------------------------------------------------------------------------------

def _clean_title(title) -> str:
    t = " ".join(str(title or "").split())
    if not t or len(t) > TITLE_CAP or "<!--" in t or "-->" in t:
        raise ChecklistError(f"title must be 1-{TITLE_CAP} characters without comment marks")
    return t


def _clean_body(body) -> list[str]:
    text = str(body or "").strip("\n")
    if len(text) > BODY_CAP or "-->" in text or "<!--" in text:
        raise ChecklistError(f"body must be at most {BODY_CAP} characters without comment marks")
    return text.split("\n") if text.strip() else []


def _clean_deps(deps, known: set[str], self_id: str | None = None) -> list[str]:
    out = []
    for d in deps or []:
        d = str(d).strip()
        if not re.fullmatch(r"FF-\d+", d):
            raise ChecklistError(f"bad dependency {d!r}")
        if d == self_id:
            raise ChecklistError("an item cannot depend on itself")
        if d not in known:
            raise ChecklistError(f"dependency {d} does not exist")
        if d not in out:
            out.append(d)
    return out


def _acyclic(entries: list[dict]) -> bool:
    graph = {i["id"]: _deps(i) for i in items(entries)}
    state: dict[str, int] = {}

    def visit(n: str) -> bool:
        if state.get(n) == 1:
            return False
        if state.get(n) == 2:
            return True
        state[n] = 1
        ok = all(visit(d) for d in graph.get(n, []) if d in graph)
        state[n] = 2
        return ok
    return all(visit(n) for n in graph)


def _set_deps(item: dict, deps: list[str]) -> None:
    item["meta"]["deps"] = ",".join(deps)
    item["dirty"] = True


def _new_item(entries: list[dict], spec: dict, inherit: dict | None = None) -> dict:
    known = {i["id"] for i in items(entries)}
    new_id = next_id(entries)
    meta: dict = {}
    for flag in ("premium", "cloud"):
        v = spec.get(flag, (inherit or {}).get(flag))
        if v is not None and str(v).lower() in ("true", "false"):
            meta[flag] = str(v).lower() if not isinstance(v, bool) else ("true" if v else "false")
    item = {"kind": "item", "raw": None, "ticked": False, "id": new_id, "title": _clean_title(spec.get("title")),
            "meta": meta, "body": _clean_body(spec.get("body")), "dirty": True}
    _set_deps(item, _clean_deps(spec.get("deps"), known, new_id))
    if spec.get("pieces") is not None:
        item["body"] = item["body"] + _piece_lines(new_id, spec["pieces"], set())
    return item


# ---- operations --------------------------------------------------------------------------------------------------

def _find(entries: list[dict], item_id) -> dict:
    for i in items(entries):
        if i["id"] == item_id:
            return i
    raise ChecklistError(f"no such item {item_id}")


def _do_add(entries, op):
    entries.append(_new_item(entries, op))
    return f"add {entries[-1]['id']}: {entries[-1]['title']}"


def _do_change(entries, op):
    it = _find(entries, op.get("id"))
    known = {i["id"] for i in items(entries)}
    if "title" in op:
        it["title"] = _clean_title(op["title"])
    if "body" in op:
        it["body"] = _clean_body(op["body"])
    if "deps" in op:
        _set_deps(it, _clean_deps(op["deps"], known, it["id"]))
    if op.get("pieces") is not None:                       # new pieces are appended; existing ones (ticked or filed) are never touched
        it["body"] = it["body"] + _piece_lines(it["id"], op["pieces"], {p["id"] for p in pieces(it)})
    if is_locked(it):
        it["meta"]["changed"] = time.strftime("%Y-%m-%d")
    it["dirty"] = True
    return f"change {it['id']}" + (" (filed: marked changed since filing)" if is_locked(it) else "")


def _do_remove(entries, op):
    it = _find(entries, op.get("id"))
    if is_locked(it):
        raise ChecklistError(f"{it['id']} is filed and cannot be removed")
    for other in items(entries):
        if it["id"] in _deps(other):
            _set_deps(other, [d for d in _deps(other) if d != it["id"]] + [d for d in _deps(it) if d not in _deps(other)])
    entries.remove(it)
    return f"remove {it['id']}"


def _do_split(entries, op):
    it = _find(entries, op.get("id"))
    parts = op.get("into")
    if is_locked(it):
        raise ChecklistError(f"{it['id']} is filed and cannot be split")
    if not isinstance(parts, list) or len(parts) < 2:
        raise ChecklistError("a split needs at least two parts")
    at = entries.index(it)
    created: list[dict] = []
    for n, spec in enumerate(parts):      # the old item stays in place until the children exist, so its id is never reused
        spec = dict(spec)
        if "deps" not in spec:
            spec["deps"] = _deps(it) if n == 0 else [created[-1]["id"]]
        if it["id"] in [str(d) for d in spec["deps"]]:
            raise ChecklistError("a part of a split cannot depend on the item being split")
        child = _new_item(entries, spec, inherit=it["meta"])
        entries.insert(at + n, child)
        created.append(child)
    entries.remove(it)
    last = created[-1]["id"]
    for other in items(entries):
        if it["id"] in _deps(other):
            _set_deps(other, [last if d == it["id"] else d for d in _deps(other)])
    return f"split {it['id']} into " + ", ".join(c["id"] for c in created)


DISPATCH = {"add": _do_add, "change": _do_change, "remove": _do_remove, "split": _do_split}


def _run(entries: list[dict], ops: list, only: set[int] | None):
    """Apply the selected ops in order to entries; return one result per op (ok/summary or refusal)."""
    results = []
    for n, op in enumerate(ops):
        if only is not None and n not in only:
            results.append({"index": n, "ok": None, "summary": "not selected"})
            continue
        trial = _copy(entries)
        try:
            if not isinstance(op, dict) or op.get("op") not in OPS:
                raise ChecklistError(f"unknown op {op.get('op') if isinstance(op, dict) else op!r}")
            summary = DISPATCH[op["op"]](trial, op)
            if not _acyclic(trial):
                raise ChecklistError("that would make the dependencies circular")
        except ChecklistError as e:
            results.append({"index": n, "ok": False, "summary": str(e)})
            continue
        entries[:] = trial
        results.append({"index": n, "ok": True, "summary": summary})
    return results


def _copy(entries: list[dict]) -> list[dict]:
    return [dict(e, meta=dict(e["meta"]), body=list(e["body"])) if e["kind"] == "item" else dict(e) for e in entries]


def preview(slug: str, proposal: dict, root: Path | None = None) -> list[dict]:
    ops = proposal.get("ops") if isinstance(proposal, dict) else None
    if not isinstance(ops, list) or not ops:
        raise ChecklistError("the proposal has no ops")
    entries = parse(store.read_file(slug, "checklist.md", root))
    return _run(entries, ops, None)


def apply(slug: str, proposal: dict, only: list[int] | None = None, root: Path | None = None) -> dict:
    ops = proposal.get("ops") if isinstance(proposal, dict) else None
    if not isinstance(ops, list) or not ops:
        raise ChecklistError("the proposal has no ops")
    selected = set(only) if only is not None else None
    entries = parse(store.read_file(slug, "checklist.md", root))
    results = _run(entries, ops, selected)
    bad = [r for r in results if r["ok"] is False]
    if bad:
        raise ChecklistError("; ".join(f"op {r['index']}: {r['summary']}" for r in bad))
    if not any(r["ok"] for r in results):
        raise ChecklistError("nothing selected")
    store.write_file(slug, "checklist.md", render(entries), root)
    return {"results": results, "items": len(items(entries))}
