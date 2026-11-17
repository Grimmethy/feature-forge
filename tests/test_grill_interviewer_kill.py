"""Tests for the interviewer kill event, retry route, and failed-session send.

This test file verifies the shared contract for handling a killed interviewer:
1. When the interviewer exits with SIGKILL, the error event carries code "interviewer_killed",
   session_id, exact message, and last_round fields.
2. The retry route re-runs the last round under the same session id and clears the failed state.
3. Sending a message to a failed session returns 409 with an error message naming the cause.
"""
import json
import sys
import unittest
from unittest.mock import patch, MagicMock
from io import StringIO
from pathlib import Path
import tempfile

# Add server to path
sys.path.insert(0, "server")

from core import grill, store
from app import create_app


class TestInterviewerKillEvent(unittest.TestCase):
    """Test that a SIGKILL exit yields the correct error event and marks session failed."""

    def test_sigkill_yields_error_event_with_exact_fields(self):
        """When the interviewer exits with SIGKILL, stream_turn yields an error frame
        with code='interviewer_killed', session_id, exact message, and last_round,
        and marks the session as failed."""
        # Setup: create a temporary feature directory
        with tempfile.TemporaryDirectory() as tmpdir:
            slug = "test-slug"
            sid = "test-sid"
            
            # Create the feature directory structure
            feature_dir = Path(tmpdir) / slug
            grill_dir = feature_dir / ".grill"
            grill_dir.mkdir(parents=True)
            
            # Create request.md (required by build_seed)
            (feature_dir / "request.md").write_text("Test feature\n")
            
            # Create initial meta (not failed yet)
            meta = {
                "id": sid,
                "feature": slug,
                "node": "feature",
                "provider": "claude",
                "account": "test-account",
                "started": "2026-01-01T00:00:00",
                "saved": False,
                "seeded": True,
                "turns": 1
            }
            (grill_dir / f"{sid}.json").write_text(json.dumps(meta))
            
            # Capture stderr
            stderr_capture = StringIO()
            
            with patch("core.grill._call") as mock_call, \
                 patch("sys.stderr", stderr_capture), \
                 patch("core.grill.repos_root", return_value=Path(tmpdir)), \
                 patch("core.grill.store") as mock_store:
                
                # Mock store.feature_dir to return our temp directory
                def mock_feature_dir(slug_param, root=None):
                    return Path(tmpdir) / slug_param
                
                mock_store.feature_dir.side_effect = mock_feature_dir
                
                # Mock _call to return a response that contains a SIGKILL error event
                def mock_call_side_effect(method, path, body=None, timeout=30, stream=False):
                    if method == "POST" and "/message" in path and stream:
                        # Create a mock response that yields a SIGKILL error event
                        mock_resp = MagicMock()
                        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
                        mock_resp.__exit__ = MagicMock(return_value=False)
                        # Yield an error event with SIGKILL signal
                        error_event = 'data: {"type": "error", "error": "claude -p failed: exit=137 signal=SIGKILL"}\n\n'
                        mock_resp.__iter__ = MagicMock(return_value=iter([error_event.encode("utf-8")]))
                        return mock_resp
                    # For other calls, return a mock response
                    return MagicMock()
                
                mock_call.side_effect = mock_call_side_effect
                
                # Drive stream_turn
                frames = list(grill.stream_turn(slug, sid, "test message", root=Path(tmpdir)))
                
                # Find the error frame
                error_frame = None
                for frame in frames:
                    if isinstance(frame, str) and frame.startswith("data:"):
                        try:
                            parsed = json.loads(frame[5:])
                            if parsed.get("type") == "error":
                                error_frame = parsed
                                break
                        except json.JSONDecodeError:
                            pass
                
                self.assertIsNotNone(error_frame, "Expected an error frame")
                self.assertEqual(error_frame["type"], "error")
                self.assertEqual(error_frame["code"], "interviewer_killed")
                self.assertEqual(error_frame["session_id"], sid)
                self.assertEqual(
                    error_frame["message"],
                    "The interviewer was stopped (killed by the system, usually memory pressure). Nothing was lost."
                )
                self.assertEqual(error_frame["last_round"], 2)  # turn is incremented from initial turns=1
                self.assertTrue(error_frame.get("retryable"))
                self.assertTrue(error_frame.get("killed"))
                
                # Check stderr log line
                stderr_output = stderr_capture.getvalue()
                self.assertIn("interviewer_killed", stderr_output)
                self.assertIn("exit_code=137", stderr_output)
                self.assertIn("signal=SIGKILL", stderr_output)
                self.assertIn("MemAvailable=", stderr_output)
                self.assertIn("SwapTotal=", stderr_output)
                self.assertIn("SwapFree=", stderr_output)
                
                # Check that meta was saved with failed state
                saved_meta_path = grill_dir / f"{sid}.json"
                self.assertTrue(saved_meta_path.exists())
                saved_meta = json.loads(saved_meta_path.read_text())
                self.assertIn("failed", saved_meta)
                self.assertEqual(saved_meta["failed"]["signal"], "SIGKILL")
                self.assertEqual(saved_meta["failed"]["last_round"], 2)


class TestRetryRoute(unittest.TestCase):
    """Test that the retry route re-runs the last round and clears the failed state."""

    def test_retry_route_clears_failed_state_and_returns_round(self):
        """POST /api/grill/sessions/<sid>/retry returns 200 with session_id and round,
        and clears the failed state."""
        with tempfile.TemporaryDirectory() as tmpdir:
            slug = "test-slug"
            sid = "test-sid"
            
            # Create the feature directory structure
            feature_dir = Path(tmpdir) / slug
            grill_dir = feature_dir / ".grill"
            grill_dir.mkdir(parents=True)
            
            # Create request.md (required by list_features)
            (feature_dir / "request.md").write_text("Test feature\n")
            
            # Create a failed session meta
            meta = {
                "id": sid,
                "feature": slug,
                "node": "feature",
                "provider": "claude",
                "account": "test-account",
                "started": "2026-01-01T00:00:00",
                "saved": False,
                "seeded": True,
                "turns": 1,
                "failed": {
                    "at": "2026-01-01T00:00:00",
                    "exit": "137",
                    "signal": "SIGKILL",
                    "message": "test message",
                    "last_round": 5
                }
            }
            (grill_dir / f"{sid}.json").write_text(json.dumps(meta))
            
            app = create_app(root=Path(tmpdir))
            client = app.test_client()
            
            # Call retry route
            response = client.post(f"/api/grill/sessions/{sid}/retry")
            
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.data)
            self.assertEqual(data["session_id"], sid)
            self.assertEqual(data["round"], 5)
            
            # Verify failed state was cleared
            saved_meta_path = grill_dir / f"{sid}.json"
            self.assertTrue(saved_meta_path.exists())
            saved_meta = json.loads(saved_meta_path.read_text())
            self.assertNotIn("failed", saved_meta)


class TestFailedSessionSend(unittest.TestCase):
    """Test that sending a message to a failed session returns 409."""

    def test_send_to_failed_session_returns_409(self):
        """POST /api/grill/<slug>/<sid>/message returns 409 with error message
        naming the cause when session is failed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            slug = "test-slug"
            sid = "test-sid"
            
            # Create the feature directory structure
            feature_dir = Path(tmpdir) / slug
            grill_dir = feature_dir / ".grill"
            grill_dir.mkdir(parents=True)
            
            # Create request.md (required by list_features)
            (feature_dir / "request.md").write_text("Test feature\n")
            
            # Create a failed session meta
            meta = {
                "id": sid,
                "feature": slug,
                "node": "feature",
                "provider": "claude",
                "account": "test-account",
                "started": "2026-01-01T00:00:00",
                "saved": False,
                "seeded": True,
                "turns": 1,
                "failed": {
                    "at": "2026-01-01T00:00:00",
                    "exit": "137",
                    "signal": "SIGKILL",
                    "message": "test message",
                    "last_round": 5
                }
            }
            (grill_dir / f"{sid}.json").write_text(json.dumps(meta))
            
            app = create_app(root=Path(tmpdir))
            client = app.test_client()
            
            # Call message route
            response = client.post(
                f"/api/grill/{slug}/{sid}/message",
                json={"message": "test message"}
            )
            
            self.assertEqual(response.status_code, 409)
            data = json.loads(response.data)
            self.assertIn("error", data)
            error_msg = data["error"]
            # Error message should name the interviewer and mention retry or new start
            self.assertTrue(
                "interviewer" in error_msg.lower() or "killed" in error_msg.lower(),
                f"Error message should mention interviewer or killed: {error_msg}"
            )
            self.assertTrue(
                "retry" in error_msg.lower() or "new start" in error_msg.lower(),
                f"Error message should mention retry or new start: {error_msg}"
            )


if __name__ == "__main__":
    unittest.main()
