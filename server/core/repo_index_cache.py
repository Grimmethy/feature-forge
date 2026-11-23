"""TTL cache for the repo index scan (Python mirror of src/repo-index-cache.js).

Standard library only. Expiry is lazy: it is checked on each call, with no
background work of any kind. Concurrent callers share one
in-flight scan, and a generation guard keeps a scan that started before
``clear_repo_index_cache()`` from repopulating the cache.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable

_lock = threading.Lock()
_cache: tuple[Any, float] | None = None  # (value, stored-at ms)
_inflight: "_Flight | None" = None
_generation = 0


class _Flight:
    """One shared in-flight scan; joiners wait on ``done``."""

    def __init__(self) -> None:
        self.done = threading.Event()
        self.value: Any = None
        self.error: BaseException | None = None


def _monotonic_ms() -> float:
    return time.monotonic() * 1000.0


def get_repo_index(
    scan_fn: Callable[[], Any],
    ttl_ms: float = 30000,
    now: Callable[[], float] | None = None,
) -> Any:
    global _cache, _inflight
    clock = now or _monotonic_ms

    with _lock:
        cached = _cache
        if cached is not None and clock() - cached[1] < ttl_ms:
            return cached[0]
        flight = _inflight
        owner = flight is None
        if owner:
            flight = _Flight()
            _inflight = flight
        gen = _generation

    if not owner:
        flight.done.wait()
        if flight.error is not None:
            raise flight.error
        return flight.value

    try:
        value = scan_fn()
        with _lock:
            if gen == _generation:
                _cache = (value, clock())
        flight.value = value
        return value
    except BaseException as exc:
        flight.error = exc
        raise
    finally:
        with _lock:
            if gen == _generation and _inflight is flight:
                _inflight = None
        flight.done.set()


def clear_repo_index_cache() -> None:
    global _cache, _inflight, _generation
    with _lock:
        _cache = None
        _inflight = None
        _generation += 1
