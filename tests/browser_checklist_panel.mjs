// Real-browser test of the checklist rows, the per-item Grill button and the proposal review, against a FAKE chat plugin.
// Start the server on 7499 with a throwaway features folder (see browser_grill_panel.mjs), then:
//   PLAYWRIGHT_DIR=... CHROMIUM=... node tests/browser_checklist_panel.mjs
import { createRequire } from 'module';
import http from 'http';
const require = createRequire((process.env.PLAYWRIGHT_DIR || '/media/model-cache/github/uxforge') + '/node_modules/');
const { chromium } = require('playwright-core');
const base = 'http://127.0.0.1:7499';
const BLOCK = '```checklist-diff\n{"ops": [{"op": "add", "title": "Docs page", "deps": ["FF-3"]}, {"op": "remove", "id": "FF-1"}, {"op": "change", "id": "FF-2", "title": "Build it better"}]}\n```';
const CHECKLIST = '# Checklist: Rows\n\n- [x] FF-1 Scaffold <!-- task: adhoc-1 premium: true deps: filed: 2026-11-13 -->\n- [ ] FF-2 Build <!-- deps: FF-1 -->\n  Body of build.\n- [ ] FF-3 Wire <!-- deps: FF-2 -->\n';
const log = { calls: [], transcript: [] };
const fake = http.createServer((req, res) => {
  let body = ''; req.on('data', c => body += c); req.on('end', () => {
    const b = body ? JSON.parse(body) : null; log.calls.push([req.method, req.url, b]);
    if (req.method === 'POST' && req.url === '/api/chat/new') { res.end(JSON.stringify({ id: 'chat-fake-1' })); return; }
    if (req.method === 'POST' && req.url.endsWith('/message')) {
      log.transcript.push({ role: 'user', text: b.message }, { role: 'assistant', text: 'Here is the plan:\n' + BLOCK });
      res.writeHead(200, { 'Content-Type': 'text/event-stream' });
      res.write('data: ' + JSON.stringify({ type: 'chunk', text: 'Here is the plan' }) + '\n\n');
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
  await page.click('#bNew'); await page.fill('#nt', 'Rows'); await page.fill('#nr', 'rows');
  await page.click('#nf button[type=submit]'); await page.waitForSelector('.card[data-s="rows"]', { timeout: 10000 });
  await page.evaluate(async t => { await fetch('/api/features/rows/file?path=checklist.md', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: t }) }); }, CHECKLIST);
  await page.click('.f[data-p="checklist.md"]'); await page.waitForSelector('.row[data-item="FF-2"]');
  ok((await page.$$('.row')).length === 3, 'three checklist rows');
  ok(await page.isChecked('.row[data-item="FF-1"] input'), 'FF-1 is ticked');
  ok((await page.textContent('.row[data-item="FF-1"]')).includes('filed'), 'FF-1 shows the filed mark');
  ok((await page.textContent('.row[data-item="FF-2"]')).includes('Body of build.'), 'the item body shows');
  ok((await page.textContent('.row[data-item="FF-2"]')).includes('after FF-1'), 'dependencies show');
  await page.click('.row[data-item="FF-2"] [data-grill]'); await page.waitForSelector('#grill', { state: 'visible' });
  ok((await page.textContent('#gtitle')).includes('FF-2'), 'the panel names the item');
  await page.click('#gstart'); await page.waitForSelector('#gtext', { state: 'visible' });
  await page.fill('#gtext', 'plan it'); await page.click('#gsend');
  await page.waitForFunction(() => document.querySelector('#gt').innerText.includes('Here is the plan'), null, { timeout: 15000 });
  ok(log.calls.some(c => c[1] === '/api/chat/new'), 'a chat session was opened');
  ok(log.transcript[0].text.includes('checklist item FF-2') || log.calls.some(c => c[2] && c[2].message && c[2].message.includes('checklist item FF-2')), 'the seed is about FF-2');
  await page.click('#grev'); await page.waitForSelector('#prop .pop');
  const ops = await page.$$eval('#prop .pop', ls => ls.map(l => ({ t: l.textContent, dis: l.querySelector('input').disabled, on: l.querySelector('input').checked })));
  ok(ops.length === 3, 'three proposed ops listed');
  ok(ops[1].dis && !ops[1].on && /refused/.test(ops[1].t), 'removing the filed FF-1 is shown refused and cannot be ticked');
  ok(ops[0].on && ops[2].on, 'valid ops start ticked');
  await page.uncheck('#prop .pop[data-op="2"] input');
  await page.click('#gapply');
  await page.waitForFunction(() => document.querySelector('#view').innerText.includes('Docs page'), null, { timeout: 10000 });
  const text = await page.innerText('#view');
  ok(text.includes('Docs page') && text.includes('after FF-3'), 'the added item appears in the reloaded checklist');
  ok(!text.includes('Build it better'), 'the unticked change was not applied');
  await page.click('.row[data-item="FF-3"] [data-grill]');
  ok(await page.evaluate(() => document.querySelector('#toast').textContent.includes('End the current grill session')), 'a second item grill is refused while one is open');
  const src = await page.evaluate(() => document.documentElement.innerHTML.split('<script>').slice(-1)[0]);
  ok(!/setInterval|setTimeout/.test(src), 'no timers');
  ok(dialogs === 0, 'no blocking dialogs');
  ok(errs.filter(e => !/status of 400/.test(e)).length === 0, 'no console or page errors');
} finally { await browser.close(); fake.close(); }
