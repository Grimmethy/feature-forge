// Real-browser test of the Create repo button: the first press only shows the steps, "Create now" does them.
// Start the fake-backed server on an empty features folder: python tests/browser_filing_server.py <empty folder> 7599
// then: PLAYWRIGHT_DIR=... CHROMIUM=... [FF_PORT=7599] node tests/browser_create_repo.mjs
import { createRequire } from 'module';
const require = createRequire((process.env.PLAYWRIGHT_DIR || '/media/model-cache/github/uxforge') + '/node_modules/');
const { chromium } = require('playwright-core');
const base = `http://127.0.0.1:${process.env.FF_PORT || 7599}`;
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM, args: ['--no-sandbox'] });
const page = await browser.newPage({ viewport: { width: 1400, height: 850 } });
const errs = []; page.on('pageerror', e => errs.push(String(e))); page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
let dialogs = 0; page.on('dialog', d => { dialogs++; d.dismiss(); });
const ok = (c, m) => { if (!c) { console.log('FAIL', m, errs); process.exitCode = 1; } else console.log('ok  ', m); };
const plan = () => page.evaluate(async () => (await (await fetch('/api/repos/plan?name=brand-new')).json()).steps.map(s => s.done));
try {
  await page.goto(base + '/', { waitUntil: 'load', timeout: 20000 });
  await page.click('#bNew'); await page.fill('#nt', 'Make repo'); await page.fill('#nr', 'needs a new repo');
  await page.click('#nf button[type=submit]'); await page.waitForSelector('.card[data-s="make-repo"]', { timeout: 10000 });
  await page.click('#bRepo'); await page.waitForSelector('#rnew');
  ok(!(await page.$('#rcreate')), 'no Create repo box while no repo is chosen');
  await page.fill('#rnew', 'brand-new'); await page.click('#rf button[type=submit]');
  await page.waitForFunction(() => document.querySelector('#bRepo').textContent === 'Repo: brand-new (new)', null, { timeout: 10000 });
  await page.click('#bRepo'); await page.waitForSelector('#rcreate');
  ok((await page.textContent('#rcreate')).includes('brand-new does not exist yet'), 'the box says the repo does not exist yet');
  ok(!(await page.$('#rcgo')), 'nothing to confirm before the steps are shown');
  await page.click('#rcplan'); await page.waitForSelector('#rcgo');
  const steps = await page.$$eval('#rcsteps .rstep', ls => ls.map(l => l.dataset.step));
  ok(steps.join(',') === 'git,github,register,pipeline', 'the four steps are listed in order');
  ok((await page.textContent('#rcsteps')).includes('private GitHub repo'), 'the GitHub step says private');
  ok((await plan()).every(d => d === false), 'showing the steps created nothing');
  await page.click('#rcgo');
  await page.waitForFunction(() => document.querySelector('#bRepo').textContent === 'Repo: brand-new', null, { timeout: 10000 });
  ok(true, 'after Create now the repo button no longer says (new)');
  const results = await page.$$eval('#rcsteps .rstep b', bs => bs.map(b => b.textContent));
  ok(results.length === 4 && results.every(r => r === 'done'), 'every step reports done');
  ok((await plan()).every(d => d === true), 'all four steps are now done on the server');
  await page.click('#bRepo');
  await page.waitForFunction(() => !document.querySelector('#rcreate') && document.querySelector('#rnew'), null, { timeout: 10000 });
  ok(true, 'the box is gone once the repo exists');
  const src = await page.evaluate(() => document.documentElement.innerHTML.split('<script>').slice(-1)[0]);
  ok(!/setInterval|setTimeout/.test(src), 'no timers');
  ok(dialogs === 0, 'no blocking dialogs');
  ok(errs.length === 0, 'no console or page errors');
} finally { await browser.close(); }
