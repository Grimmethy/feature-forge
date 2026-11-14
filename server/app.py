"""Feature Forge HTTP API (Flask, 127.0.0.1:7466). All persistence goes through server.core.store.

Routes: GET / (the single-page UI), GET /api/health, GET|POST /api/features, GET /api/features/<slug>/tree,
GET|PUT /api/features/<slug>/file?path=, GET /api/features/<slug>/render?path=, GET /api/search?q=,
GET /api/repos, GET|POST /api/features/<slug>/repo, GET /api/features/<slug>/checklist, POST .../checklist/preview|apply,
POST /api/grill/<slug>/<sid>/proposal, and the grill routes: POST /api/grill/start,
GET /api/grill/<slug>/sessions, POST /api/grill/<slug>/<sid>/begin|message (server-sent events), /save and /end.
No timers and no polling: every response is computed when asked.
"""
from __future__ import annotations

import os
import posixpath
import re
import sys
from pathlib import Path

import markdown as md
from flask import Flask, Response, jsonify, request, send_from_directory, stream_with_context

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.core import checklist, grill, store  # noqa: E402

HREF_RE = re.compile(r'href="(?![a-z][a-z0-9+.-]*:|/|#)([^"#]+\.md)"', re.I)
WEB_DIR = Path(__file__).resolve().parents[1] / "web"
SNIPPET = 60
SEARCH_CAP = 200
REPO_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")


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


def _set_repo_line(text: str, name: str) -> str:
    """Put 'repo: <name>' into request.md: replace the existing line, or add one under the first heading."""
    if re.search(r"^repo:\s*\S+\s*$", text, re.M | re.I):
        return re.sub(r"^repo:\s*\S+\s*$", f"repo: {name}", text, count=1, flags=re.M | re.I)
    lines = text.split("\n")
    at = 1 if lines and lines[0].startswith("#") else 0
    return "\n".join(lines[:at] + ["", f"repo: {name}"] + lines[at:])


def _sse(gen) -> Response:
    return Response(stream_with_context(gen), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def create_app(root: Path | None = None) -> Flask:
    app = Flask(__name__)
    app.config["FEATURE_ROOT"] = root

    def froot() -> Path | None:
        return app.config["FEATURE_ROOT"]

    @app.errorhandler(store.StoreError)
    def store_error(e: store.StoreError):
        return jsonify({"error": str(e)}), (404 if str(e).startswith("no such") else 400)

    @app.errorhandler(checklist.ChecklistError)
    def checklist_error(e: checklist.ChecklistError):
        return jsonify({"error": str(e)}), 400

    @app.errorhandler(grill.GrillError)
    def grill_error(e: grill.GrillError):
        msg = str(e)
        code = 502 if msg.startswith("chat plugin unavailable") else 404 if msg.startswith("no such") else 400
        return jsonify({"error": msg}), code

    @app.get("/")
    def index():
        return send_from_directory(WEB_DIR, "index.html")

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

    @app.get("/api/features/<slug>/checklist")
    def get_checklist(slug):
        entries = checklist.parse(store.read_file(slug, "checklist.md", froot()))
        return jsonify([{"id": i["id"], "title": i["title"], "ticked": i["ticked"], "locked": checklist.is_locked(i),
                         "deps": checklist._deps(i), "body": "\n".join(i["body"]), "meta": i["meta"]}
                        for i in checklist.items(entries)])

    @app.post("/api/features/<slug>/checklist/preview")
    def checklist_preview(slug):
        proposal = (request.get_json(silent=True) or {}).get("proposal")
        return jsonify({"results": checklist.preview(slug, proposal, froot())})

    @app.post("/api/features/<slug>/checklist/apply")
    def checklist_apply(slug):
        body = request.get_json(silent=True) or {}
        only = body.get("only")
        if only is not None and not (isinstance(only, list) and all(isinstance(n, int) and not isinstance(n, bool) for n in only)):
            return jsonify({"error": "only must be a list of operation numbers"}), 400
        return jsonify(checklist.apply(slug, body.get("proposal"), only, froot()))

    @app.post("/api/grill/<slug>/<sid>/proposal")
    def grill_proposal(slug, sid):
        proposal = grill.proposal_from_session(slug, sid, froot())
        return jsonify({"proposal": proposal, "preview": checklist.preview(slug, proposal, froot())})

    @app.get("/api/repos")
    def repos():
        return jsonify(grill.repo_index())

    @app.get("/api/features/<slug>/repo")
    def get_repo(slug):
        store.feature_dir(slug, froot())
        return jsonify(grill.target_repo(slug, froot()))

    @app.post("/api/features/<slug>/repo")
    def set_repo(slug):
        """The owner's decision: which repo this feature is built in (an existing one, or the name of a new one)."""
        name = str((request.get_json(silent=True) or {}).get("name", "")).strip()
        if not REPO_NAME_RE.match(name):
            return jsonify({"error": "name must be letters, digits, dots, dashes or underscores"}), 400
        store.write_file(slug, "request.md", _set_repo_line(store.read_file(slug, "request.md", froot()), name), froot())
        return jsonify(grill.target_repo(slug, froot()))

    @app.post("/api/grill/start")
    def grill_start():
        body = request.get_json(silent=True) or {}
        return jsonify(grill.start(str(body.get("feature", "")), str(body.get("node") or "feature"), root=froot())), 201

    @app.get("/api/grill/<slug>/sessions")
    def grill_sessions(slug):
        return jsonify(grill.list_sessions(slug, froot()))

    @app.post("/api/grill/<slug>/<sid>/begin")
    def grill_begin(slug, sid):
        grill.load_meta(slug, sid, froot())
        return _sse(grill.stream_turn(slug, sid, None, froot()))

    @app.post("/api/grill/<slug>/<sid>/message")
    def grill_message(slug, sid):
        text = str((request.get_json(silent=True) or {}).get("message", "")).strip()
        if not text:
            return jsonify({"error": "message is required"}), 400
        grill.load_meta(slug, sid, froot())
        return _sse(grill.stream_turn(slug, sid, text, froot()))

    @app.post("/api/grill/<slug>/<sid>/save")
    def grill_save(slug, sid):
        return jsonify(grill.save_to_interview(slug, sid, froot()))

    @app.post("/api/grill/<slug>/<sid>/end")
    def grill_end(slug, sid):
        return jsonify(grill.end(slug, sid, froot()))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("FEATUREFORGE_PORT", "7466")), threaded=True)
