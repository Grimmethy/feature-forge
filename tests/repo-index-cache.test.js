const test = require('node:test');
const assert = require('node:assert');
const { getRepoIndex, clearRepoIndexCache } = require('../src/repo-index-cache.js');

test('sequential calls reuse the cached value', async () => {
  clearRepoIndexCache();
  let count = 0;
  const scan = async () => { count++; return [{ name: 'a' }]; };
  const now = () => 1000;
  const a = await getRepoIndex(scan, { now });
  const b = await getRepoIndex(scan, { now });
  assert.strictEqual(count, 1);
  assert.deepStrictEqual(a, b);
});

test('concurrent calls share one scan', async () => {
  clearRepoIndexCache();
  let count = 0;
  let release;
  const gate = new Promise((r) => { release = r; });
  const scan = async () => { count++; await gate; return ['x']; };
  const now = () => 1000;
  const ps = [1, 2, 3].map(() => getRepoIndex(scan, { now }));
  release();
  const res = await Promise.all(ps);
  assert.strictEqual(count, 1);
  assert.strictEqual(res[0], res[1]);
  assert.strictEqual(res[1], res[2]);
});

test('rescans after TTL using injected now', async () => {
  clearRepoIndexCache();
  let count = 0;
  let t = 1000;
  const now = () => t;
  const scan = async () => ++count;
  assert.strictEqual(await getRepoIndex(scan, { ttlMs: 100, now }), 1);
  t = 1099;
  assert.strictEqual(await getRepoIndex(scan, { ttlMs: 100, now }), 1);
  t = 1100;
  assert.strictEqual(await getRepoIndex(scan, { ttlMs: 100, now }), 2);
  assert.strictEqual(count, 2);
});

test('rejected scans are not cached', async () => {
  clearRepoIndexCache();
  let count = 0;
  const now = () => 1000;
  const scan = async () => {
    count++;
    if (count === 1) throw new Error('boom');
    return 'ok';
  };
  await assert.rejects(getRepoIndex(scan, { now }), /boom/);
  assert.strictEqual(await getRepoIndex(scan, { now }), 'ok');
  assert.strictEqual(count, 2);
});
