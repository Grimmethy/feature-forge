// Static layout check for the Feature Forge checklist item card (no browser).
// Viewport note: 1366x647 and 1100x647 with the Grill panel open were NOT measured
// in a browser; this test only checks the CSS rules in web/index.html.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');

function rule(selector) {
  const start = html.indexOf(selector + '{');
  assert.notStrictEqual(start, -1, 'missing rule for ' + selector);
  const end = html.indexOf('}', start);
  return html.slice(start + selector.length + 1, end);
}

test('checklist item card wraps instead of overflowing', () => {
  const row = rule('.row');
  assert.match(row, /flex-wrap:wrap/);
  assert.doesNotMatch(row, /white-space:nowrap/);
  assert.doesNotMatch(row, /overflow-x:scroll/);
  assert.doesNotMatch(row, /min-width:(1[1-9]\d\d|[2-9]\d\d\d)px/);
});

test('checklist button group wraps and has no fixed min width', () => {
  const acts = rule('.row .acts');
  assert.match(acts, /flex-wrap:wrap/);
  assert.doesNotMatch(acts, /white-space:nowrap/);
  assert.doesNotMatch(acts, /min-width:(1[1-9]\d\d|[2-9]\d\d\d)px/);
});

test('pane can shrink below its content width', () => {
  const view = rule('#view');
  assert.match(view, /min-width:0/);
  assert.doesNotMatch(view, /overflow-x:scroll/);
});
