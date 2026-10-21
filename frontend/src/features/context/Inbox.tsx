import { useEffect, useRef, useState } from 'react';
import { loadInboxPreview, PreviewError } from './api';
import { FieldEvidence } from './FieldEvidence';
import type { InboxPreview, InboxRecord, RawMessageEnvelope } from './types';
import './inbox.css';

type Channel = RawMessageEnvelope['channel'];
type Resource = { state: 'loading' } | { state: 'error'; error: Error } | { state: 'ready'; data: InboxPreview };
const channels: Channel[] = ['WHATSAPP', 'EMAIL', 'TELEGRAM', 'UNKNOWN'];

export function Inbox({ load = loadInboxPreview }: { load?: () => Promise<InboxPreview> }) {
  const [resource, setResource] = useState<Resource>({ state: 'loading' });
  const [attempt, setAttempt] = useState(0);
  const [channel, setChannel] = useState('ALL');
  const [readiness, setReadiness] = useState('ALL');
  const [processing, setProcessing] = useState('ALL');
  const [view, setView] = useState('ALL');
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<InboxRecord | null>(null);
  const returnFocus = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    let active = true;
    setResource({ state: 'loading' });
    load().then(data => { if (active) setResource({ state: 'ready', data }); })
      .catch(error => { if (active) setResource({ state: 'error', error: error instanceof Error ? error : new Error('Preview unavailable') }); });
    return () => { active = false; };
  }, [load, attempt]);

  const rows = resource.state === 'ready' ? resource.data.records.filter(row =>
    (channel === 'ALL' || row.message.raw.channel === channel) &&
    (readiness === 'ALL' || row.context.status === readiness) &&
    (processing === 'ALL' || row.message.processing_status === processing) &&
    (view === 'ALL' || row.context.status !== 'READY') &&
    `${row.title} ${row.message.raw.text} ${row.message.raw.sender_alias} ${row.message.raw.provider_message_id}`.toLowerCase().includes(search.toLowerCase().trim())) : [];

  function clearFilters() { setChannel('ALL'); setReadiness('ALL'); setProcessing('ALL'); setSearch(''); setView('ALL'); }
  function inspect(row: InboxRecord, button: HTMLButtonElement) { returnFocus.current = button; setSelected(row); }
  function closeDetail() { setSelected(null); returnFocus.current?.focus(); }

  return <div className="p1-inbox">
    <header className="p1-page-heading"><div><h1>Message Inbox</h1><p>Review incoming requests, extracted information and source evidence.</p></div><button type="button" className="p1-primary" onClick={() => { setSelected(null); setAttempt(value => value + 1); }}>↻ <span>Refresh examples</span></button></header>
    <div className="p1-tabs" role="group" aria-label="Inbox views"><button type="button" aria-pressed={view === 'ALL'} onClick={() => setView('ALL')}>All messages</button><button type="button" aria-pressed={view === 'ATTENTION'} onClick={() => setView('ATTENTION')}>Needs attention</button><span className="p1-demo-label">Synthetic fixtures · read-only preview</span></div>
    <section className="p1-filter-card" aria-label="Inbox filters"><div className="p1-filter-fields">
      <label className="p1-search"><span>Search messages</span><input type="search" placeholder="Search title, sender, message or provider ID" value={search} onChange={event => setSearch(event.target.value)} /></label>
      <label><span>Channel</span><select value={channel} onChange={event => setChannel(event.target.value)}><option value="ALL">All channels</option>{channels.map(value => <option key={value} value={value}>{value.charAt(0) + value.slice(1).toLowerCase()}</option>)}</select></label>
      <label><span>Information</span><select value={readiness} onChange={event => setReadiness(event.target.value)}><option value="ALL">All information states</option>{['READY', 'PARTIAL', 'CONFLICT', 'UNRESOLVED'].map(value => <option key={value}>{value}</option>)}</select></label>
      <label><span>Processing</span><select value={processing} onChange={event => setProcessing(event.target.value)}><option value="ALL">All processing states</option>{['RECEIVED', 'PROCESSING', 'PROCESSED', 'PROCESSING_FAILED'].map(value => <option key={value}>{value}</option>)}</select></label>
      <button type="button" className="p1-secondary" onClick={clearFilters}>× &nbsp; Clear</button>
    </div><div className="p1-filter-caption"><span aria-live="polite">{resource.state === 'ready' ? `${rows.length} examples` : 'Synthetic development data'}</span><span>Fixed message time · Asia/Kuala_Lumpur</span></div></section>
    {resource.state === 'loading' && <p role="status" className="p1-state">Loading synthetic Inbox…</p>}
    {resource.state === 'error' && <div role="alert" className="p1-state"><h2>{resource.error instanceof PreviewError && [401, 403].includes(resource.error.status) ? 'Access denied' : 'Inbox unavailable'}</h2><p>{resource.error.message}</p><button type="button" className="p1-secondary" onClick={() => setAttempt(value => value + 1)}>Retry loading</button></div>}
    {resource.state === 'ready' && <section className="p1-table-card" aria-label="Messages">
      <div className="p1-table-scroll" tabIndex={0} role="region" aria-label="Message table, scroll horizontally on small screens">
        <table><caption className="p1-sr-only">Synthetic inbound messages and expected extraction states</caption><thead><tr><th scope="col">Received at</th><th scope="col">Message</th><th scope="col">Channel</th><th scope="col">Processing</th><th scope="col">Information</th><th scope="col">Identity</th><th scope="col">Review</th><th scope="col">Action</th></tr></thead>
        <tbody>{rows.map(row => <tr key={row.message.message_id}>
          <td className="p1-date"><time dateTime={row.message.raw.received_at}>{new Intl.DateTimeFormat('en-MY', { timeZone: resource.data.business_timezone, dateStyle: 'medium', timeStyle: 'short' }).format(new Date(row.message.raw.received_at))}</time></td>
          <td className="p1-message-cell"><button type="button" className="p1-title-button" onClick={event => inspect(row, event.currentTarget)}>{row.title}</button><span className="p1-row-secondary">{row.message.raw.sender_alias} · {row.message.raw.text}</span></td>
          <td><span className="p1-badge p1-blue">{row.message.raw.channel}</span></td>
          <td><span className={`p1-badge ${row.message.processing_status === 'PROCESSING_FAILED' ? 'p1-attention' : 'p1-neutral'}`}>{row.message.processing_status === 'PROCESSING_FAILED' ? 'FAILED' : row.message.processing_status}</span></td>
          <td><span className={`p1-badge ${row.context.status === 'READY' ? 'p1-ready' : 'p1-attention'}`}>{row.context.status}</span></td>
          <td className="p1-identity">{row.context.customer_identity_status === 'LINK_VERIFIED' ? 'Verified link' : row.context.customer_identity_status === 'AMBIGUOUS' ? 'Ambiguous' : 'Unverified'}</td>
          <td><span className="p1-badge p1-neutral">{row.review.status}</span></td>
          <td><button type="button" className="p1-icon-button" aria-label={`View evidence: ${row.title}`} onClick={event => inspect(row, event.currentTarget)}><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><path d="M14 3h7v7M21 3l-11 11M10 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-5" /></svg></button></td>
        </tr>)}</tbody></table>
      </div>
      {rows.length === 0 && <p role="status" className="p1-empty">No messages match this view.</p>}
      <footer className="p1-table-footer"><span>Showing {rows.length ? '1' : '0'} to {rows.length} of {rows.length} entries</span><span>Hand-labelled expected results · no extraction has run</span></footer>
    </section>}
    <p className="p1-preview-note">Development fixtures only. No live channels, AI inference, persisted reviews or verified production identity links. Select a message to inspect its source evidence.</p>
    {selected && resource.state === 'ready' && <MessageDetail row={selected} timezone={resource.data.business_timezone} onClose={closeDetail} />}
  </div>;
}

function MessageDetail({ row, timezone, onClose }: { row: InboxRecord; timezone: string; onClose: () => void }) {
  const { message, context, review } = row;
  const panel = useRef<HTMLElement>(null);
  useEffect(() => { panel.current?.focus(); }, [row]);
  return <section ref={panel} tabIndex={-1} className="p1-detail" aria-label="Message details" onKeyDown={event => { if (event.key === 'Escape') onClose(); }}>
    <header className="p1-detail-heading"><div><p className="p1-eyebrow">SOURCE MESSAGE · FIXTURE</p><h2>{row.title}</h2><p>{message.raw.sender_alias} <span className="p1-muted">via {message.raw.channel.toLowerCase()}</span></p></div><button type="button" className="p1-icon-button" aria-label="Close message details" onClick={onClose}>×</button></header>
    <dl className="p1-dimensions"><div><dt>Processing</dt><dd>{message.processing_status}</dd></div><div><dt>Information</dt><dd>{context.status}</dd></div><div><dt>Identity</dt><dd>{context.customer_identity_status}</dd></div><div><dt>Review</dt><dd>{review.status}</dd></div></dl>
    {context.status !== 'READY' && <div className="p1-notice" role="note"><strong>Needs attention</strong><p>{context.conflicts?.join('; ') || (context.missing_fields?.length ? `Missing: ${context.missing_fields.join(', ')}` : 'Association or extraction unresolved. Manual review required.')}</p></div>}
    {message.diagnostic && <p className="p1-notice">{message.diagnostic}</p>}
    <blockquote className="p1-original">{message.raw.text}</blockquote>
    <div className="p1-source-meta"><time dateTime={message.raw.received_at}>{new Intl.DateTimeFormat('en-MY', { timeZone: timezone, dateStyle: 'medium', timeStyle: 'short' }).format(new Date(message.raw.received_at))} · {timezone}</time><span>Provider ID: {message.raw.provider_message_id}</span><span>Message: {message.message_id}</span>{message.raw.reply_to_provider_message_id && <span>Reply to: {message.raw.reply_to_provider_message_id}</span>}</div>
    <FieldEvidence fields={message.fields ?? []} timezone={timezone} />
    <footer className="p1-detail-footer"><span>Expected order: {context.order_id ?? 'Unlinked'}</span><span>Context v{context.context_version} · review actions planned for P1-01+</span></footer>
  </section>;
}
