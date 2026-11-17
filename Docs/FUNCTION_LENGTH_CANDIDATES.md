# Function Length Decomposition Candidates

### AC-1 · Extract route groups from create_app into blueprints or modular sub-functions
Strength: Strong
Files: server/app.py
Symbol: create_app
Snippet:
```


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
// ... [truncated for review: this function continues for 131 more line(s) not shown]
```

Problem:
The `create_app` function in `server/app.py` is a 331+ line monolith that mixes eight distinct concerns: app configuration, error handlers, static file serving, feature CRUD, repo operations, checklist management, grill proposals, and view rendering. These concerns have no logical ordering dependency and are independently understandable units. A developer searching for "how does checklist filing work?" must navigate through unrelated feature routes and error handlers to find it. The truncated tail (131 more lines of `/api/repos` routes) makes the function even longer than the snippet shows, worsening the problem.

Solution:
Decompose `create_app` by extracting six sub-functions: `register_error_handlers(app)`, `register_static_routes(app)`, `register_feature_routes(app, froot)`, `register_repo_routes(app)`, `register_checklist_routes(app, froot)`, and `register_grill_routes(app, froot)`. Each sub-function would be 15–120 lines, well under the 100-line threshold. Pass the `froot()` closure or shared state as parameters rather than capturing it in nested scopes. Alternatively, convert these into Flask blueprints for even cleaner separation.

Benefits:
Each route group becomes independently testable by mocking only its dependencies. Review-ability improves because a PR touching checklist logic no longer requires understanding feature routes or error handler status codes. The factory function itself becomes a clear wiring diagram rather than a tangled implementation, making onboarding and maintenance significantly easier.
