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

### AC-2 · Decompose _file_pieces into six focused functions
Strength: Strong
Files: server/core/filing.py
Symbol: _file_pieces
Snippet:
```


def _file_pieces(slug, entries, it, item_id, piece_id, accept_lint, root, project, dep_tasks) -> dict:
    ps = checklist.pieces(it)
    todo = [p for p in ps if not p["ticked"] and not p["meta"].get("task")]
    if piece_id is not None:
        target = next((p for p in ps if p["id"] == piece_id), None)
        if target is None:
            raise FilingError(f"no such piece {piece_id} in {item_id}")
        if target not in todo:
            raise FilingError(f"{piece_id} is already {'done' if target['ticked'] else 'filed as ' + target['meta']['task']}")
        earlier = [p for p in todo if ps.index(p) < ps.index(target)]
        if earlier:
            raise FilingError(f"file {earlier[0]['id']} first: {piece_id} comes after it")
        todo = [target]
    if not todo:
        raise FilingError(f"{item_id} has no unfiled pieces")
    # Lint every piece before any write. A piece that fails is marked blocked and skipped;
    # pieces that pass continue unchanged.
    blocked: set[str] = set()
    warnings: list[str] = []
    for p in todo:
        piece_warnings = lint(p["title"] + "\n" + p["body"])
        if piece_warnings and not accept_lint:
            blocked.add(p["id"])
            warnings.extend(f"{p['id']}: {w}" for w in piece_warnings)
    repo_line_warnings = lint_piece_repo_mismatch(
        [p for p in todo if p["id"] not in blocked],
        project.get("label") or Path(project["repoRoot"]).name,
        lambda piece, feature_repo: feature_repo,
    )
    if repo_line_warnings:
        warnings.extend(repo_line_warnings)
    if blocked and not accept_lint:
        raise FilingError(
            "polling language in piece(s) " + ", ".join(sorted(blocked)) + ": "
            + " or ".join(w for w in warnings if any(w.startswith(b + ": " for b in blocked)))
            + "; reword to use a trigger, or accept the warning"
        )
    todo = [p for p in todo if p["id"] not in blocked]
    # Route each piece to its target repo. Pieces with no override inherit
    # the feature repo; pieces whose target differs from the feature repo get
    # that repo's header line prepended into the queued text.
    feature_repo = grill.target_repo(slug, root)["name"]

    def _repo_known(name: str) -> bool:
        try:
            project_for(name)
            return True
        except NotRegisteredError:
            return False

    routed = route_pieces(todo, feature_repo, _repo_known)
    for r in routed:
        if r["status"] == "blocked":
            raise FilingError(r["message"])
    premium = it["meta"].get("premium") == "true"
    out = {"id": item_id, "pieces": [], "premium": premium, "warnings": warnings}
    _deps_map: dict[str, set[str]] = {}
    for _q in checklist.pieces(it):
        _after = _q["meta"].get("after", "").strip()
        if _after and _after != "none":
            _deps_map[_q["id"]] = {a for a in _after.split() if a}
    for p in todo:
        after_meta = p["meta"].get("after", "").strip()
        if after_meta:
            after_labels = [a for a in after_meta.split() if a]
            if after_labels == ["none"]:
                deps = list(dep_tasks)
            else:
                deps = []
                now = checklist.pieces(it)                              # re-read: pieces filed a moment ago carry their task ids now
                for label in after_labels:
                    peer = next((q for q in now if q["id"] == label), None)
                    if peer is None:
                        raise FilingError(f"piece {label} in {item_id}/{p['id']} refers to an unknown piece")
                    if not peer["meta"].get("task"):
                        raise FilingError(f"piece {label} in {item_id}/{p['id']} has no task yet: file it first")
                    deps.append(peer["meta"]["task"])
        else:
            now = checklist.pieces(it)                              # re-read: the pieces filed a moment ago carry their task ids now
            before = now[:[q["id"] for q in now].index(p["id"])]
            prev = next((q["meta"]["task"] for q in reversed(before) if q["meta"].get("task")), None)
            if prev:
                deps = [prev]                                       # pieces chain: each waits for the one before it
            elif before:
                deps = []                                           # earlier pieces were done by hand: nothing to wait for
            else:
                deps = list(dep_tasks)                              # the first piece waits for what the step waits for
        p_files = parallel_files.files_of("\n".join(p["body"]) if isinstance(p.get("body"), list) else (p["body"] or ""))
        for prev in todo[:todo.index(p)]:
            prev_files = parallel_files.files_of("\n".join(prev["body"]) if isinstance(prev.get("body"), list) else (prev["body"] or ""))
            if not p_files or not prev_files:
                continue
            if parallel_files.depends_transitively(p["id"], prev["id"], _deps_map):
                continue
            for shared in sorted(p_files & prev_files):
                warnings.append(f"{p['id']} and {prev['id']} both name {shared}; they can run in parallel and may conflict")
        _target = next(r for r in routed if r["piece"]["id"] == p["id"])
        text = record_text(slug, item_id, root, p["id"])
        if _target["targetRepo"] != feature_repo:
            text = re.sub(
                r"^Repo: " + re.escape(feature_repo) + r"\.$",
                f"Repo: {_target['targetRepo']}.",
                text,
                count=1,
                flags=re.MULTILINE,
            )
        try:
            task = _queue_task(project, f"{item_id}/{p['id']} {p['title']}", text, f"feature-forge:{slug}/{item_id}/{p['id']}", deps)
        except FilingError as e:
            raise FilingError(f"{e} (filed so far: {', '.join(x['task'] for x in out['pieces']) or 'nothing'})")
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        checklist.update_piece(it, p["id"], {"task": task, "filed": stamp})
        it["meta"].setdefault("filed", stamp)                   # the first piece filed locks the item
        it["dirty"] = True
        _write_entries(slug, entries, root)                     # each task exists now: record it before anything else can fail
        entry = {"piece": p["id"], "status": "filed", "repo": _target["targetRepo"], "task": task}
        if premium:
            try:
                _post(f"/api/task-anywhere/{task}/premium-priority?project={project['repoRoot']}", {"enabled": True, "by": "operator-ui"})
            except FilingError as e:
                entry["premiumError"] = str(e)
        out["pieces"].append(entry)
    out["task"] = out["pieces"][-1]["task"]
    return out
```

Problem:
The `_file_pieces` function is 124 lines long and performs six unrelated responsibilities: piece selection, linting, routing, dependency resolution, conflict detection, and the filing loop. Each phase has its own invariants, error modes, and test cases, but they currently share one function's scope and one set of local variables (`todo`, `warnings`, `blocked`, `routed`, `_deps_map`, `out`). This forces readers to hold six different mental models simultaneously and makes it difficult to reason about, test, or modify any single phase in isolation.

Solution:
Extract each phase into its own clearly-named function: `_select_pieces` (filter checklist, optional narrowing, ordering), `_lint_pieces` (lint text, check repo/line mismatch, decide what's blocked), `_route_pieces` (determine target repo per piece), `_resolve_deps` (build `_deps_map` from `after:` metadata), `_detect_conflicts` (compute shared files between parallel pieces), and `_file_one_piece` (inner loop body for formatting, rewriting, queuing, and writing). Then `_file_pieces` becomes a thin orchestrator that calls these functions in sequence and assembles the final output.

Benefits:
Each phase becomes independently testable with focused unit tests, review-able in isolation, and modifiable without risk of unintended side effects on other phases. The orchestrator function becomes a clear high-level description of the workflow, and the shared local variables are replaced by explicit function parameters and return values, making data flow transparent.

VERDICT: GENUINE
