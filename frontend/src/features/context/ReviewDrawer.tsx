import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import type { ContextReviewRequest, OrderContextRecord, RequestedItem } from './types';
import { operationalApi } from './operationalApi';

export interface ReviewDrawerProps {
  context: OrderContextRecord;
  isOpen: boolean;
  onClose: () => void;
  onUpdated: (updated: OrderContextRecord) => void;
}

export function ReviewDrawer({ context, isOpen, onClose, onUpdated }: ReviewDrawerProps) {
  if (!isOpen) return null;

  const evidenceSku = (context.field_evidence?.sku?.[0]?.normalized_value || context.field_evidence?.sku?.[0]?.quote || '') as string;
  const evidenceQty = (context.field_evidence?.quantity?.[0]?.normalized_value || context.field_evidence?.quantity?.[0]?.quote || '') as string;
  const evidenceUnit = (context.field_evidence?.unit?.[0]?.normalized_value || context.field_evidence?.unit?.[0]?.quote || '') as string;
  const evidenceDelivery = (context.field_evidence?.requested_delivery_at?.[0]?.normalized_value || context.field_evidence?.requested_delivery_at?.[0]?.quote || '') as string;
  const evidenceQualifier = (context.field_evidence?.requested_delivery_at?.[0]?.qualifier || '') as string;

  const initialItems: RequestedItem[] = (context.requested_items && context.requested_items.length > 0)
    ? context.requested_items.map(it => ({ sku: it.sku || '', quantity: it.quantity || '', unit: it.unit || '' }))
    : [{ sku: evidenceSku || '', quantity: evidenceQty || '', unit: evidenceUnit || '' }];

  const [items, setItems] = useState<RequestedItem[]>(initialItems);
  const [deliveryAt, setDeliveryAt] = useState(
    context.requested_delivery_at || (evidenceDelivery.includes('T') ? evidenceDelivery : (evidenceDelivery && /^\d{4}-\d{2}-\d{2}$/.test(evidenceDelivery) ? evidenceDelivery : ''))
  );
  const [qualifier, setQualifier] = useState(context.delivery_qualifier || evidenceQualifier || (evidenceDelivery && !evidenceDelivery.includes('T') ? 'DATE_ONLY' : ''));
  const [specialInstructions, setSpecialInstructions] = useState(context.special_instructions || '');
  const [note, setNote] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const updateItem = (index: number, field: keyof RequestedItem, value: string) => {
    setItems(prev => {
      const next = [...prev];
      next[index] = { ...next[index], [field]: value };
      return next;
    });
  };

  const addItem = () => {
    setItems(prev => [...prev, { sku: '', quantity: '', unit: 'pcs' }]);
  };

  const removeItem = (index: number) => {
    if (items.length <= 1) return;
    setItems(prev => prev.filter((_, i) => i !== index));
  };

  const candidateProposals: { field: string; label: string; value: string; method: string }[] = [];
  if (context.field_evidence) {
    for (const [key, evList] of Object.entries(context.field_evidence)) {
      if (Array.isArray(evList)) {
        for (const ev of evList) {
          const val = String(ev.normalized_value || ev.quote || '');
          if (val && (ev.method === 'MODEL' || ev.validation_status === 'UNRESOLVED')) {
            const label = key === 'sku' ? 'SKU' : key === 'quantity' ? 'Quantity' : key === 'unit' ? 'Unit' : 'Delivery';
            if (!candidateProposals.some(p => p.field === key && p.value === val)) {
              candidateProposals.push({ field: key, label, value: val, method: String(ev.method || 'MODEL') });
            }
          }
        }
      }
    }
  }

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
        fieldEdits.conflicts = [];
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
              <p style={{ margin: '4px 0 8px 0', fontSize: '11px', color: '#166534' }}>
                Evidence-grounded observations extracted from text. Click to apply directly to review form:
              </p>
              <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                {candidateProposals.map(cp => (
                  <button
                    key={`${cp.field}-${cp.value}`}
                    type="button"
                    className="p1-secondary"
                    style={{ fontSize: '11px', padding: '3px 8px', background: '#ffffff', borderColor: '#86efac', color: '#166534' }}
                    onClick={() => {
                      if (cp.field === 'sku') updateItem(0, 'sku', cp.value);
                      else if (cp.field === 'quantity') updateItem(0, 'quantity', cp.value);
                      else if (cp.field === 'unit') updateItem(0, 'unit', cp.value);
                      else if (cp.field === 'requested_delivery_at') {
                        setDeliveryAt(cp.value);
                        if (!cp.value.includes('T')) setQualifier('DATE_ONLY');
                      }
                    }}
                  >
                    Apply {cp.label}: <strong>{cp.value}</strong> <span style={{ color: '#64748b', fontSize: '10px' }}>({cp.method})</span>
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
                      <option value="pcs">pcs</option>
                      <option value="box">box</option>
                      <option value="kg">kg</option>
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
                {evidenceDelivery && !deliveryAt.includes('T') && (
                  <span className="p1-form-hint" style={{ color: '#0369a1', display: 'block', marginTop: '4px' }}>
                    Extracted date: <strong>{evidenceDelivery}</strong> (DATE_ONLY). Enter full ISO timestamp with offset (e.g. {evidenceDelivery}T15:00:00+08:00) to confirm delivery.
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
              disabled={submitting}
              onClick={() => handleSubmit('ACCEPT_EXTRACTION')}
            >
              Accept Extraction
            </button>
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
