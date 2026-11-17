"""Tests for the grill stream events (server/core/grill.py: stream_turn).

The model call (grill._call) is stubbed; no real model is reached.
"""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from server.core import grill, store


def _events(frames):
    """Parse SSE frames produced by stream_turn into a list of dicts."""
    out = []
    for f in frames:
        text = f if isinstance(f, str) else f.decode("utf-8")
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            out.append(json.loads(text[start:end + 1]))
    return out


class _StubStream:
    """Stands in for the streaming response object returned by grill._call."""

    def __init__(self, lines):
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(self._lines)


class GrillEventsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.slug = store.create_feature("Stream test", "a request", self.root)
        self.sid = "s1"
        self.meta = {"id": self.sid, "feature": self.slug, "node": "feature", "provider": "claude",
                     "account": "test", "started": "2026-01-01T00:00:00", "saved": False, "seeded": False}
        grill.save_meta(self.slug, self.meta, self.root)
        # Avoid reading the feature's files when building the seed.
        p = mock.patch.object(grill, "build_seed", return_value="seed")
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, message, call_stub):
        with mock.patch.object(grill, "_call", side_effect=call_stub):
            return list(grill.stream_turn(self.slug, self.sid, message, self.root))

    def test_first_event_is_turn_start(self):
        def ok(method, path, body=None, timeout=None, stream=False):
            return _StubStream(["data: {\"type\": \"text\", \"text\": \"hi\"}"])

        events = _events(self._run("hello", ok))
        self.assertTrue(events, "stream produced no events")
        self.assertEqual(events[0]["type"], "turn-start")

    def test_raised_exception_yields_exactly_one_error_then_closes(self):
        def boom(method, path, body=None, timeout=None, stream=False):
            raise RuntimeError("boom")

        events = _events(self._run("hello", boom))
        errors = [e for e in events if e.get("type") == "error"]
        self.assertEqual(len(errors), 1)
        self.assertEqual(events[-1]["type"], "error")
        self.assertIn("boom", errors[0]["message"])

    def test_slow_stub_yields_timeout_error(self):
        # TURN_TIME_LIMIT_S is read at call time inside stream_turn, so patching the module attribute works.
        limit = 0.05

        def slow(method, path, body=None, timeout=None, stream=False):
            # The stub stands in for the HTTP client: it runs longer than the limit, then the client times out.
            time.sleep(limit * 4)
            raise TimeoutError("timed out")

        with mock.patch.object(grill, "TURN_TIME_LIMIT_S", limit):
            events = _events(self._run("hello", slow))
        errors = [e for e in events if e.get("type") == "error"]
        self.assertEqual(len(errors), 1)
        self.assertIn("timed out", errors[0]["message"])

    def test_retry_does_not_duplicate_history(self):
        def boom(method, path, body=None, timeout=None, stream=False):
            raise RuntimeError("transient")

        def ok(method, path, body=None, timeout=None, stream=False):
            return _StubStream(["data: {\"type\": \"text\", \"text\": \"ok\"}"])

        self._run("same message", boom)
        self.assertEqual(grill.load_meta(self.slug, self.sid, self.root).get("turns") or 0, 0)

        self._run("same message", ok)
        after_first_success = grill.load_meta(self.slug, self.sid, self.root)["turns"]
        self.assertEqual(after_first_success, 1)

        # A failed attempt at turn 2 must not advance the count, and a retry of that turn reuses its number.
        self._run("second message", boom)
        self.assertEqual(grill.load_meta(self.slug, self.sid, self.root)["turns"], 1)
        self._run("second message", ok)
        self.assertEqual(grill.load_meta(self.slug, self.sid, self.root)["turns"], 2)


    def _relay(self, lines):
        import io
        err = io.StringIO()

        def stub(method, path, body=None, timeout=None, stream=False):
            return _StubStream(lines)

        with mock.patch("sys.stderr", err):
            events = _events(self._run("hello", stub))
        return events, err.getvalue()

    def test_relayed_sigkill_error_marks_failed_and_is_retryable(self):
        frame = {"type": "error", "error": "claude -p failed: exit=null signal=SIGKILL (no stderr, no stdout)"}
        events, err = self._relay(["data: " + json.dumps(frame)])
        errors = [e for e in events if e.get("type") == "error"]
        self.assertEqual(len(errors), 1)
        self.assertTrue(errors[0]["retryable"])
        self.assertTrue(errors[0]["killed"])
        failed = grill.load_meta(self.slug, self.sid, self.root)["failed"]
        self.assertEqual(failed["signal"], "SIGKILL")
        self.assertEqual(failed["exit"], "null")
        self.assertIn("at", failed)
        self.assertIn("SIGKILL", failed["message"])
        self.assertEqual(err.count("[grill] turn failed"), 1)
        self.assertIn("exit=null signal=SIGKILL", err)

    def test_normal_stream_sets_no_failure(self):
        events, err = self._relay(["data: {\"type\": \"text\", \"text\": \"hi\"}", "data: not json"])
        self.assertNotIn("failed", grill.load_meta(self.slug, self.sid, self.root))
        self.assertEqual(err, "")
        self.assertFalse([e for e in events if e.get("type") == "error"])

    def test_error_without_exit_text_is_unknown_but_failed(self):
        events, err = self._relay(["data: {\"type\": \"error\", \"error\": \"something odd\"}"])
        failed = grill.load_meta(self.slug, self.sid, self.root)["failed"]
        self.assertEqual((failed["exit"], failed["signal"]), ("unknown", "unknown"))
        self.assertNotIn("killed", [e for e in events if e.get("type") == "error"][0])
        self.assertIn("exit=unknown signal=unknown", err)


if __name__ == "__main__":
    unittest.main()
