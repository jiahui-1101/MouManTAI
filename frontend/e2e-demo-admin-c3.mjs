/** Chrome proof of Demo Admin login -> Dashboard -> C3-only durable decision. */
import assert from 'node:assert/strict';
import { chromium } from 'playwright';

const base = process.env.MOUMANTAI_BROWSER_BASE;
const username = process.env.MOUMANTAI_DEMO_ADMIN_USERNAME;
const password = process.env.MOUMANTAI_DEMO_ADMIN_PASSWORD;
if (!base || !username || !password) throw new Error('Demo Admin browser environment required');
const browser = await chromium.launch({ headless: true, channel: 'chrome' });
try {
  const context = await browser.newContext({ ignoreHTTPSErrors: process.env.MOUMANTAI_BROWSER_ALLOW_SELF_SIGNED === '1' });
  const page = await context.newPage();
  await page.goto(`${base}/order-requests`);
  await page.getByLabel('Demo Admin username').fill(username);
  await page.getByLabel('Demo Admin password').fill(password);
  await page.getByRole('button', { name: 'Open isolated session' }).click();
  await page.getByText('MOCK / DEMO-ONLY · Server session:', { exact: false }).waitFor();
  const cookie = (await context.cookies()).find(value => value.name === 'moumantai_demo_session');
  assert.ok(cookie?.httpOnly && cookie.secure && cookie.sameSite === 'Strict');
  await page.goto(base);
  await page.getByText('1 pending C3 classification review.').waitFor({ timeout: 10_000 })
    .catch(async error => { console.error((await page.locator('body').innerText()).slice(0, 2000)); throw error; });
  await page.getByRole('link', { name: 'Open Human Review' }).click();
  const panel = page.getByRole('region', { name: 'C3 classification reviews' });
  await panel.getByRole('button', { name: /TELEGRAM.*UNKNOWN.*REAL/ }).click();
  await panel.getByRole('article', { name: 'C3 review evidence' }).waitFor();
  assert.match(await panel.innerText(), /bot-readiness \/ native-browser-/);
  assert.match(await panel.innerText(), /Origin: REAL \/ VERIFIED/);
  await panel.getByLabel('Decision reason').fill('Demo Admin corrected only the classification');
  await panel.getByLabel('Corrected intent').selectOption('OTHER');
  page.once('dialog', dialog => dialog.accept());
  await panel.getByRole('button', { name: 'Correct classification' }).click();
  await panel.getByText('Classification decision recorded.').waitFor();
  await page.reload();
  await panel.getByRole('button', { name: 'View C3 decision history' }).click();
  await panel.getByRole('button', { name: /TELEGRAM.*REAL/ }).first().click();
  await panel.getByRole('article', { name: 'C3 review evidence' }).waitFor();
  assert.match(await panel.innerText(), /Decision: CORRECT by user_owner_01/);
  assert.equal(await panel.getByRole('button', { name: /Approve classification|Reject classification|Correct classification/ }).count(), 0);
  if (process.env.C3_BROWSER_SCREENSHOT) await page.screenshot({ path: process.env.C3_BROWSER_SCREENSHOT, fullPage: true });
  console.log('PASS Chrome: HTTPS Demo Admin session, Dashboard review, classification-only decision and refresh');
} finally { await browser.close(); }
