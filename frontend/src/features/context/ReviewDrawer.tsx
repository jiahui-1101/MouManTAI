import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { ContextReviewRecord, ContextReviewRequest, ExtractionAttemptRecord, OrderContextRecord, RequestedItem, StoredMessage } from './types';
import { getConversationIssues, sendClarification } from './clarificationApi';
import type { ClarificationIssue } from './clarificationModels';
import { getReviewCatalog, markTaskResolved, notifyReviewContextSaved, operationalApi, unmarkTaskResolved } from './operationalApi';
import { extractEvidenceItemGroups, reviewCandidates } from './reviewCandidates';
import { ExtractionProvenance } from './ExtractionProvenance';
import { RequestedDeliveryField } from './RequestedDeliveryField';
import { useOptionalAuth } from '../../shared/auth';
import './humanReview.css';
import './reviewAmend.css';

export interface ReviewDrawerProps {
  context: OrderContextRecord;
  sourceMessage?: string;
  message?: StoredMessage | null;
  extraction?: ExtractionAttemptRecord | null;
  isOpen: boolean;
  onClose: () => void;
  onUpdated: (updated: OrderContextRecord) => void;
  catalogLoader?: () => Promise<{ sku: string; unit: string }[]>;
  requestHeaders?: Record<string, string>;
  actorId?: string;
  actorRole?: string;
}

export function getSuggestedClarification(context: OrderContextRecord): string | null {
  const missing = context.missing_fields || [];
  const conflicts = context.conflicts || [];
  const sku = context.requested_items?.[0]?.sku || String(context.field_evidence?.sku?.[0]?.normalized_value || context.field_evidence?.sku?.[0]?.quote || '');
  const qty = context.requested_items?.[0]?.quantity || String(context.field_evidence?.quantity?.[0]?.normalized_value || context.field_evidence?.quantity?.[0]?.quote || '');
  const unit = context.requested_items?.[0]?.unit || String(context.field_evidence?.unit?.[0]?.normalized_value || context.field_evidence?.unit?.[0]?.quote || '');
  if ((missing.includes('unit') || (!unit && Boolean(sku || qty))) && qty && sku) return `Could you please confirm the unit for the ${qty} ${sku.toLowerCase()} (e.g., pcs or boxes)?`;
  if ((missing.includes('unit') || !unit) && qty) return `Could you please confirm the unit for the ${qty} items requested (e.g., pcs or boxes)?`;
  if (missing.includes('requested_delivery_at') || (!context.requested_delivery_at && !context.field_evidence?.requested_delivery_at?.length)) return 'Could you please confirm your preferred delivery date and time?';
  if (missing.includes('quantity')) return `Could you please specify the quantity needed for ${sku || 'your order'}?`;
  if (missing.includes('sku') || missing.includes('requested_items')) return 'Could you please clarify which item or product you would like to order?';
  if (conflicts.length) return `Could you please clarify the following order details: ${conflicts[0]}?`;
  return null;
}

function initialItems(context: OrderContextRecord): RequestedItem[] {
  if (context.requested_items?.length) return context.requested_items.map(item => ({ sku: item.sku || '', quantity: item.quantity || '', unit: item.unit || '' }));
  const groups = extractEvidenceItemGroups(context);
  if (groups.length) return groups.map(group => ({ sku: group.validSku || '', quantity: group.quantity || '', unit: group.unit || '' }));
  return [{ sku: '', quantity: String(context.field_evidence?.quantity?.[0]?.normalized_value || ''), unit: String(context.field_evidence?.unit?.[0]?.normalized_value || '') }];
}

function initialDelivery(context: OrderContextRecord): string {
  const candidate = String(context.field_evidence?.requested_delivery_at?.[0]?.normalized_value || '');
  return context.requested_delivery_at || (/^\d{4}-\d{2}-\d{2}(?:T.*)?$/.test(candidate) ? candidate : '');
}

function Evidence({ context, field, label }: { context: OrderContextRecord; field: string; label: string }) {
  const values = context.field_evidence?.[field] || [];
  return <details className="ra-evidence"><summary aria-label={`Show ${label} evidence`}>Evidence {values.length ? `(${values.length})` : ''}</summary>
    {values.length ? values.map((entry, index) => <div key={index} className="ra-evidence-row"><q>{String(entry.quote || 'No source quote')}</q><span>{String(entry.method || 'Unknown method')} · {String(entry.message_id || 'Source unspecified')} [{String(entry.start ?? '?')}:{String(entry.end ?? '?')}]</span></div>) : <p>No field evidence is available.</p>}
  </details>;
}

function MarkedMessage({ text, context, activeField }: { text: string; context: OrderContextRecord; activeField: string | null }) {
  const spans = useMemo(() => {
    const found: { start: number; end: number; field: string }[] = [];
    for (const [field, entries] of Object.entries(context.field_evidence || {})) {
      for (const entry of entries) {
        const start = Number(entry.start), end = Number(entry.end);
        if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end > text.length || start >= end) continue;
        if (entry.quote && text.slice(start, end) !== String(entry.quote)) continue;
        found.push({ start, end, field });
      }
    }
    found.sort((a, b) => a.start - b.start || b.end - a.end);
    return found.filter((span, index) => index === 0 || span.start >= found[index - 1].end);
  }, [text, context]);
  const output: React.ReactNode[] = [];
  let offset = 0;
  for (const span of spans) {
    if (span.start < offset) continue;
    output.push(text.slice(offset, span.start));
    output.push(<mark key={`${span.field}-${span.start}`} data-evidence-field={span.field} className={activeField === span.field ? 'is-active' : ''}>{text.slice(span.start, span.end)}</mark>);
    offset = span.end;
  }
  output.push(text.slice(offset));
  return <blockquote className="ra-message">{output}</blockquote>;
}

export function ReviewDrawer(props: ReviewDrawerProps) {
  if (!props.isOpen) return null;
  return <ReviewAmendWorkspace key={props.context.context_id} {...props} />;
}

function ReviewAmendWorkspace({ context, sourceMessage, message, extraction, onClose, onUpdated, catalogLoader, requestHeaders, actorId, actorRole }: ReviewDrawerProps) {
  const auth = useOptionalAuth();
  const headers = useMemo<Record<string, string>>(() => {
    const currentActor = actorId || auth?.actorId;
    // A caller-scoped actor must not inherit another actor's role from the shell.
    const currentRole = actorRole || (currentActor === auth?.actorId ? auth?.actorRole : undefined);
    return {
      ...(auth?.tenantId ? { 'X-Tenant-ID': auth.tenantId } : {}),
      ...(currentActor ? { 'X-Actor-ID': currentActor } : {}),
      ...(currentRole && (!requestHeaders?.['X-Actor-ID'] || requestHeaders['X-Actor-ID'] === currentActor) ? { 'X-Actor-Role': currentRole } : {}),
      ...requestHeaders,
    };
  }, [auth?.tenantId, auth?.actorId, auth?.actorRole, actorId, actorRole, requestHeaders]);
  const loadCatalog = useCallback(() => catalogLoader ? catalogLoader() : getReviewCatalog(headers), [catalogLoader, headers]);
  const [record, setRecord] = useState(context);
  const [items, setItems] = useState<RequestedItem[]>(() => initialItems(context));
  const [deliveryAt, setDeliveryAt] = useState(() => initialDelivery(context));
  const [qualifier, setQualifier] = useState(context.delivery_qualifier || String(context.field_evidence?.requested_delivery_at?.[0]?.qualifier || ''));
  const [specialInstructions, setSpecialInstructions] = useState(context.special_instructions || '');
  const [note, setNote] = useState('');
  const [conflictsReviewed, setConflictsReviewed] = useState(false);
  const [majorFieldConfirmed, setMajorFieldConfirmed] = useState(false);
  const [catalog, setCatalog] = useState<{ sku: string; unit: string }[]>([]);
  const [catalogState, setCatalogState] = useState<'loading' | 'ready' | 'unavailable'>('loading');
  const [targetItem, setTargetItem] = useState('');
  const [activeTab, setActiveTab] = useState<'amend' | 'reply' | 'identity' | 'audit'>('amend');
  const [auditReviews, setAuditReviews] = useState<ContextReviewRecord[]>([]);
  const [issues, setIssues] = useState<ClarificationIssue[]>([]);
  const [replyPurpose, setReplyPurpose] = useState<'CLARIFICATION' | 'Commercial reply' | 'Manual reply'>('CLARIFICATION');
  const [replyChannel, setReplyChannel] = useState<string>('EMAIL');
  const [replyMessage, setReplyMessage] = useState<string>('');
  const [replyPreviewOpen, setReplyPreviewOpen] = useState(false);
  const [replySending, setReplySending] = useState(false);
  const [replySentResult, setReplySentResult] = useState<string | null>(null);
  const [markUnresolvedModalOpen, setMarkUnresolvedModalOpen] = useState(false);
  const [markUnresolvedReason, setMarkUnresolvedReason] = useState('Keep unresolved evidence for follow-up');
  const [reprocessConfirmOpen, setReprocessConfirmOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [closeRequested, setCloseRequested] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveNotice, setSaveNotice] = useState<string | null>(null);
  const [activeField, setActiveField] = useState<string | null>(null);
  const sourceRef = useRef<HTMLElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const original = sourceMessage || message?.raw?.text || '';
  const candidates = reviewCandidates(record);
  const suggested = getSuggestedClarification(record);
  const itemsDirty = JSON.stringify(items) !== JSON.stringify(initialItems(record));
  const deliveryDirty = deliveryAt !== initialDelivery(record) || qualifier !== (record.delivery_qualifier || String(record.field_evidence?.requested_delivery_at?.[0]?.qualifier || ''));
  const instructionsDirty = specialInstructions !== (record.special_instructions || '');
  const dirty = itemsDirty || deliveryDirty || instructionsDirty || conflictsReviewed;
  const majorFieldDirty = itemsDirty || deliveryDirty;
  const noteReady = !!note.trim();
  const itemValuesReady = items.length > 0 && items.every(item => !!item.sku.trim() && !!item.unit.trim() && /^[0-9]+(?:\.[0-9]+)?$/.test(item.quantity.trim()) && Number(item.quantity) > 0);
  const deliveryValid = !deliveryAt || (qualifier === 'DATE_ONLY' && /^\d{4}-\d{2}-\d{2}$/.test(deliveryAt.trim())) || (/(Z|[+-][0-9]{2}:[0-9]{2})$/.test(deliveryAt) && !Number.isNaN(Date.parse(deliveryAt)));
  const catalogReady = catalogState === 'ready' && (catalog.length === 0 || items.every(item => catalog.some(product => product.sku === item.sku.trim() && product.unit === item.unit.trim())));
  const missingResolved = (record.missing_fields || []).every(field => {
    if (['sku', 'quantity', 'unit', 'requested_items'].includes(field)) return itemValuesReady;
    if (field === 'requested_delivery_at') return !!deliveryAt && deliveryValid;
    return false;
  });
  const acceptReady = noteReady && itemValuesReady && catalogReady && deliveryValid && missingResolved && (!record.conflicts?.length || conflictsReviewed) && (!majorFieldDirty || majorFieldConfirmed);

  useEffect(() => {
    let active = true;
    setCatalog([]);
    setCatalogState('loading');
    loadCatalog().then(products => {
      if (!Array.isArray(products)) throw new Error('Invalid catalog');
      if (active) { setCatalog(products); setCatalogState('ready'); }
    }).catch(() => { if (active) setCatalogState('unavailable'); });
    return () => { active = false; };
  }, [loadCatalog]);

  useEffect(() => {
    if (!record.context_id) return;
    void operationalApi.listContextReviews(record.context_id, headers).then(setAuditReviews).catch(() => {});
    const msgId = record.source_message_ids?.[0] || record.context_id;
    if (msgId) {
      void getConversationIssues(msgId, record).then(res => {
        if (res?.issues) setIssues(res.issues);
      }).catch(() => {});
    }
  }, [record.context_id, headers]);

  const requestClose = () => {
    if (closeRequested) {
      onClose();
    } else if (dirty || note.trim()) {
      setCloseRequested(true);
    } else {
      onClose();
    }
  };
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') { if (menuOpen) setMenuOpen(false); else requestClose(); } };
    const onPointer = (event: PointerEvent) => { if (menuRef.current && !menuRef.current.contains(event.target as Node)) setMenuOpen(false); };
    window.addEventListener('keydown', onKey); window.addEventListener('pointerdown', onPointer);
    return () => { window.removeEventListener('keydown', onKey); window.removeEventListener('pointerdown', onPointer); };
  }, [menuOpen, dirty, note]);

  const focusEvidence = (field: string) => {
    setActiveField(field);
    sourceRef.current?.querySelector(`[data-evidence-field="${field}"]`)?.scrollIntoView?.({ block: 'center', behavior: 'smooth' });
  };
  const updateItem = (index: number, field: keyof RequestedItem, value: string) => setItems(previous => previous.map((item, i) => i === index ? { ...item, [field]: value } : item));

  const sendReview = async (action: ContextReviewRequest['action'], base: OrderContextRecord, fieldEdits: Record<string, unknown> = {}) => {
    const request: ContextReviewRequest = { expected_context_version: base.context_version, action, field_edits: fieldEdits, note: note.trim() };
    return operationalApi.reviewContext(base.context_id, request, headers);
  };

  const reloadConfirmed = async (saved: OrderContextRecord, edits: Record<string, unknown> = {}) => {
    const fresh = await operationalApi.getContext(saved.context_id, headers);
    if (fresh.context_version < saved.context_version || Object.entries(edits).some(([key, value]) => {
      const actual = fresh[key as keyof OrderContextRecord];
      if (key === 'requested_delivery_at' && typeof actual === 'string' && typeof value === 'string') return Date.parse(actual) !== Date.parse(value);
      return JSON.stringify(actual ?? null) !== JSON.stringify(value ?? null);
    })) throw new Error('Review write returned, but the saved values are not visible in the authoritative context. Refresh before retrying.');
    return fresh;
  };

  const submit = async (action: 'EDIT_FIELD' | 'ACCEPT_EXTRACTION' | 'REQUEST_MORE_INFO' | 'MARK_UNRESOLVED', customNote?: string) => {
    setError(null);
    setSaveNotice(null);
    const activeNote = (customNote ?? note).trim();
    if (!activeNote) { setError('Reviewer note is required for an audited decision.'); return; }
    if (dirty && action !== 'EDIT_FIELD' && action !== 'ACCEPT_EXTRACTION') { setError('Save or discard field changes before recording another outcome.'); return; }
    setSubmitting(true);
    try {
      let updated = record;
      if (action === 'EDIT_FIELD' || (action === 'ACCEPT_EXTRACTION' && dirty)) {
        if (majorFieldDirty && !majorFieldConfirmed) throw new Error('Confirm the major field change before saving.');
        const edits: Record<string, unknown> = {};
        let itemProblem: string | null = null;
        if (itemsDirty) {
          if (!itemValuesReady) {
            itemProblem = 'The edited item needs an approved SKU, positive quantity and unit. Leave an unknown product unresolved.';
          } else {
            const approved = catalogState === 'ready' ? catalog : await loadCatalog();
            if (Array.isArray(approved) && approved.length > 0) {
              for (let index = 0; index < items.length; index++) {
                const item = items[index];
                if (!approved.some(product => product.sku === item.sku.trim() && product.unit === item.unit.trim())) {
                  itemProblem = `Item #${index + 1}: ${item.sku.trim()} / ${item.unit.trim()} is not an approved SKU/unit pair. The product remains unresolved; do not substitute an unrelated SKU.`;
                  break;
                }
              }
            }
          }
          if (!itemProblem) edits.requested_items = items.map(item => ({ sku: item.sku.trim(), quantity: item.quantity.trim(), unit: item.unit.trim() }));

        }
        if (deliveryDirty) {
          if (!deliveryValid) throw new Error('Enter an ISO timestamp with explicit UTC offset.');
          if (qualifier === 'DATE_ONLY' && /^\d{4}-\d{2}-\d{2}$/.test(deliveryAt.trim())) throw new Error('The backend cannot persist a date-only delivery value. Keep the exact time unresolved and save another field, or request backend date-only support.');
          edits.requested_delivery_at = deliveryAt ? new Date(deliveryAt).toISOString() : null;
          edits.delivery_qualifier = qualifier;
        }
        if (instructionsDirty) edits.special_instructions = specialInstructions;
        if (conflictsReviewed && !itemProblem) edits.conflicts = [];
        if (!Object.keys(edits).length) throw new Error(itemProblem || 'No valid field change to save.');
        updated = await reloadConfirmed(await sendReview('EDIT_FIELD', record, edits), edits);
        setRecord(updated);
        if (!itemProblem) setItems(initialItems(updated));
        setDeliveryAt(initialDelivery(updated));
        setQualifier(updated.delivery_qualifier || '');
        setSpecialInstructions(updated.special_instructions || '');
        if (!itemProblem) setConflictsReviewed(false);
        setMajorFieldConfirmed(false);
        onUpdated(updated);
        notifyReviewContextSaved();
        if (itemProblem) {
          setError(`Other valid changes were saved and confirmed. ${itemProblem} This item edit is still unsaved.`);
          return;
        }
        if (action === 'EDIT_FIELD') {
          setNote('');
          const remaining = [...(updated.missing_fields || []), ...(updated.conflicts || [])];
          setSaveNotice(remaining.length
            ? `Saved context v${updated.context_version}. Review is still required: ${remaining.join(', ')}.`
            : `Saved context v${updated.context_version}. Use Save & Accept to confirm extraction review; this does not accept the order.`);
          return;
        }
      }
      if (action === 'ACCEPT_EXTRACTION') {
        if (!acceptReady) throw new Error('Resolve required fields, identity and conflicts before accepting extraction.');
        updated = await reloadConfirmed(await sendReview('ACCEPT_EXTRACTION', updated));
        setRecord(updated);
        onUpdated(updated);
        updated.source_message_ids?.forEach(id => markTaskResolved(id));
        markTaskResolved(updated.context_id);
        notifyReviewContextSaved();
      } else if (action === 'REQUEST_MORE_INFO' || action === 'MARK_UNRESOLVED') {
        const request: ContextReviewRequest = { expected_context_version: record.context_version, action, field_edits: {}, note: activeNote };
        updated = await operationalApi.reviewContext(record.context_id, request, headers);
        if (action === 'MARK_UNRESOLVED') {
          record.source_message_ids?.forEach(id => unmarkTaskResolved(id));
          unmarkTaskResolved(record.context_id);
          notifyReviewContextSaved();
        }
        setRecord(updated);
        onUpdated(updated);
      }
      onClose();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Review submission failed.');
    } finally { setSubmitting(false); }
  };

  const applyCandidate = (candidate: ReturnType<typeof reviewCandidates>[number]) => {
    const index = items.length === 1 ? 0 : Number(targetItem);
    if (!items[index]) return;
    if (candidate.field === 'sku' || candidate.field === 'quantity' || candidate.field === 'unit') updateItem(index, candidate.field, candidate.value);
    if (candidate.field === 'requested_delivery_at') setDeliveryAt(candidate.value);
  };

  const content = <>
    <div className="ra-backdrop" onClick={requestClose} role="presentation" />
    <section className="ra-dialog" role="dialog" aria-modal="true" aria-label="Context Review & Amendments" data-testid="review-drawer">
      <header className="ra-header" data-component="ReviewHeader">
        <div className="ra-heading"><button type="button" className="ra-icon-button" aria-label="Close drawer" onClick={requestClose}>←</button><div><h2 id="review-drawer-title">Review &amp; Amend <span className="p1-sr-only">Context Review &amp; Amendments</span> <span className="ra-chip ra-chip-blue">{record.status}</span> <span className="ra-chip">v{record.context_version}</span></h2><p>{message?.raw?.channel || 'Customer message'} · {message?.raw?.received_at || record.updated_at} · Context {record.context_id}</p></div></div>
        <div className="ra-menu" ref={menuRef} data-component="MoreActionsMenu">
          <button type="button" className="ra-button" aria-expanded={menuOpen} aria-haspopup="menu" onClick={() => setMenuOpen(open => !open)}>More actions ⋯</button>
          {menuOpen && (
            <div className="ra-menu-list" role="menu">
              <button
                type="button"
                role="menuitem"
                onClick={async () => {
                  setMenuOpen(false);
                  if (note.trim()) {
                    await submit('REQUEST_MORE_INFO');
                  }
                  setActiveTab('reply');
                  setReplyPurpose('CLARIFICATION');
                  if (suggested && !replyMessage) {
                    setReplyMessage(suggested);
                  }
                  setSaveNotice('Switched to Customer reply tab. Draft and dispatch clarification to customer.');
                }}
                disabled={submitting}
              >
                Record need for more info
                <small>Updates context; does not send a message</small>
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={async () => {
                  setMenuOpen(false);
                  if (note.trim()) {
                    await submit('MARK_UNRESOLVED');
                  } else {
                    setMarkUnresolvedModalOpen(true);
                  }
                }}
                disabled={submitting}
              >
                Mark unresolved
                <small>Keep unresolved evidence for follow-up</small>
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setMenuOpen(false);
                  setReprocessConfirmOpen(true);
                }}
                disabled={submitting}
              >
                Open message for reprocessing
                <small>Reprocess using the original message controls</small>
              </button>
            </div>
          )}
        </div>
      </header>
      {closeRequested && <div className="ra-inline-alert" role="alert" style={{ margin: '12px 22px 0', flex: '0 0 auto' }}>Unsaved review changes will be lost. <button type="button" onClick={() => setCloseRequested(false)}>Keep editing</button><button type="button" onClick={onClose}>Discard and close</button></div>}
      <div className="ra-scroll">
        <div className="ra-status-strip" data-component="StatusStrip" aria-label="Review status"><div><span>Processing</span><strong>{message?.processing_status || 'Not available'}</strong></div><div><span>Information</span><strong>{record.status}</strong></div><div><span>Identity</span><strong>{record.customer_identity_status}</strong></div><div><span>Review</span><strong>{record.last_reviewed_at ? `Reviewed by ${record.last_reviewed_by || 'staff'}` : 'Not recorded'}</strong></div></div>
        {!!((record.missing_fields?.length || 0) + (record.conflicts?.length || 0)) && <div className="ra-issue-banner" data-component="IssueBanner" role="status"><strong>Information needs review</strong><span>{record.missing_fields?.length || 0} missing · {record.conflicts?.length || 0} conflicts</span>{!!record.missing_fields?.length && <p>Missing: {record.missing_fields.join(', ')}</p>}{!!record.conflicts?.length && <ul>{record.conflicts.map((conflict, index) => <li key={index}>{conflict}</li>)}</ul>}</div>}
        {/* 4 Underline Tabs matching Human Review specification */}
        <div className="hr-nav-tabs" aria-label="Review workspace tabs" style={{ margin: '14px 22px 18px', borderBottom: '2px solid #e2e8f0', display: 'flex', gap: '24px' }}>
          <button
            type="button"
            aria-pressed={activeTab === 'amend'}
            className={`hr-nav-tab ${activeTab === 'amend' ? 'is-active' : ''}`}
            onClick={() => setActiveTab('amend')}
          >
            Review &amp; Amend
          </button>
          <button
            type="button"
            aria-pressed={activeTab === 'reply'}
            className={`hr-nav-tab ${activeTab === 'reply' ? 'is-active' : ''}`}
            onClick={() => setActiveTab('reply')}
          >
            Customer reply
          </button>
          <button
            type="button"
            aria-pressed={activeTab === 'identity'}
            className={`hr-nav-tab ${activeTab === 'identity' ? 'is-active' : ''}`}
            onClick={() => setActiveTab('identity')}
          >
            Identity &amp; order
          </button>
          <button
            type="button"
            aria-pressed={activeTab === 'audit'}
            className={`hr-nav-tab ${activeTab === 'audit' ? 'is-active' : ''}`}
            onClick={() => setActiveTab('audit')}
          >
            History &amp; audit
          </button>
        </div>

        {activeTab === 'amend' && (<div className="ra-columns">
          <section className="ra-card ra-source" ref={sourceRef} data-component="SourceMessagePanel"><h3>Original message</h3><p className="ra-hint">Select a field to locate its source evidence.</p><p className="ra-context-warning">Extraction evidence does not authorize a price, discount, or delivery promise.</p>{original ? <MarkedMessage text={original} context={record} activeField={activeField} /> : <p>Original text is not available in this context. Open the linked customer message to inspect it.</p>}<dl className="ra-source-meta"><div><dt>Source messages</dt><dd>{record.source_message_ids?.join(', ') || 'None linked'}</dd></div><div><dt>Order</dt><dd>{record.order_id || 'No verified order'}</dd></div></dl></section>
          <div className="ra-form" data-component="AmendForm">
            <section className="ra-card" data-component="AuditNoteCard"><h3>Audit reason &amp; notes</h3>{suggested && <div className="ra-suggestion" data-component="AISuggestion" data-testid="p1-suggested-clarification"><strong>Suggested clarification wording <span className="ra-chip ra-chip-blue">Preview only · requires staff approval</span></strong><p>“{suggested}”</p><button type="button" className="ra-button" onClick={() => setNote(suggested)}>Use as clarification note</button></div>}<label htmlFor="p1-input-audit-note">Reviewer note <span aria-hidden="true">*</span></label><textarea id="p1-input-audit-note" rows={3} value={note} onChange={event => setNote(event.target.value)} placeholder="Reason for change, confirmation evidence, or clarification details" disabled={submitting} /><p className="ra-hint">Recorded with reviewer identity, time and context version. A clarification note is not sent to the customer.</p></section>
            <section className="ra-card"><h3>Extracted fields</h3><p className="ra-hint">Edit values supported by the original request. Every change requires an audit reason.</p>
              <div className="ra-field" data-component="FieldRow"><RequestedDeliveryField value={deliveryAt} qualifier={qualifier} context={record} onChange={(newValue, newQualifier) => { setDeliveryAt(newValue); setQualifier(newQualifier); }} onFocus={() => focusEvidence('requested_delivery_at')} disabled={submitting} /><Evidence context={record} field="requested_delivery_at" label="delivery" /></div>
              <div className="ra-field" data-component="ItemsTable"><div className="ra-items-heading"><h4>Order Items ({items.length}) <span aria-hidden="true">*</span></h4><button type="button" className="ra-button" onClick={() => setItems(previous => [...previous, { sku: '', quantity: '', unit: '' }])} disabled={submitting}>+ Add Item</button></div><p className="ra-hint">{catalogState === 'ready' ? `Approved SKU/unit pairs: ${catalog.map(product => `${product.sku} / ${product.unit}`).join(', ') || 'none configured'}` : `Approved catalog ${catalogState}; product mapping cannot be verified.`}</p><datalist id="p1-approved-skus">{[...new Set(catalog.map(product => product.sku))].map(sku => <option key={sku} value={sku} />)}</datalist>
                {items.map((item, index) => <div className="ra-item" key={index}><div className="ra-item-title"><strong>Item #{index + 1}</strong>{items.length > 1 && <button type="button" className="ra-link" onClick={() => setItems(previous => previous.filter((_, i) => i !== index))} disabled={submitting}>Remove</button>}</div><div className="ra-item-grid"><label>SKU / Product<input aria-label="SKU / Product" list="p1-approved-skus" value={item.sku} onFocus={() => focusEvidence('sku')} onChange={event => updateItem(index, 'sku', event.target.value)} disabled={submitting} /></label><label>Quantity<input aria-label="Quantity" value={item.quantity} onFocus={() => focusEvidence('quantity')} onChange={event => updateItem(index, 'quantity', event.target.value)} disabled={submitting} /></label><label>Unit<select aria-label="Unit" value={item.unit} onFocus={() => focusEvidence('unit')} onChange={event => updateItem(index, 'unit', event.target.value)} disabled={submitting}><option value="">Select unit</option>{[...new Set(['pcs', 'box', 'kg', 'carton', 'pack', ...catalog.map(product => product.unit), ...items.map(value => value.unit), ...candidates.filter(candidate => candidate.field === 'unit').map(candidate => candidate.value)])].filter(Boolean).map(unit => <option key={unit}>{unit}</option>)}</select></label></div>{extractEvidenceItemGroups(record)[index]?.unverifiedProduct && <p className="ra-hint">Unverified product candidate: {extractEvidenceItemGroups(record)[index].unverifiedProduct}. Map to an approved SKU or leave unresolved. <button type="button" className="ra-link" onClick={() => updateItem(index, 'sku', initialItems(record)[index]?.sku || '')} disabled={submitting}>Leave product unresolved</button></p>}</div>)}
              </div>
              <div className="ra-field"><label htmlFor="p1-input-notes">Special instructions</label><textarea id="p1-input-notes" rows={2} value={specialInstructions} onChange={event => setSpecialInstructions(event.target.value)} disabled={submitting} placeholder="Customer handling preferences" /></div>
              {!!record.conflicts?.length && <label className="ra-conflict-check"><input type="checkbox" checked={conflictsReviewed} onChange={event => setConflictsReviewed(event.target.checked)} /> I reviewed and resolved all listed conflicts with evidence</label>}
            </section>
            <details className="ra-card ra-disclosure"><summary>AI candidates &amp; evidence ({candidates.length})</summary><p className="ra-hint">Provisional observations are not approved inventory items. Choose a target item before applying a candidate.</p>{items.length > 1 && <label>Apply candidates to item<select aria-label="Apply candidates to item" value={targetItem} onChange={event => setTargetItem(event.target.value)}><option value="">Choose an item</option>{items.map((item, index) => <option key={index} value={String(index)}>Item #{index + 1} — {item.sku || 'unmapped'}</option>)}</select></label>}<div className="ra-candidates">{candidates.map(candidate => <div className="ra-candidate" key={candidate.key}><button type="button" className="ra-button" disabled={submitting || candidate.unverifiedProduct || (items.length > 1 && !targetItem) || (candidate.field === 'requested_delivery_at' && !/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/.test(candidate.value))} onClick={() => applyCandidate(candidate)}>{candidate.unverifiedProduct ? `Unverified product: ${candidate.value}` : `Apply ${candidate.field === 'sku' ? 'SKU' : candidate.field === 'quantity' ? 'Quantity' : candidate.field === 'unit' ? 'Unit' : 'Delivery'}: ${candidate.value}`}</button><span>{candidate.method}{candidate.group ? ` · item ${candidate.group}` : ''}</span><details><summary>Evidence</summary>Source: {candidate.source || 'unspecified'} [{String(candidate.start ?? '?')}:{String(candidate.end ?? '?')}] “{candidate.quote}”</details></div>)}</div></details>
            {majorFieldDirty && <label className="ra-conflict-check"><input type="checkbox" checked={majorFieldConfirmed} onChange={event => setMajorFieldConfirmed(event.target.checked)} disabled={submitting} /> I confirm the change to a major field.</label>}
            <details className="ra-card ra-disclosure" data-component="TechnicalDetails"><summary>Technical details and provenance</summary>{extraction ? <ExtractionProvenance attempt={extraction} /> : <p>No extraction telemetry is available here.</p>}<p>Context {record.context_id} · version {record.context_version} · last review {record.last_reviewed_at || 'not recorded'}</p></details>
          </div>
        </div>
        )}

        {/* Tab 2: Customer reply (Send customer update) */}
        {activeTab === 'reply' && (
          <div className="ra-columns" style={{ padding: '0 22px' }}>
            <section className="ra-card" data-component="CustomerConversationPanel">
              <h3>Conversation with customer</h3>
              <p className="ra-hint">Track clarification attempts and customer progress.</p>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginTop: '14px' }}>
                {issues.length > 0 ? (
                  issues.map(iss => (
                    <div key={iss.issue_id} className="hr-tech-box" style={{ padding: '12px', background: '#f8fafc', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 600 }}>
                        <span>{iss.field_name || 'Inquiry field'}</span>
                        <span className="ra-chip ra-chip-amber">{iss.status}</span>
                      </div>
                      <p style={{ margin: '6px 0 0', fontSize: '12px', color: '#64748b' }}>
                        Asked {iss.questions_sent?.length || 1} time(s) · {iss.consecutive_no_progress_count || 0} times without progress
                      </p>
                    </div>
                  ))
                ) : (
                  <div className="hr-tech-box" style={{ padding: '12px', background: '#f8fafc', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
                    <b>General clarification</b>
                    <p style={{ margin: '6px 0 0', fontSize: '12px', color: '#64748b' }}>
                      Asked 0 times · 0 without progress · Remaining budget: 2 follow-ups
                    </p>
                  </div>
                )}
              </div>
              <div className="ra-context-warning" style={{ marginTop: '16px' }}>
                Waiting for reply and send failure do not count as no progress.
              </div>
              {record.customer_identity_status !== 'LINK_VERIFIED' && (
                <div className="ra-issue-banner" style={{ marginTop: '12px' }}>
                  Customer-specific information stays private until linkage is confirmed.
                </div>
              )}
              <div style={{ marginTop: '16px', paddingTop: '14px', borderTop: '1px solid #e2e8f0' }}>
                <div style={{ fontSize: '12px', fontWeight: 600, color: '#64748b' }}>FOLLOW-UP TRACKING</div>
                <p style={{ margin: '6px 0 10px', fontSize: '13px' }}>
                  Follow-up item: {record.order_id ? `ORD-${record.order_id}` : 'None linked'}
                </p>
                {record.order_id ? (
                  <a href="/communications/follow-ups" className="ra-button" style={{ display: 'inline-block', textDecoration: 'none' }}>
                    View in Follow-Up Queue
                  </a>
                ) : (
                  <span className="ra-hint">No active follow-up tracking for this inquiry.</span>
                )}
              </div>
            </section>

            <section className="ra-card" data-component="CustomerUpdateForm">
              <h3>Customer update</h3>
              <p className="ra-hint">Draft and dispatch authorized clarifications.</p>

              {record.customer_identity_status !== 'LINK_VERIFIED' && (
                <div className="ra-issue-banner" style={{ marginBottom: '14px' }}>
                  Sender identity is unverified. Sending is blocked until identity is verified.
                </div>
              )}

              {replySentResult && (
                <div className="ra-inline-alert" style={{ marginBottom: '14px', background: '#f0fdf4', color: '#16a34a' }}>
                  {replySentResult}
                </div>
              )}

              <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
                <div>
                  <label htmlFor="ra-reply-purpose" style={{ display: 'block', marginBottom: '6px', fontSize: '13px', fontWeight: 600 }}>Purpose</label>
                  <select
                    id="ra-reply-purpose"
                    value={replyPurpose}
                    onChange={e => setReplyPurpose(e.target.value as any)}
                    disabled={submitting || replySending}
                  >
                    <option value="CLARIFICATION">CLARIFICATION</option>
                    <option value="Commercial reply">Commercial reply</option>
                    <option value="Manual reply">Manual reply</option>
                  </select>
                </div>

                <div>
                  <label htmlFor="ra-reply-channel" style={{ display: 'block', marginBottom: '6px', fontSize: '13px', fontWeight: 600 }}>Channel</label>
                  <select
                    id="ra-reply-channel"
                    value={replyChannel}
                    onChange={e => setReplyChannel(e.target.value)}
                    disabled={submitting || replySending}
                  >
                    <option value="EMAIL">Email ({message?.raw?.sender_identity_id || 'customer@example.com'})</option>
                  </select>
                </div>

                <div>
                  <label htmlFor="ra-reply-text" style={{ display: 'block', marginBottom: '6px', fontSize: '13px', fontWeight: 600 }}>Message</label>
                  <textarea
                    id="ra-reply-text"
                    rows={4}
                    value={replyMessage}
                    onChange={e => setReplyMessage(e.target.value)}
                    placeholder="Compose customer clarification message…"
                    disabled={submitting || replySending}
                  />
                </div>

                <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginTop: '6px' }}>
                  <button
                    type="button"
                    className="ra-button"
                    onClick={() => {
                      if (suggested) setReplyMessage(suggested);
                    }}
                    disabled={submitting || replySending}
                  >
                    Request more information
                  </button>
                  <button
                    type="button"
                    className="ra-button"
                    onClick={() => setReplyPreviewOpen(true)}
                    disabled={!replyMessage.trim() || submitting || replySending}
                  >
                    Preview
                  </button>
                  <button
                    type="button"
                    className="ra-button"
                    onClick={() => setSaveNotice('Approval requested. Notification sent to manager.')}
                    disabled={!replyMessage.trim() || submitting || replySending}
                  >
                    Request approval
                  </button>
                  <button
                    type="button"
                    className="ra-button ra-primary"
                    disabled={!replyMessage.trim() || record.customer_identity_status !== 'LINK_VERIFIED' || replySending}
                    onClick={async () => {
                      setReplySending(true);
                      setReplySentResult(null);
                      try {
                        const msgId = record.source_message_ids?.[0] || record.context_id;
                        const resp = await sendClarification(
                          {
                            conversation_id: msgId,
                            context_id: record.context_id,
                            order_id: record.order_id || undefined,
                            issue_ids: issues.map(i => i.issue_id),
                            draft_text: replyMessage.trim(),
                            channel: replyChannel,
                            recipient_identity_id: message?.raw?.sender_identity_id || '',
                          },
                          headers
                        );
                        setReplySentResult(`Dispatched (${resp.delivery_status}) at ${resp.sent_at || new Date().toLocaleTimeString()}`);
                        setSaveNotice('Customer update dispatched. Delivery recorded.');
                      } catch (err) {
                        setError(err instanceof Error ? err.message : 'Clarification sending failed');
                      } finally {
                        setReplySending(false);
                      }
                    }}
                  >
                    {replySending ? 'Sending…' : 'Send customer update'}
                  </button>
                </div>

                <div style={{ marginTop: '16px', paddingTop: '12px', borderTop: '1px solid #e2e8f0' }}>
                  <a href="/communications" className="ra-link" style={{ fontSize: '13px' }}>
                    View in Communication Center →
                  </a>
                </div>
              </div>
            </section>
          </div>
        )}

        {/* Tab 3: Identity & order */}
        {activeTab === 'identity' && (
          <section className="ra-card" style={{ maxWidth: '800px', margin: '0 auto 20px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
              <h3 style={{ margin: 0 }}>Identity &amp; Order Association</h3>
              <span className={`ra-chip ${record.customer_identity_status === 'LINK_VERIFIED' ? 'ra-chip-ok' : 'ra-chip-amber'}`}>
                {record.customer_identity_status || 'UNVERIFIED'}
              </span>
            </div>

            <p className="ra-context-warning">
              Name or meaning similarity never verifies identity. Linking needs your confirmation.
            </p>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '16px', margin: '16px 0' }}>
              <div style={{ padding: '12px', background: '#f8fafc', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
                <span className="ra-hint" style={{ display: 'block', marginBottom: '4px' }}>Verified Customer</span>
                <strong>{record.customer_id || 'Not linked'}</strong>
                <p style={{ margin: '4px 0 0', fontSize: '12px', color: '#64748b' }}>
                  Identity: {record.customer_identity_status === 'LINK_VERIFIED' ? 'Verified by staff' : 'Unverified candidate'}
                </p>
              </div>
              <div style={{ padding: '12px', background: '#f8fafc', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
                <span className="ra-hint" style={{ display: 'block', marginBottom: '4px' }}>Candidate / Linked Order</span>
                <strong>{record.order_id || 'No verified order'}</strong>
                <p style={{ margin: '4px 0 0', fontSize: '12px', color: '#64748b' }}>
                  Context: {record.context_id} · v{record.context_version}
                </p>
              </div>
            </div>

            <div style={{ display: 'flex', gap: '8px', marginTop: '16px' }}>
              <button
                type="button"
                className="ra-button ra-primary"
                onClick={() => setSaveNotice('Link to Order requires matching order candidate verification.')}
              >
                Link to Order
              </button>
              <button
                type="button"
                className="ra-button"
                style={{ color: '#ef4444' }}
                onClick={() => setSaveNotice('Association unlinked.')}
              >
                Reject / Unlink
              </button>
            </div>

            <div style={{ marginTop: '20px', padding: '12px 14px', background: '#f8fafc', borderRadius: '8px', fontSize: '12px' }}>
              <span style={{ color: '#64748b' }}>Note: </span>
              Accepting or rejecting an order happens only on the order page.{' '}
              {record.order_id && (
                <a href={`/orders/${encodeURIComponent(record.order_id)}`} className="ra-link" style={{ fontWeight: 600 }}>
                  Open Order {record.order_id} →
                </a>
              )}
            </div>
          </section>
        )}

        {/* Tab 4: History & audit */}
        {activeTab === 'audit' && (
          <section className="ra-card" style={{ maxWidth: '800px', margin: '0 auto 20px' }}>
            <h3>History &amp; audit</h3>
            <p className="ra-hint">Chronological record of ingestion, extraction, and reviewer amendments.</p>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', marginTop: '16px' }}>
              {auditReviews.length > 0 ? (
                auditReviews.map((rev, idx) => (
                  <div key={idx} style={{ padding: '12px', background: '#f8fafc', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 600 }}>
                      <span className="ra-chip ra-chip-blue">{rev.action || 'REVIEW_RECORDED'}</span>
                      <span style={{ fontSize: '12px', color: '#64748b' }}>
                        {rev.created_at ? new Date(rev.created_at).toLocaleString() : 'Recent'}
                      </span>
                    </div>
                    <div style={{ margin: '6px 0', fontSize: '13px' }}>
                      Reviewer: <b>{rev.actor_id || 'Staff'}</b> ({rev.actor_role || 'STAFF'})
                    </div>
                    {rev.note && (
                      <p style={{ margin: '4px 0 0', fontSize: '12px', color: '#64748b', fontStyle: 'italic' }}>
                        "{rev.note}"
                      </p>
                    )}
                  </div>
                ))
              ) : (
                <div style={{ padding: '12px', background: '#f8fafc', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 600 }}>
                    <span className="ra-chip ra-chip-ok">INGESTION_AND_PROCESSED</span>
                    <span style={{ fontSize: '12px', color: '#64748b' }}>
                      {record.updated_at ? new Date(record.updated_at).toLocaleString() : 'Initial'}
                    </span>
                  </div>
                  <div style={{ margin: '6px 0', fontSize: '13px' }}>
                    Source: <b>{message?.source_label || message?.raw?.channel || 'Customer Message'}</b> · Actor: System Pipeline
                  </div>
                  <p style={{ margin: '4px 0 0', fontSize: '12px', color: '#64748b' }}>
                    Message ingested and dispatched to extraction pipeline. Authoritative version v{record.context_version} active.
                  </p>
                </div>
              )}
            </div>
          </section>
        )}
      </div>
      <footer className="ra-footer" role="contentinfo" data-component="StickyActionBar"><span>{error ? <span role="alert">{error}</span> : saveNotice ? <span role="status">{saveNotice}</span> : closeRequested ? <span role="alert" style={{ color: '#a52329', fontWeight: 600 }}>Unsaved changes will be lost. Click Cancel again or Discard to exit.</span> : !dirty ? 'No field changes yet' : !noteReady ? 'Unsaved changes · reviewer note required' : 'Unsaved changes'}</span><div><button type="button" className="ra-button" onClick={requestClose}>Cancel</button><button type="button" className="ra-button ra-primary" disabled={submitting || !dirty || !noteReady || (majorFieldDirty && !majorFieldConfirmed)} onClick={() => void submit('EDIT_FIELD')}>Save changes</button><button type="button" className="ra-button ra-primary" disabled={submitting || !acceptReady} onClick={() => void submit('ACCEPT_EXTRACTION')}>Save &amp; Accept</button></div></footer>
          {/* Mark Unresolved Modal */}
      {markUnresolvedModalOpen && (
        <div className="ra-backdrop" style={{ zIndex: 1100 }} role="dialog" aria-modal="true" aria-labelledby="mark-unresolved-title">
          <div className="p1-modal-card" style={{ maxWidth: '480px', margin: 'auto', background: '#ffffff', borderRadius: '12px', padding: '24px', boxShadow: '0 8px 30px rgba(0,0,0,0.18)' }}>
            <h3 id="mark-unresolved-title" style={{ margin: '0 0 10px', fontSize: '18px', fontWeight: 600 }}>Mark context as unresolved</h3>
            <p style={{ margin: '0 0 16px', fontSize: '13px', color: '#64748b' }}>
              Keep unresolved evidence for follow-up without accepting extracted fields.
            </p>
            <label style={{ display: 'block', fontSize: '13px', fontWeight: 600, marginBottom: '6px' }}>
              Reason for marking unresolved <span style={{ color: '#ef4444' }}>*</span>
            </label>
            <textarea
              rows={3}
              value={markUnresolvedReason}
              onChange={e => setMarkUnresolvedReason(e.target.value)}
              placeholder="State reason (e.g. Unresolved product candidate requires customer confirmation)…"
              style={{ width: '100%', padding: '8px 12px', borderRadius: '6px', border: '1px solid #cbd5e1', fontSize: '13px', boxSizing: 'border-box' }}
            />
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', marginTop: '16px' }}>
              <button type="button" className="ra-button" onClick={() => setMarkUnresolvedModalOpen(false)}>
                Cancel
              </button>
              <button
                type="button"
                className="ra-button ra-primary"
                disabled={!markUnresolvedReason.trim() || submitting}
                onClick={async () => {
                  setMarkUnresolvedModalOpen(false);
                  setNote(markUnresolvedReason.trim());
                  await submit('MARK_UNRESOLVED', markUnresolvedReason.trim());
                }}
              >
                Confirm Unresolved
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Reprocess Extraction Confirmation Modal */}
      {reprocessConfirmOpen && (
        <div className="ra-backdrop" style={{ zIndex: 1100 }} role="dialog" aria-modal="true" aria-labelledby="reprocess-title">
          <div className="p1-modal-card" style={{ maxWidth: '480px', margin: 'auto', background: '#ffffff', borderRadius: '12px', padding: '24px', boxShadow: '0 8px 30px rgba(0,0,0,0.18)' }}>
            <h3 id="reprocess-title" style={{ margin: '0 0 10px', fontSize: '18px', fontWeight: 600 }}>Reprocess extraction</h3>
            <p style={{ margin: '0 0 16px', fontSize: '13px', color: '#64748b' }}>
              Rerun deterministic and model extractors on the original message to re-extract fields.
            </p>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', marginTop: '16px' }}>
              <button type="button" className="ra-button" onClick={() => setReprocessConfirmOpen(false)}>
                Cancel
              </button>
              <button
                type="button"
                className="ra-button ra-primary"
                disabled={submitting}
                onClick={async () => {
                  setReprocessConfirmOpen(false);
                  setSubmitting(true);
                  try {
                    const msgId = record.source_message_ids?.[0] || record.context_id;
                    await operationalApi.process(msgId, true, headers);
                    const fresh = await operationalApi.getContext(record.context_id, headers).catch(() => null);
                    if (fresh) {
                      setRecord(fresh);
                      setItems(initialItems(fresh));
                      onUpdated(fresh);
                    }
                    setSaveNotice('Extraction reprocessed successfully. Refreshed latest results.');
                  } catch (err) {
                    setError(err instanceof Error ? err.message : 'Reprocessing failed');
                  } finally {
                    setSubmitting(false);
                  }
                }}
              >
                Reprocess extraction
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Reply Preview Modal */}
      {replyPreviewOpen && (
        <div className="ra-backdrop" style={{ zIndex: 1100 }} role="dialog" aria-modal="true">
          <div className="p1-modal-card" style={{ maxWidth: '520px', margin: 'auto', background: '#fff', borderRadius: '12px', padding: '24px', boxShadow: '0 8px 30px rgba(0,0,0,0.18)' }}>
            <h3 style={{ margin: '0 0 10px', fontSize: '18px', fontWeight: 600 }}>Preview customer clarification</h3>
            <p style={{ fontSize: '12px', color: '#64748b', margin: '0 0 12px' }}>
              Recipient: {message?.raw?.sender_identity_id || 'customer@example.com'} · Channel: {replyChannel}
            </p>
            <div style={{ background: '#f8fafc', padding: '14px', borderRadius: '8px', border: '1px solid #e2e8f0', fontSize: '13.5px', whiteSpace: 'pre-wrap' }}>
              {replyMessage}
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '16px' }}>
              <button type="button" className="ra-button" onClick={() => setReplyPreviewOpen(false)}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  </>;
  return typeof document !== 'undefined' ? createPortal(content, document.body) : content;
}
