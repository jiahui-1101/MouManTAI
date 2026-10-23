import { useEffect, useRef, useState } from 'react';

import { createPortal } from 'react-dom';

import type { ReactNode } from 'react';

import { PreviewError } from './api';

import { operationalApi } from './operationalApi';

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



function formatChannel(channel: string | undefined): string {

  if (!channel) return 'Unknown';

  const clean = channel.replace(/^SYNTHETIC_/, '');
  if (clean === 'WHATSAPP') return 'WhatsApp';

  return clean.charAt(0).toUpperCase() + clean.slice(1).toLowerCase();

}



type SortKey = 'ingested_at' | 'text' | 'processing_status';

type SortDir = 'asc' | 'desc';



function sortMessages(items: StoredMessage[], by: SortKey, dir: SortDir): StoredMessage[] {

  return [...items].sort((a, b) => {

    let cmp = 0;

    if (by === 'ingested_at') {

      cmp = (a.ingested_at ?? '').localeCompare(b.ingested_at ?? '');

    } else if (by === 'text') {

      cmp = (a.raw?.text ?? '').localeCompare(b.raw?.text ?? '');

    } else if (by === 'processing_status') {

      cmp = (a.processing_status ?? '').localeCompare(b.processing_status ?? '');

    }

    return dir === 'asc' ? cmp : -cmp;

  });

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



  function select(id: string, button: HTMLButtonElement) { returnFocus.current = button; setSelected(id); }

  function closeDetail() { setSelected(null); returnFocus.current?.focus(); }

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



  return <div className="p1-inbox">

    <header className="p1-page-heading"><div><h1>Message Inbox</h1><p>Start with the original customer or supplier message, then review the extracted business context.</p></div><button type="button" className="p1-secondary" disabled={resource.state !== 'ready' || composing} onClick={() => { setSaved(null); setComposing(true); }}>+ Add test message</button></header>
    <section className="p1-channel-guide" aria-label="Supported message sources"><div><strong>Message sources</strong><p>WhatsApp · Email · Telegram</p></div><span>Synthetic adapters for local demos; no live account connection.</span><span>Message → extraction evidence → human review → publish</span></section>

    <div className="p1-tabs"><span className="p1-active-label">Persisted messages</span><span className="p1-demo-label">Local PostgreSQL · synthetic channel only</span></div>

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

    </div><div className="p1-filter-caption"><span>{resource.state === 'ready' ? `${resource.page.total} persisted messages` : 'PostgreSQL Inbox'}</span><span>Display timezone · Asia/Kuala_Lumpur</span></div></section>

    {resource.state === 'loading' && <p role="status" className="p1-state">Loading persisted messages…</p>}

    {resource.state === 'error' && <div role="alert" className="p1-state"><h2>{resource.error instanceof PreviewError && [401, 403].includes(resource.error.status) ? 'Access denied' : 'Inbox unavailable'}</h2><p>{resource.error.message}</p><button type="button" className="p1-secondary" onClick={() => setAttempt(n => n + 1)}>Retry Inbox</button></div>}

    {resource.state === 'ready' && <section className="p1-table-card" aria-label="Persisted messages"><div className="p1-table-scroll" role="region" aria-label="Persisted message table, scroll horizontally on small screens" tabIndex={0}>

      <table className="p1-orbyte-main-table"><caption className="p1-sr-only">Persisted original messages awaiting downstream work</caption><thead><tr>

        <th scope="col" className={`p1-th-sortable${sortBy === 'ingested_at' ? ' is-active' : ''}`} aria-sort={sortBy === 'ingested_at' ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'} onClick={() => handleSort('ingested_at')}>Received At <span className="p1-th-arrows">{sortBy === 'ingested_at' ? (sortDir === 'asc' ? '↑' : '↓') : '↑↓'}</span></th>

        <th scope="col" className={`p1-th-sortable${sortBy === 'text' ? ' is-active' : ''}`} aria-sort={sortBy === 'text' ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'} onClick={() => handleSort('text')}>Original Message <span className="p1-th-arrows">{sortBy === 'text' ? (sortDir === 'asc' ? '↑' : '↓') : '↑↓'}</span></th>

        <th scope="col">Source</th>

        <th scope="col" className={`p1-th-sortable${sortBy === 'processing_status' ? ' is-active' : ''}`} aria-sort={sortBy === 'processing_status' ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'} onClick={() => handleSort('processing_status')}>Processing <span className="p1-th-arrows">{sortBy === 'processing_status' ? (sortDir === 'asc' ? '↑' : '↓') : '↑↓'}</span></th>

        <th scope="col">Information</th><th scope="col">Identity</th><th scope="col">Review</th><th scope="col" className="p1-th-actions">Actions</th>

      </tr></thead>

      <tbody>{sortMessages(resource.page.items, sortBy, sortDir).map(message => <tr key={message.message_id} className="p1-inbox-row"><td className="p1-date"><time dateTime={message.ingested_at}>{formatTime(message.ingested_at)}</time></td><td className="p1-message-cell"><button type="button" className="p1-title-button" onClick={event => select(message.message_id, event.currentTarget)}>{message.raw.sender_alias}</button><span className="p1-row-secondary">{message.raw.text}</span><span className="p1-row-secondary p1-subtle-id">{message.raw.provider_message_id}</span></td><td className="p1-source-cell"><span className="p1-orbyte-source-badge">{formatChannel(message.raw.channel)}</span></td><td><span className={`p1-orbyte-status-badge is-${message.processing_status === 'PROCESSED' ? 'valid' : message.processing_status === 'PROCESSING' ? 'attention' : message.processing_status === 'PROCESSING_FAILED' ? 'conflict' : 'neutral'}`}>{message.processing_status}</span></td><td className="p1-identity">{message.processing_status === 'PROCESSED' ? (message.extractor_version?.startsWith('p1-ai-pipeline-') ? <span className="p1-orbyte-status-badge is-model">AI pipeline · inspect trace</span> : <span className="p1-orbyte-status-badge is-valid">Extracted (RULE)</span>) : message.processing_status === 'PROCESSING' ? <span className="p1-orbyte-status-badge is-attention">Extracting…</span> : message.processing_status === 'PROCESSING_FAILED' ? <span className="p1-orbyte-status-badge is-conflict">Extraction failed</span> : <span className="p1-orbyte-status-badge is-neutral">Awaiting extraction</span>}</td><td className="p1-subtle-text">Inspect detail</td><td className="p1-subtle-text">Inspect detail</td><td className="p1-actions-cell"><div className="p1-orbyte-actions-group"><button type="button" className="p1-orbyte-action-icon-btn" aria-label={`View message ${message.raw.provider_message_id}`} title="Inspect message details" onClick={event => select(message.message_id, event.currentTarget)}><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg></button><button type="button" className="p1-orbyte-action-icon-btn is-sync" disabled={processingId === message.message_id} aria-label={`Reprocess message ${message.raw.provider_message_id}`} title={message.processing_status === 'PROCESSED' ? 'Reprocess extraction' : 'Run extraction'} onClick={() => handleInlineProcess(message.message_id, message.processing_status === 'PROCESSED')}><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={processingId === message.message_id ? 'p1-spin' : ''}><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg></button></div></td></tr>)}</tbody></table>

    </div>{resource.page.items.length === 0 && <p role="status" className="p1-empty">No persisted messages match this view. Add a test message to begin.</p>}

      <footer className="p1-table-footer"><span className="p1-footer-count">Showing {resource.page.items.length ? offset + 1 : 0} to {Math.min(offset + resource.page.items.length, resource.page.total)} of {resource.page.total} entries</span><div className="p1-orbyte-pagination"><div className="p1-rows-per-page"><span>Rows per page:</span><span className="p1-rows-badge">15</span></div><div className="p1-pagination-controls"><button type="button" className="p1-page-btn" disabled={offset === 0} aria-label="Previous" onClick={() => setOffset(n => Math.max(0, n - PAGE_SIZE))}>‹</button><span className="p1-page-active">{Math.floor(offset / PAGE_SIZE) + 1}</span><button type="button" className="p1-page-btn" disabled={offset + PAGE_SIZE >= resource.page.total || offset + PAGE_SIZE > 10_000} aria-label="Next" onClick={() => setOffset(n => n + PAGE_SIZE)}>›</button></div></div></footer>

    </section>}

    <p className="p1-preview-note">Local development tenant only · no production authentication. Synthetic multi-channel adapters (WhatsApp, Email, Telegram) are implemented. Deterministic extraction is persisted with exact Unicode evidence spans.</p>

    {selected && <StoredMessageDetail id={selected} api={api} onUpdated={() => setAttempt(n => n + 1)} onClose={closeDetail} />}

  </div>;

}



function StoredMessageDetail({ id, api, onUpdated, onClose }: { id: string; api: OperationalApi; onUpdated?: () => void; onClose: () => void }) {

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

  const panel = useRef<HTMLElement>(null);

  useEffect(() => { panel.current?.focus(); }, []);



  const [panelWidth, setPanelWidth] = useState<number>(() => {

    try {

      const saved = localStorage.getItem('moumantai_panel_width');

      if (saved) {

        const val = parseInt(saved, 10);

        if (!isNaN(val) && val >= 380 && val <= (typeof window !== 'undefined' ? window.innerWidth * 0.95 : 1200)) {

          return val;

        }

      }

    } catch {}

    return 580;

  });

  const [isResizing, setIsResizing] = useState(false);



  useEffect(() => {

    if (!isResizing) return;

    function handleMouseMove(e: MouseEvent) {

      const rightOffset = showReviewDrawer ? 520 : 0;

      const maxWidth = Math.max(380, window.innerWidth - rightOffset - 40);

      const newWidth = Math.max(380, Math.min(window.innerWidth - rightOffset - e.clientX, maxWidth));

      setPanelWidth(newWidth);

    }

    function handleMouseUp() {

      setIsResizing(false);

      try {

        localStorage.setItem('moumantai_panel_width', panelWidth.toString());

      } catch {}

    }

    window.addEventListener('mousemove', handleMouseMove);

    window.addEventListener('mouseup', handleMouseUp);

    document.body.style.cursor = 'col-resize';

    document.body.style.userSelect = 'none';

    return () => {

      window.removeEventListener('mousemove', handleMouseMove);

      window.removeEventListener('mouseup', handleMouseUp);

      document.body.style.cursor = '';

      document.body.style.userSelect = '';

    };

  }, [isResizing, panelWidth, showReviewDrawer]);



  useEffect(() => {

    function onKeyDown(e: KeyboardEvent) {

      if (e.key === 'Escape') {

        if (showReviewDrawer) {

          setShowReviewDrawer(false);

        } else {

          onClose();

        }

      }

    }

    window.addEventListener('keydown', onKeyDown);

    return () => window.removeEventListener('keydown', onKeyDown);

  }, [onClose, showReviewDrawer]);



  useEffect(() => {

    let active = true;

    setData(null); setExtraction(null); setAttempts([]); setAssociation(null); setError(null); setAssocError(null);

    setActiveContext(null); setShowContextModal(false); setShowReviewDrawer(false); setContextLoading(false); setContextError(null);

    setSelectedEvidenceRef(null); setUploadedAttachments([]);

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



  async function handleOpenOrderContext() {

    setContextLoading(true);

    setContextError(null);

    try {

      const ctx = await api.createContextFromMessage(id);

      setActiveContext(ctx);

      setShowContextModal(true);

    } catch (err) {

      setContextError(err instanceof Error ? err.message : 'Failed to generate/view order context');

    } finally {

      setContextLoading(false);

    }

  }



  async function handleDirectReview() {

    setContextLoading(true);

    setContextError(null);

    try {

      const ctx = await api.createContextFromMessage(id);

      setActiveContext(ctx);

      setShowReviewDrawer(true);

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

      onUpdated?.();

    } catch (err) {

      setAssocError(err instanceof Error ? err.message : 'Decision failed');

      api.getAssociation(id).then(setAssociation).catch(() => {});

    } finally {

      setDeciding(false);

    }

  }



  return <>

    <div className="p1-drawer-backdrop" onClick={onClose} aria-label="Close message details" role="button" tabIndex={0} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') onClose(); }} />

    <section className={`p1-detail ${isResizing ? 'p1-is-resizing' : ''} ${showReviewDrawer ? 'p1-detail-shifted' : ''}`} style={{ width: `${panelWidth}px` }} ref={panel} tabIndex={-1} aria-label="Persisted message details">

      <div className={`p1-resize-handle ${isResizing ? 'active' : ''}`} onMouseDown={e => { e.preventDefault(); setIsResizing(true); }} title="Drag left or right to resize panel width">

        <div className="p1-resize-handle-bar" />

      </div>

      <header className="p1-detail-heading">

        <div className="p1-detail-heading-left">

          <p className="p1-eyebrow">PERSISTED SOURCE · SYNTHETIC</p>

          <div className="p1-detail-title-row">

            <h2>Original message</h2>

            {data && <span className="p1-orbyte-source-badge">{formatChannel(data.raw?.channel)}</span>}

          </div>

        </div>

        <button type="button" className="p1-close-button" aria-label="Close message details" onClick={onClose}>

          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">

            <line x1="18" y1="6" x2="6" y2="18"></line>

            <line x1="6" y1="6" x2="18" y2="18"></line>

          </svg>

          <span>Close</span>

        </button>

      </header>

    {!data && !error && <p role="status">Loading original message…</p>}

    {error && <div role="alert"><p>{error}</p><button type="button" className="p1-secondary" onClick={() => setAttempt(n => n + 1)}>Retry message</button></div>}

    {data && <>

      <div className="p1-detail-actions">

        {data.processing_status === 'RECEIVED' && (

          <button type="button" className="p1-btn p1-btn-primary p1-primary" disabled={processing} onClick={() => handleProcess(false)}>

            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><polygon points="5 3 19 12 5 21 5 3"/></svg>

            <span>{processing ? 'Processing…' : 'Process extraction'}</span>

          </button>

        )}

        {data.processing_status === 'PROCESSED' && (

          <>

            <button

              type="button"

              className="p1-btn p1-btn-primary p1-primary"

              disabled={contextLoading}

              onClick={handleDirectReview}

            >

              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>

              <span>{contextLoading ? 'Opening Review…' : 'Review & Amend'}</span>

            </button>

            <button

              type="button"

              className="p1-btn p1-btn-secondary p1-secondary"

              disabled={contextLoading}

              onClick={handleOpenOrderContext}

            >

              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>

              <span>{contextLoading ? 'Opening Context…' : 'View Order Context'}</span>

            </button>

            <button type="button" className="p1-btn p1-btn-secondary p1-secondary" disabled={processing} onClick={() => handleProcess(true)}>

              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className={processing ? 'p1-spin' : ''}><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>

              <span>{processing ? 'Reprocessing…' : 'Reprocess extraction'}</span>

            </button>

          </>

        )}

        {data.processing_status === 'PROCESSING_FAILED' && (

          <button type="button" className="p1-btn p1-btn-primary p1-primary" disabled={processing} onClick={() => handleProcess(true)}>

            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>

            <span>{processing ? 'Retrying…' : 'Retry extraction'}</span>

          </button>

        )}

      </div>

      {contextError && <p className="p1-conflict-box" role="alert">{contextError}</p>}

      <dl className="p1-dimensions">

        <div><dt>Processing</dt><dd>{data.processing_status}</dd></div>

        <div><dt>Information</dt><dd>{extraction ? `Extracted (${(extraction.fields ?? []).length} fields)` : 'Not extracted'}</dd></div>

        <div><dt>Identity</dt><dd>{association ? association.status : 'Unavailable'}</dd></div>

        <div><dt>Review</dt><dd>{association?.last_decision ? association.last_decision.decision : 'Not started'}</dd></div>

      </dl>

      <blockquote className="p1-original">

        {extraction?.fields?.length ? renderHighlightedText(data.raw.text, extraction.fields) : data.raw.text}

      </blockquote>

      <details className="p1-metadata-accordion">

        <summary className="p1-metadata-summary">

          <span>Envelope & Ingestion Technical Metadata</span>

          <span className="p1-metadata-pill">11 attributes</span>

        </summary>

        <dl className="p1-persisted-metadata">

          <div><dt>Sender display alias</dt><dd>{data.raw.sender_alias}</dd></div>

          <div><dt>Platform identity (unverified)</dt><dd>{data.raw.sender_identity_id}</dd></div>

          <div><dt>Provider</dt><dd>{data.synthetic_provider}</dd></div>

          <div><dt>Provider message ID</dt><dd>{data.raw.provider_message_id}</dd></div>

          <div><dt>Internal message ID</dt><dd className="p1-mono">{data.message_id}</dd></div>

          <div><dt>Message timestamp</dt><dd>{formatTime(data.raw.message_at)}</dd></div>

          <div><dt>First envelope receipt</dt><dd>{formatTime(data.raw.received_at)}</dd></div>

          <div><dt>Server persisted at</dt><dd>{formatTime(data.ingested_at)}</dd></div>

          <div><dt>Last state update</dt><dd>{formatTime(data.updated_at)}</dd></div>

          <div><dt>Business timezone</dt><dd>{data.raw.business_timezone ?? 'Missing — no trusted default'}</dd></div>

          <div><dt>Thread / reply</dt><dd>{data.raw.thread_ref ?? 'None'} / {data.raw.reply_to_provider_message_id ?? 'None'}</dd></div>

        </dl>

      </details>



      <section className="p1-evidence">

        <div className="p1-evidence-section-header">

          <h3>Extraction evidence</h3>

          {extraction && (

            <span className="p1-attempt-indicator">

              Attempt {extraction.attempt_id.slice(0, 8)} · Started {formatTime(extraction.started_at)}

              {extraction.completed_at ? ` · Completed ${formatTime(extraction.completed_at)}` : ''}

            </span>

          )}

        </div>

        {extraction ? (

          <>

            <ExtractionProvenance attempt={extraction} />

            {(extraction.fields ?? []).length > 0 ? (

              <div className="p1-field-table-wrapper" role="region" aria-label="Extracted fields, scroll horizontally on small screens" tabIndex={0}>

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

            {(extraction.fields ?? []).some(f => f.evidence?.some(e => e.method === 'MODEL')) && (

              <details className="p1-model-proposals-details">

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

              <div className="p1-attempt-history-card">

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



      <section className="p1-evidence" aria-label="Identity and order association">

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>

          <h3>Identity & Order Association</h3>

          {association && (

            <span className={`p1-badge ${association.status === 'LINK_VERIFIED' ? 'p1-ready' : association.status === 'CONFLICT' ? 'p1-critical' : 'p1-attention'}`}>

              {association.status} (v{association.version})

            </span>

          )}

        </div>



        {assocError && <div className="p1-conflict-box" role="alert">{assocError}</div>}



        {association && (

          <>

            <div style={{ marginTop: '8px', fontSize: '11px' }}>

              <p>

                <strong>Verified Customer:</strong>{' '}

                {association.verified_customer ? (

                  <span className="p1-badge p1-ready">{association.verified_customer.display_name} ({association.verified_customer.customer_id})</span>

                ) : (

                  <span className="p1-muted">Unverified sender ({data.raw.sender_identity_id})</span>

                )}

              </p>

              <p style={{ marginTop: '4px' }}>

                <strong>Verified Order:</strong>{' '}

                {association.verified_order ? (

                  <span className="p1-badge p1-blue">{association.verified_order.order_id} ({association.verified_order.description || association.verified_order.status})</span>

                ) : (

                  <span className="p1-muted">None</span>

                )}

              </p>

            </div>



            {(association.conflicts?.length ?? 0) > 0 && (

              <div className="p1-conflict-box" role="alert">

                <strong>Conflicts Detected:</strong>

                <ul style={{ margin: '4px 0 0 16px', padding: 0 }}>

                  {(association.conflicts ?? []).map((c, i) => (

                    <li key={i}>{c}</li>

                  ))}

                </ul>

              </div>

            )}



            {(association.candidates?.length ?? 0) > 0 && (

              <div style={{ marginTop: '10px' }}>

                <h4 style={{ fontSize: '11px', marginBottom: '6px' }}>Suggested Association Candidates</h4>

                <ul className="p1-candidate-list" aria-label="Candidate orders">

                  {(association.candidates ?? []).map((cand, idx) => (

                    <li key={`${cand.customer_id}-${cand.order_id ?? idx}`} className="p1-candidate-card">

                      <div className="p1-candidate-header">

                        <strong>{cand.customer_name} ({cand.customer_id})</strong>

                        <span className="p1-badge p1-blue">{cand.match_type} ({(cand.confidence * 100).toFixed(0)}%)</span>

                      </div>

                      {cand.order_id && <p>Order Target: <code>{cand.order_id}</code></p>}

                      <p className="p1-muted" style={{ fontSize: '10px', marginTop: '2px' }}>

                        {cand.reasons.join(' · ')}

                      </p>

                      <div className="p1-assoc-controls">

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



            <div className="p1-assoc-controls" style={{ marginTop: '8px' }}>

              <button

                type="button"

                className="p1-secondary"

                disabled={deciding || association.status === 'UNVERIFIED'}

                onClick={() => handleDecide('REJECTED')}

              >

                Reject / Unlink

              </button>

            </div>



            {association.last_decision && (

              <div className="p1-decision-box" aria-label="Audit decision history">

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



      <section className="p1-evidence" aria-label="Attachments and OCR Evidence">

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>

          <h3>Attachments & Document Evidence</h3>

          <label className="p1-action-btn" style={{ cursor: 'pointer', fontSize: '11px', padding: '4px 8px' }}>

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



        {(() => {

          const rawAtts = (data.raw.attachments as AttachmentRecord[] | undefined) || [];

          const allAtts = [...rawAtts, ...uploadedAttachments];

          if (!allAtts.length) {

            return <p className="p1-muted">No attachments associated with this message. You can upload a PDF or image to inspect document text and OCR.</p>;

          }

          return (

            <ul className="p1-attachment-list" style={{ listStyle: 'none', padding: 0, marginTop: '10px' }}>

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

          );

        })()}

      </section>



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

              contextId={activeContext.context_id}

              onClose={() => setShowContextModal(false)}

              onContextUpdated={updated => setActiveContext(updated)}

            />

          </div>

        </div>

      ))}

      {showReviewDrawer && activeContext && (

        <ReviewDrawer

          context={activeContext}

          isOpen={showReviewDrawer}

          onClose={() => setShowReviewDrawer(false)}

          onUpdated={(updated) => {

            setActiveContext(updated);

            setShowReviewDrawer(false);

            onUpdated?.();

          }}

        />

      )}

    </>}

  </section></>;

}

