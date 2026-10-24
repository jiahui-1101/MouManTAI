import { render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { AuthProvider } from '../../shared/auth';
import { C3ReviewPanel } from './C3ReviewPanel';

afterEach(() => vi.restoreAllMocks());

it('does not display another isolated session tenant under the selected organization', async () => {
  const request = vi.fn().mockResolvedValue(new Response(JSON.stringify({
    tenant_id: 'tenant_elsewhere', actor_id: 'user_owner_01',
  }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
  vi.stubGlobal('fetch', request);
  render(<AuthProvider initialTenantId="tenant_demo_01" initialActorId="user_owner_01">
    <C3ReviewPanel />
  </AuthProvider>);
  expect(await screen.findByRole('alert')).toHaveTextContent('does not match');
  expect(request).toHaveBeenCalledWith('/demo-bff/session', expect.anything());
  expect(request).toHaveBeenCalledTimes(1);
  vi.unstubAllGlobals();
});
