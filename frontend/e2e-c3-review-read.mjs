/** Local synthetic C3 read-only browser smoke; requires the isolated BFF and fixture. */
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
  assert.equal(denied.status(), 401, 'review read requires operator session');
  const session = await page.request.post(`${base}/demo-bff/session`, {
    headers: { Origin: base }, data: { bootstrap_token: token },
  });
  assert.equal(session.status(), 200, 'operator bootstrap');
  await page.goto(`${base}/human-review`);
  const panel = page.getByRole('region', { name: 'C3 classification reviews' });
  await panel.getByText('C3 classification reviews').waitFor();
  await panel.getByRole('button', { name: /TELEGRAM.*UNKNOWN.*SYNTHETIC/ }).waitFor();
  await panel.getByRole('button', { name: /TELEGRAM.*UNKNOWN.*SYNTHETIC/ }).click();
  await panel.getByRole('article', { name: 'C3 review evidence' }).waitFor();
  assert.match(await panel.innerText(), /Classification: NONE \(unavailable\)/);
  assert.match(await panel.innerText(), /Origin: SYNTHETIC \/ SYNTHETIC/);
  assert.match(await panel.innerText(), /approval is separate from order acceptance/i);
  assert.match(await panel.innerText(), /actions are unavailable/);
  assert.equal(await panel.getByRole('button', { name: /approve|reject|correct/i }).count(), 0);
  const csrf = (await session.json()).csrf_token;
  const deniedMutation = await page.request.post(`${base}/demo-bff/c3-reviews/fake/decide`, {
    headers: { Origin: base, 'X-CSRF-Token': csrf }, data: {},
  });
  assert.equal(deniedMutation.status(), 404, 'no C3 decision facade route');
  if (process.env.C3_BROWSER_SCREENSHOT) await page.screenshot({ path: process.env.C3_BROWSER_SCREENSHOT, fullPage: true });
  const revoke = await page.request.delete(`${base}/demo-bff/session`, {
    headers: { Origin: base, 'X-CSRF-Token': csrf },
  });
  assert.equal(revoke.status(), 200, 'session revocation');
  await panel.getByRole('button', { name: 'Refresh C3 reviews' }).click();
  await panel.getByRole('alert').waitFor();
  assert.equal(await panel.getByRole('article', { name: 'C3 review evidence' }).count(), 0,
    'revoked session clears previously displayed evidence');
  console.log('PASS Chrome: session gate and revocation, durable C3 review evidence, no decision control or route');
} finally {
  await browser.close();
}
