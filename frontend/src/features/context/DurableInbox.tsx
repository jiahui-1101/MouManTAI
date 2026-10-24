import { useOptionalAuth } from '../../shared/auth';
import { useScopedOperationalApi } from './useScopedOperationalApi';
import { useEffect, useRef, useState } from 'react';

import { createPortal } from 'react-dom';

import type { ReactNode } from 'react';

import { PreviewError } from './api';

import { getResolvedTaskIds } from './operationalApi';

import type { OperationalApi } from './operationalApi';

import { SyntheticComposer } from './SyntheticComposer';

import { OrderContextDetail } from './OrderContextDetail';

import { ReviewDrawer } from './ReviewDrawer';

import { AttachmentViewer } from './AttachmentViewer';

import { ExtractionProvenance } from './ExtractionProvenance';

import type {

  AttachmentRecord,

  DevelopmentContext,

  ExtractedField,

  ExtractionAttemptRecord,

  IngestResponse,

  MessageAssociationRecord,

  MessagePage,

  OrderContextRecord,

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



const PAGE_SIZE = 15;





function formatSource(message: StoredMessage | undefined): string {
  if (!message) return 'Synthetic';
  if (message.source_label) {
    return message.source_label;
  }
  const rawMode = (message.raw as any)?.adapter_mode;
  const isReal = rawMode === 'REAL' || (message.provider && message.provider !== 'SYNTHETIC') || message.synthetic_provider === null;
  if (isReal) {
    const ch = message.raw?.channel;
    if (ch === 'TELEGRAM') return 'Telegram';
    if (ch === 'EMAIL') return 'Gmail';
    if (ch === 'WHATSAPP') return 'WhatsApp';
    return ch ? (ch.charAt(0).toUpperCase() + ch.slice(1).toLowerCase()) : 'Real';
  }
  return 'Synthetic';
}





type SortKey = 'ingested_at' | 'text' | 'processing_status';

type SortDir = 'asc' | 'desc';



function sortMessages(items: StoredMessage[], by: SortKey, dir: SortDir): StoredMessage[] {

  return [...items].sort((a, b) => {

    let cmp = 0;

    if (by === 'ingested_at') {

      cmp = (a.raw.received_at ?? '').localeCompare(b.raw.received_at ?? '');

    } else if (by === 'text') {

      cmp = (a.raw?.text ?? '').localeCompare(b.raw?.text ?? '');

    } else if (by === 'processing_status') {

      cmp = (a.processing_status ?? '').localeCompare(b.processing_status ?? '');

    }

    return dir === 'asc' ? cmp : -cmp;

  });

}

function MessageRow({
  message,
  onOpen,
  onProcess,
  onDelete,
  processing,
  deleting,
}: {
  message: StoredMessage;
  onOpen: (button: HTMLButtonElement) => void;
  onProcess: () => void;
  onDelete: () => void;
  processing: boolean;
  deleting: boolean;
}) {
  return <tr className="p1-inbox-row">
    <td className="p1-date"><time dateTime={message.raw.received_at}>{formatTime(message.raw.received_at)}</time></td>
    <td className="p1-message-cell"><button type="button" className="p1-title-button" onClick={event => onOpen(event.currentTarget)}>{message.raw.sender_alias}</button><span className="p1-row-secondary">{message.raw.text}</span><span className="p1-row-secondary p1-subtle-id">{message.raw.provider_message_id}{message.raw.attachments?.length ? ` · ${message.raw.attachments.length} attachment${message.raw.attachments.length === 1 ? '' : 's'}` : ''}</span></td>
    <td className="p1-source-cell"><span className="p1-orbyte-source-badge">{formatSource(message)}</span></td>
    <td><span className={`p1-orbyte-status-badge is-${message.processing_status === 'PROCESSED' ? 'valid' : message.processing_status === 'PROCESSING' ? 'attention' : message.processing_status === 'PROCESSING_FAILED' ? 'conflict' : 'neutral'}`}>{message.processing_status}</span></td>
    <td>{message.processing_status === 'PROCESSED' ? (message.extractor_version?.startsWith('p1-ai-pipeline-') ? <span className="p1-orbyte-status-badge is-model">Model-assisted</span> : <span className="p1-orbyte-status-badge is-valid">Extracted</span>) : <span className="p1-subtle-text">Not available</span>}</td>

    <td className="p1-subtle-text" title="The message API does not provide generated, queued, sent, or failed reply state">Not reported</td>
    <td className="p1-actions-cell">
      <div className="p1-orbyte-actions-group">
        <button
          type="button"
          className="p1-orbyte-action-icon-btn"
          aria-label={`View message ${message.raw.provider_message_id}`}
          title="Inspect message details"
          onClick={event => onOpen(event.currentTarget)}
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14v-7"/>
            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
          </svg>
        </button>
        <button
          type="button"
          className="p1-orbyte-action-icon-btn is-sync"
          disabled={processing || deleting}
          aria-label={`Reprocess message ${message.raw.provider_message_id}`}
          title={message.processing_status === 'PROCESSED' ? 'Reprocess extraction' : 'Run extraction'}
          onClick={onProcess}
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={processing ? 'p1-spin' : ''}>
            <polyline points="23 4 23 10 17 10"/>
            <polyline points="1 20 1 14 7 14"/>
            <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
          </svg>
        </button>
        <button
          type="button"
          className="p1-orbyte-action-icon-btn is-delete"
          disabled={processing || deleting}
          aria-label={`Delete message ${message.raw.provider_message_id}`}
          title="Delete message"
          onClick={onDelete}
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M3 6h18"/>
            <path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/>
            <path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>
            <line x1="10" y1="11" x2="10" y2="17"/>
            <line x1="14" y1="11" x2="14" y2="17"/>
          </svg>
        </button>
      </div>
    </td>
  </tr>;
}



export function DurableInbox({ api }: { api?: OperationalApi }) {
  const auth = useOptionalAuth();
  const scopedApi = useScopedOperationalApi();
  const identity = JSON.stringify([auth?.tenantId, auth?.actorId]);
  return <DurableInboxContents key={identity} api={api ?? scopedApi} />;
}

function DurableInboxContents({ api }: { api: OperationalApi }) {

  const [resource, setResource] = useState<Resource>({ state: 'loading' });


  const [tenantId, setTenantId] = useState<string | null>(null);

  const [channel, setChannel] = useState('ALL');

  const [processing, setProcessing] = useState('ALL');

  const [search, setSearch] = useState('');

  const [offset, setOffset] = useState(0);

  const [attempt, setAttempt] = useState(0);

  const [composing, setComposing] = useState(false);

  const [selected, setSelected] = useState<string | null>(() => {
    if (typeof window !== 'undefined') {
      const match = window.location.pathname.match(/\/inbox\/customer-messages\/([^/?#]+)/);
      if (match) return decodeURIComponent(match[1]);
      return new URLSearchParams(window.location.search).get('message');
    }
    return null;
  });

  const [saved, setSaved] = useState<IngestResponse | null>(null);

  const [processingId, setProcessingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<StoredMessage | null>(null);
  const [inboxToast, setInboxToast] = useState<string | null>(null);

  const [sortBy, setSortBy] = useState<SortKey>('ingested_at');

  const [sortDir, setSortDir] = useState<SortDir>('desc');

  const returnFocus = useRef<HTMLButtonElement | null>(null);

  const processLock = useRef(false);



  function handleSort(key: SortKey) {

    if (sortBy === key) {

      setSortDir(d => d === 'asc' ? 'desc' : 'asc');

    } else {

      setSortBy(key);

      setSortDir('asc');

    }

  }



  useEffect(() => {

    let active = true;

    setResource({ state: 'loading' });

    Promise.all([api.list({ channel, processing, search, offset, limit: PAGE_SIZE }), api.config()]).then(([page, context]) => {

      if (active) { setTenantId(context.tenant_id); setResource({ state: 'ready', page, context }); }

    }).catch(error => { if (active) setResource({ state: 'error', error: error instanceof Error ? error : new Error('Inbox unavailable') }); });

    return () => { active = false; };

  }, [api, channel, processing, search, offset, attempt]);





  function select(id: string, button: HTMLButtonElement) {
    returnFocus.current = button;
    const url = new URL(window.location.href);
    url.searchParams.set('message', id);
    window.history.replaceState(window.history.state, '', url);
    setSelected(id);
  }

  function closeDetail() {
    const url = new URL(window.location.href);
    url.searchParams.delete('message');
    if (window.location.pathname.startsWith('/inbox/customer-messages/')) {
      window.history.replaceState(window.history.state, '', '/inbox/customer-messages' + (url.search || ''));
    } else {
      window.history.replaceState(window.history.state, '', url.pathname + (url.search || ''));
    }
    setSelected(null);
    returnFocus.current?.focus();
  }

  function submitted(result: IngestResponse) {

    setSaved(result); setComposing(false); setOffset(0); setSearch(''); setChannel('ALL'); setProcessing('ALL'); setAttempt(n => n + 1);

    // Auto-process message immediately upon creation so extraction runs without requiring manual action

    void api.process(result.message.message_id).then(res => {

      setSaved({ message: res.message, duplicate: result.duplicate });

      setAttempt(n => n + 1);

    }).catch(() => {});

  }



  async function handleInlineProcess(messageId: string, isReprocess: boolean) {

    if (processLock.current) return;

    processLock.current = true;

    setProcessingId(messageId);

    try {

      await api.process(messageId, isReprocess);

      setAttempt(n => n + 1);

    } catch {

      // Refresh on error to reflect any status change

      setAttempt(n => n + 1);

    } finally {

      processLock.current = false;
      setProcessingId(null);
    }
  }

  async function handleDeleteMessage(target: StoredMessage) {
    setDeletingId(target.message_id);
    try {
      await api.deleteMessage(target.message_id);
      setDeleteTarget(null);
      if (selected === target.message_id) {
        setSelected(null);
      }
      setInboxToast('Message deleted successfully.');
      setTimeout(() => setInboxToast(null), 3000);
      setAttempt(n => n + 1);
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to delete message');
    } finally {
      setDeletingId(null);
    }
  }



  return <div className={`p1-inbox ${selected ? 'has-selected' : ''}`}>
    <div className="p1-inbox-list-view">
      <header className="p1-page-heading"><div><h1 aria-label="Message Inbox">Customer Messages</h1><p>Inspect original messages, extraction evidence and verified identity links.</p></div><button type="button" className="p1-primary" disabled={resource.state !== 'ready' || composing} onClick={() => { setSaved(null); setComposing(true); }}>+ New synthetic message</button></header>

      <div className="p1-tabs"><span className="p1-active-label">Persisted messages</span><span className="p1-demo-label">Local development identity · provider mode shown per message</span></div>

      {saved && <p role="status" className="p1-success">{saved.duplicate ? 'Duplicate delivery — original message retrieved.' : 'Message saved.'} ID: {saved.message.message_id}. Awaiting processing; extraction has not run.</p>}

      {composing && tenantId && (
        <SyntheticComposer
          tenantId={tenantId}
          ingest={payload => api.ingest(payload)}
          uploadAttachment={file => api.uploadAttachment(file)}
          onSuccess={submitted}
          onCancel={() => setComposing(false)}
        />
      )}

      <section className="p1-filter-card" aria-label="Inbox filters"><div className="p1-filter-fields p1-durable-filters">
        <label className="p1-search"><span>Search messages</span><input type="search" maxLength={200} value={search} placeholder="Search original text, sender or provider ID" onChange={event => { setSearch(event.target.value); setOffset(0); }} /></label>
        <label><span>Channel</span><select value={channel} onChange={event => { setChannel(event.target.value); setOffset(0); }}><option value="ALL">All channels</option>{['WHATSAPP', 'EMAIL', 'TELEGRAM', 'UNKNOWN'].map(value => <option key={value}>{value}</option>)}</select></label>
        <label><span>Processing</span><select value={processing} onChange={event => { setProcessing(event.target.value); setOffset(0); }}><option value="ALL">All processing states</option>{['RECEIVED', 'PROCESSING', 'PROCESSED', 'PROCESSING_FAILED'].map(value => <option key={value}>{value}</option>)}</select></label>
        <button type="button" className="p1-secondary" onClick={() => { setSearch(''); setChannel('ALL'); setProcessing('ALL'); setOffset(0); }}>Clear</button>
        <button type="button" className="p1-secondary" onClick={() => setAttempt(n => n + 1)}>Refresh</button>
      </div><div className="p1-filter-caption"><span>{resource.state === 'ready' ? `${resource.page.total} persisted messages` : 'PostgreSQL Inbox'}</span><span>Display timezone · Asia/Kuala_Lumpur</span></div><p className="p1-filter-limit">Intent, reply-state and review-state filters require a conversation API; the current filters query persisted source messages.</p></section>

      {resource.state === 'loading' && <p role="status" className="p1-state">Loading persisted messages…</p>}

      {resource.state === 'error' && <div role="alert" className="p1-state"><h2>{resource.error instanceof PreviewError && [401, 403].includes(resource.error.status) ? 'Access denied' : 'Inbox unavailable'}</h2><p>{resource.error.message}</p><button type="button" className="p1-secondary" onClick={() => setAttempt(n => n + 1)}>Retry Inbox</button></div>}

      {resource.state === 'ready' && <section className="p1-table-card" aria-label="Persisted messages"><div className="p1-table-scroll" role="region" aria-label="Persisted message table, scroll horizontally on small screens" tabIndex={0}>
        <table className="p1-orbyte-main-table"><caption className="p1-sr-only">Persisted original messages awaiting downstream work</caption><thead><tr>
          <th scope="col" className={`p1-th-sortable${sortBy === 'ingested_at' ? ' is-active' : ''}`} aria-sort={sortBy === 'ingested_at' ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}><button type="button" className="p1-sort-button" onClick={() => handleSort('ingested_at')}>Received At <span className="p1-th-arrows" aria-hidden="true">{sortBy === 'ingested_at' ? (sortDir === 'asc' ? '↑' : '↓') : '↑↓'}</span></button></th>
          <th scope="col" className={`p1-th-sortable${sortBy === 'text' ? ' is-active' : ''}`} aria-sort={sortBy === 'text' ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}><button type="button" className="p1-sort-button" onClick={() => handleSort('text')}>Original Message <span className="p1-th-arrows" aria-hidden="true">{sortBy === 'text' ? (sortDir === 'asc' ? '↑' : '↓') : '↑↓'}</span></button></th>
          <th scope="col">Source</th>
          <th scope="col" className={`p1-th-sortable${sortBy === 'processing_status' ? ' is-active' : ''}`} aria-sort={sortBy === 'processing_status' ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}><button type="button" className="p1-sort-button" onClick={() => handleSort('processing_status')}>Processing <span className="p1-th-arrows" aria-hidden="true">{sortBy === 'processing_status' ? (sortDir === 'asc' ? '↑' : '↓') : '↑↓'}</span></button></th>
          <th scope="col">Extraction</th><th scope="col">Reply</th><th scope="col" className="p1-th-actions">Actions</th>
        </tr></thead>
        <tbody>{sortMessages(resource.page.items, sortBy, sortDir).map(message => (
          <MessageRow
            key={message.message_id}
            message={message}
            processing={processingId === message.message_id}
            deleting={deletingId === message.message_id}
            onOpen={button => select(message.message_id, button)}
            onProcess={() => handleInlineProcess(message.message_id, message.processing_status === 'PROCESSED')}
            onDelete={() => setDeleteTarget(message)}
          />
        ))}</tbody></table>
      </div>{resource.page.items.length === 0 && <p role="status" className="p1-empty">No persisted messages match this view. Submit a synthetic message to begin.</p>}
        <footer className="p1-table-footer"><span className="p1-footer-count">Showing {resource.page.items.length ? offset + 1 : 0} to {Math.min(offset + resource.page.items.length, resource.page.total)} of {resource.page.total} entries</span><div className="p1-orbyte-pagination"><div className="p1-rows-per-page"><span>Rows per page:</span><span className="p1-rows-badge">15</span></div><div className="p1-pagination-controls"><button type="button" className="p1-page-btn" disabled={offset === 0} aria-label="Previous" onClick={() => setOffset(n => Math.max(0, n - PAGE_SIZE))}>‹</button><span className="p1-page-active">{Math.floor(offset / PAGE_SIZE) + 1}</span><button type="button" className="p1-page-btn" disabled={offset + PAGE_SIZE >= resource.page.total || offset + PAGE_SIZE > 10_000} aria-label="Next" onClick={() => setOffset(n => n + PAGE_SIZE)}>›</button></div></div></footer>
      </section>}

      <p className="p1-preview-note">Local development tenant only · no production authentication. The composer creates synthetic test messages; provider-backed records retain their own source labels. Extraction evidence is persisted with exact Unicode spans.</p>
    </div>

    {deleteTarget && (
      <div className="p1-confirm-backdrop" role="dialog" aria-modal="true" aria-labelledby="delete-dialog-title">
        <div className="p1-confirm-modal">
          <h3 id="delete-dialog-title">Delete message</h3>
          <p>
            Are you sure you want to delete this message from <strong>{deleteTarget.raw.sender_alias || 'sender'}</strong>?
            <br />
            <span style={{ fontSize: '12px', color: '#64748b', marginTop: '6px', display: 'block', wordBreak: 'break-all' }}>
              ID: {deleteTarget.raw.provider_message_id}
            </span>
            This will remove the message and permanently prevent it from appearing again.
          </p>
          <div className="p1-confirm-actions">
            <button
              type="button"
              className="p1-btn p1-btn-secondary"
              disabled={deletingId !== null}
              onClick={() => setDeleteTarget(null)}
            >
              Cancel
            </button>
            <button
              type="button"
              className="p1-btn p1-btn-danger"
              disabled={deletingId !== null}
              onClick={() => handleDeleteMessage(deleteTarget)}
            >
              {deletingId ? 'Deleting…' : 'Delete'}
            </button>
          </div>
        </div>
      </div>
    )}

    {inboxToast && (
      <div className="p1-toast" role="status">
        {inboxToast}
      </div>
    )}

    {selected && <StoredMessageDetail id={selected} api={api} onUpdated={() => setAttempt(n => n + 1)} onClose={closeDetail} />}
  </div>;

}



function StoredMessageDetail({ id, api, onUpdated, onClose }: { id: string; api: OperationalApi; onUpdated?: () => void; onClose: () => void }) {
  const auth = useOptionalAuth();
  const [data, setData] = useState<StoredMessage | null>(null);
  const [extraction, setExtraction] = useState<ExtractionAttemptRecord | null>(null);
  const [attempts, setAttempts] = useState<ExtractionAttemptRecord[]>([]);
  const [association, setAssociation] = useState<MessageAssociationRecord | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [processing, setProcessing] = useState(false);
  const [deciding, setDeciding] = useState(false);
  const [assocError, setAssocError] = useState<string | null>(null);
  const [activeContext, setActiveContext] = useState<OrderContextRecord | null>(null);
  const [showContextModal, setShowContextModal] = useState(false);
  const [showReviewDrawer, setShowReviewDrawer] = useState(false);
  const [contextLoading, setContextLoading] = useState(false);
  const [contextError, setContextError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [selectedEvidenceRef, setSelectedEvidenceRef] = useState<string | null>(null);
  const [uploadingAttachment, setUploadingAttachment] = useState<boolean>(false);
  const [uploadedAttachments, setUploadedAttachments] = useState<AttachmentRecord[]>([]);
  const [activeTab, setActiveTab] = useState<'message' | 'extraction' | 'identity' | 'attachments' | 'metadata'>('message');
  const [confirmAction, setConfirmAction] = useState<{ title: string; description: string; onConfirm: () => void } | null>(null);
  const [reviewDecision, setReviewDecision] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const panel = useRef<HTMLElement>(null);
  useEffect(() => { panel.current?.focus(); }, []);

  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  function showToast(msg: string) {
    if (toastTimer.current) clearTimeout(toastTimer.current);
    setToast(msg);
    toastTimer.current = setTimeout(() => setToast(null), 3500);
  }

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        if (confirmAction) {
          setConfirmAction(null);
        } else if (!showReviewDrawer) {
          onClose();
        }
      }
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [onClose, showReviewDrawer, confirmAction]);

  useEffect(() => {
    let active = true;
    setData(null); setExtraction(null); setAttempts([]); setAssociation(null); setError(null); setAssocError(null);
    setActiveContext(null); setShowContextModal(false); setShowReviewDrawer(false); setContextLoading(false); setContextError(null);
    setSelectedEvidenceRef(null); setUploadedAttachments([]); setConfirmAction(null);

    setReviewDecision(null);
    if (getResolvedTaskIds().has(id)) {
      setReviewDecision('Accepted');
    }
    api.createContextFromMessage(id).then(ctx => {
      if (active) {
        setActiveContext(ctx);
        if (getResolvedTaskIds().has(id) || getResolvedTaskIds().has(ctx.context_id)) {
          setReviewDecision('Accepted');
        } else if (ctx.last_reviewed_at) {
          if (ctx.status === 'UNRESOLVED') {
            setReviewDecision('Unresolved');
          } else if (ctx.status === 'INFORMATION_READY') {
            setReviewDecision('Accepted');
          } else {
            setReviewDecision('In progress');
          }
        }
      }
    }).catch(() => { /* context not created yet */ });

    api.detail(id).then(message => {
      if (active) {
        setData(message);
        api.getExtraction(id).then(ext => { if (active) setExtraction(ext); }).catch(() => { /* Not yet extracted */ });
        api.listAttempts(id).then(hist => { if (active) setAttempts(hist.items); }).catch(() => { /* Not yet extracted */ });
        api.getAssociation(id).then(assoc => { if (active) setAssociation(assoc); }).catch(() => { /* Not yet evaluated */ });
      }
    }).catch(failure => { if (active) setError(failure instanceof Error ? failure.message : 'Message unavailable'); });
    return () => { active = false; };
  }, [id, api, attempt]);

  useEffect(() => {
    const handleSaved = () => {
      if (!data?.message_id) return;
      const resolved = getResolvedTaskIds();
      if (resolved.has(data.message_id)) {
        setReviewDecision('Accepted');
      }
    };
    window.addEventListener('moumantai:review-context-saved', handleSaved);
    return () => window.removeEventListener('moumantai:review-context-saved', handleSaved);
  }, [data?.message_id]);

  async function handleDirectReview() {
    setContextLoading(true);
    setContextError(null);
    try {
      const ctx = await api.createContextFromMessage(id);
      setActiveContext(ctx);
      setShowReviewDrawer(true);
      setActiveTab('extraction');
    } catch (err) {
      setContextError(err instanceof Error ? err.message : 'Failed to generate/view order context for review');
    } finally {
      setContextLoading(false);
    }
  }

  const processingLock = useRef(false);
  async function handleProcess(reprocess: boolean) {
    if (processingLock.current) return;
    processingLock.current = true;
    setProcessing(true);
    try {
      const res = await api.process(id, reprocess);
      setData(res.message);
      setExtraction(res.attempt);
      const hist = await api.listAttempts(id).catch(() => ({ items: [res.attempt] }));
      setAttempts(hist.items);
      api.getAssociation(id).then(setAssociation).catch(() => {});
      showToast(reprocess ? 'Extraction reprocessed.' : 'Extraction completed.');
      onUpdated?.();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Processing failed');
    } finally {
      processingLock.current = false;
      setProcessing(false);
    }
  }

  async function handleDecide(decision: 'CONFIRMED' | 'REJECTED', target_customer_id?: string, target_order_id?: string) {
    if (!association) return;
    setDeciding(true);
    setAssocError(null);
    try {
      const updated = await api.decideAssociation(id, {
        decision,
        target_customer_id,
        target_order_id,
        reason: decision === 'CONFIRMED' ? 'Manual staff confirmation' : 'Manual staff rejection',
        expected_version: association.version,
      });
      setAssociation(updated);
      showToast(decision === 'CONFIRMED' ? 'Link confirmed.' : 'Association unlinked.');
      onUpdated?.();
    } catch (err) {
      setAssocError(err instanceof Error ? err.message : 'Decision failed');
      api.getAssociation(id).then(setAssociation).catch(() => {});
    } finally {
      setDeciding(false);
    }
  }

  const rawMode = (data?.raw as any)?.adapter_mode;
  const isReal = rawMode === 'REAL' || (data?.provider && data?.provider !== 'SYNTHETIC') || data?.synthetic_provider === null;
  const senderInitial = (data?.raw.sender_alias || data?.raw.sender_identity_id || 'M').charAt(0).toUpperCase();

  const unresolvedCount = (extraction?.fields ?? []).filter(
    f => f.validation_status === 'UNRESOLVED' || f.validation_status === 'MISSING' || !f.value
  ).length;

  const rawAtts = (data?.raw.attachments as AttachmentRecord[] | undefined) || [];
  const allAtts = [...rawAtts, ...uploadedAttachments];

  const isExplicitlyResolved = Boolean(data?.message_id && getResolvedTaskIds().has(data.message_id)) || activeContext?.status === 'INFORMATION_READY';
  const currentReviewStatus = reviewDecision || (
    isExplicitlyResolved ? 'Accepted' :
    (activeContext?.last_reviewed_at
      ? (activeContext.status === 'UNRESOLVED' ? 'Unresolved' : activeContext.status === 'INFORMATION_READY' ? 'Accepted' : 'In progress')
      : (association?.last_decision ? association.last_decision.decision : 'Not started'))
  );
  const hasManualReview = !isExplicitlyResolved && Boolean(
    unresolvedCount > 0 ||
    data?.processing_status === 'PROCESSING_FAILED' ||
    association?.status === 'CONFLICT' ||
    association?.status === 'LINK_CANDIDATE' ||
    (extraction?.fields ?? []).some(f => f.metadata?.disposition === 'rejected')
  );

  return (
    <>
      <section
        className={`p1-detail p1-detail-fullpage ${showReviewDrawer ? 'p1-detail-shifted' : ''}`}
        ref={panel}
        tabIndex={-1}
        aria-label="Persisted message details"
      >
        <header className="p1-fp-header">
          <div className="p1-fp-header-left">
            <button
              type="button"
              className="p1-fp-back-btn"
              aria-label="Back to Customer Messages"
              title="Back to Customer Messages"
              onClick={onClose}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <line x1="19" y1="12" x2="5" y2="12"></line>
                <polyline points="12 19 5 12 12 5"></polyline>
              </svg>
            </button>
            <div className="p1-fp-header-titles">
              <p className="p1-eyebrow">PERSISTED SOURCE · {isReal ? 'REAL PROVIDER' : 'SYNTHETIC'}</p>
              <h2 className="p1-fp-title">Original message</h2>
              <p className="p1-fp-subtitle">Persisted source · {isReal ? 'real provider' : 'synthetic'}</p>
            </div>
          </div>

          <div className="p1-fp-header-right">
            {data?.processing_status === 'RECEIVED' && (
              <button
                type="button"
                className="p1-fp-reprocess-btn"
                disabled={processing}
                onClick={() => handleProcess(false)}
              >
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={processing ? 'p1-spin' : ''} aria-hidden="true">
                  <polygon points="5 3 19 12 5 21 5 3"/>
                </svg>
                <span>{processing ? 'Processing…' : 'Process extraction'}</span>
              </button>
            )}
            {data?.processing_status === 'PROCESSED' && (
              <button
                type="button"
                className="p1-fp-reprocess-btn"
                disabled={processing}
                onClick={() => {
                  setConfirmAction({
                    title: 'Reprocess extraction',
                    description: 'A new extraction attempt will run on this message. Current evidence is kept.',
                    onConfirm: () => {
                      setConfirmAction(null);
                      void handleProcess(true);
                    },
                  });
                }}
              >
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={processing ? 'p1-spin' : ''} aria-hidden="true">
                  <polyline points="23 4 23 10 17 10"/>
                  <polyline points="1 20 1 14 7 14"/>
                  <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
                </svg>
                <span>{processing ? 'Reprocessing…' : '↻ Reprocess extraction'}</span>
              </button>
            )}
            {data?.processing_status === 'PROCESSING_FAILED' && (
              <button
                type="button"
                className="p1-fp-reprocess-btn"
                disabled={processing}
                onClick={() => handleProcess(true)}
              >
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={processing ? 'p1-spin' : ''} aria-hidden="true">
                  <polyline points="23 4 23 10 17 10"/>
                  <polyline points="1 20 1 14 7 14"/>
                  <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
                </svg>
                <span>{processing ? 'Retrying…' : 'Retry extraction'}</span>
              </button>
            )}
          </div>
        </header>

        {!data && !error && <p role="status">Loading original message…</p>}
        {error && (
          <div role="alert" className="p1-state">
            <p>{error}</p>
            <button type="button" className="p1-secondary" onClick={() => setAttempt(n => n + 1)}>Retry message</button>
          </div>
        )}

        {data && (
          <>
            {/* Sender Card */}
            <div className="p1-fp-sender-card">
              <div className="p1-fp-avatar" aria-hidden="true">{senderInitial}</div>
              <div className="p1-fp-sender-info">
                <div className="p1-fp-sender-top">
                  <strong className="p1-fp-sender-name">{data.raw.sender_alias || data.raw.sender_identity_id}</strong>
                  <span className="p1-orbyte-source-badge">{formatSource(data)}</span>
                </div>
                <div className="p1-fp-sender-meta">
                  <span>{(data.raw as any).email || (data.raw.sender_identity_id?.includes('@') ? data.raw.sender_identity_id : (data.raw.channel?.toLowerCase() || 'channel'))}</span>
                  <span> · </span>
                  <time dateTime={data.raw.received_at}>{formatTime(data.raw.received_at)}</time>
                </div>
              </div>
            </div>

            {/* 4 Stat Boxes */}
            <div className="p1-fp-stats-grid">
              <div className="p1-fp-stat-card">
                <div className="p1-fp-stat-label">PROCESSING</div>
                <div className="p1-fp-stat-val">{data.processing_status}</div>
              </div>
              <div className="p1-fp-stat-card">
                <div className="p1-fp-stat-label">INFORMATION</div>
                <div className="p1-fp-stat-val">
                  {extraction ? `Extracted (${(extraction.fields ?? []).length} fields)` : 'Not extracted'}
                </div>
              </div>
              <div className="p1-fp-stat-card">
                <div className="p1-fp-stat-label">IDENTITY</div>
                <div className="p1-fp-stat-val">
                  {association ? association.status : 'Not associated'}
                </div>
              </div>
              <div className="p1-fp-stat-card">
                <div className="p1-fp-stat-label">REVIEW</div>
                <div className="p1-fp-stat-val">
                  {currentReviewStatus}
                </div>
              </div>
            </div>

            {contextError && <p className="p1-conflict-box" role="alert">{contextError}</p>}

            {/* Two-Column Area */}
            <div className="p1-fp-main-columns">
              {/* Left Column: 5 Tabs */}
              <div className="p1-fp-left-card">
                <div className="p1-fp-tabs-bar" role="tablist" aria-label="Customer message detail tabs">
                  <button
                    type="button"
                    role="tab"
                    id="tab-message"
                    aria-selected={activeTab === 'message'}
                    aria-controls="panel-message"
                    className={`p1-fp-tab-btn ${activeTab === 'message' ? 'is-active' : ''}`}
                    onClick={() => setActiveTab('message')}
                  >
                    Message
                  </button>
                  <button
                    type="button"
                    role="tab"
                    id="tab-extraction"
                    aria-selected={activeTab === 'extraction'}
                    aria-controls="panel-extraction"
                    className={`p1-fp-tab-btn ${activeTab === 'extraction' ? 'is-active' : ''}`}
                    onClick={() => setActiveTab('extraction')}
                  >
                    Extraction evidence
                  </button>
                  <button
                    type="button"
                    role="tab"
                    id="tab-identity"
                    aria-selected={activeTab === 'identity'}
                    aria-controls="panel-identity"
                    className={`p1-fp-tab-btn ${activeTab === 'identity' ? 'is-active' : ''}`}
                    onClick={() => setActiveTab('identity')}
                  >
                    Identity &amp; order
                  </button>
                  <button
                    type="button"
                    role="tab"
                    id="tab-attachments"
                    aria-selected={activeTab === 'attachments'}
                    aria-controls="panel-attachments"
                    className={`p1-fp-tab-btn ${activeTab === 'attachments' ? 'is-active' : ''}`}
                    onClick={() => setActiveTab('attachments')}
                  >
                    Attachments
                  </button>
                  <button
                    type="button"
                    role="tab"
                    id="tab-metadata"
                    aria-selected={activeTab === 'metadata'}
                    aria-controls="panel-metadata"
                    className={`p1-fp-tab-btn ${activeTab === 'metadata' ? 'is-active' : ''}`}
                    onClick={() => setActiveTab('metadata')}
                  >
                    Technical metadata
                  </button>
                </div>

                {/* Tab 1: Message */}
                <div
                  role="tabpanel"
                  id="panel-message"
                  aria-labelledby="tab-message"
                  className={`p1-fp-tab-panel ${activeTab === 'message' ? 'is-active' : ''}`}
                >
                  <section className="p1-fp-inquiry-box" aria-label="Customer reply availability">
                    <h4>Customer reply</h4>
                    <p>This message record does not provide inquiry eligibility, approved public knowledge, or a generated or sent reply. Extraction evidence is not authorization to answer a price, discount, or delivery question.</p>
                  </section>

                  <h3 className="p1-fp-section-title">Message content</h3>
                  <blockquote className="p1-fp-original-quote">
                    {extraction?.fields?.length ? renderHighlightedText(data.raw.text, extraction.fields) : data.raw.text}
                  </blockquote>
                </div>

                {/* Tab 2: Extraction evidence */}
                <div
                  role="tabpanel"
                  id="panel-extraction"
                  aria-labelledby="tab-extraction"
                  className={`p1-fp-tab-panel ${activeTab === 'extraction' ? 'is-active' : ''}`}
                >
                  <section className="p1-evidence" style={{ margin: 0, border: 'none', padding: 0 }}>
                    {extraction ? (
                      <>
                        {(extraction.fields ?? []).length > 0 ? (
                          <div className="p1-field-table-wrapper">
                            <table className="p1-field-table" aria-label="Extracted candidate fields">
                              <thead>
                                <tr>
                                  <th>Field</th>
                                  <th>Value</th>
                                  <th>Method</th>
                                  <th>Status</th>
                                  <th>Evidence quote</th>
                                </tr>
                              </thead>
                              <tbody>
                                {(extraction.fields ?? []).filter(f => !['duplicate', 'rejected'].includes(f.metadata?.disposition ?? '')).map((f, idx) => {
                                  const method = f.evidence?.[0]?.method ?? 'RULE';
                                  return (
                                    <tr key={`${f.field_name}-${idx}`} className="p1-field-row">
                                      <td className="p1-field-name-cell">
                                        <strong>
                                          {f.field_name.split('_').map((part, i, arr) => (
                                            <span key={i}>
                                              {part}
                                              {i < arr.length - 1 ? '_\u200B' : ''}
                                            </span>
                                          ))}
                                        </strong>
                                      </td>
                                      <td className="p1-field-val-cell">
                                        {f.value ? (
                                          <span className="p1-val-text">{f.value}</span>
                                        ) : (
                                          <div className="p1-unresolved-stack">
                                            <span className="p1-muted">—</span>
                                            <span className="p1-pending-tag">Pending Review</span>
                                          </div>
                                        )}
                                      </td>
                                      <td className="p1-method-cell">
                                        <div className="p1-orbyte-method-group">
                                          <span className={`p1-orbyte-source-badge is-${method.toLowerCase()}`}>
                                            {method}
                                          </span>
                                          {f.qualifier && (
                                            <span className="p1-orbyte-qualifier-badge">
                                              {f.qualifier}
                                            </span>
                                          )}
                                        </div>
                                      </td>
                                      <td className="p1-status-cell">
                                        <span className={`p1-orbyte-status-badge is-${f.validation_status.toLowerCase()}`}>
                                          {f.validation_status}
                                        </span>
                                      </td>
                                      <td className="p1-evidence-quote-cell">
                                        {f.evidence?.length ? (
                                          <div className="p1-evidence-tokens">
                                            <span className="p1-quote-chip">
                                              {f.evidence.map(ev => `"${ev.quote}" [${ev.start}:${ev.end}]`).join(' · ')}
                                            </span>
                                          </div>
                                        ) : '—'}
                                        {f.metadata?.reason ? <div className="p1-evidence-reason-note">{f.metadata.reason}</div> : null}
                                      </td>
                                    </tr>
                                  );
                                })}
                              </tbody>
                            </table>
                          </div>
                        ) : (
                          <p className="p1-muted">No explicit order fields recognized by deterministic rules.</p>
                        )}

                        {hasManualReview && (
                          <div className="p1-fp-warning-banner" role="alert" style={{ marginTop: '16px' }}>
                            Manual review required.
                          </div>
                        )}

                        <div className="p1-evidence-section-header" style={{ marginTop: '20px' }}>
                          <h4 style={{ fontSize: '13px', margin: 0, fontWeight: 650 }}>Extraction attempt</h4>
                          <span className="p1-attempt-indicator">
                            Attempt {extraction.attempt_id.slice(0, 8)} · Started {formatTime(extraction.started_at)}
                            {extraction.completed_at ? ` · Completed ${formatTime(extraction.completed_at)}` : ''}
                          </span>
                        </div>

                        <ExtractionProvenance attempt={extraction} />

                        {(extraction.fields ?? []).some(f => f.evidence?.some(e => e.method === 'MODEL')) && (
                          <details className="p1-model-proposals-details" style={{ marginTop: '16px' }}>
                            <summary className="p1-model-proposals-summary">
                              <span>Raw model observations and normalization</span>
                              <span className="p1-counter-pill">
                                {(extraction.fields ?? []).filter(f => f.evidence?.some(e => e.method === 'MODEL')).length} observations
                              </span>
                            </summary>
                            <div className="p1-model-proposals-list">
                              {(extraction.fields ?? []).filter(f => f.evidence?.some(e => e.method === 'MODEL')).map((f, i) => {
                                const disposition = f.metadata?.disposition ?? f.validation_status;
                                const isRejected = disposition === 'rejected' || disposition === 'INVALID';
                                return (
                                  <div key={i} className="p1-proposal-item-card">
                                    <div className="p1-proposal-item-header">
                                      <span className="p1-proposal-field-badge">{f.field_name}</span>
                                      <span className="p1-proposal-trace">
                                        {f.evidence?.map(e => `${e.method} "${e.quote}" [${e.start}:${e.end}]`).join(' → ')}
                                      </span>
                                      <span className="p1-proposal-arrow">→</span>
                                      <span className="p1-proposal-target">{f.value ?? 'unresolved'}</span>
                                      <span className={`p1-disposition-pill ${isRejected ? 'is-rejected' : 'is-accepted'}`}>
                                        {disposition}
                                      </span>
                                    </div>
                                    {f.metadata?.reason && (
                                      <div className="p1-proposal-reason-box">
                                        <span className="p1-proposal-reason-title">Safety Rule:</span> {f.metadata.reason}
                                      </div>
                                    )}
                                  </div>
                                );
                              })}
                            </div>
                          </details>
                        )}

                        {attempts.length > 1 && (
                          <div className="p1-attempt-history-card" style={{ marginTop: '16px' }}>
                            <h4>Attempt history ({attempts.length})</h4>
                            <div className="p1-attempt-timeline">
                              {attempts.map((att, idx) => (
                                <div key={att.attempt_id} className={`p1-attempt-row ${idx === 0 ? 'is-active' : ''}`}>
                                  <span className="p1-attempt-seq">{idx === 0 ? 'Current' : `#${attempts.length - idx}`}</span>
                                  <span className="p1-attempt-time">{formatTime(att.started_at)}</span>
                                  <span className="p1-badge p1-neutral">{att.status}</span>
                                  <span className="p1-attempt-ver p1-mono">{att.extractor_version}</span>
                                  <span className="p1-attempt-hash p1-mono">({att.attempt_id.slice(0, 8)})</span>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </>
                    ) : data.processing_status === 'PROCESSING_FAILED' ? (
                      <p className="p1-notice" role="alert">Extraction failed: {data.raw ? 'Processing failed' : ''}. Check diagnostic logs.</p>
                    ) : (
                      <div className="p1-pending-card">
                        <div className="p1-pending-content">
                          <div className="p1-pending-indicator" aria-hidden="true" />
                          <div>
                            <strong>Awaiting Extraction</strong>
                            <p className="p1-notice" style={{ margin: '6px 0 8px' }}>
                              Awaiting processing. No extraction attempt has completed.
                            </p>
                            <p style={{ margin: 0, fontSize: '11px', color: '#64748b' }}>
                              Process runs deterministic rules first; optional models are called only when needed and configured.
                            </p>
                          </div>
                        </div>
                        <button
                          type="button"
                          className="p1-primary p1-gpu-action-btn"
                          disabled={processing}
                          onClick={() => handleProcess(false)}
                        >
                          {processing ? 'Processing…' : 'Run extraction'}
                        </button>
                      </div>
                    )}
                  </section>
                </div>

                {/* Tab 3: Identity & order */}
                <div
                  role="tabpanel"
                  id="panel-identity"
                  aria-labelledby="tab-identity"
                  className={`p1-fp-tab-panel ${activeTab === 'identity' ? 'is-active' : ''}`}
                >
                  <section className="p1-evidence" aria-label="Identity and order association" style={{ margin: 0, border: 'none', padding: 0 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
                      <h3 style={{ margin: 0, fontSize: '16px' }}>Identity &amp; Order Association</h3>
                      {association && (
                        <span className={`p1-badge ${association.status === 'LINK_VERIFIED' ? 'p1-ready' : association.status === 'CONFLICT' ? 'p1-critical' : 'p1-attention'}`}>
                          {association.status} (v{association.version})
                        </span>
                      )}
                    </div>

                    {assocError && <div className="p1-conflict-box" role="alert">{assocError}</div>}

                    {association && (
                      <>
                        <div style={{ marginTop: '8px', fontSize: '13px', lineHeight: 1.6 }}>
                          <p style={{ margin: '0 0 6px' }}>
                            <strong>Verified Customer:</strong>{' '}
                            {association.verified_customer ? (
                              <span className="p1-badge p1-ready">{association.verified_customer.display_name} ({association.verified_customer.customer_id})</span>
                            ) : (
                              <span className="p1-muted">Unverified sender ({data.raw.sender_identity_id})</span>
                            )}
                          </p>
                          <p style={{ margin: 0 }}>
                            <strong>Verified Order:</strong>{' '}
                            {association.verified_order ? (
                              <span className="p1-badge p1-blue">{association.verified_order.order_id} ({association.verified_order.description || association.verified_order.status})</span>
                            ) : (
                              <span className="p1-muted">None</span>
                            )}
                          </p>
                        </div>

                        {(association.conflicts?.length ?? 0) > 0 && (
                          <div className="p1-conflict-box" role="alert" style={{ marginTop: '12px' }}>
                            <strong>Conflicts Detected:</strong>
                            <ul style={{ margin: '4px 0 0 16px', padding: 0 }}>
                              {(association.conflicts ?? []).map((c, i) => (
                                <li key={i}>{c}</li>
                              ))}
                            </ul>
                          </div>
                        )}

                        {(association.candidates?.length ?? 0) > 0 && (
                          <div style={{ marginTop: '14px' }}>
                            <h4 style={{ fontSize: '12px', marginBottom: '8px', fontWeight: 650 }}>Suggested Association Candidates</h4>
                            <ul className="p1-candidate-list" aria-label="Candidate orders">
                              {(association.candidates ?? []).map((cand, idx) => (
                                <li key={`${cand.customer_id}-${cand.order_id ?? idx}`} className="p1-candidate-card">
                                  <div className="p1-candidate-header">
                                    <strong>{cand.customer_name} ({cand.customer_id})</strong>
                                    <span className="p1-badge p1-blue">{cand.match_type} ({(cand.confidence * 100).toFixed(0)}%)</span>
                                  </div>
                                  {cand.order_id && <p style={{ margin: '4px 0' }}>Order Target: <code>{cand.order_id}</code></p>}
                                  <p className="p1-muted" style={{ fontSize: '11px', marginTop: '2px' }}>
                                    {cand.reasons.join(' · ')}
                                  </p>
                                  <div className="p1-assoc-controls" style={{ marginTop: '8px' }}>
                                    <button
                                      type="button"
                                      className="p1-action-btn"
                                      disabled={deciding}
                                      onClick={() => handleDecide('CONFIRMED', cand.customer_id, cand.order_id ?? undefined)}
                                    >
                                      Confirm link
                                    </button>
                                  </div>
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}

                        <div className="p1-assoc-controls" style={{ marginTop: '16px' }}>
                          <button
                            type="button"
                            className="p1-secondary p1-unlink-btn"
                            disabled={deciding || association.status === 'UNVERIFIED'}
                            onClick={() => {
                              setConfirmAction({
                                title: 'Reject / Unlink Association',
                                description: 'The identity and order association will be removed.',
                                onConfirm: () => {
                                  setConfirmAction(null);
                                  void handleDecide('REJECTED');
                                },
                              });
                            }}
                          >
                            Reject / Unlink
                          </button>
                        </div>

                        {association.last_decision && (
                          <div className="p1-decision-box" aria-label="Audit decision history" style={{ marginTop: '16px' }}>
                            <strong>Last Decision:</strong>{' '}
                            <span className={`p1-badge ${association.last_decision.decision === 'CONFIRMED' ? 'p1-ready' : 'p1-critical'}`}>
                              {association.last_decision.decision}
                            </span>{' '}
                            by <code>{association.last_decision.actor_id}</code> ({association.last_decision.actor_role}) at {formatTime(association.last_decision.decided_at)}
                            <p style={{ marginTop: '4px', color: '#55657d' }}>Reason: {association.last_decision.reason}</p>
                          </div>
                        )}
                      </>
                    )}
                  </section>
                </div>

                {/* Tab 4: Attachments */}
                <div
                  role="tabpanel"
                  id="panel-attachments"
                  aria-labelledby="tab-attachments"
                  className={`p1-fp-tab-panel ${activeTab === 'attachments' ? 'is-active' : ''}`}
                >
                  <section className="p1-evidence" aria-label="Attachments and OCR Evidence" style={{ margin: 0, border: 'none', padding: 0 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
                      <h3 style={{ margin: 0, fontSize: '16px' }}>Attachments &amp; Document Evidence</h3>
                      <label className="p1-action-btn" style={{ cursor: 'pointer', fontSize: '12px', padding: '6px 12px' }}>
                        {uploadingAttachment ? 'Uploading...' : 'Upload Attachment'}
                        <input
                          type="file"
                          data-testid="attachment-upload-input"
                          accept=".pdf,.png,.jpg,.jpeg"
                          style={{ display: 'none' }}
                          disabled={uploadingAttachment}
                          onChange={async (e) => {
                            const file = e.target.files?.[0];
                            if (!file) return;
                            setUploadingAttachment(true);
                            try {
                              const record = await api.uploadAttachment(file);
                              setUploadedAttachments((prev) => [...prev, record]);
                              setSelectedEvidenceRef(record.evidence_ref);
                              showToast('Attachment uploaded successfully.');
                            } catch (err: unknown) {
                              alert(err instanceof Error ? err.message : 'Attachment upload failed');
                            } finally {
                              setUploadingAttachment(false);
                              e.target.value = '';
                            }
                          }}
                        />
                      </label>
                    </div>

                    {!allAtts.length ? (
                      <p className="p1-muted">No attachments associated with this message. You can upload a PDF or image to inspect document text and OCR.</p>
                    ) : (
                      <ul className="p1-attachment-list" style={{ listStyle: 'none', padding: 0, margin: 0 }}>
                        {allAtts.map((att) => (
                          <li
                            key={att.evidence_ref}
                            className="p1-candidate-card"
                            style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}
                            data-testid={`attachment-row-${att.evidence_ref}`}
                          >
                            <div>
                              <strong>{att.filename}</strong>
                              <div className="p1-muted" style={{ fontSize: '11px', marginTop: '2px' }}>
                                {att.media_type} · {(att.size_bytes / 1024).toFixed(1)} KB · Ref: <code>{att.evidence_ref}</code>
                              </div>
                            </div>
                            <div style={{ display: 'flex', gap: '6px' }}>
                              <button
                                type="button"
                                className="p1-action-btn"
                                onClick={() => setSelectedEvidenceRef(att.evidence_ref)}
                                data-testid={`inspect-att-${att.evidence_ref}`}
                              >
                                Inspect / OCR
                              </button>
                              <a
                                href={`/v1/attachments/${encodeURIComponent(att.evidence_ref)}/content`}
                                target="_blank"
                                rel="noreferrer"
                                className="p1-secondary"
                                style={{ textDecoration: 'none', display: 'inline-flex', alignItems: 'center' }}
                              >
                                Download
                              </a>
                            </div>
                          </li>
                        ))}
                      </ul>
                    )}
                  </section>
                </div>

                {/* Tab 5: Technical metadata */}
                <div
                  role="tabpanel"
                  id="panel-metadata"
                  aria-labelledby="tab-metadata"
                  className={`p1-fp-tab-panel ${activeTab === 'metadata' ? 'is-active' : ''}`}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
                    <h3 style={{ margin: 0, fontSize: '16px' }}>Envelope &amp; Ingestion Technical Metadata</h3>
                    <span className="p1-metadata-pill">11 attributes</span>
                  </div>
                  <dl className="p1-persisted-metadata">
                    <div><dt>Sender display alias</dt><dd>{data.raw.sender_alias}</dd></div>
                    <div><dt>Platform identity (unverified)</dt><dd>{data.raw.sender_identity_id}</dd></div>
                    <div><dt>Provider</dt><dd>{data.provider || data.synthetic_provider || 'REAL'}</dd></div>
                    <div><dt>Provider message ID</dt><dd>{data.raw.provider_message_id}</dd></div>
                    <div><dt>Internal message ID</dt><dd className="p1-mono">{data.message_id}</dd></div>
                    <div><dt>Message timestamp</dt><dd>{formatTime(data.raw.message_at)}</dd></div>
                    <div><dt>First envelope receipt</dt><dd>{formatTime(data.raw.received_at)}</dd></div>
                    <div><dt>Server persisted at</dt><dd>{formatTime(data.ingested_at)}</dd></div>
                    <div><dt>Last state update</dt><dd>{formatTime(data.updated_at)}</dd></div>
                    <div><dt>Business timezone</dt><dd>{data.raw.business_timezone ?? 'Missing — no trusted default'}</dd></div>
                    <div><dt>Thread / reply</dt><dd>{data.raw.thread_ref ?? 'None'} / {data.raw.reply_to_provider_message_id ?? 'None'}</dd></div>
                  </dl>
                </div>
              </div>

              {/* Right Column: Review summary Card */}
              <div className="p1-fp-summary-card">
                <h3>Review summary</h3>
                <div className="p1-fp-summary-row">
                  <span>Processing</span>
                  <strong>{data.processing_status === 'RECEIVED' ? 'RECEIVED (Awaiting)' : data.processing_status}</strong>
                </div>
                <div className="p1-fp-summary-row">
                  <span>Extracted fields</span>
                  <strong>{(extraction?.fields ?? []).length}</strong>
                </div>
                <div className="p1-fp-summary-row">
                  <span>Unresolved fields</span>
                  <strong>{unresolvedCount}</strong>
                </div>
                <div className="p1-fp-summary-row">
                  <span>Identity</span>
                  <strong>{association ? association.status : 'UNVERIFIED'}</strong>
                </div>
                <div className="p1-fp-summary-row">
                  <span>Attachments</span>
                  <strong>{allAtts.length}</strong>
                </div>

                {hasManualReview && (
                  <div className="p1-fp-warning-banner">
                    Manual review required.
                  </div>
                )}

                <button
                  type="button"
                  className="p1-fp-btn-primary"
                  disabled={contextLoading || data.processing_status !== 'PROCESSED'}
                  onClick={handleDirectReview}
                >
                  {contextLoading ? 'Opening Review…' : 'Review & Amend'}
                </button>

                {association?.verified_order?.order_id ? (
                  <button
                    type="button"
                    className="p1-fp-btn-secondary"
                    onClick={() => {
                      const orderId = association?.verified_order?.order_id;
                      if (orderId && typeof window !== 'undefined') {
                        window.location.href = `/orders/${encodeURIComponent(orderId)}`;
                      }
                    }}
                  >
                    View Order Context
                  </button>
                ) : (
                  <>
                    <button
                      type="button"
                      className="p1-fp-btn-secondary is-disabled"
                      disabled
                      title="No verified order is linked yet"
                    >
                      View Order Context
                    </button>
                    <p className="p1-detail-no-order-hint">
                      No verified order is linked yet. Link one in Identity &amp; order.
                    </p>
                  </>
                )}

                <hr className="p1-fp-summary-divider" />
                <p className="p1-fp-summary-disclaimer">
                  The reply above is not an authorisation to answer price, discount or delivery questions.
                </p>
              </div>
            </div>
          </>
        )}

        {selectedEvidenceRef && (
          <AttachmentViewer
            evidenceRef={selectedEvidenceRef}
            onClose={() => setSelectedEvidenceRef(null)}
            api={api}
          />
        )}

        {showContextModal && activeContext && (typeof document !== 'undefined' ? createPortal(
          <div className="p1-modal-backdrop" role="dialog" aria-modal="true" aria-label="Order Context Details">
            <div className="p1-modal-card">
              <OrderContextDetail
                requestHeaders={{ 'X-Tenant-ID': activeContext.tenant_id, ...(auth ? { 'X-Actor-ID': auth.actorId } : {}) }}
                contextId={activeContext.context_id}
                onClose={() => setShowContextModal(false)}
                onContextUpdated={updated => setActiveContext(updated)}
              />
            </div>
          </div>,
          document.body
        ) : (
          <div className="p1-modal-backdrop" role="dialog" aria-modal="true" aria-label="Order Context Details">
            <div className="p1-modal-card">
              <OrderContextDetail
                requestHeaders={{ 'X-Tenant-ID': activeContext.tenant_id, ...(auth ? { 'X-Actor-ID': auth.actorId } : {}) }}
                contextId={activeContext.context_id}
                onClose={() => setShowContextModal(false)}
                onContextUpdated={updated => setActiveContext(updated)}
              />
            </div>
          </div>
        ))}

        {showReviewDrawer && activeContext && (
          <ReviewDrawer
            requestHeaders={{ 'X-Tenant-ID': activeContext.tenant_id, ...(auth ? { 'X-Actor-ID': auth.actorId } : {}) }}
            context={activeContext}
            sourceMessage={data && activeContext.source_message_ids?.includes(data.message_id) ? data.raw.text : undefined}
            message={data}
            extraction={extraction}
            isOpen={showReviewDrawer}
            onClose={() => setShowReviewDrawer(false)}
            onUpdated={(updated) => {
              setActiveContext(updated);
              if (updated.status === 'UNRESOLVED') {
                setReviewDecision('Unresolved');
              } else if (getResolvedTaskIds().has(id) || getResolvedTaskIds().has(updated.context_id) || updated.status === 'INFORMATION_READY') {
                setReviewDecision('Accepted');
              } else if (updated.last_reviewed_at) {
                setReviewDecision('In progress');
              }
              onUpdated?.();
            }}
          />
        )}

        {confirmAction && (
          <div className="p1-confirm-backdrop" role="dialog" aria-modal="true" aria-labelledby="confirm-action-title">
            <div className="p1-confirm-modal">
              <h3 id="confirm-action-title">{confirmAction.title}</h3>
              <p>{confirmAction.description}</p>
              <div className="p1-confirm-actions">
                <button type="button" className="p1-btn p1-btn-secondary" onClick={() => setConfirmAction(null)}>Cancel</button>
                <button type="button" className="p1-btn p1-btn-primary" onClick={confirmAction.onConfirm}>Confirm</button>
              </div>
            </div>
          </div>
        )}

        {toast && (
          <div className="p1-toast" role="status">
            {toast}
          </div>
        )}
      </section>
    </>
  );
}

