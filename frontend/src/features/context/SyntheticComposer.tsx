import { useRef, useState } from 'react';
import type { FormEvent } from 'react';
import type { IngestResponse, RawMessageEnvelope } from './types';

export function SyntheticComposer({ tenantId, ingest, onSuccess, onCancel }: {
  tenantId: string;
  ingest: (payload: RawMessageEnvelope) => Promise<IngestResponse>;
  onSuccess: (result: IngestResponse) => void;
  onCancel: () => void;
}) {
  const [providerId, setProviderId] = useState(() => `synthetic-${crypto.randomUUID()}`);
  const [sender, setSender] = useState('Synthetic buyer');
  const [identity, setIdentity] = useState('synthetic_platform_sender');
  const [text, setText] = useState('');
  const [thread, setThread] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [frozen, setFrozen] = useState<RawMessageEnvelope | null>(null);
  const sending = useRef(false);

  async function send(payload: RawMessageEnvelope) {
    if (sending.current) return;
    sending.current = true;
    setPending(true);
    setError(null);
    try { onSuccess(await ingest(payload)); }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'Submission failed. Retry the same message.'); }
    finally { sending.current = false; setPending(false); }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (frozen) { void send(frozen); return; }
    if (!providerId.trim() || !identity.trim() || !sender.trim() || !text.trim()) {
      setError('Provider ID, sender identity, display alias and original text are required.');
      return;
    }
    if (providerId.length > 200 || identity.length > 200 || sender.length > 200 || text.length > 20_000 || thread.length > 200) {
      setError('Text must be at most 20,000 characters; identifiers and aliases at most 200.');
      return;
    }
    const timestamp = new Date().toISOString();
    const payload: RawMessageEnvelope = { tenant_id: tenantId, channel: 'WHATSAPP', adapter_mode: 'SYNTHETIC',
      provider_message_id: providerId, sender_identity_id: identity, sender_alias: sender, text,
      received_at: timestamp, message_at: timestamp, business_timezone: 'Asia/Kuala_Lumpur',
      thread_ref: thread || null, reply_to_provider_message_id: null, attachments: [], language: null };
    setFrozen(payload);
    void send(payload);
  }

  return <section className="p1-compose-card" aria-labelledby="compose-title"><div className="p1-compose-heading"><h2 id="compose-title">New synthetic message</h2><button type="button" className="p1-secondary" disabled={pending} onClick={onCancel}>Close form</button></div>
    <p className="p1-muted">Synthetic WhatsApp-shaped adapter only · no live provider. Extraction starts in a later task.</p>
    <form onSubmit={submit} noValidate>
      <fieldset disabled={pending || frozen !== null}><legend className="p1-sr-only">Synthetic message input</legend>
        <div className="p1-compose-fields"><label>Provider message ID<input value={providerId} maxLength={200} onChange={event => setProviderId(event.target.value)} /></label>
        <label>Sender platform identity<input value={identity} maxLength={200} onChange={event => setIdentity(event.target.value)} /></label>
        <label>Sender display alias<input value={sender} maxLength={200} onChange={event => setSender(event.target.value)} /></label>
        <label>Thread reference (optional)<input value={thread} maxLength={200} onChange={event => setThread(event.target.value)} /></label></div>
        <label>Original message text<textarea value={text} maxLength={20_000} rows={4} onChange={event => setText(event.target.value)} placeholder="Enter a synthetic customer request…" /></label>
      </fieldset>
      {error && <p role="alert" className="p1-notice">{error}</p>}
      <div className="p1-compose-actions"><button type="submit" className="p1-primary" disabled={pending}>{pending ? 'Saving message…' : frozen ? 'Retry same submission' : 'Save synthetic message'}</button>
        {frozen && !pending && <button type="button" className="p1-secondary" onClick={() => { setFrozen(null); setError(null); setProviderId(`synthetic-${crypto.randomUUID()}`); }}>Start a different message</button>}
        <span className="p1-muted">Timestamps are fixed on first submit. A retry reuses the complete original submission and provider ID.</span></div>
    </form>
  </section>;
}
