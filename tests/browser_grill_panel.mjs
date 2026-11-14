// Real-browser test of the repo chooser and the grill panel, against a FAKE chat plugin (no model, no tokens).
// Needs playwright-core (PLAYWRIGHT_DIR, a folder holding node_modules/playwright-core) and a Chromium (CHROMIUM, the executable).
// Start the server first, on port 7499 with a throwaway features folder and a throwaway repos folder holding two git repos
// named alpha and beta (each with a README.md whose first prose line is "Makes alphas." / "Builds betas."):
//   FEATUREFORGE_CHAT_URL=http://127.0.0.1:7498 FEATUREFORGE_REPOS_ROOT=<repos> python -c "from pathlib import Path; from server.app import create_app; create_app(Path('<features>')).run(host='127.0.0.1', port=7499)"
// then: PLAYWRIGHT_DIR=... CHROMIUM=... node tests/browser_grill_panel.mjs
import { createRequire } from 'module';
import http from 'http';
const require = createRequire((process.env.PLAYWRIGHT_DIR || '/media/model-cache/github/uxforge') + '/node_modules/');
const { chromium } = require('playwright-core');
const base = 'http://127.0.0.1:7499';
// ---- fake chat plugin on 7498 (same endpoints the real one has) ----
const log = { calls: [], transcript: [] };
const fake = http.createServer((req, res) => {
  let body = ''; req.on('data', c => body += c); req.on('end', () => {
    const b = body ? JSON.parse(body) : null; log.calls.push([req.method, req.url, b]);
    if (req.method === 'POST' && req.url === '/api/chat/new') { res.end(JSON.stringify({ id: 'chat-fake-1' })); return; }
    if (req.method === 'POST' && req.url.endsWith('/message')) {
      log.transcript.push({ role: 'user', text: b.message });
      const reply = log.transcript.length === 1 ? 'Q1 - which repo? -> alpha' : 'Q2 - tests? -> yes';
      log.transcript.push({ role: 'assistant', text: reply });
      res.writeHead(200, { 'Content-Type': 'text/event-stream' });
      const half = Math.floor(reply.length / 2);
      res.write('data: ' + JSON.stringify({ type: 'chunk', text: reply.slice(0, half) }) + '\n\n');
      res.write('data: ' + JSON.stringify({ type: 'chunk', text: reply.slice(half) }) + '\n\n');
      res.end('data: ' + JSON.stringify({ type: 'done' }) + '\n\n'); return;
    }
    if (req.method === 'GET' && req.url === '/api/chat/chat-fake-1') { res.end(JSON.stringify({ transcript: log.transcript })); return; }
    res.end('{}');
  });
});
await new Promise(r => fake.listen(7498, '127.0.0.1', r));
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM, args: ['--no-sandbox'] });
const page = await browser.newPage({ viewport: { width: 1400, height: 850 } });
const errs = []; page.on('pageerror', e => errs.push(String(e))); page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
let dialogs = 0; page.on('dialog', d => { dialogs++; d.dismiss(); });
const ok = (c, m) => { if (!c) { console.log('FAIL', m, errs); process.exitCode = 1; } else console.log('ok  ', m); };
try {
  await page.goto(base + '/', { waitUntil: 'load', timeout: 20000 });
  await page.click('#bNew'); await page.fill('#nt', 'Grill UI'); await page.fill('#nr', 'try the panel');
  await page.click('#nf button[type=submit]'); await page.waitForSelector('.card[data-s="grill-ui"]', { timeout: 10000 });
  await page.waitForSelector('#bRepo', { state: 'visible' });
  ok((await page.textContent('#bRepo')).trim() === 'Choose repo', 'a feature with no repo shows "Choose repo"');
  // ---- repo intake ----
  await page.click('#bRepo'); await page.waitForSelector('#rsel');
  const opts = await page.$$eval('#rsel option', os => os.map(o => o.textContent));
  ok(opts.some(o => o.startsWith('alpha - Makes alphas')) && opts.some(o => o.startsWith('beta')), 'the chooser lists the existing repos with their summaries');
  await page.selectOption('#rsel', 'alpha'); await page.click('#rf button[type=submit]');
  await page.waitForFunction(() => document.querySelector('#bRepo').textContent === 'Repo: alpha', null, { timeout: 10000 });
  ok(true, 'choosing an existing repo updates the button to "Repo: alpha"');
  await page.waitForSelector('#view'); await page.waitForFunction(() => document.querySelector('#view').innerText.includes('repo: alpha'));
  ok(true, 'request.md now holds the repo line');
  // ---- grill ----
  await page.click('#bGrill'); await page.waitForSelector('#grill', { state: 'visible' });
  ok((await page.textContent('#gtitle')).includes('grill-ui'), 'the panel opens for this feature');
  await page.click('#gstart');
  await page.waitForFunction(() => document.querySelector('#gt').innerText.includes('Q1 - which repo? -> alpha'), null, { timeout: 15000 });
  ok(true, 'the first round streams in, assembled from two chunks');
  const newCall = log.calls.find(c => c[1] === '/api/chat/new');
  ok(newCall && newCall[2].readOnly === true && newCall[2].provider === 'claude', 'the chat session was requested read-only on the claude provider');
  const seed = log.transcript[0].text;
  ok(seed.includes('/repos/alpha') || seed.includes('alpha'), 'the seed sent to the model names the chosen repo');
  ok(seed.includes('READ-ONLY'), 'the seed says READ-ONLY');
  await page.fill('#gtext', 'yes, build it in alpha'); await page.click('#gsend');
  await page.waitForFunction(() => document.querySelector('#gt').innerText.includes('Q2 - tests? -> yes'), null, { timeout: 15000 });
  ok(await page.evaluate(() => document.querySelector('#gt').innerText.includes('yes, build it in alpha')), 'the owner\'s answer appears and the next round streams in');
  // End before saving needs a second press (no blocking dialog)
  await page.click('#gend');
  ok(await page.evaluate(() => document.querySelector('#gt').innerText.includes('Not saved yet')), 'End on an unsaved session warns instead of ending');
  ok(!log.calls.some(c => c[1].endsWith('/close')), 'the first End press did not close the chat');
  await page.click('#gsave');
  await page.waitForFunction(() => document.querySelector('#path').textContent.endsWith('interview.md'), null, { timeout: 10000 });
  await page.waitForFunction(() => document.querySelector('#view').innerText.includes('yes, build it in alpha'));
  ok(true, 'Save to interview appends the conversation and opens interview.md showing the owner\'s words');
  await page.click('#gend');
  await page.waitForFunction(() => document.querySelector('#gt').innerText.includes('Session ended'), null, { timeout: 10000 });
  ok(log.calls.some(c => c[1] === '/api/chat/chat-fake-1/close'), 'End after saving closes the chat session');
  ok((await page.isVisible('#gstart')), 'the Start button is back after ending');
  // ---- a new repo name ----
  await page.click('#bRepo'); await page.waitForSelector('#rnew'); await page.fill('#rnew', 'brand-new'); await page.click('#rf button[type=submit]');
  await page.waitForFunction(() => document.querySelector('#bRepo').textContent === 'Repo: brand-new (new)', null, { timeout: 10000 });
  ok(true, 'a new repo name shows as "Repo: brand-new (new)"');
  await page.click('#bRepo'); await page.waitForSelector('#rnew'); await page.fill('#rnew', '../etc'); await page.click('#rf button[type=submit]');
  await page.waitForFunction(() => document.querySelector('#toast').textContent.includes('letters, digits'), null, { timeout: 10000 });
  ok(true, 'an unsafe repo name is refused with the server\'s message');
  // ---- hygiene ----
  const src = await page.content();
  ok(!/setInterval|setTimeout/.test(await page.evaluate(() => document.documentElement.innerHTML.split('<script>').slice(-1)[0])), 'the page script has no timers');
  ok(dialogs === 0, 'no blocking dialogs were raised');
  const unexpected = errs.filter(e => !/status of 400/.test(e));
  ok(unexpected.length === 0 && errs.length <= 1, 'no console or page errors other than the one deliberate 400');
} finally { await browser.close(); fake.close(); }
