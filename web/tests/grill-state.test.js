// Grill panel data-state and proposal data-count attribute tests.
// Verifies the HTML structure and JavaScript code contain the right
// data-state transitions and data-count updates without requiring a browser.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');

test('grill panel starts with data-state="idle"', () => {
  const grillMatch = html.match(/<div id="grill"[^>]*>/);
  assert.ok(grillMatch, 'grill div exists');
  const grillHtml = grillMatch[0];
  assert.match(grillHtml, /data-state="idle"/, 'grill has data-state="idle"');
});

test('proposal panel starts with data-count="0"', () => {
  const propMatch = html.match(/<div id="prop"[^>]*>/);
  assert.ok(propMatch, 'prop div exists');
  const propHtml = propMatch[0];
  assert.match(propHtml, /data-count="0"/, 'prop has data-count="0"');
});

test('Premium button has aria-pressed', () => {
  assert.match(html, /data-flag="premium"[^>]*aria-pressed/, 'premium button has aria-pressed');
});

test('Cloud button has aria-pressed', () => {
  assert.match(html, /data-flag="cloud"[^>]*aria-pressed/, 'cloud button has aria-pressed');
});

test('gReset sets data-state to idle', () => {
  assert.match(html, /function gReset\(\).*setAttribute\('data-state','idle'\)/s, 'gReset sets data-state to idle');
});

test('gReset sets data-count to 0', () => {
  assert.match(html, /function gReset\(\).*setAttribute\('data-count','0'\)/s, 'gReset sets data-count to 0');
});

test('openGrill sets data-state to starting', () => {
  assert.match(html, /function openGrill\(\).*setAttribute\('data-state','starting'\)/s, 'openGrill sets data-state to starting');
});

test('gstream sets data-state to busy at start', () => {
  assert.match(html, /async function gstream\([^)]*\).*setAttribute\('data-state','busy'\)/s, 'gstream sets data-state to busy');
});

test('gstream sets data-state to ready on success', () => {
  assert.match(html, /setAttribute\('data-state','busy'\).*setAttribute\('data-state','ready'\)/s, 'gstream sets busy then ready');
});

test('gend sets data-state to ended', () => {
  assert.match(html, /\$\('gend'\).*setAttribute\('data-state','ended'\)/s, 'gend sets data-state to ended');
});

test('showProp sets data-count to PROP.proposal.ops.length', () => {
  assert.match(html, /function showProp\(\).*setAttribute\('data-count',\s*String\(PROP\.proposal\.ops\.length\)\)/s, 'showProp sets data-count');
});

test('showProp adds data-op-id to each pop element', () => {
  assert.match(html, /data-op-id=".*esc\(op\.op\).*"/, 'showProp adds data-op-id attribute');
});
