// Real-browser check: the sidebar shows 'Loading features...' while /api/features is held, and it is gone once the list renders.
// Start a Feature Forge server, then: PLAYWRIGHT_DIR=... CHROMIUM=... FF_PORT=7599 node tests/browser_sidebar_loading.mjs
import { createRequire } from 'module';
const require = createRequire((process.env.PLAYWRIGHT_DIR || '/media/model-cache/github/uxforge') + '/node_modules/');
const { chromium } = require('playwright-core');
const base = `http://127.0.0.1:${process.env.FF_PORT || 7599}`;
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM, args: ['--no-sandbox'] });
const page = await browser.newPage();
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };
const feats = [{ slug: 'a', title: 'Alpha', status: 'Planned', ticked: 0, total: 1, repo: '' }];
let release;
const gate = new Promise(r => { release = r; });
let mode = 'hold';
await page.route('**/api/features', async route => {
  if (route.request().method() !== 'GET') return route.continue();
  if (mode === 'hold') await gate;
  if (mode === 'fail') return route.fulfill({ status: 500, contentType: 'application/json', body: '{"error":"boom"}' });
  return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(feats) });
});
try {
  await page.goto(base + '/', { waitUntil: 'domcontentloaded' });
  ok((await page.textContent('#feature-list-status')).includes('Loading features...'), 'loading line shows while /api/features is held');
  release();
  await page.waitForSelector('#list .card[data-s="a"]');
  ok((await page.$('#feature-list-status')) === null, 'loading line is gone once the list renders');
  ok((await page.textContent('#filters')).includes('All 1'), 'filter counts rendered');
  mode = 'fail';
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#bListRetry', { timeout: 10000 });
  ok((await page.textContent('#feature-list-status')).includes('Could not load features.'), 'a failed load shows the error line');
  mode = 'ok';
  await page.click('#bListRetry');
  await page.waitForSelector('#list .card[data-s="a"]');
  ok((await page.$('#feature-list-status')) === null, 'Retry renders the list and removes the status line');
} finally { await browser.close(); }
