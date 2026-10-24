/** Local, synthetic-only Orders facade. Never included in the browser bundle. */
import { randomBytes, timingSafeEqual } from 'node:crypto';
import type { IncomingMessage, ServerResponse } from 'node:http';
import type { Plugin } from 'vite';

type Session = { csrf: string; expires: number; tenant: string; actor: string };
const sessions = new Map<string, Session>();
const lifetimeMs = 20 * 60_000;
const cookieName = 'moumantai_demo_session';
const json = (response: ServerResponse, status: number, value: unknown) => {
  response.statusCode = status;
  response.setHeader('Content-Type', 'application/json; charset=utf-8');
  response.setHeader('Cache-Control', 'no-store');
  response.setHeader('X-Content-Type-Options', 'nosniff');
  response.end(JSON.stringify(value));
};
const error = (response: ServerResponse, status: number, code: string, message: string) =>
  json(response, status, { code, message });
const exact = (left: string, right: string) => {
  const a = Buffer.from(left); const b = Buffer.from(right);
  return a.length === b.length && timingSafeEqual(a, b);
};
const cookie = (request: IncomingMessage) => {
  const header = request.headers.cookie ?? '';
  const found = header.split(';').map(item => item.trim()).find(item => item.startsWith(`${cookieName}=`));
  return found?.slice(cookieName.length + 1) ?? '';
};
const readBody = async (request: IncomingMessage): Promise<unknown> => {
  let value = '';
  for await (const chunk of request) {
    value += chunk.toString();
    if (value.length > 4096) throw new Error('BODY_TOO_LARGE');
  }
  return JSON.parse(value);
};
const upstreamPath = (method: string, path: string): string | null => {
  const id = '[A-Za-z0-9_-]{1,128}';
  const request = new RegExp(`^/demo-bff/order-requests/(${id})(?:/(feasibility|review|accept-mock|timeline|operational-status))?$`).exec(path);
  if (path === '/demo-bff/order-requests' && method === 'GET') return '/v1/backend-v2/order-requests';
  if (request) {
    const suffix = request[2] ?? '';
    if (method === 'GET' && ['', 'feasibility', 'timeline', 'operational-status'].includes(suffix))
      return `/v1/backend-v2/order-requests/${request[1]}${suffix ? `/${suffix}` : ''}`;
    if (method === 'POST' && ['review', 'accept-mock'].includes(suffix))
      return `/v1/backend-v2/order-requests/${request[1]}/${suffix}`;
  }
  const receipt = new RegExp(`^/demo-bff/reservations/(${id})$`).exec(path);
  if (method === 'GET' && receipt) return `/v1/backend-v2/mock-orbyte/reservations/${receipt[1]}`;
  const commitment = new RegExp(`^/demo-bff/commitments/(${id})/(timeline|notification-intents)$`).exec(path);
  if (method === 'GET' && commitment)
    return `/v1/orchestration/commitments/${commitment[1]}/${commitment[2]}`;
  if (method === 'GET' && path === '/demo-bff/c3-reviews') return '/v1/c3/reviews';
  if (method === 'GET' && path === '/demo-bff/c3-reviews/decided') return '/v1/c3/reviews?state=DECIDED';
  const c3Review = new RegExp(`^/demo-bff/c3-reviews/(${id})$`).exec(path);
  if (method === 'GET' && c3Review) return `/v1/c3/reviews/${c3Review[1]}`;
  return null;
};

export function demoBff(): Plugin {
  return {
    name: 'moumantai-isolated-orders-facade',
    apply: 'serve',
    configureServer(server) {
      server.middlewares.use('/demo-bff', async (request, response) => {
        const path = `/demo-bff${request.url?.split('?')[0] ?? ''}`;
        const method = request.method ?? '';
        const host = request.headers.host ?? '';
        const origin = request.headers.origin;
        const remote = request.socket.remoteAddress ?? '';
        const local = ['127.0.0.1', '::1', '::ffff:127.0.0.1'].includes(remote);
        const loopbackHost = /^(?:127\.0\.0\.1|localhost)(?::\d+)?$/.test(host);
        if (!local || !loopbackHost || (origin && origin !== `http://${host}` && origin !== `https://${host}`))
          return error(response, 403, 'ORIGIN_FORBIDDEN', 'Local same-origin access required');
        const bootstrap = process.env.MOUMANTAI_BFF_BOOTSTRAP_TOKEN ?? '';
        const key = process.env.MOUMANTAI_ISOLATED_E2E_KEY ?? '';
        const tenant = process.env.MOUMANTAI_ISOLATED_E2E_TENANT_ID ?? '';
        const actor = process.env.MOUMANTAI_ISOLATED_E2E_MANAGER_ID ?? '';
        const configured = process.env.MOUMANTAI_SYNTHETIC_MODE === '1' &&
          process.env.MOUMANTAI_ISOLATED_E2E === '1' &&
          !['production', 'prod'].includes((process.env.ENVIRONMENT ?? '').toLowerCase()) &&
          !['production', 'prod'].includes((process.env.APP_ENV ?? '').toLowerCase()) &&
          bootstrap.length >= 32 && key.length >= 32 && bootstrap !== key && !!tenant && !!actor;
        if (!configured) return error(response, 503, 'DEMO_AUTHORITY_UNAVAILABLE', 'Isolated demo session is not configured');
        const isMutation = method === 'POST' || method === 'DELETE';
        if (isMutation && !origin) return error(response, 403, 'ORIGIN_REQUIRED', 'Origin required for mutation');
        if (path === '/demo-bff/session' && method === 'POST') {
          if (!request.headers['content-type']?.startsWith('application/json'))
            return error(response, 415, 'JSON_REQUIRED', 'JSON request required');
          let body: unknown;
          try { body = await readBody(request); } catch { return error(response, 400, 'INVALID_BODY', 'Invalid session request'); }
          const token = (body as { bootstrap_token?: unknown })?.bootstrap_token;
          if (typeof token !== 'string' || !exact(token, bootstrap))
            return error(response, 401, 'BOOTSTRAP_DENIED', 'Operator bootstrap denied');
          const previous = cookie(request);
          if (previous) sessions.delete(previous);
          const sid = randomBytes(32).toString('hex');
          const session = { csrf: randomBytes(32).toString('hex'), expires: Date.now() + lifetimeMs, tenant, actor };
          sessions.set(sid, session);
          response.setHeader('Set-Cookie', `${cookieName}=${sid}; HttpOnly; SameSite=Strict; Path=/demo-bff; Max-Age=1200${origin?.startsWith('https:') ? '; Secure' : ''}`);
          return json(response, 200, { tenant_id: tenant, actor_id: actor, csrf_token: session.csrf, expires_at: new Date(session.expires).toISOString(), integration_mode: 'MOCK' });
        }
        const sid = cookie(request); const session = sessions.get(sid);
        if (!session || session.expires <= Date.now() || session.tenant !== tenant || session.actor !== actor) {
          if (sid) sessions.delete(sid);
          return error(response, 401, 'SESSION_REQUIRED', 'Valid isolated operator session required');
        }
        if (path === '/demo-bff/session' && method === 'GET')
          return json(response, 200, { tenant_id: tenant, actor_id: actor, csrf_token: session.csrf, expires_at: new Date(session.expires).toISOString(), integration_mode: 'MOCK' });
        if (path === '/demo-bff/session' && method === 'DELETE') {
          if (!exact(String(request.headers['x-csrf-token'] ?? ''), session.csrf))
            return error(response, 403, 'CSRF_DENIED', 'Session CSRF token required');
          sessions.delete(sid);
          response.setHeader('Set-Cookie', `${cookieName}=; HttpOnly; SameSite=Strict; Path=/demo-bff; Max-Age=0`);
          return json(response, 200, { revoked: true });
        }
        const target = upstreamPath(method, path);
        if (!target) return error(response, 404, 'ROUTE_NOT_ALLOWED', 'Facade route unavailable');
        if (request.headers['x-tenant-id'] || request.headers['x-actor-id'] || request.headers['x-isolated-e2e-key'])
          return error(response, 403, 'CLIENT_IDENTITY_DENIED', 'Client identity headers are not accepted');
        if (method === 'POST' && (!exact(String(request.headers['x-csrf-token'] ?? ''), session.csrf)))
          return error(response, 403, 'CSRF_DENIED', 'Session CSRF token required');
        if (method === 'POST' && !request.headers['content-type']?.startsWith('application/json'))
          return error(response, 415, 'JSON_REQUIRED', 'JSON request required');
        let body: string | undefined;
        if (method === 'POST') {
          try { body = JSON.stringify(await readBody(request)); }
          catch { return error(response, 400, 'INVALID_BODY', 'Invalid JSON command'); }
        }
        try {
          const upstreamPort = process.env.MOUMANTAI_LOCAL_API_PORT ?? '8000';
          if (!/^\d{2,5}$/.test(upstreamPort)) return error(response, 503, 'BACKEND_UNAVAILABLE', 'Invalid local backend configuration');
          const upstream = await fetch(`http://127.0.0.1:${upstreamPort}${target}`, {
            method, body,
            headers: {
              'Accept': 'application/json', 'X-Tenant-ID': tenant, 'X-Actor-ID': actor,
              'X-Isolated-E2E-Key': key,
              ...(body ? { 'Content-Type': 'application/json' } : {}),
            },
            signal: AbortSignal.timeout(15_000),
          });
          response.statusCode = upstream.status;
          response.setHeader('Content-Type', 'application/json; charset=utf-8');
          response.setHeader('Cache-Control', 'no-store');
          response.setHeader('X-Content-Type-Options', 'nosniff');
          response.end(await upstream.text());
        } catch {
          error(response, 503, 'BACKEND_UNAVAILABLE', 'Isolated backend unavailable');
        }
      });
    },
  };
}
