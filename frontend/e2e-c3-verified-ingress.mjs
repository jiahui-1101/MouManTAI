/** Chrome check over a real-mode verified fixture already classified by the worker. */
import assert from 'node:assert/strict';
import { chromium } from 'playwright';

const base = process.env.C3_BROWSER_BASE_URL ?? 'http://127.0.0.1:5177';
const token = process.env.MOUMANTAI_BFF_BOOTSTRAP_TOKEN;
if (!token) throw new Error('MOUMANTAI_BFF_BOOTSTRAP_TOKEN is required');

const browser = await chromium.launch({ headless: true, channel: 'chrome' });
try {
  const context = await browser.newContext();
  const page = await context.newPage();
  const denied = await page.request.get(`${base}/demo-bff/c3-reviews`, { headers: { Origin: base } });
  assert.equal(denied.status(), 401);
  const session = await page.request.post(`${base}/demo-bff/session`, {
    headers: { Origin: base }, data: { bootstrap_token: token },
  });
  assert.equal(session.status(), 200);
  await page.goto(`${base}/human-review`);
  const panel = page.getByRole('region', { name: 'C3 classification reviews' });
  await panel.getByRole('button', { name: /TELEGRAM.*UNKNOWN.*REAL/ }).waitFor({ timeout: 10_000 })
    .catch(async error => { console.error(await panel.innerText()); throw error; });
  await panel.getByRole('button', { name: /TELEGRAM.*UNKNOWN.*REAL/ }).click();
  await panel.getByRole('article', { name: 'C3 review evidence' }).waitFor();
  assert.match(await panel.innerText(), /bot-readiness \/ native-browser-1/);
  assert.match(await panel.innerText(), /Origin: REAL \/ VERIFIED/);
  assert.equal(await panel.getByRole('button', { name: /approve|reject|correct/i }).count(), 0);
  const csrf = (await session.json()).csrf_token;
  const forbidden = await page.request.post(`${base}/demo-bff/c3-reviews/fake/decide`, {
    headers: { Origin: base, 'X-CSRF-Token': csrf }, data: {},
  });
  assert.equal(forbidden.status(), 404);
  if (process.env.C3_BROWSER_SCREENSHOT) await page.screenshot({ path: process.env.C3_BROWSER_SCREENSHOT, fullPage: true });
  console.log('PASS Chrome: worker-created REAL/VERIFIED C3 review visible; decision route absent');
} finally {
  await browser.close();
}
