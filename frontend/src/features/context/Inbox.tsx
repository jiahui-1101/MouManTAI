import { useEffect, useState } from 'react';
import { loadInboxPreview, PreviewError } from './api';
import { FieldEvidence } from './FieldEvidence';
import type { InboxPreview, InboxRecord, RawMessageEnvelope } from './types';
import './inbox.css';

type Channel = RawMessageEnvelope['channel'];
type Resource = { state: 'loading' } | { state: 'error'; error: Error } | { state: 'ready'; data: InboxPreview };
const channels: ('ALL' | Channel)[] = ['ALL', 'WHATSAPP', 'EMAIL', 'TELEGRAM', 'UNKNOWN'];

export function Inbox({ load = loadInboxPreview }: { load?: () => Promise<InboxPreview> }) {
  const [resource, setResource] = useState<Resource>({ state: 'loading' });
  const [attempt, setAttempt] = useState(0);
  const [channel, setChannel] = useState<'ALL' | Channel>('ALL');
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setResource({ state: 'loading' });
    load().then(data => { if (active) setResource({ state: 'ready', data }); })
      .catch(error => { if (active) setResource({ state: 'error', error: error instanceof Error ? error : new Error('Preview unavailable') }); });
    return () => { active = false; };
  }, [load, attempt]);

  const rows = resource.state === 'ready' ? resource.data.records.filter(row =>
    (channel === 'ALL' || row.message.raw.channel === channel) &&
    `${row.title} ${row.message.raw.text} ${row.message.raw.sender_alias} ${row.message.raw.provider_message_id}`.toLowerCase().includes(search.toLowerCase().trim())) : [];
  const current = rows.find(row => row.message.message_id === selected) ?? rows[0];

  return <div className="p1-inbox">
    <header className="p1-page-heading"><div><p className="p1-eyebrow">BUSINESS CONTEXT · P1</p><h1>Inbox</h1><p className="p1-muted">Trace every request back to its source.</p></div><span className="p1-badge p1-purple">Synthetic fixtures</span></header>
    <aside className="p1-preview-note">Development preview · read-only, hand-labelled examples. No channel connection or AI inference. Reviews and order links are expected fixture states.</aside>
    <div className="p1-toolbar">
      <div role="group" aria-label="Filter by channel" className="p1-filters">{channels.map(value =>
        <button type="button" key={value} aria-pressed={channel === value} onClick={() => setChannel(value)}>{value === 'ALL' ? 'All messages' : value.charAt(0) + value.slice(1).toLowerCase()}</button>)}</div>
      <label className="p1-search"><span>Search messages</span><input type="search" placeholder="Search requests or sender…" value={search} onChange={event => setSearch(event.target.value)} /></label>
    </div>
    {resource.state === 'loading' && <p role="status" className="p1-state">Loading synthetic Inbox…</p>}
    {resource.state === 'error' && <div role="alert" className="p1-state"><h2>{resource.error instanceof PreviewError && [401, 403].includes(resource.error.status) ? 'Access denied' : 'Inbox unavailable'}</h2><p>{resource.error.message}</p><button type="button" onClick={() => setAttempt(value => value + 1)}>Retry loading</button></div>}
    {resource.state === 'ready' && <div className="p1-workspace">
      <section className="p1-list" aria-label="Messages"><div className="p1-list-heading"><h2>Messages</h2><span aria-live="polite">{rows.length} examples</span></div>
        {rows.length === 0 ? <p role="status" className="p1-state">No messages match this view.</p> : <ul>{rows.map(row => <li key={row.message.message_id}>
          <button className="p1-message" type="button" aria-pressed={current?.message.message_id === row.message.message_id} onClick={() => setSelected(row.message.message_id)}>
            <span className="p1-message-meta"><span>{row.message.raw.channel}</span><time dateTime={row.message.raw.received_at}>{new Intl.DateTimeFormat('en-MY', { timeZone: resource.data.business_timezone, hour: '2-digit', minute: '2-digit' }).format(new Date(row.message.raw.received_at))}</time></span>
            <strong>{row.title}</strong><span className="p1-muted">{row.message.raw.sender_alias}</span><span className="p1-snippet">{row.message.raw.text}</span>
            <span className="p1-message-status"><span className={`p1-badge ${row.context.status === 'READY' ? 'p1-neutral' : 'p1-attention'}`}>{row.context.status}</span><span>Review {row.review.status.toLowerCase()}</span></span>
          </button>
        </li>)}</ul>}
      </section>
      {current ? <MessageDetail row={current} timezone={resource.data.business_timezone} /> : <section className="p1-detail p1-state"><p>Select a message to inspect its evidence.</p></section>}
    </div>}
  </div>;
}

function MessageDetail({ row, timezone }: { row: InboxRecord; timezone: string }) {
  const { message, context, review } = row;
  return <section className="p1-detail" aria-label="Message details">
    <header className="p1-detail-heading"><p className="p1-eyebrow">SOURCE MESSAGE</p><h2>{row.title}</h2><p>{message.raw.sender_alias} <span className="p1-muted">via {message.raw.channel.toLowerCase()}</span></p></header>
    <dl className="p1-dimensions">
      <div><dt>Processing</dt><dd>{message.processing_status}</dd></div>
      <div><dt>Information</dt><dd>{context.status}</dd></div>
      <div><dt>Identity</dt><dd>{context.customer_identity_status}</dd></div>
      <div><dt>Review</dt><dd>{review.status}</dd></div>
    </dl>
    {context.status !== 'READY' && <div className="p1-notice" role="note"><strong>Needs attention</strong><p>{context.conflicts?.join('; ') || (context.missing_fields?.length ? `Missing: ${context.missing_fields.join(', ')}` : 'Association or extraction unresolved. Manual review required.')}</p></div>}
    {message.diagnostic && <p className="p1-notice">{message.diagnostic}</p>}
    <blockquote className="p1-original">{message.raw.text}</blockquote>
    <div className="p1-source-meta"><time dateTime={message.raw.received_at}>{new Intl.DateTimeFormat('en-MY', { timeZone: timezone, dateStyle: 'medium', timeStyle: 'short' }).format(new Date(message.raw.received_at))} · {timezone}</time><span>Provider ID: {message.raw.provider_message_id}</span><span>Message: {message.message_id}</span>{message.raw.reply_to_provider_message_id && <span>Reply to: {message.raw.reply_to_provider_message_id}</span>}</div>
    <FieldEvidence fields={message.fields ?? []} timezone={timezone} />
    <footer className="p1-detail-footer"><span>Expected order: {context.order_id ?? 'Unlinked'}</span><span>Context v{context.context_version} · review actions planned for P1-01+</span></footer>
  </section>;
}
