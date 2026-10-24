/** Focused TLS, session, CSRF, scope and allowlist regression for Demo Admin. */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createServer as createHttpServer, request as httpRequest } from 'node:http';
import { request as httpsRequest } from 'node:https';
import { randomBytes, scryptSync } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, rmdirSync, unlinkSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createServer as createNetServer } from 'node:net';
import { createDemoGateway } from './demoGateway.mjs';

const listen = server => new Promise(resolve => server.listen(0, '127.0.0.1', () => resolve(server.address().port)));
const close = server => new Promise(resolve => server.close(resolve));
const freePort = async () => { const server = createNetServer(); const port = await listen(server); await close(server); return port; };
const call = (port, path, { method = 'GET', origin, cookie, csrf, json, headers = {} } = {}) =>
  new Promise((resolve, reject) => {
    const payload = json === undefined ? null : JSON.stringify(json);
    const req = httpsRequest({ hostname: '127.0.0.1', port, path, method, rejectUnauthorized: false,
      headers: { Host: `localhost:${port}`, ...(origin ? { Origin: origin } : {}), ...(cookie ? { Cookie: cookie } : {}),
        ...(csrf ? { 'X-CSRF-Token': csrf } : {}), ...(payload ? { 'Content-Type': 'application/json' } : {}), ...headers } }, res => {
      let body = ''; res.on('data', chunk => { body += chunk; });
      res.on('end', () => resolve({ status: res.statusCode, headers: res.headers,
        json: () => JSON.parse(body) }));
    });
    req.on('error', reject);
    if (payload) req.write(payload);
    req.end();
  });

test('Demo Admin gateway enforces login, CSRF, tenant scope, expiry and revocation', async () => {
  const directory = mkdtempSync(join(tmpdir(), 'moumantai-gateway-'));
  const cert = join(directory, 'cert.pem'); const keyPath = join(directory, 'key.pem');
  const generated = spawnSync('openssl', ['req', '-x509', '-newkey', 'rsa:2048', '-nodes',
    '-keyout', keyPath, '-out', cert, '-days', '1', '-subj', '/CN=localhost',
    '-addext', 'subjectAltName=DNS:localhost,IP:127.0.0.1'], { stdio: 'ignore' });
  assert.equal(generated.status, 0, 'OpenSSL test certificate');
  const password = randomBytes(32).toString('hex');
  const salt = randomBytes(32);
  const hash = scryptSync(password, salt, 64, { N: 16384, r: 8, p: 1 });
  const upstream = createHttpServer((req, res) => {
    res.setHeader('Content-Type', 'application/json');
    res.end(JSON.stringify({ path: req.url, tenant: req.headers['x-tenant-id'],
      actor: req.headers['x-actor-id'], key: req.headers['x-isolated-e2e-key'] }));
  });
  const apiPort = await listen(upstream);
  const port = await freePort();
  const origin = `https://localhost:${port}`;
  const env = { ENVIRONMENT: 'staging', APP_ENV: 'synthetic', MOUMANTAI_SYNTHETIC_MODE: '1',
    MOUMANTAI_ISOLATED_E2E: '1', MOUMANTAI_DEMO_ADMIN_AUTH: '1',
    MOUMANTAI_DEMO_ADMIN_USERNAME: 'demo-admin',
    MOUMANTAI_DEMO_ADMIN_PASSWORD_HASH: `scrypt$16384$8$1$${salt.toString('hex')}$${hash.toString('hex')}`,
    MOUMANTAI_ISOLATED_E2E_KEY: randomBytes(32).toString('hex'),
    MOUMANTAI_ISOLATED_E2E_TENANT_ID: 'tenant-fixed',
    MOUMANTAI_ISOLATED_E2E_MANAGER_ID: 'user_manager_01',
    MOUMANTAI_DEMO_ORIGIN: origin, MOUMANTAI_DEMO_PRIVATE_API: `http://127.0.0.1:${apiPort}`,
    MOUMANTAI_DEMO_TLS_KEY: keyPath, MOUMANTAI_DEMO_TLS_CERT: cert,
    TELEGRAM_OUTBOUND_ENABLED: 'false', WHATSAPP_OUTBOUND_ENABLED: 'false',
    RESEND_OUTBOUND_ENABLED: 'false' };
  const gateway = createDemoGateway(env);
  await new Promise(resolve => gateway.listen(port, '127.0.0.1', resolve));
  try {
    assert.equal((await call(port, '/demo-bff/c3-reviews')).status, 401);
    assert.equal((await call(port, '/demo-bff/session', { method: 'POST', json: {
      username: 'demo-admin', password } })).status, 403, 'login requires exact Origin');
    assert.equal((await call(port, '/demo-bff/session', { method: 'POST', origin, json: {
      username: 'demo-admin', password: 'wrong' } })).status, 401);
    const login = await call(port, '/demo-bff/session', { method: 'POST', origin, json: {
      username: 'demo-admin', password } });
    assert.equal(login.status, 200);
    const cookie = login.headers['set-cookie'][0].split(';')[0];
    assert.match(login.headers['set-cookie'][0], /HttpOnly; Secure; SameSite=Strict/);
    const csrf = login.json().csrf_token;
    assert.equal(login.json().tenant_id, 'tenant-fixed');
    assert.equal((await call(port, '/demo-bff/order-requests', { cookie, origin: 'https://evil.example' })).status, 403);
    assert.equal((await call(port, '/demo-bff/order-requests', { cookie,
      headers: { 'X-Tenant-ID': 'foreign' } })).status, 403);
    assert.equal((await call(port, '/v1/backend-v2/order-requests', { cookie })).status, 404);
    assert.equal((await call(port, '/demo-bff/overview', { cookie })).json().path, '/v1/overview');
    assert.equal((await call(port, '/demo-bff/c3-reviews/review-1/decide', {
      method: 'POST', cookie, origin, json: { action: 'REJECT' } })).status, 403);
    const proxied = await call(port, '/demo-bff/c3-reviews/review-1/decide', {
      method: 'POST', cookie, origin, csrf, json: { action: 'REJECT' } });
    assert.equal(proxied.status, 200);
    assert.equal(proxied.json().tenant, 'tenant-fixed');
    assert.equal(proxied.json().actor, 'user_manager_01');
    assert.equal(proxied.json().key, env.MOUMANTAI_ISOLATED_E2E_KEY);
    assert.equal((await call(port, '/demo-bff/session', { method: 'DELETE', cookie, origin, csrf })).status, 200);
    assert.equal((await call(port, '/demo-bff/order-requests', { cookie })).status, 401);
    const second = await call(port, '/demo-bff/session', { method: 'POST', origin, json: {
      username: 'demo-admin', password } });
    const secondCookie = second.headers['set-cookie'][0].split(';')[0];
    const realNow = Date.now;
    Date.now = () => realNow() + 21 * 60_000;
    try { assert.equal((await call(port, '/demo-bff/order-requests', { cookie: secondCookie })).status, 401); }
    finally { Date.now = realNow; }
    for (let i = 0; i < 5; i++) assert.equal((await call(port, '/demo-bff/session', {
      method: 'POST', origin, json: { username: 'demo-admin', password: 'wrong' } })).status, 401);
    assert.equal((await call(port, '/demo-bff/session', { method: 'POST', origin, json: {
      username: 'demo-admin', password } })).status, 429);
  } finally {
    await close(gateway); await close(upstream);
    unlinkSync(cert); unlinkSync(keyPath); rmdirSync(directory);
  }
});

test('Render managed HTTPS adapter keeps exact host and Secure session policy', async () => {
  const password = randomBytes(20).toString('hex');
  const salt = randomBytes(32);
  const hash = scryptSync(password, salt, 64, { N: 16384, r: 8, p: 1 });
  const env = { ENVIRONMENT: 'staging', APP_ENV: 'synthetic',
    MOUMANTAI_SYNTHETIC_MODE: '1', MOUMANTAI_ISOLATED_E2E: '1',
    MOUMANTAI_DEMO_ADMIN_AUTH: '1', MOUMANTAI_DEMO_HOSTING: 'render',
    RENDER_SERVICE_TYPE: 'web', RENDER_EXTERNAL_HOSTNAME: 'moumantai-demo.onrender.com',
    MOUMANTAI_DEMO_PRIVATE_API_HOST: 'moumantai-demo-api',
    MOUMANTAI_DEMO_ADMIN_USERNAME: 'demo-admin',
    MOUMANTAI_DEMO_ADMIN_PASSWORD_HASH: `scrypt$16384$8$1$${salt.toString('hex')}$${hash.toString('hex')}`,
    MOUMANTAI_ISOLATED_E2E_KEY: randomBytes(32).toString('hex'),
    MOUMANTAI_ISOLATED_E2E_TENANT_ID: 'tenant-fixed',
    MOUMANTAI_ISOLATED_E2E_MANAGER_ID: 'user_manager_01',
    TELEGRAM_OUTBOUND_ENABLED: 'false', WHATSAPP_OUTBOUND_ENABLED: 'false',
    RESEND_OUTBOUND_ENABLED: 'false' };
  const gateway = createDemoGateway(env);
  const port = await listen(gateway);
  const send = (host, origin) => new Promise((resolve, reject) => {
    const payload = JSON.stringify({ username: 'demo-admin', password });
    const req = httpRequest({ hostname: '127.0.0.1', port, path: '/demo-bff/session',
      method: 'POST', headers: { Host: host, Origin: origin,
        'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(payload),
        'CF-Connecting-IP': '203.0.113.15' } }, res => {
      res.resume(); res.on('end', () => resolve(res));
    });
    req.on('error', reject); req.end(payload);
  });
  try {
    const origin = 'https://moumantai-demo.onrender.com';
    assert.equal((await send('evil.example', origin)).statusCode, 403);
    assert.equal((await send('moumantai-demo.onrender.com', 'https://evil.example')).statusCode, 403);
    const login = await send('moumantai-demo.onrender.com', origin);
    assert.equal(login.statusCode, 200);
    assert.match(login.headers['set-cookie'][0], /HttpOnly; Secure; SameSite=Strict/);
    assert.equal(login.headers['strict-transport-security'], 'max-age=31536000');
  } finally { await close(gateway); }
});
