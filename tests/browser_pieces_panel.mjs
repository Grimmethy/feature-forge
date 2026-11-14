// Real-browser test of the sub-pieces shown under each checklist row. Start any Feature Forge server on an empty features folder, e.g.
//   python tests/browser_filing_server.py <empty features folder> 7599
// then: PLAYWRIGHT_DIR=... CHROMIUM=... [FF_PORT=7599] node tests/browser_pieces_panel.mjs
import { createRequire } from 'module';
const require = createRequire((process.env.PLAYWRIGHT_DIR || '/media/model-cache/github/uxforge') + '/node_modules/');
const { chromium } = require('playwright-core');
const base = `http://127.0.0.1:${process.env.FF_PORT || 7599}`;
const CHECKLIST = [
  '# Checklist: Pieces', '',
  '- [ ] FF-1 Filing and lanes <!-- deps: -->',
  '  Some plain explanation of the step.',
  '  - [x] 1a Filing core <!-- merged: f02d0e5 -->',
  '  - [x] 1b Filing routes <!-- merged: 762078b -->',
  '  - [ ] 1c Sonnet cloud lane <!-- needs: owner decision -->',
  '- [x] FF-2 Done step <!-- deps: FF-1 manual: true merged: abc1234 -->',
  '  - [x] 2a Only piece <!-- merged: abc1234 -->',
  '- [ ] FF-3 Nothing nested here <!-- deps: FF-2 -->',
  '  Just text.', ''].join('\n');
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM, args: ['--no-sandbox'] });
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
const errs = []; page.on('pageerror', e => errs.push(String(e))); page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
let dialogs = 0; page.on('dialog', d => { dialogs++; d.dismiss(); });
const ok = (c, m) => { if (!c) { console.log('FAIL', m, errs); process.exitCode = 1; } else console.log('ok  ', m); };
try {
  await page.goto(base + '/', { waitUntil: 'load', timeout: 20000 });
  await page.click('#bNew'); await page.fill('#nt', 'Pieces'); await page.fill('#nr', 'show pieces');
  await page.click('#nf button[type=submit]'); await page.waitForSelector('.card[data-s="pieces"]', { timeout: 10000 });
  await page.evaluate(async t => { await fetch('/api/features/pieces/file?path=checklist.md', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: t }) }); }, CHECKLIST);
  await page.click('.f[data-p="checklist.md"]'); await page.waitForSelector('.row[data-item="FF-1"]');
  const one = '.row[data-item="FF-1"]';
  ok((await page.$$(`${one} .piece`)).length === 3, 'FF-1 shows its three sub-pieces');
  ok((await page.$$eval(`${one} .piece b`, bs => bs.map(b => b.textContent))).join(',') === '1a,1b,1c', 'the pieces show their labels in order');
  ok((await page.textContent(one)).includes('2/3 pieces'), 'the row shows the progress count 2/3 pieces');
  ok((await page.$$eval(`${one} .piece input`, is => is.map(i => i.checked))).join(',') === 'true,true,false', 'done pieces are ticked and the open one is not');
  ok((await page.textContent(`${one} .piece[data-piece="1a"] .tag.merged`)).includes('f02d0e5'), 'a done piece shows its merge commit');
  ok((await page.textContent(`${one} .piece[data-piece="1c"] .tag.need`)).includes('owner decision'), 'an open piece shows what it needs');
  ok(!(await page.$(`${one} .piece[data-piece="1c"] .tag.merged`)), 'an open piece shows no merge commit');
  ok((await page.textContent(one)).includes('Some plain explanation of the step.'), 'the plain explanation still shows');
  ok(!(await page.textContent(`${one} small`)).includes('[x]'), 'the piece lines are not repeated as raw text');
  ok((await page.$$('.row[data-item="FF-2"] .piece')).length === 1 && (await page.textContent('.row[data-item="FF-2"]')).includes('1/1 pieces'), 'a finished step shows 1/1 pieces');
  ok(!(await page.$('.row[data-item="FF-3"] .pieces')) && (await page.$$('.row[data-item="FF-3"] .piece')).length === 0 && !/\d+\/\d+ pieces/.test(await page.textContent('.row[data-item="FF-3"]')), 'a step with no pieces shows no piece list and no count');
  ok((await page.$$('.row')).length === 3, 'the pieces are not extra top-level rows');
  const src = await page.evaluate(() => document.documentElement.innerHTML.split('<script>').slice(-1)[0]);
  ok(!/setInterval|setTimeout/.test(src), 'no timers');
  ok(dialogs === 0, 'no blocking dialogs');
  ok(errs.length === 0, 'no console or page errors');
} finally { await browser.close(); }
