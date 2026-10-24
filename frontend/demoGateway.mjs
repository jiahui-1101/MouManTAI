/** Temporary single-admin HTTPS gateway for the isolated hackathon demo. */
import { createServer as createHttpsServer } from 'node:https';
import { createServer as createHttpServer } from 'node:http';
import { randomBytes, scryptSync, timingSafeEqual } from 'node:crypto';
import { readFileSync, statSync } from 'node:fs';
import { resolve, sep } from 'node:path';
import { isIP } from 'node:net';
import { fileURLToPath } from 'node:url';

const root = resolve(fileURLToPath(new URL('.', import.meta.url)), 'dist');
const cookieName = 'moumantai_demo_session';
const ttlMs = 20 * 60_000;
const json = (res, status, value) => {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' });
  res.end(JSON.stringify(value));
};
const error = (res, status, code) => json(res, status, { code, message: code });
const equal = (a, b) => {
  const left = Buffer.from(a); const right = Buffer.from(b);
  return left.length === right.length && timingSafeEqual(left, right);
};
const cookie = req => (req.headers.cookie ?? '').split(';').map(x => x.trim())
  .find(x => x.startsWith(`${cookieName}=`))?.slice(cookieName.length + 1) ?? '';
const body = async req => {
  let value = '';
  for await (const chunk of req) {
    value += chunk.toString();
    if (value.length > 4096) throw new Error('BODY_TOO_LARGE');
  }
  return JSON.parse(value);
};
const hashParts = value => {
  const parts = value.split('$');
  if (parts.length !== 6 || parts[0] !== 'scrypt') throw new Error('Invalid Demo Admin hash');
  const [N, r, p] = parts.slice(1, 4).map(Number);
  if (N !== 16384 || r !== 8 || p !== 1 || !/^[a-f0-9]{32,}$/.test(parts[4]) ||
      !/^[a-f0-9]{128}$/.test(parts[5])) throw new Error('Invalid Demo Admin hash parameters');
  return { N, r, p, salt: Buffer.from(parts[4], 'hex'), digest: Buffer.from(parts[5], 'hex') };
};
const verifyPassword = (password, configured) => {
  if (typeof password !== 'string' || password.length > 1024) return false;
  const candidate = scryptSync(password, configured.salt, 64,
    { N: configured.N, r: configured.r, p: configured.p });
  return timingSafeEqual(candidate, configured.digest);
};
const id = '[A-Za-z0-9_-]{1,128}';
export const upstreamPath = (method, path) => {
  if (method === 'GET' && path === '/demo-bff/overview') return '/v1/overview';
  if (method === 'GET' && path === '/demo-bff/order-requests') return '/v1/backend-v2/order-requests';
  const request = new RegExp(`^/demo-bff/order-requests/(${id})(?:/(feasibility|review|accept-mock|timeline|operational-status))?$`).exec(path);
  if (request) {
    const suffix = request[2] ?? '';
    if (method === 'GET' && ['', 'feasibility', 'timeline', 'operational-status'].includes(suffix))
      return `/v1/backend-v2/order-requests/${request[1]}${suffix ? `/${suffix}` : ''}`;
    if (method === 'POST' && ['review', 'accept-mock'].includes(suffix))
      return `/v1/backend-v2/order-requests/${request[1]}/${suffix}`;
  }
  const reservation = new RegExp(`^/demo-bff/reservations/(${id})$`).exec(path);
  if (method === 'GET' && reservation) return `/v1/backend-v2/mock-orbyte/reservations/${reservation[1]}`;
  const commitment = new RegExp(`^/demo-bff/commitments/(${id})/(timeline|notification-intents)$`).exec(path);
  if (method === 'GET' && commitment) return `/v1/orchestration/commitments/${commitment[1]}/${commitment[2]}`;
  if (method === 'GET' && path === '/demo-bff/c3-reviews') return '/v1/c3/reviews';
  if (method === 'GET' && path === '/demo-bff/c3-reviews/decided') return '/v1/c3/reviews?state=DECIDED';
  const review = new RegExp(`^/demo-bff/c3-reviews/(${id})$`).exec(path);
  if (method === 'GET' && review) return `/v1/c3/reviews/${review[1]}`;
  const decision = new RegExp(`^/demo-bff/c3-reviews/(${id})/decide$`).exec(path);
  if (method === 'POST' && decision) return `/v1/c3/reviews/${decision[1]}/decide`;
  return null;
};

const mime = pathname => pathname.endsWith('.js') ? 'text/javascript; charset=utf-8'
  : pathname.endsWith('.css') ? 'text/css; charset=utf-8'
  : pathname.endsWith('.svg') ? 'image/svg+xml'
  : pathname.endsWith('.png') ? 'image/png'
  : pathname.endsWith('.ico') ? 'image/x-icon'
  : 'text/html; charset=utf-8';

export function createDemoGateway(env = process.env) {
  const sessions = new Map();
  const attempts = new Map();
  if (env.ENVIRONMENT !== 'staging' || env.APP_ENV !== 'synthetic' ||
      env.MOUMANTAI_SYNTHETIC_MODE !== '1' || env.MOUMANTAI_ISOLATED_E2E !== '1' ||
      env.MOUMANTAI_DEMO_ADMIN_AUTH !== '1') throw new Error('Isolated staging mode required');
  const username = env.MOUMANTAI_DEMO_ADMIN_USERNAME ?? '';
  const manager = env.MOUMANTAI_ISOLATED_E2E_MANAGER_ID ?? '';
  const tenant = env.MOUMANTAI_ISOLATED_E2E_TENANT_ID ?? '';
  const key = env.MOUMANTAI_ISOLATED_E2E_KEY ?? '';
  const renderFree = env.MOUMANTAI_DEMO_HOSTING === 'render-free';
  const render = renderFree || env.MOUMANTAI_DEMO_HOSTING === 'render';
  if (render && (env.RENDER_SERVICE_TYPE !== 'web' ||
      (!renderFree && !/^[a-z0-9-]+$/.test(env.MOUMANTAI_DEMO_PRIVATE_API_HOST ?? '')) ||
      !/^[a-z0-9-]+\.onrender\.com$/.test(env.RENDER_EXTERNAL_HOSTNAME ?? '')))
    throw new Error('Unsafe Render gateway configuration');
  const origin = render ? `https://${env.RENDER_EXTERNAL_HOSTNAME}` : env.MOUMANTAI_DEMO_ORIGIN ?? '';
  const api = new URL(render
    ? renderFree ? 'http://127.0.0.1:8000' : `http://${env.MOUMANTAI_DEMO_PRIVATE_API_HOST}:8000`
    : env.MOUMANTAI_DEMO_PRIVATE_API ?? 'http://127.0.0.1:8000');
  if (!username || !manager || !tenant || key.length < 32 ||
      !/^https:\/\/[^/]+$/.test(origin) ||
      api.protocol !== 'http:' || !(render || ['127.0.0.1', 'localhost', 'api'].includes(api.hostname)) ||
      api.pathname !== '/' || api.search || api.hash || api.username || api.password ||
      env.TELEGRAM_OUTBOUND_ENABLED !== 'false' || env.WHATSAPP_OUTBOUND_ENABLED !== 'false' ||
      env.RESEND_OUTBOUND_ENABLED !== 'false') throw new Error('Unsafe Demo Admin configuration');
  const configured = hashParts(env.MOUMANTAI_DEMO_ADMIN_PASSWORD_HASH ?? '');
  const tls = render ? null : { key: readFileSync(env.MOUMANTAI_DEMO_TLS_KEY),
    cert: readFileSync(env.MOUMANTAI_DEMO_TLS_CERT) };

  return (render ? createHttpServer : createHttpsServer)(...(render ? [] : [tls]), async (req, res) => {
    res.setHeader('Strict-Transport-Security', 'max-age=31536000');
    res.setHeader('Referrer-Policy', 'strict-origin-when-cross-origin');
    const path = (req.url ?? '').split('?')[0];
    const method = req.method ?? '';
    const suppliedOrigin = req.headers.origin;
    if (req.headers.host !== new URL(origin).host ||
        (suppliedOrigin && suppliedOrigin !== origin)) return error(res, 403, 'ORIGIN_FORBIDDEN');
    if (!path.startsWith('/demo-bff/')) {
      if (path.startsWith('/v1/') || path.startsWith('/internal/') || method !== 'GET')
        return error(res, 404, 'ROUTE_NOT_ALLOWED');
      let decoded;
      try { decoded = decodeURIComponent(path === '/' ? '/index.html' : path); }
      catch { return error(res, 400, 'INVALID_PATH'); }
      let file = resolve(root, `.${decoded}`);
      if (!file.startsWith(root + sep) || !statSafe(file)?.isFile()) file = resolve(root, 'index.html');
      try {
        res.writeHead(200, { 'Content-Type': mime(file), 'X-Content-Type-Options': 'nosniff',
          'Cache-Control': file.endsWith('index.html') ? 'no-store' : 'public, max-age=3600' });
        return res.end(readFileSync(file));
      } catch { return error(res, 404, 'FILE_NOT_FOUND'); }
    }
    const mutation = method === 'POST' || method === 'DELETE';
    if (mutation && suppliedOrigin !== origin) return error(res, 403, 'ORIGIN_REQUIRED');
    if (path === '/demo-bff/session' && method === 'POST') {
      if (!req.headers['content-type']?.startsWith('application/json')) return error(res, 415, 'JSON_REQUIRED');
      const forwarded = String(req.headers['cf-connecting-ip'] ?? '');
      const ip = render && isIP(forwarded) ? forwarded : req.socket.remoteAddress ?? 'unknown';
      const window = attempts.get(ip) ?? { count: 0, until: Date.now() + 15 * 60_000 };
      if (Date.now() > window.until) { window.count = 0; window.until = Date.now() + 15 * 60_000; }
      if (window.count >= 5) return error(res, 429, 'LOGIN_RATE_LIMITED');
      let value;
      try { value = await body(req); } catch { return error(res, 400, 'INVALID_BODY'); }
      const passwordValid = verifyPassword(value?.password, configured);
      const valid = typeof value?.username === 'string' && equal(value.username, username)
        && passwordValid;
      if (!valid) {
        window.count += 1; attempts.set(ip, window);
        return error(res, 401, 'LOGIN_DENIED');
      }
      attempts.delete(ip);
      const previous = cookie(req);
      if (previous) sessions.delete(previous);
      const sid = randomBytes(32).toString('hex');
      const session = { tenant, actor: manager, csrf: randomBytes(32).toString('hex'),
        expires: Date.now() + ttlMs };
      sessions.set(sid, session);
      res.setHeader('Set-Cookie', `${cookieName}=${sid}; HttpOnly; Secure; SameSite=Strict; Path=/demo-bff; Max-Age=1200`);
      return json(res, 200, { tenant_id: tenant, actor_id: manager, csrf_token: session.csrf,
        expires_at: new Date(session.expires).toISOString(), integration_mode: 'MOCK' });
    }
    const sid = cookie(req); const session = sessions.get(sid);
    if (!session || session.expires <= Date.now() || session.tenant !== tenant || session.actor !== manager) {
      if (sid) sessions.delete(sid);
      return error(res, 401, 'SESSION_REQUIRED');
    }
    if (path === '/demo-bff/session' && method === 'GET')
      return json(res, 200, { tenant_id: tenant, actor_id: manager, csrf_token: session.csrf,
        expires_at: new Date(session.expires).toISOString(), integration_mode: 'MOCK' });
    if (mutation && !equal(String(req.headers['x-csrf-token'] ?? ''), session.csrf))
      return error(res, 403, 'CSRF_DENIED');
    if (path === '/demo-bff/session' && method === 'DELETE') {
      sessions.delete(sid);
      res.setHeader('Set-Cookie', `${cookieName}=; HttpOnly; Secure; SameSite=Strict; Path=/demo-bff; Max-Age=0`);
      return json(res, 200, { revoked: true });
    }
    if (['x-tenant-id', 'x-actor-id', 'x-actor-role', 'x-isolated-e2e-key'].some(h => req.headers[h]))
      return error(res, 403, 'CLIENT_IDENTITY_DENIED');
    const target = upstreamPath(method, path);
    if (!target) return error(res, 404, 'ROUTE_NOT_ALLOWED');
    let payload;
    if (method === 'POST') {
      if (!req.headers['content-type']?.startsWith('application/json')) return error(res, 415, 'JSON_REQUIRED');
      try { payload = JSON.stringify(await body(req)); } catch { return error(res, 400, 'INVALID_BODY'); }
    }
    try {
      const response = await fetch(`${api.origin}${target}`, { method, body: payload,
        headers: { Accept: 'application/json', 'Content-Type': 'application/json',
          'X-Tenant-ID': tenant, 'X-Actor-ID': manager, 'X-Isolated-E2E-Key': key },
        signal: AbortSignal.timeout(15_000) });
      res.writeHead(response.status, { 'Content-Type': 'application/json; charset=utf-8',
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' });
      res.end(await response.text());
    } catch { error(res, 503, 'BACKEND_UNAVAILABLE'); }
  });
}

function statSafe(path) { try { return statSync(path); } catch { return null; } }

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const server = createDemoGateway();
  const host = process.env.MOUMANTAI_DEMO_LISTEN_HOST ?? '0.0.0.0';
  const port = Number(process.env.PORT ?? process.env.MOUMANTAI_DEMO_LISTEN_PORT ?? '8443');
  server.listen(port, host, () => console.log(`Demo Admin gateway listening on ${host}:${port}`));
}
