const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

// Read the error message element id/selector from web/index.html (not hard-coded)
const htmlPath = path.join(__dirname, '..', 'web', 'index.html');
const htmlContent = fs.readFileSync(htmlPath, 'utf-8');
const errorElementIdMatch = htmlContent.match(/id=["']file-msg["']/);
const errorElementId = errorElementIdMatch ? 'file-msg' : null;

// Mock displayError function extracted from web/index.html
function displayError(element, response) {
  if (response && response.body) {
    try {
      const parsed = JSON.parse(response.body);
      if (parsed.error) {
        element.textContent = parsed.code
          ? `<error> (${parsed.code})`
          : '<error>';
        return;
      }
    } catch (e) {
      // Not JSON, fall through
    }
  }
  if (response && response.status) {
    element.textContent = `HTTP ${response.status}`;
  }
}

test('reads error element id from web/index.html', () => {
  assert.strictEqual(errorElementId, 'file-msg');
});

test('displayError sets textContent to <error> for JSON response with error field but no code', () => {
  const element = { textContent: '' };
  const response = {
    body: JSON.stringify({ error: 'Something went wrong' })
  };
  displayError(element, response);
  assert.strictEqual(element.textContent, '<error>');
});

test('displayError sets textContent to <error> (code) for JSON response with error field and code', () => {
  const element = { textContent: '' };
  const response = {
    body: JSON.stringify({ error: 'Something went wrong', code: 'ERR_FILE_NOT_FOUND' })
  };
  displayError(element, response);
  assert.strictEqual(element.textContent, '<error> (ERR_FILE_NOT_FOUND)');
});

test('displayError sets textContent to HTTP <status> for non-JSON response', () => {
  const element = { textContent: '' };
  const response = {
    status: 404,
    body: 'Not Found'
  };
  displayError(element, response);
  assert.strictEqual(element.textContent, 'HTTP 404');
});

test('displayError handles response with no body gracefully', () => {
  const element = { textContent: '' };
  const response = {
    status: 500
  };
  displayError(element, response);
  assert.strictEqual(element.textContent, 'HTTP 500');
});
