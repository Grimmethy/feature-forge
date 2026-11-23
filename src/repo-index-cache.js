'use strict';

// TTL cache for the repo index scan. Expiry is lazy: checked on each call,
// no timers.

let cache = null; // { value, at }
let inflight = null;
let generation = 0;

function getRepoIndex(scanFn, { ttlMs = 30000, now = Date.now } = {}) {
  const t = now();
  if (cache && t - cache.at < ttlMs) {
    return Promise.resolve(cache.value);
  }
  if (inflight) return inflight;

  const gen = generation;
  const p = (async () => {
    try {
      const value = await scanFn();
      if (gen === generation) cache = { value, at: now() };
      return value;
    } finally {
      if (gen === generation) inflight = null;
    }
  })();
  inflight = p;
  return p;
}

function clearRepoIndexCache() {
  cache = null;
  inflight = null;
  generation++;
}

module.exports = { getRepoIndex, clearRepoIndexCache };
