import { useRef, useState } from 'react';
import type { FormEvent } from 'react';
import type { AttachmentRecord, Channel, IngestResponse, RawMessageEnvelope } from './types';

interface ScenarioTemplate {
  name: string;
  channel: Channel;
  sender: string;
  identity: string;
  text: string;
}

const SCENARIO_TEMPLATES: ScenarioTemplate[] = [
  {
    name: 'WhatsApp: Casual SME Order (Hello boss, "tmr before 3pm")',
    channel: 'WHATSAPP',
    sender: 'Uncle Lim (Corner Burger Stall)',
    identity: '+6012-388-9123',
    text: 'Hello boss! Good morning 👋 We need 50 burgers for tmr before 3pm please. Normal delivery to Subang SS15 branch. Can send receipt on WhatsApp ya, thank you!',
  },
  {
    name: 'WhatsApp: Urgent Chatty Stock Add (Missing Date / Urgent)',
    channel: 'WHATSAPP',
    sender: 'Sarah @ Sunshine Cafe',
    identity: '+6017-889-4451',
    text: 'Hi MouManTAI team! We are running very low on beef patties tonight. Can we urgently get 30 pcs burgers sent over? Please let us know if feasible and what time driver can reach 🙏',
  },
  {
    name: 'WhatsApp: Specific Packing & Multi-box Request',
    channel: 'WHATSAPP',
    sender: 'Ah Huat Cafe',
    identity: '+6019-552-7810',
    text: 'Morning boss, placing reorder for 80 burgers. Deliver this Friday 2026-10-24 by 11am sharp. Please pack into 4 separate boxes of 20pcs each for our cold storage. Thanks ya.',
  },
  {
    name: 'Email (via WhatsApp): Formal Procurement Purchase Order (PO-2026-9042)',
    channel: 'WHATSAPP',
    sender: 'Procurement @ Sunrise Bistro Sdn. Bhd.',
    identity: 'purchasing@sunrisebistro.my',
    text: `Dear MouManTAI Sales & Fulfilment Team,\n\nPlease process our official purchase order PO-2026-9042 for next week's university catering requirement:\n- Product: BURGER (Standard Beef Patties)\n- Quantity: 150 pcs\n- Requested Delivery Date: 2026-10-28 before 10:00 AM\n- Delivery Bay: Central Kitchen Loading Dock 2, Petaling Jaya\n\nKindly confirm order acceptance and dispatch the pro-forma invoice at your earliest convenience.\n\nBest regards,\nDavid Tan\nProcurement Department, Sunrise Bistro Sdn. Bhd.`,
  },
  {
    name: 'Email (via WhatsApp): Rescheduling & Clause Clarification Request',
    channel: 'WHATSAPP',
    sender: 'Campus Cafeteria Operations',
    identity: 'ops@campusdining.edu.my',
    text: `Hi Team,\n\nRegarding PO-DEMO-2026-1042, due to unexpected campus holiday scheduling, we would like to request moving delivery from 26 October 2026 to 27 October 2026 before 3:00 PM. Quantity remains 100 pcs burgers.\n\nAs noted in the purchase order rescheduling clause, manual written confirmation is required. Please confirm if this updated delivery slot can be accommodated.\n\nThank you,\nJessica Wong\nOperations Supervisor`,
  },
  {
    name: 'Telegram (via WhatsApp): Fast Pop-up Restock ("tmr lunch")',
    channel: 'WHATSAPP',
    sender: '@burgerbro_kl',
    identity: 'tg_user_882914',
    text: 'hey guys! reordering 40 burgers for our pop-up stall tmr lunch time around 12:30pm. usual drop off at depot bay. let me know total rm thanks bro',
  },
  {
    name: 'Telegram (via WhatsApp): Short Incomplete Query (Missing Quantity & Date)',
    channel: 'WHATSAPP',
    sender: '@snack_corner_my',
    identity: 'tg_user_334102',
    text: 'yo boss need burgers for tomorrow event! what is your earliest delivery slot available?',
  },
];

export function SyntheticComposer({ tenantId, ingest, uploadAttachment, onSuccess, onCancel }: {
  tenantId: string;
  ingest: (payload: RawMessageEnvelope) => Promise<IngestResponse>;
  uploadAttachment?: (file: File) => Promise<AttachmentRecord>;
  onSuccess: (result: IngestResponse) => void;
  onCancel: () => void;
}) {
  const [channel, setChannel] = useState<Channel>('WHATSAPP');
  const [providerId, setProviderId] = useState(() => `synthetic-${crypto.randomUUID()}`);
  const [sender, setSender] = useState('Synthetic buyer');
  const [identity, setIdentity] = useState('synthetic_platform_sender');
  const [text, setText] = useState('');
  const [thread, setThread] = useState('');
  const [businessTimezone, setBusinessTimezone] = useState('Asia/Kuala_Lumpur');
  const [attachedRecord, setAttachedRecord] = useState<AttachmentRecord | null>(null);
  const [uploadingAttachment, setUploadingAttachment] = useState(false);
  const [attachmentError, setAttachmentError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [frozen, setFrozen] = useState<RawMessageEnvelope | null>(null);
  const sending = useRef(false);

  async function handleFile(file: File) {
    if (!uploadAttachment) return;
    setUploadingAttachment(true);
    setAttachmentError(null);
    try {
      const rec = await uploadAttachment(file);
      setAttachedRecord(rec);
    } catch (err) {
      setAttachmentError(err instanceof Error ? err.message : 'Upload failed');
    } finally {
      setUploadingAttachment(false);
    }
  }

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
    const payload: RawMessageEnvelope = { tenant_id: tenantId, channel, adapter_mode: 'SYNTHETIC',
      provider_message_id: providerId, sender_identity_id: identity, sender_alias: sender, text,
      received_at: timestamp, message_at: timestamp, business_timezone: businessTimezone || null,
      thread_ref: thread || null, reply_to_provider_message_id: null,
      attachments: attachedRecord ? [{
        attachment_id: attachedRecord.attachment_id,
        filename: attachedRecord.filename,
        media_type: attachedRecord.media_type,
        size_bytes: attachedRecord.size_bytes,
        evidence_ref: attachedRecord.evidence_ref,
      }] : [],
      language: null };
    setFrozen(payload);
    void send(payload);
  }

  return <section className="p1-compose-card" aria-labelledby="compose-title"><div className="p1-compose-heading"><h2 id="compose-title">New synthetic message</h2><button type="button" className="p1-secondary" disabled={pending} onClick={onCancel}>Close form</button></div>
    <p className="p1-muted">Synthetic input. Saving persists the original; Process starts extraction. Business timezone is an explicit synthetic declaration.</p>
    <form onSubmit={submit} noValidate>
      <fieldset disabled={pending || frozen !== null}><legend className="p1-sr-only">Synthetic message input</legend>
        <div style={{ marginBottom: '14px' }}>
          <label style={{ fontSize: '11px', fontWeight: 600, color: '#475569', display: 'block', marginBottom: '4px' }}>
            Quick Load Realistic Scenario Template
          </label>
          <select
            aria-label="Scenario Template Preset"
            defaultValue=""
            style={{ width: '100%', padding: '7px 10px', fontSize: '12px', borderRadius: '4px', border: '1px solid #cbd5e1', background: '#f8fafc' }}
            onChange={e => {
              const tmpl = SCENARIO_TEMPLATES.find(t => t.name === e.target.value);
              if (tmpl) {
                setChannel(tmpl.channel);
                setSender(tmpl.sender);
                setIdentity(tmpl.identity);
                setText(tmpl.text);
              }
            }}
          >
            <option value="">-- Choose a realistic multi-channel SME scenario --</option>
            {SCENARIO_TEMPLATES.map(t => (
              <option key={t.name} value={t.name}>{t.name}</option>
            ))}
          </select>
        </div>
        <div className="p1-compose-fields">
          <label>Synthetic business timezone
            <select value={businessTimezone} onChange={event => setBusinessTimezone(event.target.value)}>
              <option value="">Missing / unknown</option>
              <option value="Asia/Kuala_Lumpur">Asia/Kuala_Lumpur (declared for this synthetic message)</option>
              <option value="Asia/Singapore">Asia/Singapore</option>
              <option value="America/New_York">America/New_York</option>
            </select>
          </label>
          <label>Channel
            <select aria-label="Channel" value={channel} onChange={event => setChannel(event.target.value as Channel)}>
              <option value="WHATSAPP">WHATSAPP</option>
              <option value="EMAIL">EMAIL</option>
              <option value="TELEGRAM">TELEGRAM</option>
            </select>
          </label>
          <label>Provider message ID<input value={providerId} maxLength={200} onChange={event => setProviderId(event.target.value)} /></label>
          <label>Sender platform identity<input value={identity} maxLength={200} onChange={event => setIdentity(event.target.value)} /></label>
          <label>Sender display alias<input value={sender} maxLength={200} onChange={event => setSender(event.target.value)} /></label>
          <label>Thread reference (optional)<input value={thread} maxLength={200} onChange={event => setThread(event.target.value)} /></label>
        </div>
        <label>Original message text<textarea value={text} maxLength={20_000} rows={4} onChange={event => setText(event.target.value)} placeholder="Enter a synthetic customer request…" /></label>
        {uploadAttachment && (
          <div style={{ marginTop: '12px', padding: '10px 12px', background: '#f8fafc', border: '1px dashed #cbd5e1', borderRadius: '4px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <span style={{ fontSize: '11px', fontWeight: 600, color: '#0f172a' }}>Attach Document / PO Scan (OCR)</span>
                <span style={{ fontSize: '11px', color: '#64748b', marginLeft: '6px' }}>Optional PDF or image (.pdf, .png, .jpg)</span>
              </div>
              <label className="p1-action-btn" style={{ cursor: 'pointer', fontSize: '11px', padding: '4px 8px', margin: 0 }}>
                {uploadingAttachment ? 'Uploading…' : attachedRecord ? 'Replace file' : 'Attach file'}
                <input
                  type="file"
                  accept=".pdf,.png,.jpg,.jpeg"
                  data-testid="composer-attachment-input"
                  style={{ display: 'none' }}
                  disabled={pending || uploadingAttachment}
                  onChange={e => {
                    const f = e.target.files?.[0];
                    if (f) void handleFile(f);
                    e.target.value = '';
                  }}
                />
              </label>
            </div>
            {attachmentError && <p style={{ fontSize: '11px', color: '#ef4444', marginTop: '6px' }} role="alert">{attachmentError}</p>}
            {attachedRecord && (
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: '8px', padding: '6px 10px', background: '#fff', border: '1px solid #e2e8f0', borderRadius: '4px', fontSize: '11px' }}>
                <div>
                  <strong style={{ color: '#0f172a' }}>{attachedRecord.filename}</strong>
                  <span style={{ color: '#64748b', marginLeft: '8px' }}>{(attachedRecord.size_bytes / 1024).toFixed(1)} KB · <code>{attachedRecord.evidence_ref}</code></span>
                </div>
                <button
                  type="button"
                  onClick={() => setAttachedRecord(null)}
                  style={{ border: 'none', background: 'transparent', color: '#64748b', cursor: 'pointer', fontSize: '14px', padding: '0 4px' }}
                  aria-label="Remove attached file"
                >
                  ✕
                </button>
              </div>
            )}
          </div>
        )}
      </fieldset>
      {error && <p role="alert" className="p1-notice">{error}</p>}
      <div className="p1-compose-actions"><button type="submit" className="p1-primary" disabled={pending}>{pending ? 'Saving message…' : frozen ? 'Retry same submission' : 'Save synthetic message'}</button>
        {frozen && !pending && <button type="button" className="p1-secondary" onClick={() => { setFrozen(null); setError(null); setProviderId(`synthetic-${crypto.randomUUID()}`); }}>Start a different message</button>}
        <span className="p1-muted">Timestamps are fixed on first submit. A retry reuses the complete original submission and provider ID.</span></div>
    </form>
  </section>;
}
