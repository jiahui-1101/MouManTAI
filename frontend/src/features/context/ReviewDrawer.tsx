import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { ContextReviewRequest, ExtractionAttemptRecord, OrderContextRecord, RequestedItem, StoredMessage } from './types';
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
  const acceptReady = noteReady && itemValuesReady && catalogReady && deliveryValid && missingResolved && record.customer_identity_status === 'LINK_VERIFIED' && (!record.conflicts?.length || conflictsReviewed) && (!majorFieldDirty || majorFieldConfirmed);

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
    const fresh = await operationalApi.getContext(saved.context_id);
    if (fresh.context_version < saved.context_version || Object.entries(edits).some(([key, value]) => {
      const actual = fresh[key as keyof OrderContextRecord];
      if (key === 'requested_delivery_at' && typeof actual === 'string' && typeof value === 'string') return Date.parse(actual) !== Date.parse(value);
      return JSON.stringify(actual ?? null) !== JSON.stringify(value ?? null);
    })) throw new Error('Review write returned, but the saved values are not visible in the authoritative context. Refresh before retrying.');
    return fresh;
  };

  const submit = async (action: 'EDIT_FIELD' | 'ACCEPT_EXTRACTION' | 'REQUEST_MORE_INFO' | 'MARK_UNRESOLVED') => {
    setError(null);
    setSaveNotice(null);
    if (!noteReady) { setError('Reviewer note is required for an audited decision.'); return; }
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
        updated = await sendReview(action, record);
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
        <div className="ra-menu" ref={menuRef} data-component="MoreActionsMenu"><button type="button" className="ra-button" aria-expanded={menuOpen} aria-haspopup="menu" onClick={() => setMenuOpen(open => !open)}>More actions ⋯</button>{menuOpen && <div className="ra-menu-list" role="menu"><button type="button" role="menuitem" onClick={() => void submit('REQUEST_MORE_INFO')} disabled={submitting}>Record need for more info<small>Updates context; does not send a message</small></button><button type="button" role="menuitem" onClick={() => void submit('MARK_UNRESOLVED')} disabled={submitting}>Mark unresolved<small>Keep unresolved evidence for follow-up</small></button>{record.source_message_ids?.[0] && <a role="menuitem" href={`/inbox?message=${encodeURIComponent(record.source_message_ids[0])}`}>Open message for reprocessing<small>Reprocess using the original message controls</small></a>}</div>}</div>
      </header>
      {closeRequested && <div className="ra-inline-alert" role="alert" style={{ margin: '12px 22px 0', flex: '0 0 auto' }}>Unsaved review changes will be lost. <button type="button" onClick={() => setCloseRequested(false)}>Keep editing</button><button type="button" onClick={onClose}>Discard and close</button></div>}
      <div className="ra-scroll">
        <div className="ra-status-strip" data-component="StatusStrip" aria-label="Review status"><div><span>Processing</span><strong>{message?.processing_status || 'Not available'}</strong></div><div><span>Information</span><strong>{record.status}</strong></div><div><span>Identity</span><strong>{record.customer_identity_status}</strong></div><div><span>Review</span><strong>{record.last_reviewed_at ? `Reviewed by ${record.last_reviewed_by || 'staff'}` : 'Not recorded'}</strong></div></div>
        {!!((record.missing_fields?.length || 0) + (record.conflicts?.length || 0)) && <div className="ra-issue-banner" data-component="IssueBanner" role="status"><strong>Information needs review</strong><span>{record.missing_fields?.length || 0} missing · {record.conflicts?.length || 0} conflicts</span>{!!record.missing_fields?.length && <p>Missing: {record.missing_fields.join(', ')}</p>}{!!record.conflicts?.length && <ul>{record.conflicts.map((conflict, index) => <li key={index}>{conflict}</li>)}</ul>}</div>}
        <div className="ra-columns">
          <section className="ra-card ra-source" ref={sourceRef} data-component="SourceMessagePanel"><h3>Original message</h3><p className="ra-hint">Select a field to locate its source evidence.</p><p className="ra-context-warning">Extraction evidence does not authorize a price, discount, or delivery promise.</p>{original ? <MarkedMessage text={original} context={record} activeField={activeField} /> : <p>Original text is not available in this context. Open the linked customer message to inspect it.</p>}<dl className="ra-source-meta"><div><dt>Source messages</dt><dd>{record.source_message_ids?.join(', ') || 'None linked'}</dd></div><div><dt>Order</dt><dd>{record.order_id || 'No verified order'}</dd></div></dl></section>
          <div className="ra-form" data-component="AmendForm">
            <section className="ra-card"><h3>Extracted fields</h3><p className="ra-hint">Edit values supported by the original request. Every change requires an audit reason.</p>
              <div className="ra-field" data-component="FieldRow"><RequestedDeliveryField value={deliveryAt} qualifier={qualifier} context={record} onChange={(newValue, newQualifier) => { setDeliveryAt(newValue); setQualifier(newQualifier); }} onFocus={() => focusEvidence('requested_delivery_at')} disabled={submitting} /><Evidence context={record} field="requested_delivery_at" label="delivery" /></div>
              <div className="ra-field" data-component="ItemsTable"><div className="ra-items-heading"><h4>Order Items ({items.length}) <span aria-hidden="true">*</span></h4><button type="button" className="ra-button" onClick={() => setItems(previous => [...previous, { sku: '', quantity: '', unit: '' }])} disabled={submitting}>+ Add Item</button></div><p className="ra-hint">{catalogState === 'ready' ? `Approved SKU/unit pairs: ${catalog.map(product => `${product.sku} / ${product.unit}`).join(', ') || 'none configured'}` : `Approved catalog ${catalogState}; product mapping cannot be verified.`}</p><datalist id="p1-approved-skus">{[...new Set(catalog.map(product => product.sku))].map(sku => <option key={sku} value={sku} />)}</datalist>
                {items.map((item, index) => <div className="ra-item" key={index}><div className="ra-item-title"><strong>Item #{index + 1}</strong>{items.length > 1 && <button type="button" className="ra-link" onClick={() => setItems(previous => previous.filter((_, i) => i !== index))} disabled={submitting}>Remove</button>}</div><div className="ra-item-grid"><label>SKU / Product<input aria-label="SKU / Product" list="p1-approved-skus" value={item.sku} onFocus={() => focusEvidence('sku')} onChange={event => updateItem(index, 'sku', event.target.value)} disabled={submitting} /></label><label>Quantity<input aria-label="Quantity" value={item.quantity} onFocus={() => focusEvidence('quantity')} onChange={event => updateItem(index, 'quantity', event.target.value)} disabled={submitting} /></label><label>Unit<select aria-label="Unit" value={item.unit} onFocus={() => focusEvidence('unit')} onChange={event => updateItem(index, 'unit', event.target.value)} disabled={submitting}><option value="">Select unit</option>{[...new Set(['pcs', 'box', 'kg', 'carton', 'pack', ...catalog.map(product => product.unit), ...items.map(value => value.unit), ...candidates.filter(candidate => candidate.field === 'unit').map(candidate => candidate.value)])].filter(Boolean).map(unit => <option key={unit}>{unit}</option>)}</select></label></div>{extractEvidenceItemGroups(record)[index]?.unverifiedProduct && <p className="ra-hint">Unverified product candidate: {extractEvidenceItemGroups(record)[index].unverifiedProduct}. Map to an approved SKU or leave unresolved. <button type="button" className="ra-link" onClick={() => updateItem(index, 'sku', initialItems(record)[index]?.sku || '')} disabled={submitting}>Leave product unresolved</button></p>}<div className="ra-item-evidence"><Evidence context={record} field="sku" label="product" /><Evidence context={record} field="quantity" label="quantity" /><Evidence context={record} field="unit" label="unit" /></div></div>)}
              </div>
              <div className="ra-field"><label htmlFor="p1-input-notes">Special instructions</label><textarea id="p1-input-notes" rows={2} value={specialInstructions} onChange={event => setSpecialInstructions(event.target.value)} disabled={submitting} placeholder="Customer handling preferences" /></div>
              {!!record.conflicts?.length && <label className="ra-conflict-check"><input type="checkbox" checked={conflictsReviewed} onChange={event => setConflictsReviewed(event.target.checked)} /> I reviewed and resolved all listed conflicts with evidence</label>}
            </section>
            <details className="ra-card ra-disclosure"><summary>AI candidates &amp; evidence ({candidates.length})</summary><p className="ra-hint">Provisional observations are not approved inventory items. Choose a target item before applying a candidate.</p>{items.length > 1 && <label>Apply candidates to item<select aria-label="Apply candidates to item" value={targetItem} onChange={event => setTargetItem(event.target.value)}><option value="">Choose an item</option>{items.map((item, index) => <option key={index} value={String(index)}>Item #{index + 1} — {item.sku || 'unmapped'}</option>)}</select></label>}<div className="ra-candidates">{candidates.map(candidate => <div className="ra-candidate" key={candidate.key}><button type="button" className="ra-button" disabled={submitting || candidate.unverifiedProduct || (items.length > 1 && !targetItem) || (candidate.field === 'requested_delivery_at' && !/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/.test(candidate.value))} onClick={() => applyCandidate(candidate)}>{candidate.unverifiedProduct ? `Unverified product: ${candidate.value}` : `Apply ${candidate.field === 'sku' ? 'SKU' : candidate.field === 'quantity' ? 'Quantity' : candidate.field === 'unit' ? 'Unit' : 'Delivery'}: ${candidate.value}`}</button><span>{candidate.method}{candidate.group ? ` · item ${candidate.group}` : ''}</span><details><summary>Evidence</summary>Source: {candidate.source || 'unspecified'} [{String(candidate.start ?? '?')}:{String(candidate.end ?? '?')}] “{candidate.quote}”</details></div>)}</div></details>
            <section className="ra-card" data-component="AuditNoteCard"><h3>Audit reason &amp; notes</h3>{suggested && <div className="ra-suggestion" data-component="AISuggestion" data-testid="p1-suggested-clarification"><strong>Suggested clarification wording <span className="ra-chip ra-chip-blue">Preview only · requires staff approval</span></strong><p>“{suggested}”</p><button type="button" className="ra-button" onClick={() => setNote(suggested)}>Use as clarification note</button></div>}<label htmlFor="p1-input-audit-note">Reviewer note <span aria-hidden="true">*</span></label><textarea id="p1-input-audit-note" rows={3} value={note} onChange={event => setNote(event.target.value)} placeholder="Reason for change, confirmation evidence, or clarification details" disabled={submitting} /><p className="ra-hint">Recorded with reviewer identity, time and context version. A clarification note is not sent to the customer.</p></section>
            {majorFieldDirty && <label className="ra-conflict-check"><input type="checkbox" checked={majorFieldConfirmed} onChange={event => setMajorFieldConfirmed(event.target.checked)} disabled={submitting} /> I confirm the change to a major field.</label>}
            <details className="ra-card ra-disclosure" data-component="TechnicalDetails"><summary>Technical details and provenance</summary>{extraction ? <ExtractionProvenance attempt={extraction} /> : <p>No extraction telemetry is available here.</p>}<p>Context {record.context_id} · version {record.context_version} · last review {record.last_reviewed_at || 'not recorded'}</p></details>
          </div>
        </div>
      </div>
      <footer className="ra-footer" role="contentinfo" data-component="StickyActionBar"><span>{error ? <span role="alert">{error}</span> : saveNotice ? <span role="status">{saveNotice}</span> : closeRequested ? <span role="alert" style={{ color: '#a52329', fontWeight: 600 }}>Unsaved changes will be lost. Click Cancel again or Discard to exit.</span> : !dirty ? 'No field changes yet' : !noteReady ? 'Unsaved changes · reviewer note required' : 'Unsaved changes'}</span><div><button type="button" className="ra-button" onClick={requestClose}>Cancel</button><button type="button" className="ra-button ra-primary" disabled={submitting || !dirty || !noteReady || (majorFieldDirty && !majorFieldConfirmed)} onClick={() => void submit('EDIT_FIELD')}>Save changes</button><button type="button" className="ra-button ra-primary" disabled={submitting || !acceptReady} onClick={() => void submit('ACCEPT_EXTRACTION')}>Save &amp; Accept</button></div></footer>
    </section>
  </>;
  return typeof document !== 'undefined' ? createPortal(content, document.body) : content;
}
