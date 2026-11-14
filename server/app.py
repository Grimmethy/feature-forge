"""Feature Forge HTTP API (Flask, 127.0.0.1:7466). All persistence goes through server.core.store.

Routes: GET /api/health, GET|POST /api/features, GET /api/features/<slug>/tree,
GET|PUT /api/features/<slug>/file?path=, GET /api/features/<slug>/render?path=, GET /api/search?q=
No timers and no polling: every response is computed when asked.
"""
from __future__ import annotations

import os
import posixpath
import re
import sys
from pathlib import Path

import markdown as md
from flask import Flask, jsonify, request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.core import store  # noqa: E402

HREF_RE = re.compile(r'href="(?![a-z][a-z0-9+.-]*:|/|#)([^"#]+\.md)"', re.I)
SNIPPET = 60
SEARCH_CAP = 200


def _md_files(slug: str, root: Path | None) -> list[Path]:
    base = store.feature_dir(slug, root)
    return sorted(p for p in base.rglob("*.md") if not any(part.startswith(".") for part in p.relative_to(base).parts))


def _rewrite_links(html: str, rel: str) -> str:
    """Turn relative .md links into href="#" data-md="<path inside the feature>" so the UI can open them."""
    def fix(m: re.Match) -> str:
        target = posixpath.normpath(posixpath.join(posixpath.dirname(rel), m.group(1)))
        if target.startswith(".."):
            return 'href="#"'
        return f'href="#" data-md="{target}"'
    return HREF_RE.sub(fix, html)


def create_app(root: Path | None = None) -> Flask:
    app = Flask(__name__)
    app.config["FEATURE_ROOT"] = root

    def froot() -> Path | None:
        return app.config["FEATURE_ROOT"]

    @app.errorhandler(store.StoreError)
    def store_error(e: store.StoreError):
        return jsonify({"error": str(e)}), (404 if str(e).startswith("no such") else 400)

    @app.get("/api/health")
    def health():
        return jsonify({"ok": True})

    @app.get("/api/features")
    def features():
        return jsonify(store.list_features(froot()))

    @app.post("/api/features")
    def new_feature():
        body = request.get_json(silent=True) or {}
        slug = store.create_feature(body.get("title", ""), body.get("request", body.get("request_text", "")), froot())
        return jsonify({"slug": slug}), 201

    @app.get("/api/features/<slug>/tree")
    def tree(slug):
        base = store.feature_dir(slug, froot())
        return jsonify([{"path": p.relative_to(base).as_posix(), "words": len(p.read_text(encoding="utf-8").split())}
                        for p in _md_files(slug, froot())])

    @app.get("/api/features/<slug>/file")
    def get_file(slug):
        rel = request.args.get("path", "")
        return jsonify({"path": rel, "text": store.read_file(slug, rel, froot())})

    @app.put("/api/features/<slug>/file")
    def put_file(slug):
        rel = request.args.get("path", "")
        body = request.get_json(silent=True) or {}
        if not isinstance(body.get("text"), str):
            return jsonify({"error": "body must be JSON with a text string"}), 400
        store.write_file(slug, rel, body["text"], froot())
        return jsonify({"ok": True, "path": rel})

    @app.get("/api/features/<slug>/render")
    def render(slug):
        rel = request.args.get("path", "")
        text = store.read_file(slug, rel, froot())
        html = md.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])
        return jsonify({"path": rel, "html": _rewrite_links(html, rel)})

    @app.get("/api/search")
    def search():
        q = request.args.get("q", "").strip().lower()
        if not q:
            return jsonify([])
        hits: list[dict] = []
        for f in store.list_features(froot()):
            base = store.feature_dir(f["slug"], froot())
            for p in _md_files(f["slug"], froot()):
                text = p.read_text(encoding="utf-8")
                i = text.lower().find(q)
                if i >= 0:
                    snip = text[max(0, i - SNIPPET): i + len(q) + SNIPPET].replace("\n", " ")
                    hits.append({"slug": f["slug"], "path": p.relative_to(base).as_posix(), "snippet": snip})
                    if len(hits) >= SEARCH_CAP:
                        return jsonify(hits)
        return jsonify(hits)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("FEATUREFORGE_PORT", "7466")), threaded=True)
