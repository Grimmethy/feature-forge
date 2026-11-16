const test = require('node:test');
const assert = require('node:assert');
const { featureCounts } = require('../web/feature-counts.js');

const STATUSES = ['Grilling', 'Planned', 'Filed', 'Building', 'Done'];

test('unknown and missing statuses land in Other and All equals the sum', () => {
  const features = [
    { title: 'a', status: 'Grilling' },
    { title: 'b', status: 'Done' },
    { title: 'c', status: 'Archived' },
    { title: 'd' },
  ];
  const c = featureCounts(features, STATUSES);
  assert.strictEqual(c.Other, 2);
  assert.strictEqual(c.Grilling, 1);
  assert.strictEqual(c.Done, 1);
  const sum = STATUSES.reduce((n, s) => n + c[s], 0) + c.Other;
  assert.strictEqual(c.All, sum);
  assert.strictEqual(c.All, features.length);
});

test('counts do not depend on an active search query', () => {
  const features = [
    { title: 'alpha', status: 'Planned' },
    { title: 'beta', status: 'Archived' },
    { title: 'gamma' },
  ];
  const before = featureCounts(features, STATUSES);
  // Search narrows only the cards shown; counts are computed from the full list.
  const query = 'alp';
  const shown = features.filter(f => (f.title || '').includes(query));
  assert.strictEqual(shown.length, 1);
  const after = featureCounts(features, STATUSES);
  assert.deepStrictEqual(after, before);
  assert.strictEqual(after.All, 3);
});
