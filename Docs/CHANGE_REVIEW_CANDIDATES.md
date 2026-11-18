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

### AC-2 · This diff makes an EXISTING test fail: test_a_piece_added_to_a_filed_item_can_be_filed (te (1ca101e test_filing.py)
Strength: Strong
Source: change_review of 1ca101e "Merge Potential edge case in `_negated` with multiple negation words"
Files: tests/test_filing.py

Snippet:
```
diff --git a/tests/test_filing.py b/tests/test_filing.py
index f01afa6..63047e2 100644
--- a/tests/test_filing.py
+++ b/tests/test_filing.py
@@ -95,24 +95,34 @@ class LintTests(unittest.TestCase):
     def test_negated_not_poll_is_not_flagged(self):
         self.assertEqual(filing.lint("do not poll the queue"), [])
 
     def test_negated_never_poll_is_not_flagged(self):
         self.assertEqual(filing.lint("never poll the queue"), [])
 
     def test_negated_without_polling_is_not_flagged(self):
         self.assertEqual(filing.lint("without polling, wake on the event"), [])
 
     def test_negated_does_not_poll_is_not_flagged(self):
         self.assertEqual(filing.lint("the worker does not poll the queue"), [])
 
+    def test_double_negation_not_never_poll(self):
+        # Double-negation edge case: "do not never poll the queue" contains two
+        # negation words ("not", "never") before "poll". The current implementation
+        # only checks for the FIRST negation word in the clause, so it treats the
+        # clause as negated and suppresses the warning -- even though a strict
+        # reading of double negation would imply the opposite. This test pins the
+        # current behavior so the edge case is explicit and ready for a decision
+        # on whether to handle it.
+        self.assertEqual(filing.lint("do not never poll the queue"), [])
+
     def test_negated_no_polling_is_not_flagged(self):
         self.assertEqual(filing.lint("no polling, the file
```

Problem: [severity: high; regression shipped in 1ca101e] This diff makes an EXISTING test fail: test_a_piece_added_to_a_filed_item_can_be_filed (tests.test_filing.PieceFilingTests.test_a_piece_added_to_a_filed_item_can_be_filed). Confirmed by actually running the test (tests/test_filing.py), not inferred.  Failure scenario: Running the scoped test suite for the files this commit touched fails with: ................................E....................... ====================================================================== ERROR: test_a_piece_added_to_a_filed_item_can_be_filed (tests.test_filing.PieceFilingTests.test_a_piece_added_to_a_filed_item_can_be_filed) ---------------------------------------------------------------------- Traceback (most recent call last): File "/media/model-cache/github/feature-forge/tests/test_filing.py", line 320, in test_a_piece_added_to_a_filed_item_can_be_filed checklist.apply(self.slug, {"ops": [{"op": "change", "id": "FF-2", "pieces": ["Late piece"
Solution: Restore the behaviour the failing test expects, or update the test if this diff intentionally changed the contract it checks (and explain why in the fix).
Benefits: Restores correct behaviour for the scenario above; undoes the regression shipped in 1ca101e.
