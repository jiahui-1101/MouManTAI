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

  const currentItem = context.requested_items?.[0] || { sku: '', quantity: '', unit: '' };

  const [sku, setSku] = useState(currentItem.sku);
  const [quantity, setQuantity] = useState(currentItem.quantity);
  const [unit, setUnit] = useState(currentItem.unit);
  const [deliveryAt, setDeliveryAt] = useState(
    context.requested_delivery_at || ''
  );
  const [qualifier, setQualifier] = useState(context.delivery_qualifier || '');
  const [specialInstructions, setSpecialInstructions] = useState(context.special_instructions || '');
  const [note, setNote] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
      const items: RequestedItem[] = [{ sku: sku.trim(), quantity: quantity.trim(), unit: unit.trim() }];
      const fieldEdits: Record<string, unknown> = {};

      if (action === 'EDIT_FIELD') {
        if (!sku.trim() || !unit.trim() || !/^[0-9]+(?:\.[0-9]+)?$/.test(quantity.trim()) || Number(quantity) <= 0) {
          throw new Error('Enter an explicit SKU, positive quantity and unit. Missing fields are not defaulted.');
        }
        fieldEdits.requested_items = items;
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
          <section className="p1-drawer-section">
            <h4>Order Items</h4>
            <div className="p1-form-group">
              <label htmlFor="p1-input-sku">SKU / Product</label>
              <input
                id="p1-input-sku"
                type="text"
                value={sku}
                placeholder="e.g. SOURDOUGH, BURGER"
                onChange={e => setSku(e.target.value)}
                disabled={submitting}
              />
              <span className="p1-form-hint">Item identifier or product name recognized by inventory</span>
            </div>

            <div className="p1-form-row">
              <div className="p1-form-group">
                <label htmlFor="p1-input-qty">Quantity</label>
                <input
                  id="p1-input-qty"
                  type="text"
                  value={quantity}
                  placeholder="e.g. 50"
                  onChange={e => setQuantity(e.target.value)}
                  disabled={submitting}
                />
                <span className="p1-form-hint">Positive numeric quantity</span>
              </div>

              <div className="p1-form-group">
                <label htmlFor="p1-input-unit">Unit</label>
                <select
                  id="p1-input-unit"
                  value={unit}
                  onChange={e => setUnit(e.target.value)}
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

