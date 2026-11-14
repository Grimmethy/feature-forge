// Real-browser test of the filing buttons: File, the two-press accept for polling language, and the premium and cloud toggles.
// Start the fake-backed server first:  python tests/browser_filing_server.py <empty features folder> 7599
// then: PLAYWRIGHT_DIR=... CHROMIUM=... [FF_PORT=7599] node tests/browser_filing_panel.mjs
import { createRequire } from 'module';
const require = createRequire((process.env.PLAYWRIGHT_DIR || '/media/model-cache/github/uxforge') + '/node_modules/');
const { chromium } = require('playwright-core');
const base = `http://127.0.0.1:${process.env.FF_PORT || 7599}`;
const CHECKLIST = '# Checklist: Filing\n\n- [ ] FF-1 Build the core <!-- premium: true deps: -->\n  Write core.py.\n- [ ] FF-2 Watch the folder <!-- deps: FF-1 -->\n  Check it every 5 minutes.\n';
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM, args: ['--no-sandbox'] });
const page = await browser.newPage({ viewport: { width: 1400, height: 850 } });
const errs = []; page.on('pageerror', e => errs.push(String(e))); page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
let dialogs = 0; page.on('dialog', d => { dialogs++; d.dismiss(); });
const ok = (c, m) => { if (!c) { console.log('FAIL', m, errs); process.exitCode = 1; } else console.log('ok  ', m); };
const toast = () => page.evaluate(() => document.querySelector('#toast').textContent);
try {
  await page.goto(base + '/', { waitUntil: 'load', timeout: 20000 });
  await page.click('#bNew'); await page.fill('#nt', 'Filing'); await page.fill('#nr', 'file things\nrepo: alpha');
  await page.click('#nf button[type=submit]'); await page.waitForSelector('.card[data-s="filing"]', { timeout: 10000 });
  await page.evaluate(async t => { await fetch('/api/features/filing/file?path=checklist.md', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: t }) }); }, CHECKLIST);
  await page.click('.f[data-p="checklist.md"]'); await page.waitForSelector('.row[data-item="FF-2"]');
  const txt = sel => page.textContent(sel);
  ok((await txt('.row[data-item="FF-1"] [data-flag="premium"]')) === 'Premium: on', 'FF-1 shows Premium: on');
  ok((await txt('.row[data-item="FF-2"] [data-flag="premium"]')) === 'Premium: off', 'FF-2 shows Premium: off');
  await page.click('.row[data-item="FF-2"] [data-flag="premium"]');
  await page.waitForFunction(() => document.querySelector('.row[data-item="FF-2"] [data-flag="premium"]').textContent === 'Premium: on');
  ok(true, 'the premium toggle turns on and the row redraws');
  await page.click('.row[data-item="FF-2"] [data-flag="cloud"]');
  await page.waitForFunction(() => document.querySelector('.row[data-item="FF-2"] [data-flag="cloud"]').textContent === 'Cloud: on');
  ok(true, 'the cloud toggle turns on');
  // order: FF-2 waits for FF-1 (and arms its polling warning first)
  await page.click('.row[data-item="FF-2"] [data-file]');
  await page.waitForFunction(() => document.querySelector('.row[data-item="FF-2"] [data-file]').textContent === 'File anyway');
  ok((await txt('.row[data-item="FF-2"]')).includes('Polling language'), 'the first File press on a polling item shows the warning and arms File anyway');
  await page.click('.row[data-item="FF-2"] [data-file]');
  await page.waitForFunction(() => document.querySelector('#toast').textContent.includes('file FF-1 first'), null, { timeout: 10000 });
  ok(true, 'filing FF-2 before FF-1 is refused with the server message');
  // file FF-1
  await page.click('.row[data-item="FF-1"] [data-file]');
  await page.waitForFunction(() => document.querySelector('#toast').textContent.includes('Filed FF-1 as adhoc-fake-1'), null, { timeout: 10000 });
  await page.waitForFunction(() => document.querySelector('.row[data-item="FF-1"]').textContent.includes('task adhoc-fake-1'));
  ok(!(await page.$('.row[data-item="FF-1"] [data-file]')), 'a filed row shows its task and no File button');
  ok(!(await page.$('.row[data-item="FF-1"] [data-flag="cloud"]')), 'a filed row has no cloud toggle');
  ok((await txt('.row[data-item="FF-1"]')).includes('filed'), 'the filed tag shows');
  // FF-2 now: armed state survives the redraw, a second press files it
  await page.click('.row[data-item="FF-2"] [data-file]');
  await page.waitForFunction(() => document.querySelector('#toast').textContent.includes('Filed FF-2 as adhoc-fake-2'), null, { timeout: 10000 });
  ok(true, 'File anyway files the polling item');
  // premium on a filed row
  await page.click('.row[data-item="FF-1"] [data-flag="premium"]');
  await page.waitForFunction(() => document.querySelector('.row[data-item="FF-1"] [data-flag="premium"]').textContent === 'Premium: off');
  ok(true, 'premium can still be turned off on a filed row');
  const src = await page.evaluate(() => document.documentElement.innerHTML.split('<script>').slice(-1)[0]);
  ok(!/setInterval|setTimeout/.test(src), 'no timers');
  ok(dialogs === 0, 'no blocking dialogs');
  ok(errs.filter(e => !/status of 400/.test(e)).length === 0, 'no console or page errors other than the deliberate 400');
} finally { await browser.close(); }
