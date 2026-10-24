import { useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError } from './api';
import { useAuth } from './auth';
import { closeDemoSession, getDemoSession, openDemoAdminSession } from '../features/orders/orderRequestApi';
import './demoAdminGate.css';

const sessionKey = ['demo-bff-session'] as const;

function loginError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return 'Incorrect username or password. Please try again.';
    if (error.status === 429) return 'Too many login attempts. Please wait before trying again.';
    if (error.status === 403) return 'This page could not authorize sign-in. Reload the official HTTPS demo URL.';
  }
  return 'Demo sign-in is unavailable right now. Please retry shortly.';
}

function RequiredDemoAdminSession({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const { tenantId, actorId, setTenantId, setActorId } = useAuth();
  const session = useQuery({ queryKey: sessionKey, queryFn: getDemoSession, retry: false, refetchOnMount: 'always' });
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState('');

  useEffect(() => {
    const expired = () => {
      queryClient.setQueryData(sessionKey, null);
      queryClient.removeQueries({ queryKey: ['overview'] });
      queryClient.removeQueries({ queryKey: ['demo-bff'] });
      setFailure('Your session expired. Sign in again to continue.');
    };
    window.addEventListener('moumantai:demo-session-expired', expired);
    return () => window.removeEventListener('moumantai:demo-session-expired', expired);
  }, [queryClient]);

  useEffect(() => {
    if (!session.data) return;
    const delay = Date.parse(session.data.expires_at) - Date.now();
    if (delay <= 0) {
      window.dispatchEvent(new Event('moumantai:demo-session-expired'));
      return;
    }
    const timer = window.setTimeout(() => window.dispatchEvent(new Event('moumantai:demo-session-expired')), delay);
    return () => window.clearTimeout(timer);
  }, [session.data]);

  useEffect(() => {
    if (session.data) {
      if (session.data.tenant_id !== tenantId) setTenantId(session.data.tenant_id);
      if (session.data.actor_id !== actorId) setActorId(session.data.actor_id);
    }
  }, [session.data, tenantId, actorId, setTenantId, setActorId]);

  const signIn = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true); setFailure('');
    try {
      const value = await openDemoAdminSession(username, password);
      setPassword('');
      queryClient.setQueryData(sessionKey, value);
    } catch (error) {
      setFailure(loginError(error));
    } finally { setBusy(false); }
  };

  const signOut = async () => {
    if (!session.data) return;
    setBusy(true); setFailure('');
    try {
      await closeDemoSession(session.data);
      queryClient.setQueryData(sessionKey, null);
      queryClient.removeQueries({ queryKey: ['overview'] });
      queryClient.removeQueries({ queryKey: ['demo-bff'] });
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        window.dispatchEvent(new Event('moumantai:demo-session-expired'));
      } else {
        setFailure('Could not revoke this session. Please retry logout.');
      }
    } finally { setBusy(false); }
  };

  if (session.isPending) return <main className="demo-admin-login" role="status">Checking secure demo session…</main>;
  if (!session.data) return <main className="demo-admin-login">
    <section className="demo-admin-login-card" aria-labelledby="demo-admin-title">
      <p className="demo-admin-eyebrow">MouManTAI · Synthetic Staging</p>
      <h1 id="demo-admin-title">Demo Admin sign in</h1>
      <p>Sign in to view the Dashboard, Orders, and Human Review. This temporary demo uses synthetic data only.</p>
      <form onSubmit={signIn}>
        <label>Username<input required autoComplete="username" value={username}
          onChange={event => setUsername(event.target.value)} /></label>
        <label>Password<input required type="password" autoComplete="current-password" value={password}
          onChange={event => setPassword(event.target.value)} /></label>
        <button type="submit" disabled={busy}>{busy ? 'Signing in…' : 'Sign in to demo'}</button>
      </form>
      {failure && <p role="alert" className="demo-admin-error">{failure}</p>}
      {session.error && !(session.error instanceof ApiError && session.error.status === 401) &&
        <p role="alert" className="demo-admin-error">The session check failed. Retry when the service is available.</p>}
      <button type="button" className="demo-admin-retry" onClick={() => void session.refetch()}>Retry session check</button>
    </section>
  </main>;
  if (session.data.tenant_id !== tenantId || session.data.actor_id !== actorId)
    return <main className="demo-admin-login" role="status">Opening authorized dashboard…</main>;
  return <>
    <div className="demo-admin-session-bar"><span>Secure synthetic demo · {session.data.tenant_id}</span>
      {failure && <span role="alert">{failure}</span>}
      <button type="button" disabled={busy} onClick={() => void signOut()}>Log out</button>
    </div>
    {children}
  </>;
}

export function DemoAdminGate({ children }: { children: ReactNode }) {
  return import.meta.env.VITE_DEMO_ADMIN_LOGIN === '1'
    ? <RequiredDemoAdminSession>{children}</RequiredDemoAdminSession> : <>{children}</>;
}
