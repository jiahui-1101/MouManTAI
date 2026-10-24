/** Genuine browser check against a running migrated PostgreSQL/worker/API/Vite stack. */
import { chromium } from 'playwright';

const base = process.env.MOUMANTAI_BROWSER_BASE ?? 'http://127.0.0.1:5174';
const prefix = process.env.MOUMANTAI_E2E_REQUEST_PREFIX ?? 'fe_bff';
const acceptId = `${prefix}_accept`;
const rejectId = `${prefix}_reject`;
const bootstrap = process.env.MOUMANTAI_BFF_BOOTSTRAP_TOKEN;
if (!bootstrap) throw new Error('MOUMANTAI_BFF_BOOTSTRAP_TOKEN is required');
const browser = await chromium.launch({ headless: true,
  executablePath: process.env.CHROME_PATH ?? 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe' });
const context = await browser.newContext();
const page = await context.newPage();
try {
  await page.goto(`${base}/order-requests`);
  await page.getByLabel('Operator bootstrap token').fill(bootstrap);
  await page.getByRole('button', { name: 'Open isolated session' }).click();
  const sessionCookie = (await context.cookies()).find(value => value.name === 'moumantai_demo_session');
  if (!sessionCookie?.httpOnly || sessionCookie.sameSite !== 'Strict') throw new Error('Operator session cookie lacks required flags');
  if (await page.evaluate(() => document.cookie.includes('moumantai_demo_session')))
    throw new Error('Operator session cookie is script-readable');
  await page.getByRole('link', { name: `Inspect ${acceptId}` }).waitFor();
  await page.getByRole('link', { name: `Inspect ${acceptId}` }).click();
  await page.getByText('MOCK / DEMO-ONLY · PENDING', { exact: false }).waitFor();

  const forged = await page.evaluate(async () => {
    const response = await fetch('/demo-bff/order-requests', { headers: { 'X-Tenant-ID': 'tenant_foreign' } });
    return response.status;
  });
  if (forged !== 403) throw new Error(`Forged tenant header returned ${forged}`);
  const csrf = await page.evaluate(async (requestId) => {
    const response = await fetch(`/demo-bff/order-requests/${requestId}/review`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ expected_request_version: 1, decision: 'REVIEWED', reason: 'Forged no CSRF' }),
    });
    return response.status;
  }, acceptId);
  if (csrf !== 403) throw new Error(`Missing CSRF returned ${csrf}`);

  await page.getByLabel('Decision reason').fill('Browser verified synthetic request');
  await page.getByRole('button', { name: 'Mark reviewed' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Confirm decision' }).click();
  await page.getByText('MOCK / DEMO-ONLY · REVIEWED', { exact: false }).waitFor();
  await page.getByText('FEASIBLE · Snapshot', { exact: false }).waitFor();
  await page.getByLabel('Acceptance reason').fill('Browser approved exact synthetic terms');
  await page.getByRole('button', { name: 'Accept Order', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Confirm Accept Order' }).click();
  await page.getByText('MOCK / DEMO-ONLY · ACCEPTED', { exact: false }).waitFor();
  await page.getByRole('heading', { name: `Linked Commitment com_${acceptId}` }).waitFor();
  await page.reload();
  await page.getByText('MOCK / DEMO-ONLY · ACCEPTED', { exact: false }).waitFor();
  await page.getByRole('link', { name: 'P3 Recovery' }).waitFor();
  await page.getByRole('heading', { name: 'Same-Commitment timeline' }).waitFor();

  await page.goto(`${base}/order-requests/${rejectId}`);
  await page.getByText('MOCK / DEMO-ONLY · PENDING', { exact: false }).waitFor();
  await page.getByLabel('Decision reason').fill('Synthetic order rejected by manager');
  await page.getByRole('button', { name: 'Reject request' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Confirm decision' }).click();
  await page.getByText('MOCK / DEMO-ONLY · REJECTED', { exact: false }).waitFor();
  console.log('BROWSER E2E PASS: persisted list, review, acceptance, reload, rejection, forged identity and CSRF denial');
} catch (error) {
  await page.screenshot({ path: 'e2e-order-request-failure.png', fullPage: true });
  console.error(error);
  process.exitCode = 1;
} finally {
  await browser.close();
}
