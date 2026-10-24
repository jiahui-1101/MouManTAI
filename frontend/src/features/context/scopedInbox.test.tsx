import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AuthProvider, useAuth } from '../../shared/auth';
import { DurableInbox } from './DurableInbox';

function IdentityControls() {
  const auth = useAuth();
  return <><button onClick={() => auth.setTenantId('tenant_b')}>Switch tenant</button><button onClick={() => auth.setActorId('user_staff_01')}>Switch actor</button></>;
}

describe('Inbox shared identity lifecycle', () => {
  afterEach(() => { vi.unstubAllGlobals(); window.history.replaceState({}, '', '/'); });

  it('reloads tenant-scoped reads and discards a late previous identity response', async () => {
    let resolveOld!: (value: Response) => void;
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      const headers = new Headers(init?.headers);
      const tenant = headers.get('X-Tenant-ID');
      if (url.startsWith('/v1/messages?') && tenant === 'tenant_a') return new Promise<Response>(resolve => { resolveOld = resolve; });
      return Promise.resolve(new Response(JSON.stringify(url === '/dev/p1/config'
        ? { tenant_id: tenant, mode: 'LOCAL_SYNTHETIC_ONLY', implemented_channel: 'WHATSAPP', authentication: 'NOT_IMPLEMENTED' }
        : { items: [], total: 0, limit: 25, offset: 0 })));
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<AuthProvider initialTenantId="tenant_a"><IdentityControls /><DurableInbox /></AuthProvider>);
    await waitFor(() => expect(resolveOld).toBeTypeOf('function'));
    fireEvent.click(screen.getByRole('button', { name: 'Switch tenant' }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => url.startsWith('/v1/messages?') && new Headers(init?.headers).get('X-Tenant-ID') === 'tenant_b')).toBe(true));
    await act(async () => resolveOld(new Response(JSON.stringify({ items: [], total: 99, limit: 25, offset: 0 }))));
    expect(screen.queryByText(/99 messages/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Switch actor' }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => url.startsWith('/v1/messages?') && new Headers(init?.headers).get('X-Actor-ID') === 'user_staff_01' && new Headers(init?.headers).get('X-Tenant-ID') === 'tenant_b')).toBe(true));
    expect(fetchMock.mock.calls.every(([, init]) => !init?.method || init.method === 'GET')).toBe(true);
  });
});
