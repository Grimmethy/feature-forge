// Test for Grill panel Send button behavior during a round (no browser).
// Verifies:
// 1. The status element exists in the HTML
// 2. CSS rules hide it by default and show it when active
// 3. The JS logic queues messages when gRoundActive is true
// 4. The Ctrl+Enter handler mirrors the click handler
// 5. The gstream function sends pending messages at round end
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

test('grill send status element exists in HTML', () => {
  assert.ok(html.includes('id="gsend-status"'), 'status element missing');
  assert.ok(html.includes('class="grill-send-status"'), 'status class missing');
});

test('grill send status CSS hides by default and shows when active', () => {
  const defaultStyle = rule('#gin .grill-send-status');
  assert.match(defaultStyle, /display:none/);
  
  const activeStyle = rule('#gin .grill-send-status.active');
  assert.match(activeStyle, /display:block/);
});

test('JS queues message when gRoundActive is true', () => {
  // Check that gsend onclick handler checks gRoundActive
  assert.ok(html.includes('if(gRoundActive)'), 'gsend onclick missing gRoundActive check');
  assert.ok(html.includes('gPendingMsg=t'), 'gsend onclick missing queue logic');
  assert.ok(html.includes('gsend-status') && html.includes('textContent'), 'gsend onclick missing status update');
});

test('Ctrl+Enter handler mirrors click handler', () => {
  // Check that keydown handler for Ctrl+Enter has same logic
  assert.ok(html.includes("e.ctrlKey&&e.key==='Enter'"), 'Ctrl+Enter handler missing');
  assert.ok(html.includes('if(gRoundActive)'), 'Ctrl+Enter missing gRoundActive check');
  assert.ok(html.includes('gPendingMsg=t'), 'Ctrl+Enter missing queue logic');
});

test('gstream sends pending message at round end', () => {
  // Check that gstream function checks gPendingMsg after round completes
  assert.ok(html.includes('gRoundActive=false'), 'gstream missing round-end marker');
  assert.ok(html.includes('if(gPendingMsg)'), 'gstream missing pending msg check');
  assert.ok(html.includes('gstream('), 'gstream missing recursive call for pending msg');
});
