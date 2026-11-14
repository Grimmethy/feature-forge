"""Read-only views over the library: the board, the by-repo roll-up and a per-feature dependency graph. Standard library only.

Everything is derived from the checklists when asked (no stored state, no timers, no task-queue reads): the board puts every item in
one of three columns by its checklist comment alone, the roll-up groups features by their 'repo:' line, and the graph is an SVG
built by hand (layers by longest dependency path), styled by the page through the classes gn/done/filed/open.
"""
from __future__ import annotations

import html
from pathlib import Path

from . import checklist, store

COLUMNS = ("Not filed", "In flight", "Done")
NODE_W, NODE_H, GAP_X, GAP_Y, PAD, TITLE_CAP = 220, 40, 70, 16, 16, 28


def column(item: dict) -> str:
    if item["ticked"]:
        return "Done"
    return "In flight" if item["meta"].get("task") else "Not filed"


def board(root: Path | None = None) -> dict:
    """{'columns': {name: [card, ...]}}; a card is {slug, feature, id, title, repo, premium, cloud, took}."""
    cols = {c: [] for c in COLUMNS}
    for f in sorted(store.list_features(root), key=lambda f: -f["updated"]):
        for it in checklist.items(checklist.parse(store.read_file(f["slug"], "checklist.md", root))):
            m = it["meta"]
            cols[column(it)].append({"slug": f["slug"], "feature": f["title"], "id": it["id"], "title": it["title"], "repo": f["repo"],
                                     "premium": m.get("premium") == "true", "cloud": m.get("cloud") == "true", "took": m.get("took", "")})
    return {"columns": cols}


def by_repo(root: Path | None = None) -> list[dict]:
    """Features grouped by repo, with each group's ticked and total items; features with no repo come last."""
    groups: dict[str, dict] = {}
    for f in store.list_features(root):
        g = groups.setdefault(f["repo"], {"repo": f["repo"], "features": [], "ticked": 0, "total": 0})
        g["features"].append({k: f[k] for k in ("slug", "title", "status", "ticked", "total")})
        g["ticked"] += f["ticked"]
        g["total"] += f["total"]
    return sorted(groups.values(), key=lambda g: (g["repo"] == "", g["repo"]))


def _depths(items: list[dict]) -> dict[str, int]:
    deps = {i["id"]: checklist._deps(i) for i in items}
    memo: dict[str, int] = {}

    def depth(n: str, seen: tuple = ()) -> int:
        if n in memo:
            return memo[n]
        if n in seen:
            return 0                                     # a cycle cannot be saved by the editor; never loop on one anyway
        d = 1 + max((depth(x, seen + (n,)) for x in deps.get(n, []) if x in deps), default=-1)
        memo[n] = d
        return d
    return {n: depth(n) for n in deps}


def graph_svg(slug: str, root: Path | None = None) -> str:
    """The dependency graph of a feature's checklist as an SVG string."""
    items = checklist.items(checklist.parse(store.read_file(slug, "checklist.md", root)))
    if not items:
        return '<svg xmlns="http://www.w3.org/2000/svg" class="graph" width="240" height="40"><text x="8" y="24">No checklist items yet.</text></svg>'
    depth = _depths(items)
    rows: dict[int, int] = {}
    pos: dict[str, tuple[int, int]] = {}
    for it in items:
        d = depth[it["id"]]
        r = rows.get(d, 0)
        rows[d] = r + 1
        pos[it["id"]] = (PAD + d * (NODE_W + GAP_X), PAD + r * (NODE_H + GAP_Y))
    width = PAD * 2 + (max(depth.values()) + 1) * NODE_W + max(depth.values()) * GAP_X
    height = PAD * 2 + max(rows.values()) * NODE_H + (max(rows.values()) - 1) * GAP_Y
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" class="graph" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
           '<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
           '<path d="M0,0 L10,5 L0,10 z" class="arrow"/></marker></defs>']
    for it in items:
        x2, y2 = pos[it["id"]]
        for d in checklist._deps(it):
            if d in pos:
                x1, y1 = pos[d]
                x1 += NODE_W
                y1 += NODE_H // 2
                y2c = y2 + NODE_H // 2
                mid = (x1 + x2) // 2
                out.append(f'<path class="edge" d="M{x1},{y1} C{mid},{y1} {mid},{y2c} {x2},{y2c}" marker-end="url(#arr)"/>')
    for it in items:
        x, y = pos[it["id"]]
        state = "done" if it["ticked"] else "filed" if it["meta"].get("task") else "open"
        title = it["title"] if len(it["title"]) <= TITLE_CAP else it["title"][:TITLE_CAP - 1] + "…"
        out.append(f'<g class="gn {state}" data-id="{html.escape(it["id"])}"><title>{html.escape(it["id"] + " " + it["title"])}</title>'
                   f'<rect x="{x}" y="{y}" width="{NODE_W}" height="{NODE_H}" rx="6"/>'
                   f'<text x="{x + 10}" y="{y + 25}">{html.escape(it["id"])} {html.escape(title)}</text></g>')
    out.append("</svg>")
    return "".join(out)
