// Real-browser test of the Proposals panel: ranking order, a zero-proposal repo, the two-press outward Start request, Start request turning into a link, Dismiss per repo (the same id in two repos), and a re-scouted proposal with a changed why reappearing after an earlier dismissal.
// It starts its own fake-backed server on a temp proposals folder, so nothing real is touched:  PLAYWRIGHT_DIR=... CHROMIUM=... [FF_PORT=7598] node tests/browser_proposals_panel.mjs
// The SEL selectors are the contract with the Proposals view in web/index.html (HUB0004 3/5); keep them in step with that view.
import { createRequire } from 'module';
import { spawn } from 'child_process';
import { createHash } from 'crypto';
import fs from 'fs';
import os from 'os';
import path from 'path';
import { fileURLToPath } from 'url';
const require = createRequire((process.env.PLAYWRIGHT_DIR || '/media/model-cache/github/uxforge') + '/node_modules/');
const { chromium } = require('playwright-core');
const here = path.dirname(fileURLToPath(import.meta.url));
const port = process.env.FF_PORT || 7598;
const base = `http://127.0.0.1:${port}`;
const SEL = {
  nav: "[data-view='proposals']",
  repo: r => `.repo[data-repo='${r}']`,
  prop: (r, id) => `.repo[data-repo='${r}'] .prop[data-id='${id}']`,
  start: '[data-act=start]',
  armed: '[data-act=start][data-armed=1]',
  dismiss: '[data-act=dismiss]',
  link: 'a.feature-link',
  empty: '.empty',
};

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'ff-proposals-'));
const proposalsDir = path.join(tmp, 'proposals');
const features = path.join(tmp, 'features');
const log = path.join(proposalsDir, 'dismissals.jsonl');
fs.mkdirSync(proposalsDir);
fs.mkdirSync(features);

const proposal = (id, title, why, extra = {}) => ({ id, title, why, evidence: ['README.md'], effort: 'S', kind: 'docs', outward: false, ...extra });
const scout = (repo, value, scoutedAt, list) => fs.writeFileSync(path.join(proposalsDir, `${repo}.json`), JSON.stringify({ repo, scoutedAt, lastCommit: 'abc123', value, summary: `${repo} summary`, passes: 1, inputs: [], proposals: list }));
const keyOf = (title, why) => createHash('sha256').update(title + '\n' + why).digest('hex');
const lines = () => (fs.existsSync(log) ? fs.readFileSync(log, 'utf8').split('\n').filter(Boolean).map(l => JSON.parse(l)) : []);

// ranking: value descending, then oldest scoutedAt. empty (5, oldest) comes first, then beta (5), then alpha (4).
scout('empty', 5, '2026-10-01T00:00:00Z', []);
scout('beta', 5, '2026-11-05T00:00:00Z', [proposal('p1', 'Beta one', 'Why beta')]);
scout('alpha', 4, '2026-11-01T00:00:00Z', [proposal('p1', 'Alpha one', 'Why one'), proposal('p2', 'Alpha two', 'Why two', { effort: 'M', outward: true })]);

const server = spawn('python3', ['-I', path.join(here, 'browser_proposals_server.py'), proposalsDir, String(port)], { stdio: ['ignore', 'pipe', 'pipe'] });
let serverOut = '';
const collect = d => { serverOut += String(d); };
server.stdout.on('data', collect);
server.stderr.on('data', collect);
await new Promise((resolve, reject) => {
  const ready = d => { if (String(d).includes('Running on')) resolve(); };
  server.stdout.on('data', ready);
  server.stderr.on('data', ready);
  server.on('exit', code => reject(new Error(`server exited ${code}: ${serverOut}`)));
});

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM, args: ['--no-sandbox'] });
const page = await browser.newPage({ viewport: { width: 1400, height: 850 } });
const errs = []; page.on('pageerror', e => errs.push(String(e))); page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
const ok = (c, m) => { if (!c) { console.log('FAIL', m, errs); process.exitCode = 1; } else console.log('ok  ', m); };
const visible = sel => page.$(sel).then(Boolean);

try {
  await page.goto(base + '/', { waitUntil: 'load', timeout: 20000 });
  await page.click(SEL.nav);
  await page.waitForSelector(SEL.repo('alpha'), { timeout: 10000 });

  // ranking and zero-proposal repos
  const order = await page.$$eval('.repo', els => els.map(e => e.dataset.repo));
  ok(order.join() === 'empty,beta,alpha', `ranking is value descending, then oldest scout: ${order.join()}`);
  ok(await visible(`${SEL.repo('empty')} ${SEL.empty}`), 'a zero-proposal repo shows an empty state');
  ok(await visible(SEL.prop('beta', 'p1')), 'repos after the empty one still render');

  // protected case: the same id p1 in alpha and beta; dismiss alpha/p1 only
  const before = lines().length;
  await page.click(`${SEL.prop('alpha', 'p1')} ${SEL.dismiss}`);
  await page.waitForSelector(SEL.prop('alpha', 'p1'), { state: 'detached' });
  ok(!(await visible(SEL.prop('alpha', 'p1'))), 'Dismiss removes alpha/p1');
  ok((await visible(`${SEL.prop('beta', 'p1')} ${SEL.start}`)) && (await visible(`${SEL.prop('beta', 'p1')} ${SEL.dismiss}`)), 'the same id p1 in beta still shows its buttons');
  const afterFirst = lines();
  ok(afterFirst.length === before + 1, 'Dismiss appends exactly one line');
  const d1 = afterFirst[afterFirst.length - 1];
  ok(d1.repo === 'alpha' && d1.id === 'p1' && d1.title === 'Alpha one' && d1.key === keyOf('Alpha one', 'Why one') && typeof d1.dismissedAt === 'string' && d1.dismissedAt.length > 0, 'the line has repo, id, title, key and dismissedAt');

  // Start request on a plain proposal: one press, then a link
  await page.click(`${SEL.prop('beta', 'p1')} ${SEL.start}`);
  await page.waitForSelector(`${SEL.prop('beta', 'p1')} ${SEL.link}`, { timeout: 10000 });
  const href = await page.getAttribute(`${SEL.prop('beta', 'p1')} ${SEL.link}`, 'href');
  ok(!!href, `Start request turns the row into a link (${href})`);

  // two-press outward flow: the first press creates nothing
  const f0 = fs.readdirSync(features).length;
  await page.click(`${SEL.prop('alpha', 'p2')} ${SEL.start}`);
  await page.waitForSelector(`${SEL.prop('alpha', 'p2')} ${SEL.armed}`, { timeout: 10000 });
  ok(fs.readdirSync(features).length === f0 && !(await visible(`${SEL.prop('alpha', 'p2')} ${SEL.link}`)), 'the first press of an outward Start request does nothing yet');
  await page.click(`${SEL.prop('alpha', 'p2')} ${SEL.start}`);
  await page.waitForSelector(`${SEL.prop('alpha', 'p2')} ${SEL.link}`, { timeout: 10000 });
  ok(fs.readdirSync(features).length === f0 + 1, 'the second press creates the feature');

  // re-scout: alpha/p1 comes back with a changed why, so its old dismissal no longer hides it
  scout('alpha', 4, '2026-11-01T00:00:00Z', [proposal('p1', 'Alpha one', 'Why one, revised'), proposal('p2', 'Alpha two', 'Why two', { effort: 'M', outward: true })]);
  await page.reload({ waitUntil: 'load' });
  await page.click(SEL.nav);
  await page.waitForSelector(SEL.prop('alpha', 'p1'), { timeout: 10000 });
  ok(true, 'a re-scouted alpha/p1 with a changed why reappears after its dismissal');
  const before2 = lines().length;
  await page.click(`${SEL.prop('alpha', 'p1')} ${SEL.dismiss}`);
  await page.waitForSelector(SEL.prop('alpha', 'p1'), { state: 'detached' });
  const afterSecond = lines();
  ok(afterSecond.length === before2 + 1, 'the second Dismiss appends exactly one more line');
  const d2 = afterSecond[afterSecond.length - 1];
  ok(d2.key === keyOf('Alpha one', 'Why one, revised') && d2.key !== d1.key, 'the new line carries the key of the revised title and why');

  ok(errs.length === 0, 'no console or page errors');
} finally {
  await browser.close();
  server.kill();
  fs.rmSync(tmp, { recursive: true, force: true });
}
