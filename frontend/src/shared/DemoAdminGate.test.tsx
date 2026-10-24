import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthProvider } from './auth';
import { DemoAdminGate } from './DemoAdminGate';
import { apiRequest } from './api';

function ProtectedOverview() {
  const query = useQuery({ queryKey: ['overview'], queryFn: () => apiRequest<{ count: number }>('/demo-bff/overview') });
  return <div>{query.data ? `Authorized overview: ${query.data.count}` : 'Loading overview'}</div>;
}

const ok = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });

describe('public Demo Admin first load', () => {
  beforeEach(() => vi.stubEnv('VITE_DEMO_ADMIN_LOGIN', '1'));
  afterEach(() => { cleanup(); vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

  it('blocks protected reads, rejects bad login, loads after login, and revokes on logout', async () => {
    let authorized = false;
    const paths: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), 'http://localhost').pathname;
      paths.push(`${init?.method ?? 'GET'} ${path}`);
      if (path === '/demo-bff/session' && init?.method === 'POST') {
        const body = JSON.parse(String(init.body)) as { password: string };
        if (body.password !== 'correct-password') return ok({ code: 'LOGIN_DENIED' }, 401);
        authorized = true;
        return ok({ tenant_id: 'tenant_demo_01', actor_id: 'user_owner_01', csrf_token: 'csrf',
          expires_at: new Date(Date.now() + 600_000).toISOString(), integration_mode: 'MOCK' });
      }
      if (path === '/demo-bff/session' && init?.method === 'DELETE') {
        authorized = false;
        return ok({ revoked: true });
      }
      if (path === '/demo-bff/session') return authorized ? ok({ tenant_id: 'tenant_demo_01',
        actor_id: 'user_owner_01', csrf_token: 'csrf',
        expires_at: new Date(Date.now() + 600_000).toISOString(), integration_mode: 'MOCK' })
        : ok({ code: 'SESSION_REQUIRED' }, 401);
      if (path === '/demo-bff/overview') return authorized ? ok({ count: 2 }) : ok({ code: 'SESSION_REQUIRED' }, 401);
      throw new Error(`Unexpected request: ${path}`);
    }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><AuthProvider><DemoAdminGate>
      <ProtectedOverview />
    </DemoAdminGate></AuthProvider></QueryClientProvider>);

    expect(await screen.findByRole('heading', { name: 'Demo Admin sign in' })).toBeInTheDocument();
    expect(screen.queryByText(/Authorized overview/)).not.toBeInTheDocument();
    expect(paths).not.toContain('GET /demo-bff/overview');
    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'moumantai' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'bad-password' } });
    fireEvent.click(screen.getByRole('button', { name: 'Sign in to demo' }));
    expect(await screen.findByText('Incorrect username or password. Please try again.')).toBeInTheDocument();
    expect(paths).not.toContain('GET /demo-bff/overview');

    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'correct-password' } });
    fireEvent.click(screen.getByRole('button', { name: 'Sign in to demo' }));
    expect(await screen.findByText('Authorized overview: 2')).toBeInTheDocument();
    window.dispatchEvent(new Event('moumantai:demo-session-expired'));
    expect(await screen.findByText('Your session expired. Sign in again to continue.')).toBeInTheDocument();
    expect(screen.queryByText('Authorized overview: 2')).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'correct-password' } });
    fireEvent.click(screen.getByRole('button', { name: 'Sign in to demo' }));
    expect(await screen.findByText('Authorized overview: 2')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Log out' }));
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Demo Admin sign in' })).toBeInTheDocument());
    expect(paths).toContain('DELETE /demo-bff/session');
  });
});
