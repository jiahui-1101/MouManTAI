// @vitest-environment node
import { createServer as createHttpServer, type Server } from 'node:http';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { createServer as createViteServer, type ViteDevServer } from 'vite';
import { demoBff } from './demoBff';

const bootstrap = 'bootstrap-only-operator-token-0123456789';
const isolatedKey = 'backend-only-isolated-key-0123456789';
let upstream: Server;
let vite: ViteDevServer;
let base: string;
let cookie = '';
let csrf = '';
const observed: { path: string; tenant: string | undefined; actor: string | undefined; key: string | undefined }[] = [];

beforeAll(async () => {
  upstream = createHttpServer((request, response) => {
    observed.push({ path: request.url ?? '', tenant: request.headers['x-tenant-id'] as string,
      actor: request.headers['x-actor-id'] as string, key: request.headers['x-isolated-e2e-key'] as string });
    response.setHeader('Content-Type', 'application/json');
    response.end(JSON.stringify([{ order_request_id: 'req_01', tenant_id: 'tenant_a' }]));
  });
  await new Promise<void>(resolve => upstream.listen(0, '127.0.0.1', resolve));
  const port = (upstream.address() as { port: number }).port;
  Object.assign(process.env, { MOUMANTAI_LOCAL_API_PORT: String(port), MOUMANTAI_SYNTHETIC_MODE: '1',
    MOUMANTAI_ISOLATED_E2E: '1', MOUMANTAI_BFF_BOOTSTRAP_TOKEN: bootstrap,
    MOUMANTAI_ISOLATED_E2E_KEY: isolatedKey, MOUMANTAI_ISOLATED_E2E_TENANT_ID: 'tenant_a',
    MOUMANTAI_ISOLATED_E2E_MANAGER_ID: 'manager_01' });
  vite = await createViteServer({ configFile: false, plugins: [demoBff()], server: { host: '127.0.0.1', port: 0, strictPort: false } });
  await vite.listen();
  base = `http://127.0.0.1:${vite.httpServer!.address() && (vite.httpServer!.address() as {port:number}).port}`;
});
afterAll(async () => { await vite?.close(); await new Promise<void>(resolve => upstream?.close(() => resolve())); });
const call = (path: string, method = 'GET', headers: Record<string, string> = {}, body?: unknown) =>
  fetch(`${base}/demo-bff${path}`, { method, headers: { Origin: base, ...(body ? { 'Content-Type': 'application/json' } : {}), ...headers },
    ...(body ? { body: JSON.stringify(body) } : {}) });

describe('isolated OrderRequest facade', () => {
  it('requires trusted bootstrap and keeps backend key out of browser responses', async () => {
    expect((await call('/order-requests')).status).toBe(401);
    expect((await call('/session', 'POST', {}, { bootstrap_token: 'wrong' })).status).toBe(401);
    const response = await call('/session', 'POST', {}, { bootstrap_token: bootstrap });
    expect(response.status).toBe(200);
    cookie = response.headers.get('set-cookie')!.split(';')[0];
    expect(response.headers.get('set-cookie')).toContain('HttpOnly; SameSite=Strict');
    const payload = await response.text();
    expect(payload).not.toContain(isolatedKey);
    csrf = (JSON.parse(payload) as {csrf_token:string}).csrf_token;
    expect(csrf).toHaveLength(64);
  });
  it('overwrites identity, blocks forged headers, CSRF and non-allowlisted commands', async () => {
    const good = await call('/order-requests', 'GET', { Cookie: cookie });
    expect(good.status).toBe(200);
    expect(observed.at(-1)).toEqual({ path: '/v1/backend-v2/order-requests', tenant: 'tenant_a', actor: 'manager_01', key: isolatedKey });
    expect((await call('/order-requests', 'GET', { Cookie: cookie, 'X-Tenant-ID': 'tenant_b' })).status).toBe(403);
    expect((await call('/order-requests', 'GET', { Cookie: cookie, 'X-Actor-ID': 'staff_01' })).status).toBe(403);
    expect((await call('/order-requests/req_01/review', 'POST', { Cookie: cookie },
      { expected_request_version: 1, decision: 'REVIEWED', reason: 'Checked' })).status).toBe(403);
    expect((await call('/mock-orbyte/resources', 'POST', { Cookie: cookie, 'X-CSRF-Token': csrf }, {})).status).toBe(404);
    const review = await call('/order-requests/req_01/review', 'POST', { Cookie: cookie, 'X-CSRF-Token': csrf },
      { expected_request_version: 1, decision: 'REVIEWED', reason: 'Checked' });
    expect(review.status).toBe(200);
    expect(observed.at(-1)?.path).toBe('/v1/backend-v2/order-requests/req_01/review');
  });
  it('rejects wrong origin and revokes the session', async () => {
    const wrong = await fetch(`${base}/demo-bff/order-requests`, { headers: { Cookie: cookie, Origin: 'https://attacker.test' } });
    expect(wrong.status).toBe(403);
    expect((await call('/session', 'DELETE', { Cookie: cookie, 'X-CSRF-Token': csrf })).status).toBe(200);
    expect((await call('/order-requests', 'GET', { Cookie: cookie })).status).toBe(401);
  });
  it('disables the facade when isolated authority is unavailable', async () => {
    const prior = process.env.ENVIRONMENT;
    process.env.ENVIRONMENT = 'production';
    try {
      expect((await call('/session', 'POST', {}, { bootstrap_token: bootstrap })).status).toBe(503);
      expect((await call('/order-requests', 'GET', { Cookie: cookie })).status).toBe(503);
    } finally {
      if (prior === undefined) delete process.env.ENVIRONMENT;
      else process.env.ENVIRONMENT = prior;
    }
  });
});
