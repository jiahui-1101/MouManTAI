import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import type { ContextReviewRequest, OrderContextRecord, RequestedItem } from './types';
import { getReviewCatalog, operationalApi } from './operationalApi';
import { reviewCandidates } from './reviewCandidates';

export interface ReviewDrawerProps {
  context: OrderContextRecord;
  isOpen: boolean;
  onClose: () => void;
  onUpdated: (updated: OrderContextRecord) => void;
  catalogLoader?: () => Promise<{ sku: string; unit: string }[]>;
}

export function getSuggestedClarification(context: OrderContextRecord): string | null {
  const missing = context.missing_fields || [];
  const conflicts = context.conflicts || [];

  const sku = context.requested_items?.[0]?.sku ||
    (context.field_evidence?.sku?.[0]?.normalized_value || context.field_evidence?.sku?.[0]?.quote || '') as string;
  const qty = context.requested_items?.[0]?.quantity ||
    (context.field_evidence?.quantity?.[0]?.normalized_value || context.field_evidence?.quantity?.[0]?.quote || '') as string;
  const unit = context.requested_items?.[0]?.unit ||
    (context.field_evidence?.unit?.[0]?.normalized_value || context.field_evidence?.unit?.[0]?.quote || '') as string;

  const isUnitMissing = missing.includes('unit') || (!unit && Boolean(sku || qty));
  const isDeliveryMissing = missing.includes('requested_delivery_at') || (!context.requested_delivery_at && !(context.field_evidence?.requested_delivery_at?.length));

  if (isUnitMissing && qty && sku) {
    return `Could you please confirm the unit for the ${qty} ${sku.toLowerCase()} (e.g., pcs or boxes)?`;
  }
  if (isUnitMissing && qty) {
    return `Could you please confirm the unit for the ${qty} items requested (e.g., pcs or boxes)?`;
  }
  if (isDeliveryMissing) {
    return 'Could you please confirm your preferred delivery date and time?';
  }
  if (missing.includes('quantity')) {
    return `Could you please specify the quantity needed for ${sku || 'your order'}?`;
  }
  if (missing.includes('sku') || missing.includes('requested_items')) {
    return 'Could you please clarify which item or product you would like to order?';
  }
  if (conflicts.length > 0) {
    return `Could you please clarify the following order details: ${conflicts[0]}?`;
  }
  return null;
}

export function ReviewDrawer(props: ReviewDrawerProps) {
  if (!props.isOpen) return null;
  return <ReviewDrawerForm key={`${props.context.context_id}:${props.context.context_version}`} {...props} />;
}

function ReviewDrawerForm({ context, onClose, onUpdated, catalogLoader }: ReviewDrawerProps) {

  const evidenceQty = (context.field_evidence?.quantity?.[0]?.normalized_value || context.field_evidence?.quantity?.[0]?.quote || '') as string;
  const evidenceUnit = (context.field_evidence?.unit?.[0]?.normalized_value || context.field_evidence?.unit?.[0]?.quote || '') as string;
  const evidenceDelivery = (context.field_evidence?.requested_delivery_at?.[0]?.normalized_value || context.field_evidence?.requested_delivery_at?.[0]?.quote || '') as string;
  const evidenceQualifier = (context.field_evidence?.requested_delivery_at?.[0]?.qualifier || '') as string;

  const initialItems: RequestedItem[] = (context.requested_items && context.requested_items.length > 0)
    ? context.requested_items.map(it => ({ sku: it.sku || '', quantity: it.quantity || '', unit: it.unit || '' }))
    : [{ sku: '', quantity: evidenceQty || '', unit: evidenceUnit || '' }];

  const [items, setItems] = useState<RequestedItem[]>(initialItems);
  const [deliveryAt, setDeliveryAt] = useState(
    context.requested_delivery_at || (evidenceDelivery.includes('T') ? evidenceDelivery : (evidenceDelivery && /^\d{4}-\d{2}-\d{2}$/.test(evidenceDelivery) ? evidenceDelivery : ''))
  );
  const initialDelivery = context.requested_delivery_at || (/^\d{4}-\d{2}-\d{2}(?:T.*)?$/.test(evidenceDelivery) ? evidenceDelivery : '');
  const initialQualifier = context.delivery_qualifier || evidenceQualifier || (/^\d{4}-\d{2}-\d{2}$/.test(evidenceDelivery) ? 'DATE_ONLY' : '');
  const [qualifier, setQualifier] = useState(initialQualifier);
  const [specialInstructions, setSpecialInstructions] = useState(context.special_instructions || '');
  const [note, setNote] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [catalog, setCatalog] = useState<{ sku: string; unit: string }[]>([]);
  const [catalogState, setCatalogState] = useState('loading');
  const [targetItem, setTargetItem] = useState('');
  const [conflictsReviewed, setConflictsReviewed] = useState(false);
  const suggestedClarification = getSuggestedClarification(context);

  useEffect(() => {
    let active = true;
    const load = catalogLoader || getReviewCatalog;
    load().then(products => {
      if (!Array.isArray(products)) throw new Error('Invalid catalog');
      if (active) { setCatalog(products); setCatalogState('ready'); }
    }).catch(() => { if (active) setCatalogState('unavailable'); });
    return () => { active = false; };
  }, [catalogLoader]);

  const updateItem = (index: number, field: keyof RequestedItem, value: string) => {
    setItems(prev => {
      const next = [...prev];
      next[index] = { ...next[index], [field]: value };
      return next;
    });
  };

  const addItem = () => {
    setItems(prev => [...prev, { sku: '', quantity: '', unit: '' }]);
  };

  const removeItem = (index: number) => {
    if (items.length <= 1) return;
    setItems(prev => prev.filter((_, i) => i !== index));
  };

  const candidateProposals = reviewCandidates(context);
  const hasUnsavedEdits = JSON.stringify(items) !== JSON.stringify(initialItems) ||
    deliveryAt !== initialDelivery || qualifier !== initialQualifier ||
    specialInstructions !== (context.special_instructions || '') || conflictsReviewed;

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        onClose();
      }
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  const handleSubmit = async (action: 'ACCEPT_EXTRACTION' | 'EDIT_FIELD' | 'REQUEST_MORE_INFO' | 'MARK_UNRESOLVED') => {
    setSubmitting(true);
    setError(null);
    try {
      const fieldEdits: Record<string, unknown> = {};

      if (action === 'EDIT_FIELD') {
        if (items.length === 0) {
          throw new Error('Enter an explicit SKU, positive quantity and unit. Missing fields are not defaulted.');
        }
        for (let i = 0; i < items.length; i++) {
          const it = items[i];
          if (!it.sku.trim() || !it.unit.trim() || !/^[0-9]+(?:\.[0-9]+)?$/.test(it.quantity.trim()) || Number(it.quantity) <= 0) {
            throw new Error(`Item #${i + 1}: Enter an explicit SKU, positive quantity and unit. Missing fields are not defaulted.`);
          }
        }
        fieldEdits.requested_items = items.map(it => ({
          sku: it.sku.trim(),
          quantity: it.quantity.trim(),
          unit: it.unit.trim(),
        }));
        fieldEdits.delivery_qualifier = qualifier;
        if (deliveryAt) {
          if (!/(Z|[+-][0-9]{2}:[0-9]{2})$/.test(deliveryAt) || Number.isNaN(Date.parse(deliveryAt))) {
            throw new Error('Enter an ISO timestamp with explicit UTC offset, for example 2026-10-23T15:00:00+08:00.');
          }
          fieldEdits.requested_delivery_at = new Date(deliveryAt).toISOString();
        }
        if (specialInstructions) {
          fieldEdits.special_instructions = specialInstructions;
        }
        // If editing to resolve conflicts, clear existing conflicts
        if (!context.conflicts?.length || conflictsReviewed) fieldEdits.conflicts = [];
        const approved = catalog.length > 0 ? catalog : await (catalogLoader || getReviewCatalog)();
        for (let i = 0; i < items.length; i++) {
          if (!Array.isArray(approved) || !approved.some(p => p.sku === items[i].sku.trim() && p.unit === items[i].unit.trim())) {
            throw new Error(`Item #${i + 1}: Map to an approved SKU and its supported unit. Unknown products must remain unresolved; no automatic unit conversion.`);
          }
        }
      }

      const req: ContextReviewRequest = {
        expected_context_version: context.context_version,
        action,
        field_edits: fieldEdits,
        note: note.trim() || undefined,
      };

      const updated = await operationalApi.reviewContext(context.context_id, req, {
        'X-Actor-ID': 'user_staff_01',
        'X-Actor-Role': 'STAFF',
      });
      onUpdated(updated);
      onClose();
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError('Review submission failed');
      }
    } finally {
      setSubmitting(false);
    }
  };

  const drawerContent = (
    <>
      <div
        className="p1-review-backdrop"
        onClick={onClose}
        aria-hidden="true"
        role="presentation"
      />
      <aside
        className="p1-drawer-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="review-drawer-title"
        data-testid="review-drawer"
      >
        <div className="p1-drawer-header">
          <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
            <h3 id="review-drawer-title" style={{ margin: 0, fontSize: '16px', fontWeight: 700, color: '#0f172a' }}>
              Context Review & Amendments
            </h3>
            <p className="p1-drawer-subtitle" style={{ margin: 0, fontSize: '12px', color: '#64748b' }}>
              Review extracted terms and submit audited field amendments.
            </p>
            <div style={{ display: 'flex', gap: '6px', alignItems: 'center', marginTop: '4px' }}>
              <span className="p1-dim-badge">v{context.context_version}</span>
              <span className={`status-badge status-${context.status.toLowerCase()}`}>{context.status}</span>
            </div>
          </div>
          <button type="button" className="p1-btn-subtle" onClick={onClose} aria-label="Close drawer">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </div>

        {error && (
          <div className="p1-error-banner" role="alert">
            <strong>Error:</strong> {error}
          </div>
        )}

        <div className="p1-drawer-body">
          {candidateProposals.length > 0 && (
            <div className="p1-proposal-banner" style={{ background: '#f0fdf4', border: '1px solid #86efac', borderRadius: '6px', padding: '10px 12px', marginBottom: '14px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '12px', fontWeight: 700, color: '#166534' }}>Extraction Proposals (Model / Unresolved Candidates)</span>
                <span style={{ fontSize: '10px', background: '#dcfce7', color: '#15803d', padding: '2px 6px', borderRadius: '4px', fontWeight: 600 }}>Provisional</span>
              </div>
              <p>Unverified observations are not approved inventory items. Map product names to an approved SKU or mark unresolved. Quantity and unit conversions require staff verification.</p>
              {items.length > 1 && <label>Apply candidates to item
                <select aria-label="Apply candidates to item" value={targetItem} onChange={e => setTargetItem(e.target.value)}>
                  <option value="">Choose an item</option>
                  {items.map((_, i) => <option key={i} value={String(i)}>Item #{i + 1} — {items[i].sku || "unmapped"}</option>)}
                </select>
              </label>}
              <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                {candidateProposals.map(cp => (
                  <button
                    key={cp.key}
                    type="button"
                    disabled={submitting || cp.unverifiedProduct || (items.length > 1 && targetItem === '') ||
                      (cp.field === 'requested_delivery_at' && !/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/.test(cp.value))}
                    className="p1-secondary"
                    style={{ fontSize: '11px', padding: '3px 8px', background: '#ffffff', borderColor: '#86efac', color: '#166534' }}
                    onClick={() => {
                      const index = items.length === 1 ? 0 : Number(targetItem);
                      if (!items[index]) return;
                      if (cp.field === 'sku') updateItem(index, 'sku', cp.value);
                      else if (cp.field === 'quantity') updateItem(index, 'quantity', cp.value);
                      else if (cp.field === 'unit') updateItem(index, 'unit', cp.value);
                      else if (cp.field === 'requested_delivery_at') {
                        setDeliveryAt(cp.value);
                      }
                    }}
                  >
                    {cp.unverifiedProduct ? 'Unverified product' : `Apply ${cp.field === 'sku' ? 'SKU' : cp.field === 'quantity' ? 'Quantity' : cp.field === 'unit' ? 'Unit' : 'Delivery'}`}: <strong>{cp.value}</strong>
                    <span> ({cp.method}{cp.group ? `, item ${cp.group}` : ''})</span>
                    <span> Source: {cp.source || 'unspecified'} [{String(cp.start ?? '?')}:{String(cp.end ?? '?')}] “{cp.quote}”</span>
                  </button>
                ))}
              </div>
            </div>
          )}
          <section className="p1-drawer-section">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
              <h4 style={{ margin: 0 }}>Order Items {items.length > 1 ? `(${items.length})` : ''}</h4>
              <button
                type="button"
                className="p1-btn-subtle"
                style={{ fontSize: '12px', padding: '2px 8px', border: '1px solid #cbd5e1', borderRadius: '4px' }}
                onClick={addItem}
                disabled={submitting}
              >
                + Add Item
              </button>
            </div>
            <p>{catalogState === 'ready' ? `Approved SKU/unit pairs: ${catalog.map(p => `${p.sku} / ${p.unit}`).join(', ') || 'none configured'}` : `Approved catalog ${catalogState}; product mapping cannot be verified.`}</p>
            <datalist id="p1-approved-skus">{[...new Set(catalog.map(p => p.sku))].map(sku => <option key={sku} value={sku} />)}</datalist>
            {!!context.conflicts?.length && (
              <div className="p1-drawer-conflicts" style={{ background: '#fef2f2', border: '1px solid #fecaca', borderRadius: '6px', padding: '10px 12px', marginBottom: '14px' }}>
                <h5 style={{ margin: '0 0 6px 0', color: '#991b1b', fontSize: '12px', fontWeight: 700 }}>
                  Pending Authorization & Policy Constraints ({context.conflicts.length})
                </h5>
                <ul style={{ margin: 0, paddingLeft: '18px', color: '#b91c1c', fontSize: '11px', lineHeight: '1.4' }}>
                  {context.conflicts.map((conf, idx) => (
                    <li key={idx} style={{ marginBottom: '3px' }}>{conf}</li>
                  ))}
                </ul>
                <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginTop: '8px', fontSize: '11px', color: '#7f1d1d', fontWeight: 600, cursor: 'pointer' }}>
                  <input type="checkbox" checked={conflictsReviewed} onChange={e => setConflictsReviewed(e.target.checked)} />
                  I reviewed and resolved all listed conflicts
                </label>
              </div>
            )}

            {items.map((it, idx) => (
              <div
                key={idx}
                className="p1-item-edit-card"
                style={{
                  marginBottom: idx < items.length - 1 ? '12px' : '0',
                  padding: items.length > 1 ? '10px' : '0',
                  background: items.length > 1 ? '#f8fafc' : 'transparent',
                  borderRadius: '6px',
                  border: items.length > 1 ? '1px solid #e2e8f0' : 'none',
                }}
              >
                {items.length > 1 && (
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                    <span style={{ fontSize: '12px', fontWeight: 600, color: '#475569' }}>Item #{idx + 1}</span>
                    <button
                      type="button"
                      className="p1-btn-subtle"
                      style={{ fontSize: '11px', color: '#dc2626', padding: '1px 6px' }}
                      onClick={() => removeItem(idx)}
                      disabled={submitting}
                    >
                      Remove
                    </button>
                  </div>
                )}
                <div className="p1-form-group">
                  <label htmlFor={idx === 0 ? "p1-input-sku" : `p1-input-sku-${idx}`}>SKU / Product</label>
                  <input
                    id={idx === 0 ? "p1-input-sku" : `p1-input-sku-${idx}`}
                    list="p1-approved-skus"
                    type="text"
                    value={it.sku}
                    placeholder="e.g. SOURDOUGH, BURGER"
                    onChange={e => updateItem(idx, 'sku', e.target.value)}
                    disabled={submitting}
                  />
                  <span className="p1-form-hint">Item identifier or product name recognized by inventory</span>
                </div>

                <div className="p1-form-row">
                  <div className="p1-form-group">
                    <label htmlFor={idx === 0 ? "p1-input-qty" : `p1-input-qty-${idx}`}>Quantity</label>
                    <input
                      id={idx === 0 ? "p1-input-qty" : `p1-input-qty-${idx}`}
                      type="text"
                      value={it.quantity}
                      placeholder="e.g. 50"
                      onChange={e => updateItem(idx, 'quantity', e.target.value)}
                      disabled={submitting}
                    />
                    <span className="p1-form-hint">Positive numeric quantity</span>
                  </div>

                  <div className="p1-form-group">
                    <label htmlFor={idx === 0 ? "p1-input-unit" : `p1-input-unit-${idx}`}>Unit</label>
                    <select
                      id={idx === 0 ? "p1-input-unit" : `p1-input-unit-${idx}`}
                      value={it.unit}
                      onChange={e => updateItem(idx, 'unit', e.target.value)}
                      disabled={submitting}
                    >
                      <option value="">Missing / unknown</option>
                      {[...new Set(['pcs', 'box', 'kg', ...catalog.map(p => p.unit),
                        ...items.map(item => item.unit), ...candidateProposals.filter(p => p.field === 'unit').map(p => p.value)])]
                        .filter(Boolean).map(unit => <option key={unit} value={unit}>{unit}</option>)}
                    </select>
                    <span className="p1-form-hint">Standard packaging unit</span>
                  </div>
                </div>
              </div>
            ))}
          </section>

          <section className="p1-drawer-section">
            <h4>Requested Delivery</h4>
            <div className="p1-form-row">
              <div className="p1-form-group">
                <label htmlFor="p1-input-delivery">Date & Time (ISO with UTC offset)</label>
                <input
                  id="p1-input-delivery"
                  type="text"
                  value={deliveryAt}
                  placeholder="e.g. 2026-10-23T15:00:00+08:00"
                  onChange={e => setDeliveryAt(e.target.value)}
                  disabled={submitting}
                />
                <span className="p1-form-hint">ISO 8601 with explicit timezone offset</span>
                {evidenceDelivery && (
                  <span className="p1-form-hint" style={{ color: '#0369a1', display: 'block', marginTop: '4px' }}>
                    Extracted date/time: <strong>{evidenceDelivery}</strong> {evidenceQualifier ? `(${evidenceQualifier})` : ''}
                    {Boolean(
                      (context.field_evidence?.requested_delivery_at?.[0]?.normalization_metadata as Record<string, string> | undefined)?.extraction_correctness === 'CONFIRMED_PARSED' ||
                      (context.field_evidence?.requested_delivery_at?.[0]?.normalization_metadata as Record<string, string> | undefined)?.rescheduling === 'true'
                    ) && (
                      <span className="p1-dim-badge" style={{ display: 'inline-block', marginLeft: '6px', background: '#e0f2fe', color: '#0369a1', fontSize: '10px' }}>
                        Parsed, Pending Authorization
                      </span>
                    )}
                    {!deliveryAt.includes('T') && !deliveryAt.endsWith('Z') && (
                      <span style={{ display: 'block', marginTop: '2px' }}>
                        Enter full ISO timestamp with offset (e.g. {evidenceDelivery.split('T')[0]}T15:00:00+08:00) to confirm delivery.
                      </span>
                    )}
                    {Boolean((context.field_evidence?.requested_delivery_at?.[0]?.normalization_metadata as Record<string, string> | undefined)?.reason) && (
                      <span style={{ display: 'block', color: '#475569', marginTop: '2px' }}>
                        Reason: {String((context.field_evidence?.requested_delivery_at?.[0]?.normalization_metadata as Record<string, string>).reason)}
                      </span>
                    )}
                  </span>
                )}
              </div>

              <div className="p1-form-group">
                <label htmlFor="p1-input-qualifier">Relation / Qualifier</label>
                <select
                  id="p1-input-qualifier"
                  value={qualifier}
                  onChange={e => setQualifier(e.target.value)}
                  disabled={submitting}
                >
                  <option value="">Unresolved</option>
                  <option value="EXACT">EXACT</option>
                  <option value="DEADLINE">DEADLINE</option>
                  <option value="DATE_ONLY">DATE_ONLY</option>
                </select>
                <span className="p1-form-hint">Delivery timing constraint precision</span>
              </div>
            </div>

            <div className="p1-form-group">
              <label htmlFor="p1-input-notes">Special Instructions</label>
              <textarea
                id="p1-input-notes"
                rows={2}
                value={specialInstructions}
                onChange={e => setSpecialInstructions(e.target.value)}
                placeholder="Customer delivery or dietary notes..."
                disabled={submitting}
              />
              <span className="p1-form-hint">Optional customer handling preferences</span>
            </div>
          </section>

          <section className="p1-drawer-section">
            <h4>Audit Reason & Notes</h4>
            {suggestedClarification && (
              <div
                className="p1-suggested-clarification-card"
                data-testid="p1-suggested-clarification"
                style={{
                  background: '#eff6ff',
                  border: '1px solid #bfdbfe',
                  borderRadius: '6px',
                  padding: '10px 12px',
                  marginBottom: '12px',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                  <span style={{ fontSize: '12px', fontWeight: 700, color: '#1e40af' }}>
                    AI Suggested Clarification (P4 Draft Preview)
                  </span>
                  <span style={{ fontSize: '10px', background: '#dbeafe', color: '#1d4ed8', padding: '2px 6px', borderRadius: '4px', fontWeight: 600 }}>
                    Requires Staff Approval
                  </span>
                </div>
                <p style={{ margin: '4px 0 8px 0', fontSize: '12px', color: '#1e3a8a', fontStyle: 'italic' }}>
                  &ldquo;{suggestedClarification}&rdquo;
                </p>
                <button
                  type="button"
                  className="p1-btn-subtle"
                  style={{
                    fontSize: '11px',
                    padding: '3px 8px',
                    background: '#ffffff',
                    border: '1px solid #93c5fd',
                    color: '#1d4ed8',
                    borderRadius: '4px',
                    cursor: 'pointer',
                  }}
                  onClick={() => setNote(suggestedClarification)}
                >
                  Adopt as Clarification Note
                </button>
              </div>
            )}
            <div className="p1-form-group">
              <label htmlFor="p1-input-audit-note">Reviewer Note</label>
              <textarea
                id="p1-input-audit-note"
                rows={2}
                value={note}
                onChange={e => setNote(e.target.value)}
                placeholder="Reason for change, confirmation evidence, or clarification details..."
                disabled={submitting}
              />
              <span className="p1-form-hint">Audited business reason recorded in context timeline</span>
            </div>
          </section>
        </div>

        <div className="p1-drawer-footer">
          <div className="p1-drawer-footer-row">
            <button
              type="button"
              className="p1-btn p1-btn-primary"
              disabled={submitting}
              onClick={() => handleSubmit('EDIT_FIELD')}
            >
              Apply Field Edits
            </button>
            <button
              type="button"
              className="p1-btn p1-btn-secondary"
              disabled={submitting || hasUnsavedEdits}
              onClick={() => handleSubmit('ACCEPT_EXTRACTION')}
            >
              Accept Extraction
            </button>
            {hasUnsavedEdits && <span>Use Apply Field Edits to save your changes before accepting extraction.</span>}
          </div>
          <div className="p1-drawer-footer-row">
            <button
              type="button"
              className="p1-btn p1-btn-subtle-amber"
              disabled={submitting}
              onClick={() => handleSubmit('REQUEST_MORE_INFO')}
            >
              Request More Info
            </button>
            <button
              type="button"
              className="p1-btn p1-btn-subtle-red"
              disabled={submitting}
              onClick={() => handleSubmit('MARK_UNRESOLVED')}
            >
              Mark Unresolved
            </button>
          </div>
        </div>
      </aside>
    </>
  );

  return typeof document !== 'undefined' ? createPortal(drawerContent, document.body) : drawerContent;
}
