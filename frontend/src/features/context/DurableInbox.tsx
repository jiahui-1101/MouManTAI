import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { PreviewError } from './api';
import { operationalApi } from './operationalApi';
import type { OperationalApi } from './operationalApi';
import { SyntheticComposer } from './SyntheticComposer';
import type {
  DevelopmentContext,
  ExtractedField,
  ExtractionAttemptRecord,
  IngestResponse,
  MessagePage,
  StoredMessage,
} from './types';
import './inbox.css';

type Resource = { state: 'loading' } | { state: 'error'; error: Error } | { state: 'ready'; page: MessagePage; context: DevelopmentContext };
const formatTime = (value?: string | null) => value ? new Intl.DateTimeFormat('en-MY', { timeZone: 'Asia/Kuala_Lumpur', dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) : 'Not supplied';

function renderHighlightedText(text: string, fields: ExtractedField[]): ReactNode {
  const spans: { start: number; end: number; quote: string; name: string }[] = [];
  for (const f of fields) {
    for (const ev of f.evidence || []) {
      if (typeof ev.start === 'number' && typeof ev.end === 'number' && ev.start < ev.end) {
        spans.push({ start: ev.start, end: ev.end, quote: ev.quote, name: f.field_name });
      }
    }
  }
  if (!spans.length) {
    return text;
  }
  spans.sort((a, b) => a.start - b.start);

  const codePoints = Array.from(text);
  const elements: ReactNode[] = [];
  let current = 0;

  for (let i = 0; i < spans.length; i++) {
    const span = spans[i];
    if (span.start < current) continue;
    if (span.start > current) {
      elements.push(codePoints.slice(current, span.start).join(''));
    }
    elements.push(
      <mark key={`span-${i}`} className="p1-span-highlight" title={`${span.name}: "${span.quote}"`}>
        {codePoints.slice(span.start, span.end).join('')}
      </mark>
    );
    current = span.end;
  }
  if (current < codePoints.length) {
    elements.push(codePoints.slice(current).join(''));
  }
  return elements;
}

export function DurableInbox({ api = operationalApi }: { api?: OperationalApi }) {
  const [resource, setResource] = useState<Resource>({ state: 'loading' });
  const [tenantId, setTenantId] = useState<string | null>(null);
  const [channel, setChannel] = useState('ALL');
  const [processing, setProcessing] = useState('ALL');
  const [search, setSearch] = useState('');
  const [offset, setOffset] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const [composing, setComposing] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [saved, setSaved] = useState<IngestResponse | null>(null);
  const [processingId, setProcessingId] = useState<string | null>(null);
  const returnFocus = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    let active = true;
    setResource({ state: 'loading' });
    Promise.all([api.list({ channel, processing, search, offset }), api.config()]).then(([page, context]) => {
      if (active) { setTenantId(context.tenant_id); setResource({ state: 'ready', page, context }); }
    }).catch(error => { if (active) setResource({ state: 'error', error: error instanceof Error ? error : new Error('Inbox unavailable') }); });
    return () => { active = false; };
  }, [api, channel, processing, search, offset, attempt]);

  function select(id: string, button: HTMLButtonElement) { returnFocus.current = button; setSelected(id); }
  function closeDetail() { setSelected(null); returnFocus.current?.focus(); }
  function submitted(result: IngestResponse) {
    setSaved(result); setComposing(false); setOffset(0); setSearch(''); setChannel('ALL'); setProcessing('ALL'); setAttempt(n => n + 1);
  }

  async function handleInlineProcess(messageId: string, isReprocess: boolean) {
    setProcessingId(messageId);
    try {
      await api.process(messageId, isReprocess);
      setAttempt(n => n + 1);
    } catch {
      // Refresh on error to reflect any status change
      setAttempt(n => n + 1);
    } finally {
      setProcessingId(null);
    }
  }

  return <div className="p1-inbox">
    <header className="p1-page-heading"><div><h1>Message Inbox</h1><p>Receive synthetic messages and inspect their original content.</p></div><button type="button" className="p1-primary" disabled={resource.state !== 'ready' || composing} onClick={() => { setSaved(null); setComposing(true); }}>+ New synthetic message</button></header>
    <div className="p1-tabs"><span className="p1-active-label">Persisted messages</span><a href="/inbox/fixtures">Fixture preview ↗</a><span className="p1-demo-label">Local PostgreSQL · synthetic channel only</span></div>
    {saved && <p role="status" className="p1-success">{saved.duplicate ? 'Duplicate delivery — original message retrieved.' : 'Message saved.'} ID: {saved.message.message_id}. Awaiting processing; extraction has not run.</p>}
    {composing && tenantId && <SyntheticComposer tenantId={tenantId} ingest={payload => api.ingest(payload)} onSuccess={submitted} onCancel={() => setComposing(false)} />}
    <section className="p1-filter-card" aria-label="Inbox filters"><div className="p1-filter-fields p1-durable-filters">
      <label className="p1-search"><span>Search messages</span><input type="search" maxLength={200} value={search} placeholder="Search original text, sender or provider ID" onChange={event => { setSearch(event.target.value); setOffset(0); }} /></label>
      <label><span>Channel</span><select value={channel} onChange={event => { setChannel(event.target.value); setOffset(0); }}><option value="ALL">All channels</option>{['WHATSAPP', 'EMAIL', 'TELEGRAM', 'UNKNOWN'].map(value => <option key={value}>{value}</option>)}</select></label>
      <label><span>Processing</span><select value={processing} onChange={event => { setProcessing(event.target.value); setOffset(0); }}><option value="ALL">All processing states</option>{['RECEIVED', 'PROCESSING', 'PROCESSED', 'PROCESSING_FAILED'].map(value => <option key={value}>{value}</option>)}</select></label>
      <button type="button" className="p1-secondary" onClick={() => { setSearch(''); setChannel('ALL'); setProcessing('ALL'); setOffset(0); }}>× Clear</button>
      <button type="button" className="p1-secondary" onClick={() => setAttempt(n => n + 1)}>↻ Refresh</button>
    </div><div className="p1-filter-caption"><span>{resource.state === 'ready' ? `${resource.page.total} persisted messages` : 'PostgreSQL Inbox'}</span><span>Display timezone · Asia/Kuala_Lumpur</span></div></section>
    {resource.state === 'loading' && <p role="status" className="p1-state">Loading persisted messages…</p>}
    {resource.state === 'error' && <div role="alert" className="p1-state"><h2>{resource.error instanceof PreviewError && [401, 403].includes(resource.error.status) ? 'Access denied' : 'Inbox unavailable'}</h2><p>{resource.error.message}</p><button type="button" className="p1-secondary" onClick={() => setAttempt(n => n + 1)}>Retry Inbox</button></div>}
    {resource.state === 'ready' && <section className="p1-table-card" aria-label="Persisted messages"><div className="p1-table-scroll" role="region" aria-label="Persisted message table, scroll horizontally on small screens" tabIndex={0}>
      <table><caption className="p1-sr-only">Persisted original messages awaiting downstream work</caption><thead><tr><th scope="col">Received at</th><th scope="col">Original message</th><th scope="col">Source</th><th scope="col">Processing</th><th scope="col">Information</th><th scope="col">Identity</th><th scope="col">Review</th><th scope="col">Action</th></tr></thead>
      <tbody>{resource.page.items.map(message => <tr key={message.message_id}><td className="p1-date"><time dateTime={message.ingested_at}>{formatTime(message.ingested_at)}</time></td><td className="p1-message-cell"><button type="button" className="p1-title-button" onClick={event => select(message.message_id, event.currentTarget)}>{message.raw.sender_alias}</button><span className="p1-row-secondary">{message.raw.text}</span><span className="p1-row-secondary">{message.raw.provider_message_id}</span></td><td><span className="p1-badge p1-blue">SYNTHETIC</span><span className="p1-row-secondary">{message.raw.channel}</span></td><td><span className="p1-badge p1-neutral">{message.processing_status}</span></td><td className="p1-identity">{message.processing_status === 'PROCESSED' ? <span className="p1-badge p1-ready">Extracted (RULE)</span> : message.processing_status === 'PROCESSING' ? <span className="p1-badge p1-attention">Extracting…</span> : message.processing_status === 'PROCESSING_FAILED' ? <span className="p1-badge p1-attention">Extraction failed</span> : 'Not extracted'}</td><td className="p1-identity">Not associated</td><td className="p1-identity">Not started</td><td><button type="button" className="p1-action-btn" disabled={processingId === message.message_id} onClick={() => handleInlineProcess(message.message_id, message.processing_status === 'PROCESSED')}>{processingId === message.message_id ? '…' : message.processing_status === 'PROCESSED' ? 'Reprocess' : 'Process'}</button><button type="button" className="p1-icon-button" aria-label={`View message ${message.raw.provider_message_id}`} onClick={event => select(message.message_id, event.currentTarget)}>↗</button></td></tr>)}</tbody></table>
    </div>{resource.page.items.length === 0 && <p role="status" className="p1-empty">No persisted messages match this view. Submit a synthetic message to begin.</p>}
      <footer className="p1-table-footer"><span>Showing {resource.page.items.length ? offset + 1 : 0}–{offset + resource.page.items.length} of {resource.page.total}</span><div className="p1-pagination"><button type="button" className="p1-secondary" disabled={offset === 0} onClick={() => setOffset(n => Math.max(0, n - 25))}>Previous</button><button type="button" className="p1-secondary" disabled={offset + 25 >= resource.page.total || offset + 25 > 10_000} onClick={() => setOffset(n => n + 25)}>Next</button></div></footer>
    </section>}
    <p className="p1-preview-note">Local development tenant only · no production authentication. Only the synthetic WhatsApp-shaped adapter is implemented. Deterministic extraction is persisted with exact Unicode evidence spans.</p>
    {selected && <StoredMessageDetail id={selected} api={api} onUpdated={() => setAttempt(n => n + 1)} onClose={closeDetail} />}
  </div>;
}

function StoredMessageDetail({ id, api, onUpdated, onClose }: { id: string; api: OperationalApi; onUpdated?: () => void; onClose: () => void }) {
  const [data, setData] = useState<StoredMessage | null>(null);
  const [extraction, setExtraction] = useState<ExtractionAttemptRecord | null>(null);
  const [attempts, setAttempts] = useState<ExtractionAttemptRecord[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [processing, setProcessing] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const panel = useRef<HTMLElement>(null);
  useEffect(() => { panel.current?.focus(); }, []);

  useEffect(() => {
    let active = true;
    setData(null); setExtraction(null); setAttempts([]); setError(null);
    api.detail(id).then(message => {
      if (active) {
        setData(message);
        // Attempt to fetch extraction and attempt history
        api.getExtraction(id).then(ext => { if (active) setExtraction(ext); }).catch(() => { /* Not yet extracted */ });
        api.listAttempts(id).then(hist => { if (active) setAttempts(hist.items); }).catch(() => { /* Not yet extracted */ });
      }
    }).catch(failure => { if (active) setError(failure instanceof Error ? failure.message : 'Message unavailable'); });
    return () => { active = false; };
  }, [id, api, attempt]);

  async function handleProcess(reprocess: boolean) {
    setProcessing(true);
    try {
      const res = await api.process(id, reprocess);
      setData(res.message);
      setExtraction(res.attempt);
      const hist = await api.listAttempts(id).catch(() => ({ items: [res.attempt] }));
      setAttempts(hist.items);
      onUpdated?.();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Processing failed');
    } finally {
      setProcessing(false);
    }
  }

  return <section className="p1-detail" ref={panel} tabIndex={-1} aria-label="Persisted message details" onKeyDown={event => { if (event.key === 'Escape') onClose(); }}><header className="p1-detail-heading"><div><p className="p1-eyebrow">PERSISTED SOURCE · SYNTHETIC</p><h2>Original message</h2></div><button type="button" className="p1-icon-button" aria-label="Close message details" onClick={onClose}>×</button></header>
    {!data && !error && <p role="status">Loading original message…</p>}
    {error && <div role="alert"><p>{error}</p><button type="button" className="p1-secondary" onClick={() => setAttempt(n => n + 1)}>Retry message</button></div>}
    {data && <>
      <div className="p1-detail-actions">
        {data.processing_status === 'RECEIVED' && (
          <button type="button" className="p1-primary" disabled={processing} onClick={() => handleProcess(false)}>
            {processing ? 'Processing…' : 'Process extraction'}
          </button>
        )}
        {data.processing_status === 'PROCESSED' && (
          <button type="button" className="p1-secondary" disabled={processing} onClick={() => handleProcess(true)}>
            {processing ? 'Reprocessing…' : '↻ Reprocess extraction'}
          </button>
        )}
        {data.processing_status === 'PROCESSING_FAILED' && (
          <button type="button" className="p1-primary" disabled={processing} onClick={() => handleProcess(true)}>
            {processing ? 'Retrying…' : 'Retry extraction'}
          </button>
        )}
      </div>
      <dl className="p1-dimensions">
        <div><dt>Processing</dt><dd>{data.processing_status}</dd></div>
        <div><dt>Information</dt><dd>{extraction ? `Extracted (${(extraction.fields ?? []).length} fields)` : 'Not extracted'}</dd></div>
        <div><dt>Identity</dt><dd>Not associated</dd></div>
        <div><dt>Review</dt><dd>Not started</dd></div>
      </dl>
      <blockquote className="p1-original">
        {extraction?.fields?.length ? renderHighlightedText(data.raw.text, extraction.fields) : data.raw.text}
      </blockquote>
      <dl className="p1-persisted-metadata"><div><dt>Sender display alias</dt><dd>{data.raw.sender_alias}</dd></div><div><dt>Platform identity (unverified)</dt><dd>{data.raw.sender_identity_id}</dd></div><div><dt>Provider</dt><dd>{data.synthetic_provider}</dd></div><div><dt>Provider message ID</dt><dd>{data.raw.provider_message_id}</dd></div><div><dt>Internal message ID</dt><dd>{data.message_id}</dd></div><div><dt>Message timestamp</dt><dd>{formatTime(data.raw.message_at)}</dd></div><div><dt>First envelope receipt</dt><dd>{formatTime(data.raw.received_at)}</dd></div><div><dt>Server persisted at</dt><dd>{formatTime(data.ingested_at)}</dd></div><div><dt>Last state update</dt><dd>{formatTime(data.updated_at)}</dd></div><div><dt>Business timezone</dt><dd>{data.raw.business_timezone}</dd></div><div><dt>Thread / reply</dt><dd>{data.raw.thread_ref ?? 'None'} / {data.raw.reply_to_provider_message_id ?? 'None'}</dd></div></dl>

      <section className="p1-evidence">
        <h3>Extraction evidence</h3>
        {extraction ? (
          <>
            <p style={{ marginTop: '6px', marginBottom: '8px' }}>
              <strong>Method:</strong> <span className="p1-badge p1-blue">RULE ({extraction.extractor_version})</span>{' '}
              <span className={`p1-badge ${extraction.status === 'PROCESSED' ? 'p1-ready' : 'p1-attention'}`}>{extraction.status}</span>
            </p>
            <p className="p1-muted" style={{ fontSize: '10px' }}>
              Attempt {extraction.attempt_id.slice(0, 8)} · Started {formatTime(extraction.started_at)}
              {extraction.completed_at ? ` · Completed ${formatTime(extraction.completed_at)}` : ''}
            </p>
            {(extraction.fields ?? []).length > 0 ? (
              <table className="p1-field-table" aria-label="Extracted candidate fields">
                <thead><tr><th>Field</th><th>Value</th><th>Status</th><th>Qualifier</th><th>Evidence quote</th></tr></thead>
                <tbody>
                  {(extraction.fields ?? []).map((f, idx) => (
                    <tr key={`${f.field_name}-${idx}`}>
                      <td><strong>{f.field_name}</strong></td>
                      <td>{f.value ?? <span className="p1-muted">—</span>}</td>
                      <td><span className={`p1-badge ${f.validation_status === 'VALID' ? 'p1-ready' : 'p1-attention'}`}>{f.validation_status}</span></td>
                      <td>{f.qualifier ?? '—'}</td>
                      <td>{f.evidence?.[0] ? `"${f.evidence[0].quote}" [${f.evidence[0].start}:${f.evidence[0].end}]` : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="p1-muted">No explicit order fields recognized by deterministic rules.</p>
            )}
            {attempts.length > 1 && (
              <div className="p1-attempt-history">
                <h4>Attempt history ({attempts.length})</h4>
                <ul>
                  {attempts.map(att => (
                    <li key={att.attempt_id}>
                      {formatTime(att.started_at)} · {att.status} · {att.extractor_version} ({att.attempt_id.slice(0, 8)})
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        ) : data.processing_status === 'PROCESSING_FAILED' ? (
          <p className="p1-notice" role="alert">Extraction failed: {data.raw ? 'Processing failed' : ''}. Check diagnostic logs.</p>
        ) : (
          <p className="p1-notice">Awaiting processing. Extraction is not implemented yet; no extracted fields or evidence are available.</p>
        )}
      </section>

      <section className="p1-evidence"><h3>Attachment metadata</h3>{data.raw.attachments?.length ? <ul>{data.raw.attachments.map(attachment => <li key={attachment.attachment_id}>{attachment.filename} · {attachment.media_type} · {attachment.size_bytes} bytes · reference {attachment.evidence_ref}</li>)}</ul> : <p>No attachments supplied.</p>}<p className="p1-muted">Metadata only; upload, download and OCR are not implemented.</p></section>
    </>}
  </section>;
}
