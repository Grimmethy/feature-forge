// Grill working state: renders the element <div data-testid="grill-working">, shows the
// "Interviewer is working on turn N: <phase>" line, a CSS-only elapsed counter, and an error
// block with a Retry button. No polling: elapsed time comes only from the CSS animation and
// the server-side text. The single one-shot backstop timer is cleared on every terminal event.

// PLACEHOLDER value (3 minutes), pending human confirmation of the product choice.
export const CLIENT_TURN_LIMIT_MS = 180000;

const STYLE_ID = 'grill-working-style';
const limitSecs = Math.round(CLIENT_TURN_LIMIT_MS / 1000);
let backstopHandle = null;

// Injects the CSS once. The keyframes derive from CLIENT_TURN_LIMIT_MS, so there is one source of truth.
export function ensureStyles(doc) {
  const d = doc || (typeof document !== 'undefined' ? document : null);
  if (!d || d.getElementById(STYLE_ID)) return;
  const s = d.createElement('style');
  s.id = STYLE_ID;
  s.textContent = `@property --secs { syntax: "<integer>"; inherits: false; initial-value: 0; }
@keyframes grill-secs { from { --secs: 0; } to { --secs: ${limitSecs}; } }
.grill-working-elapsed { animation: grill-secs ${CLIENT_TURN_LIMIT_MS}ms steps(${limitSecs}, end) forwards; counter-reset: grill-secs var(--secs); }
.grill-working-elapsed::after { content: counter(grill-secs) "s"; }`;
  d.head.appendChild(s);
}

if (typeof document !== 'undefined') ensureStyles(document);

export function renderWorking(root, turn, phase, serverElapsedText) {
  if (!root) return null;
  const doc = root.ownerDocument;
  let el = root.querySelector('[data-testid="grill-working"]');
  if (!el) {
    el = doc.createElement('div');
    el.setAttribute('data-testid', 'grill-working');
    root.appendChild(el);
  }
  el.textContent = '';
  const label = doc.createElement('div');
  label.textContent = `Interviewer is working on turn ${turn}: ${phase}`;
  const elapsed = doc.createElement('span');
  elapsed.className = 'grill-working-elapsed';
  const server = doc.createElement('span');
  server.className = 'grill-working-server';
  server.textContent = serverElapsedText || '';
  el.append(label, elapsed, server);
  return el;
}

// Handler for the turn-start stream event. Expects payload fields: turn, phase, elapsedText.
export function onTurnStart(root, payload) {
  const p = payload || {};
  return renderWorking(root, p.turn, p.phase, p.elapsedText);
}

export function clearBackstop() {
  if (backstopHandle !== null) clearTimeout(backstopHandle);
  backstopHandle = null;
}

// Arms the one-shot backstop once per send. Expiry shows the error block; it never re-arms.
export function armBackstop(root, onRetry) {
  clearBackstop();
  backstopHandle = setTimeout(() => {
    backstopHandle = null;
    renderError(root, 'The interviewer did not answer in time.', onRetry);
  }, CLIENT_TURN_LIMIT_MS);
  return backstopHandle;
}

// Terminal-event handler: removes the working element and disarms the backstop.
export function clearWorking(root) {
  clearBackstop();
  if (!root) return;
  const el = root.querySelector('[data-testid="grill-working"]');
  if (el) el.remove();
}

// Clears the working state, then renders an error block with a Retry button.
// The module does not resend; the caller decides what onRetry does.
export function renderError(root, message, onRetry) {
  if (!root) return null;
  clearWorking(root);
  const doc = root.ownerDocument;
  const box = doc.createElement('div');
  box.className = 'grill-error';
  box.setAttribute('data-testid', 'grill-error');
  const msg = doc.createElement('span');
  msg.textContent = message;
  const btn = doc.createElement('button');
  btn.type = 'button';
  btn.textContent = 'Retry';
  btn.addEventListener('click', () => {
    box.remove();
    if (typeof onRetry === 'function') onRetry();
  });
  box.append(msg, btn);
  root.appendChild(box);
  return box;
}
