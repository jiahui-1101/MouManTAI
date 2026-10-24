import { useEffect, useState } from 'react';
import { useAuth } from '../../shared/auth';

interface C3Review {
  review_id: string;
  message_id: string;
  state: 'PENDING' | 'DECIDED';
  revision: number;
  created_at: string;
  reason_codes: string[];
  source: {
    channel: string;
    provider_account_id: string | null;
    provider_native_message_id: string | null;
    source_authenticity: string;
    adapter_mode: string;
  };
  candidate: {
    intent: string;
    provenance: { provider: string; version: string };
    evidence: { quote: string; source_kind: string }[];
  };
  provider_attempts: { provider: string; status: string }[];
  decision: string | null;
  decision_reason: string | null;
  reviewer_id: string | null;
  decided_at: string | null;
  decision_authority_available: boolean;
}

async function read<T>(path: string): Promise<T> {
  const response = await fetch(path, { headers: { Accept: 'application/json' } });
  if (!response.ok) {
    if (response.status === 401 || response.status === 403)
      throw new Error('Open an authorized isolated operator session to inspect C3 reviews.');
    throw new Error(`C3 reviews unavailable (${response.status}).`);
  }
  return response.json() as Promise<T>;
}

/** Durable C3 evidence stays separate from P1 context correction and order acceptance. */
export function C3ReviewPanel() {
  const { tenantId, actorId, setTenantId, setActorId } = useAuth();
  const [items, setItems] = useState<C3Review[]>([]);
  const [detail, setDetail] = useState<C3Review | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [state, setState] = useState<'PENDING' | 'DECIDED'>('PENDING');
  const [csrf, setCsrf] = useState('');
  const [reason, setReason] = useState('');
  const [correctedIntent, setCorrectedIntent] = useState('OTHER');
  const [deciding, setDeciding] = useState(false);

  const refresh = async () => {
    setLoading(true);
    setError(null);
    try {
      const session = await read<{ tenant_id: string; actor_id: string; csrf_token: string }>('/demo-bff/session');
      if (session.tenant_id !== tenantId || session.actor_id !== actorId) {
        setItems([]);
        setDetail(null);
        if (import.meta.env.VITE_DEMO_ADMIN_LOGIN === '1') {
          setTenantId(session.tenant_id);
          setActorId(session.actor_id);
          return;
        }
        throw new Error('The isolated operator session does not match the selected organization and actor.');
      }
      setCsrf(session.csrf_token);
      const page = await read<{ items: C3Review[] }>(
        state === 'PENDING' ? '/demo-bff/c3-reviews' : '/demo-bff/c3-reviews/decided');
      setItems(page.items);
      if (detail) {
        setDetail(await read<C3Review>(`/demo-bff/c3-reviews/${encodeURIComponent(detail.review_id)}`));
      }
    } catch (reason) {
      setItems([]);
      setDetail(null);
      setCsrf('');
      setError(reason instanceof Error ? reason.message : 'C3 review loading failed.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void refresh(); }, [tenantId, actorId, state]);

  const decide = async (action: 'APPROVE' | 'REJECT' | 'CORRECT') => {
    if (!detail || !csrf || !reason.trim() || deciding) return;
    if (!window.confirm(`Confirm ${action.toLowerCase()} for classification review ${detail.review_id}?`)) return;
    setDeciding(true); setError(null);
    try {
      const response = await fetch(`/demo-bff/c3-reviews/${encodeURIComponent(detail.review_id)}/decide`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
        body: JSON.stringify({ action, expected_revision: detail.revision,
          request_key: crypto.randomUUID(), reason: reason.trim(),
          corrected_intent: action === 'CORRECT' ? correctedIntent : null }),
      });
      if (!response.ok) throw new Error(`C3 decision was not recorded (${response.status}). Refresh source and review version.`);
      setReason('');
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'C3 decision failed.');
    } finally { setDeciding(false); }
  };

  return <section aria-label="C3 classification reviews" className="hr-table-card" style={{ padding: 20, marginBottom: 20 }}>
    <h2>C3 classification reviews</h2>
    <p>Durable classification candidates. Review approval is separate from order acceptance, recovery execution and provider sending.</p>
    <button type="button" onClick={() => void refresh()} disabled={loading}>Refresh C3 reviews</button>
    <button type="button" onClick={() => { setDetail(null); setState(state === 'PENDING' ? 'DECIDED' : 'PENDING'); }}>
      {state === 'PENDING' ? 'View C3 decision history' : 'View pending C3 reviews'}
    </button>
    {loading && <p role="status">Loading C3 reviews…</p>}
    {error && <p role="alert">{error}</p>}
    {!loading && !error && items.length === 0 && <p>No {state.toLowerCase()} C3 classification reviews.</p>}
    {!loading && !error && items.map(item => <button key={item.review_id} type="button"
      onClick={() => { void read<C3Review>(`/demo-bff/c3-reviews/${encodeURIComponent(item.review_id)}`)
        .then(setDetail).catch(reason => { setDetail(null); setError(String(reason)); }); }}>
      {item.source.channel} · {item.candidate.intent} · {item.reason_codes.join(', ')} · {item.source.adapter_mode}
    </button>)}
    {detail && <article aria-label="C3 review evidence">
      <h3>{detail.candidate.intent} — {detail.state}</h3>
      <p>Source: {detail.source.channel} / {detail.source.provider_account_id ?? 'No real provider account'} /
        {' '}{detail.source.provider_native_message_id ?? detail.message_id}</p>
      <p>Origin: {detail.source.adapter_mode} / {detail.source.source_authenticity}</p>
      <p>Classification: {detail.candidate.provenance.provider} ({detail.candidate.provenance.version}).
        {' '}Confidence is unavailable in this contract.</p>
      <p>Reasons: {detail.reason_codes.join(', ')}</p>
      <ul>{detail.candidate.evidence.map((evidence, index) =>
        <li key={`${evidence.source_kind}-${index}`}>{evidence.source_kind}: “{evidence.quote}”</li>)}</ul>
      <p>Provider attempts: {detail.provider_attempts.map(attempt => `${attempt.provider}: ${attempt.status}`).join(', ') || 'None'}</p>
      {detail.decision && <p>Decision: {detail.decision} by {detail.reviewer_id} at {detail.decided_at}.
        {' '}{detail.decision_reason}</p>}
      {detail.state === 'PENDING' && detail.decision_authority_available && csrf ? <div>
        <label>Decision reason<textarea value={reason} onChange={event => setReason(event.target.value)} maxLength={1000} /></label>
        <label>Corrected intent<select value={correctedIntent} onChange={event => setCorrectedIntent(event.target.value)}>
          <option value="CUSTOMER_INQUIRY">Customer inquiry</option>
          <option value="CUSTOMER_ORDER_REQUEST">Customer order request</option>
          <option value="SUPPLIER_DELAY">Supplier delay</option>
          <option value="OTHER">Other</option>
          <option value="UNKNOWN">Unknown</option>
        </select></label>
        <button type="button" disabled={deciding || !reason.trim()} onClick={() => void decide('APPROVE')}>Approve classification</button>
        <button type="button" disabled={deciding || !reason.trim()} onClick={() => void decide('REJECT')}>Reject classification</button>
        <button type="button" disabled={deciding || !reason.trim()} onClick={() => void decide('CORRECT')}>Correct classification</button>
      </div> : <p role="status">{detail.state === 'DECIDED' ? 'Classification decision recorded.' :
        'Approve, reject and correct require a trusted C3 decision authority; these actions are unavailable.'}</p>}
    </article>}
  </section>;
}
