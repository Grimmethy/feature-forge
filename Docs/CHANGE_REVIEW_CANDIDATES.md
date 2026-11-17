# Change Review Candidates

### AC-1 · Before this diff, there was no retry route. After this diff, the new `grill_retry` route f (dd5cf05 app.py)
Strength: Strong
Source: change_review of dd5cf05 "Merge HUB0018 · 4/4 · Write tests for the kill event, retry route, and failed-se"
Files: server/app.py

Snippet:
```
diff --git a/server/app.py b/server/app.py
index 8596f57..75f9862 100644
--- a/server/app.py
+++ b/server/app.py
@@ -289,35 +289,59 @@ def create_app(root: Path | None = None) -> Flask:
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
-        grill.load_meta(slug, sid, froot())
+        meta = grill.load_meta(slug, sid, froot())
+        # Check if the session is failed
+        if meta.get("failed"):
+            return jsonify({"error": "The interviewer was stopped (killed by the system, usually memory pressure). Nothing was lost. Please use the Retry button or start a new session."}), 409
         return _sse(grill.stream_turn(slug, sid, text, froot()))
 
     @app.post("/api/grill/<slug>/<sid>/save")
     def grill_save(slug, sid):
         return jsonify(grill.save_to_interview(slug, sid, froot()))
 
     @app.post("/api/grill/<slug>/<sid>/end")
     def grill_end(slug, sid):
         return jsonify(grill.end(slug, sid, froot()))
 
+    @app.post("/api/grill/sessions/<session_id>/retry")
+    def grill_retry(ses
```

Problem: [severity: high; regression shipped in dd5cf05] Before this diff, there was no retry route. After this diff, the new `grill_retry` route fails to find sessions across multiple features when a session doesn't exist in an intermediate feature, returning a 500 error instead of continuing to search or returning 404.  Failure scenario: Call `POST /api/grill/sessions/<session_id>/retry` where `<session_id>` exists in feature "beta" but not in feature "alpha" (which is listed first by `store.list_features`). The loop iterates to "alpha", calls `grill.load_meta("alpha", session_id, froot())`, which raises `store.StoreError` because the session doesn't exist in "alpha". The `except grill.GrillError` clause does not catch `StoreError`, so the exception propagates up, resulting in a 500 Internal Server Error instead of continuing to search "beta" or returning 404 "Session not found".
Solution: Catch `store.StoreError` in addition to `grill.GrillError` in the try/except block, or check session existence before calling `load_meta`. For example: `except (grill.GrillError, store.StoreError) as e:` and continue to the next slug if the session doesn't exist in the current feature.
Benefits: Restores correct behaviour for the scenario above; undoes the regression shipped in dd5cf05.
