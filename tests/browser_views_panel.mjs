// Real-browser test of the Board, By repo and Graph views. Start any Feature Forge server on an empty features folder, e.g.
//   python tests/browser_filing_server.py <empty features folder> 7599
// then: PLAYWRIGHT_DIR=... CHROMIUM=... [FF_PORT=7599] node tests/browser_views_panel.mjs
import { createRequire } from 'module';
const require = createRequire((process.env.PLAYWRIGHT_DIR || '/media/model-cache/github/uxforge') + '/node_modules/');
const { chromium } = require('playwright-core');
const base = `http://127.0.0.1:${process.env.FF_PORT || 7599}`;
const ONE = '# Checklist: One\n\n- [x] FF-1 Scaffold <!-- task: t1 manual: true took: 42 -->\n- [ ] FF-2 Build the core <!-- task: t2 premium: true deps: FF-1 -->\n- [ ] FF-3 Wire it up <!-- deps: FF-2 -->\n';
const TWO = '# Checklist: Two\n\n- [ ] FF-1 Only item <!-- deps: -->\n';
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM, args: ['--no-sandbox'] });
const page = await browser.newPage({ viewport: { width: 1500, height: 900 } });
const errs = []; page.on('pageerror', e => errs.push(String(e))); page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
let dialogs = 0; page.on('dialog', d => { dialogs++; d.dismiss(); });
const ok = (c, m) => { if (!c) { console.log('FAIL', m, errs); process.exitCode = 1; } else console.log('ok  ', m); };
try {
  await page.goto(base + '/', { waitUntil: 'load', timeout: 20000 });
  await page.evaluate(async ([one, two]) => {
    const mk = async (title, req, cl) => {
      const r = await (await fetch('/api/features', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title, request: req }) })).json();
      await fetch(`/api/features/${r.slug}/file?path=checklist.md`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: cl }) });
    };
    await mk('One', 'first\nrepo: alpha', one); await mk('Two', 'second', two);
  }, [ONE, TWO]);
  await page.click('#bRefresh');
  // ---- board ----
  await page.click('#bBoard'); await page.waitForSelector('.board .col');
  const cols = await page.$$eval('.board .col', cs => Object.fromEntries(cs.map(c => [c.dataset.col, [...c.querySelectorAll('.bcard')].map(b => b.textContent)])));
  ok(Object.keys(cols).join('|') === 'Not filed|In flight|Done', 'the board has the three columns in order');
  ok((await page.$eval('#view', e => e.getBoundingClientRect().width)) > 950, 'the board uses the full width');
  ok(cols['Done'][0].includes('took 42 min'), 'a done card shows how long it took');
  ok(cols['Done'].length === 1 && cols['Done'][0].includes('Scaffold'), 'a ticked item is in Done');
  ok(cols['In flight'].length === 1 && cols['In flight'][0].includes('Build the core') && cols['In flight'][0].includes('premium'), 'a filed item is In flight with its premium tag');
  ok(cols['Not filed'].length === 2, 'the two unfiled items are in Not filed');
  ok((await page.textContent('.board .col[data-col="In flight"] .bcard')).includes('alpha'), 'a card names its feature and repo');
  await page.click('.board .col[data-col="Not filed"] .bcard'); await page.waitForSelector('.row[data-item]');
  ok((await page.textContent('#path')).endsWith('checklist.md'), 'clicking a card opens that feature checklist');
  // ---- by repo ----
  await page.click('#bRepos'); await page.waitForSelector('.grp');
  const groups = await page.$$eval('.grp', gs => gs.map(g => g.dataset.repo + ':' + g.querySelectorAll('.card').length));
  ok(groups.join(',') === 'alpha:1,:1', 'features group by repo with the no-repo group last');
  ok((await page.textContent('.grp[data-repo=""]')).includes('(no repo yet)'), 'the no-repo group is named');
  ok((await page.textContent('.grp[data-repo="alpha"] h3')).includes('1/3 done'), 'a group shows its done count');
  // ---- graph ----
  await page.click('.grp[data-repo="alpha"] .card'); await page.waitForSelector('.row[data-item]');
  ok(await page.isVisible('#bGraph'), 'the Graph button shows inside a feature');
  await page.click('#bGraph'); await page.waitForSelector('svg.graph .gn');
  ok((await page.$$('svg.graph .gn')).length === 3 && (await page.$$('svg.graph .edge')).length === 2, 'the graph has a node per item and an edge per dependency');
  ok((await page.$eval('svg.graph .gn.done rect', r => getComputedStyle(r).stroke)) !== (await page.$eval('svg.graph .gn.open rect', r => getComputedStyle(r).stroke)), 'done and open nodes are styled differently');
  await page.click('#bBoard'); await page.waitForSelector('.board');
  ok(!(await page.isVisible('#bGraph')), 'the Graph button hides on the board');
  const src = await page.evaluate(() => document.documentElement.innerHTML.split('<script>').slice(-1)[0]);
  ok(!/setInterval|setTimeout/.test(src), 'no timers');
  ok(dialogs === 0, 'no blocking dialogs');
  ok(errs.length === 0, 'no console or page errors');
} finally { await browser.close(); }
