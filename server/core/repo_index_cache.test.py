"""Tests for server/core/repo_index_cache.py.

Run with: python3 -I server/core/repo_index_cache.test.py -v
"""
import os
import sys
import threading
import unittest

# Isolated mode (-I) drops the script directory from sys.path, so add it
# explicitly so that `repo_index_cache` resolves to the sibling module.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from repo_index_cache import get_repo_index, clear_repo_index_cache  # noqa: E402

TTL = 30000


class FakeClock:
    def __init__(self, t=0):
        self.t = t

    def __call__(self):
        return self.t


class CountingScan:
    def __init__(self):
        self.count = 0
        self._lock = threading.Lock()

    def __call__(self):
        with self._lock:
            self.count += 1
        return [{"name": "a", "registered": False}]


class RepoIndexCacheTests(unittest.TestCase):
    def setUp(self):
        clear_repo_index_cache()

    def tearDown(self):
        clear_repo_index_cache()

    def test_repeat_call_within_ttl_does_not_rescan(self):
        clock = FakeClock(1000)
        scan = CountingScan()
        first = get_repo_index(scan, ttl_ms=TTL, now=clock)
        clock.t += TTL - 1
        second = get_repo_index(scan, ttl_ms=TTL, now=clock)
        self.assertEqual(scan.count, 1)
        self.assertEqual(first, second)

    def test_call_after_ttl_rescans(self):
        clock = FakeClock(1000)
        scan = CountingScan()
        get_repo_index(scan, ttl_ms=TTL, now=clock)
        clock.t += TTL + 1
        get_repo_index(scan, ttl_ms=TTL, now=clock)
        self.assertEqual(scan.count, 2)

    def test_concurrent_calls_trigger_single_scan(self):
        clock = FakeClock(1000)
        count = [0]
        count_lock = threading.Lock()
        started = threading.Event()
        release = threading.Event()

        def scan():
            with count_lock:
                count[0] += 1
            started.set()
            release.wait(timeout=10)
            return [{"name": "a", "registered": True}]

        n = 8
        barrier = threading.Barrier(n)
        results = [None] * n

        def worker(i):
            barrier.wait(timeout=10)
            results[i] = get_repo_index(scan, ttl_ms=TTL, now=clock)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        self.assertTrue(started.wait(timeout=10))
        release.set()
        for t in threads:
            t.join(timeout=10)
            self.assertFalse(t.is_alive())
        self.assertEqual(count[0], 1)
        for r in results:
            self.assertEqual(r, [{"name": "a", "registered": True}])

    def test_clear_forces_rescan(self):
        clock = FakeClock(1000)
        scan = CountingScan()
        get_repo_index(scan, ttl_ms=TTL, now=clock)
        clear_repo_index_cache()
        get_repo_index(scan, ttl_ms=TTL, now=clock)
        self.assertEqual(scan.count, 2)

    def test_failed_scan_not_cached(self):
        clock = FakeClock(1000)
        attempts = [0]

        def failing():
            attempts[0] += 1
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            get_repo_index(failing, ttl_ms=TTL, now=clock)

        scan = CountingScan()
        result = get_repo_index(scan, ttl_ms=TTL, now=clock)
        self.assertEqual(scan.count, 1)
        self.assertEqual(result, [{"name": "a", "registered": False}])
        # Success is cached; the earlier failure was not.
        get_repo_index(scan, ttl_ms=TTL, now=clock)
        self.assertEqual(scan.count, 1)
        self.assertEqual(attempts[0], 1)


if __name__ == "__main__":
    unittest.main()
