"""Feature Forge HTTP API (Flask, 127.0.0.1:7466). All persistence goes through server.core.store.

Routes: GET / (the single-page UI), GET /api/health, GET|POST /api/features, GET /api/features/<slug>/tree,
GET|PUT /api/features/<slug>/file?path=, GET /api/features/<slug>/render?path=, GET /api/search?q=,
GET /api/repos, GET /api/repos/unregistered, GET|POST /api/features/<slug>/repo, GET /api/features/<slug>/checklist, POST .../checklist/preview|apply,
POST /api/features/<slug>/checklist/<id>/file|flag, POST /api/features/<slug>/sync, GET /api/repos/plan?name=, POST /api/repos/create, GET /api/views/board, GET /api/views/repos, GET /api/features/<slug>/graph.svg, POST /api/grill/<slug>/<sid>/proposal, and the grill routes: POST /api/grill/start,
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
from flask import Flask, Response, abort, jsonify, request, send_from_directory, stream_with_context

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.core import checklist, filing, grill, proposals, repo_create, status, store, views  # noqa: E402

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

    @app.errorhandler(filing.FilingError)
    def filing_error(e: filing.FilingError):
        msg = str(e)
        code = 404 if msg.startswith("no such") else 502 if msg.startswith("Agent Manager did not accept") else 400
        return jsonify({"error": msg}), code

    @app.errorhandler(repo_create.RepoCreateError)
    def repo_create_error(e: repo_create.RepoCreateError):
        return jsonify({"error": str(e)}), 400

    @app.errorhandler(filing.NotRegisteredError)
    def not_registered_error(e: filing.NotRegisteredError):
        return jsonify({"code": "not-registered", "repo": e.repo, "steps": repo_create.plan(e.repo), "error": str(e)}), 409

    @app.errorhandler(grill.GrillError)
    def grill_error(e: grill.GrillError):
        msg = str(e)
        code = 502 if msg.startswith("chat plugin unavailable") else 404 if msg.startswith("no such") else 400
        return jsonify({"error": msg}), code

    @app.get("/")
    def index():
        return send_from_directory(WEB_DIR, "index.html")

    @app.get("/<path:filename>")
    def static_file(filename):
        # Only the .js/.css files in web/ are served; dotfiles, other types, and anything
        # send_from_directory's safe_join rejects (traversal) return 404.
        parts = filename.split("/")
        if "\\" in filename or any(part == "" or part.startswith(".") for part in parts):
            abort(404)
        if not filename.endswith((".js", ".css")):
            abort(404)
        return send_from_directory(WEB_DIR, filename)

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
                         "deps": checklist._deps(i), "body": "\n".join(checklist.plain_body(i)), "meta": i["meta"],
                         "pieces": checklist.pieces(i), "pieceDone": sum(p["ticked"] for p in checklist.pieces(i)),
                         "pieceTotal": len(checklist.pieces(i)),
                         "pieceUnfiled": sum(1 for p in checklist.pieces(i) if not p["ticked"] and not p["meta"].get("task")),
                         "lint": filing.lint(i["title"] + "\n" + "\n".join(i["body"]))}
                        for i in checklist.items(entries)])

    @app.get("/api/repos/plan")
    def repo_plan():
        """What creating a new repo would do, step by step. Changes nothing."""
        return jsonify({"steps": repo_create.plan(request.args.get("name", ""))})

    @app.post("/api/repos/create")
    def repo_make():
        """Create the repo: only with {"name": ..., "confirm": true}, which the page sends after the owner has seen the steps."""
        body = request.get_json(silent=True) or {}
        if body.get("confirm") is not True:
            return jsonify({"error": "send confirm: true after showing the steps"}), 400
        return jsonify({"steps": repo_create.create(body.get("name", ""))})

    @app.get("/api/views/board")
    def view_board():
        return jsonify(views.board(froot()))

    @app.get("/api/views/repos")
    def view_repos():
        return jsonify(views.by_repo(froot()))

    @app.get("/api/features/<slug>/graph.svg")
    def feature_graph(slug):
        return Response(views.graph_svg(slug, froot()), mimetype="image/svg+xml")

    @app.post("/api/features/<slug>/sync")
    def feature_sync(slug):
        """Read the filed items' task states from the project's queue folders and tick the merged ones. Called when a feature is opened or refreshed."""
        return jsonify(status.sync(slug, froot()))

    @app.post("/api/sync-all")
    def sync_all():
        """Tick merged items for every feature on the board. Called on board/library load and once at server start; this endpoint exists so the UI can force a refresh."""
        return jsonify(status.sync_all(froot()))

    @app.post("/api/features/<slug>/checklist/<item_id>/file")
    def checklist_file(slug, item_id):
        accept = (request.get_json(silent=True) or {}).get("acceptLint")
        if accept is not None and not isinstance(accept, bool):
            return jsonify({"error": "acceptLint must be true or false"}), 400
        piece = (request.get_json(silent=True) or {}).get("piece")
        if piece is not None and not isinstance(piece, str):
            return jsonify({"error": "piece must be a piece label such as 4c"}), 400
        return jsonify(filing.file_item(slug, item_id, bool(accept), froot(), piece))

    @app.post("/api/features/<slug>/checklist/<item_id>/flag")
    def checklist_flag(slug, item_id):
        body = request.get_json(silent=True) or {}
        if not isinstance(body.get("value"), bool):
            return jsonify({"error": "value must be true or false"}), 400
        return jsonify(filing.set_flag(slug, item_id, str(body.get("flag")), body["value"], froot()))

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

    @app.post("/api/features/<slug>/checklist/number")
    def checklist_number(slug):
        return jsonify(checklist.number_checklist(slug, froot()))

    @app.post("/api/features/<slug>/checklist/items")
    def checklist_add_item(slug):
        body = request.get_json(silent=True) or {}
        title = body.get("title")
        if not isinstance(title, str) or not title.strip():
            return jsonify({"error": "title is required"}), 400
        item = checklist.add_item(slug, title.strip(), str(body.get("body", "")),
                                  list(body.get("deps", [])), bool(body.get("premium", False)), froot())
        return jsonify({"id": item["id"], "item": item}), 201

    @app.post("/api/grill/<slug>/<sid>/proposal")
    def grill_proposal(slug, sid):
        proposal = grill.proposal_from_session(slug, sid, froot())
        return jsonify({"proposal": proposal, "preview": checklist.preview(slug, proposal, froot())})

    @app.get("/api/repos")
    def repos():
        registered = repo_create._registered_names()
        return jsonify([{**r, "registered": r.get("name") in registered} for r in grill.repo_index()])

    @app.get("/api/repos/unregistered")
    def repos_unregistered():
        return jsonify(repo_create.unregistered_repos(grill.repos_root()))

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
        meta = grill.load_meta(slug, sid, froot())
        # Check if the session is failed
        if meta.get("failed"):
            return jsonify({"error": "The interviewer was stopped (killed by the system, usually memory pressure). Nothing was lost. Please use the Retry button or start a new session."}), 409
        return _sse(grill.stream_turn(slug, sid, text, froot()))

    @app.post("/api/grill/<slug>/<sid>/save")
    def grill_save(slug, sid):
        return jsonify(grill.save_to_interview(slug, sid, froot()))

    @app.post("/api/grill/<slug>/<sid>/end")
    def grill_end(slug, sid):
        return jsonify(grill.end(slug, sid, froot()))

    @app.post("/api/grill/sessions/<session_id>/retry")
    def grill_retry(session_id):
        """Retry a failed session. Returns 409 if the session is not failed or has no last round."""
        # Find the slug for this session_id
        for slug_data in store.list_features(froot()):
            slug = slug_data["slug"]
            try:
                meta = grill.load_meta(slug, session_id, froot())
                # Check if the session is failed
                if not meta.get("failed"):
                    return jsonify({"error": "Session is not in a failed state"}), 409
                last_round = meta["failed"].get("last_round")
                if not last_round:
                    return jsonify({"error": "Session has no last round to retry"}), 409
                # Clear the failed state
                result = grill.retry_session(slug, session_id, froot())
                return jsonify(result), 200
            except (grill.GrillError, store.StoreError):
                continue
        return jsonify({"error": "Session not found"}), 404


    @app.get("/api/proposals")
    def list_proposals():
        """Return all proposals across repos, ranked by value desc then name asc."""
        proposals_dir = os.path.expanduser("~/.local/state/pipeline-ops/reposcout/proposals")
        if not os.path.isdir(proposals_dir):
            return jsonify([]), 200

        # Load all scout files
        repos = []
        for fname in os.listdir(proposals_dir):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(proposals_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, IOError):
                continue
            repos.append(data)

        # Load dismissals
        dismissed_keys = proposals.load_dismissals(proposals_dir)

        # Mark dismissed proposals
        for repo_data in repos:
            repo_name = repo_data.get("repo", fname.replace(".json", ""))
            for prop in repo_data.get("proposals", []):
                key = proposals.dismissal_key(prop.get("title", ""), prop.get("why", ""))
                prop["dismissed"] = (repo_name, prop.get("id", ""), key) in dismissed_keys

        # Sort by value desc, then name asc
        repos.sort(key=lambda r: (-r.get("value", 0), r.get("repo", "")))

        return jsonify(repos), 200

    @app.post("/api/proposals/<repo>/<id>/dismiss")
    def dismiss_proposal(repo, id):
        """Dismiss a proposal: append a dismissal record and return the dismissal key."""
        body = request.get_json(silent=True) or {}
        why = str((body.get("why") or "")).strip()
        if not why:
            return jsonify({"error": "'why' is required"}), 400

        # Look up the proposal in the scout file
        proposals_dir = os.path.expanduser("~/.local/state/pipeline-ops/reposcout/proposals")
        scout_file = os.path.join(proposals_dir, f"{repo}.json")

        if not os.path.exists(scout_file):
            return jsonify({"error": "not found"}), 404

        try:
            with open(scout_file, "r", encoding="utf-8") as f:
                scout_data = json.load(f)
        except (json.JSONDecodeError, IOError):
            return jsonify({"error": "not found"}), 404

        # Find the proposal with matching id
        proposal = None
        for p in scout_data.get("proposals", []):
            if p.get("id") == id:
                proposal = p
                break

        if proposal is None:
            return jsonify({"error": "not found"}), 404

        title = proposal.get("title", "")
        if not title:
            return jsonify({"error": "proposal has no title"}), 400

        # Compute dismissal key and append
        now = datetime.utcnow()
        key = proposals.dismissal_key(title, why)
        proposals.append_dismissal(proposals_dir, repo, id, title, why, now)

        return jsonify({"key": key}), 200

    return app


app = create_app()


def _run_startup_sync():
    """Tick every feature's merged items once at server start so nothing stays stale."""
    try:
        status.sync_all(app.config.get("FEATURE_ROOT"))
    except Exception:
        # A broken feature must not crash the server; sync failures are logged, not fatal.
        import logging
        logging.getLogger("feature-forge").exception("sync_all on startup failed")


if __name__ == "__main__":
    # Guard against the Flask debug reloader: when werkzeug restarts the process it sets
    # WERKZEUG_RUN_MAIN so only the reloaded process runs the startup side-effect.
    if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        _run_startup_sync()
    app.run(host="127.0.0.1", port=int(os.environ.get("FEATUREFORGE_PORT", "7466")), threaded=True)
