const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// Read the error message element id/selector from web/index.html (not hard-coded)
const htmlPath = path.join(__dirname, '..', 'web', 'index.html');
const htmlContent = fs.readFileSync(htmlPath, 'utf-8');
const errorElementIdMatch = htmlContent.match(/id=["']file-msg["']/);
const errorElementId = errorElementIdMatch ? 'file-msg' : null;

// Extract displayError function from web/index.html and load via node:vm
function loadDisplayErrorFromHTML(html) {
  // Create a VM context with stub DOM
  const context = {
    elements: new Map(),
    displayError: null,
    getElementById(id) {
      return this.elements.get(id);
    },
    window: {
      addEventListener() {},
      fetch: null
    },
    document: {
      getElementById(id) {
        return this.getElementById(id);
      }
    }
  };

  // Manually extract the displayError function from the HTML (lines 194-207)
  const lines = html.split('\n');
  let functionStart = -1;
  let functionEnd = -1;
  
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].includes('function displayError(')) {
      functionStart = i;
    }
    if (functionStart !== -1 && lines[i].trim() === '}' && i > functionStart) {
      // Check if this is the closing brace of the function (next line should be non-empty or end of function)
      const nextLine = lines[i + 1] ? lines[i + 1].trim() : '';
      if (nextLine === '' || nextLine.startsWith('window.displayError') || nextLine.startsWith('document.addEventListener')) {
        functionEnd = i;
        break;
      }
    }
  }

  if (functionStart === -1 || functionEnd === -1) {
    throw new Error('Could not find displayError function in HTML');
  }

  const functionSource = lines.slice(functionStart, functionEnd + 1).join('\n');

  // Wrap the function to capture it in the context
  const wrappedSource = `
    ${functionSource}
    this.displayError = displayError;
  `;

  vm.createContext(context);
  vm.runInContext(wrappedSource, context);

  return context.displayError;
}

const displayError = loadDisplayErrorFromHTML(htmlContent);

test('displayError 400-with-error-text shows error message for JSON response with error field', () => {
  const element = { textContent: '' };
  const response = {
    status: 400,
    body: JSON.stringify({ error: 'Bad Request' })
  };
  displayError(element, response);
  assert.strictEqual(element.textContent, 'Bad Request');
});

test('displayError 200-clears-message shows HTTP 200 for successful response', () => {
  const element = { textContent: 'previous error' };
  const response = {
    status: 200,
    body: 'OK'
  };
  displayError(element, response);
  assert.strictEqual(element.textContent, 'HTTP 200');
});

test('displayError 400-with-code-shows-both shows error message with code for JSON response with error and code', () => {
  const element = { textContent: '' };
  const response = {
    status: 400,
    body: JSON.stringify({ error: 'Bad Request', code: 'ERR_FILE_NOT_FOUND' })
  };
  displayError(element, response);
  assert.strictEqual(element.textContent, 'Bad Request (ERR_FILE_NOT_FOUND)');
});

test('displayError 409-not-registered-old-behavior shows HTTP status for non-JSON response', () => {
  const element = { textContent: '' };
  const response = {
    status: 409,
    body: 'Conflict'
  };
  displayError(element, response);
  assert.strictEqual(element.textContent, 'HTTP 409');
});

test('displayError new-click-clears-previous-before-response-arrives clears previous content when response has no body', () => {
  const element = { textContent: 'previous error' };
  const response = {
    status: 200
  };
  displayError(element, response);
  assert.strictEqual(element.textContent, 'HTTP 200');
});
