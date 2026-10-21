import { useState } from 'react';
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

  const currentItem = context.requested_items?.[0] || { sku: 'BURGER', quantity: '1', unit: 'pcs' };

  const [sku, setSku] = useState(currentItem.sku);
  const [quantity, setQuantity] = useState(currentItem.quantity);
  const [unit, setUnit] = useState(currentItem.unit);
  const [deliveryAt, setDeliveryAt] = useState(
    context.requested_delivery_at ? new Date(context.requested_delivery_at).toISOString().slice(0, 16) : ''
  );
  const [qualifier, setQualifier] = useState(context.delivery_qualifier || 'EXACT');
  const [specialInstructions, setSpecialInstructions] = useState(context.special_instructions || '');
  const [note, setNote] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (action: 'ACCEPT_EXTRACTION' | 'EDIT_FIELD' | 'REQUEST_MORE_INFO' | 'MARK_UNRESOLVED') => {
    setSubmitting(true);
    setError(null);
    try {
      const items: RequestedItem[] = [{ sku: sku.trim(), quantity: quantity.trim(), unit: unit.trim() }];
      const fieldEdits: Record<string, unknown> = {};

      if (action === 'EDIT_FIELD') {
        fieldEdits.requested_items = items;
        fieldEdits.delivery_qualifier = qualifier;
        if (deliveryAt) {
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
    <div className="p1-drawer-backdrop" role="dialog" aria-modal="true" aria-labelledby="review-drawer-title">
      <div className="p1-drawer-panel">
        <div className="p1-drawer-header">
          <div>
            <h3 id="review-drawer-title">Context Review & Amendments</h3>
            <span className="p1-dim-badge">v{context.context_version}</span>
            <span className={`p1-badge p1-badge-${context.status.toLowerCase()}`}>{context.status}</span>
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
                onChange={e => setSku(e.target.value)}
                disabled={submitting}
              />
            </div>

            <div className="p1-form-row">
              <div className="p1-form-group">
                <label htmlFor="p1-input-qty">Quantity</label>
                <input
                  id="p1-input-qty"
                  type="text"
                  value={quantity}
                  onChange={e => setQuantity(e.target.value)}
                  disabled={submitting}
                />
              </div>

              <div className="p1-form-group">
                <label htmlFor="p1-input-unit">Unit</label>
                <select
                  id="p1-input-unit"
                  value={unit}
                  onChange={e => setUnit(e.target.value)}
                  disabled={submitting}
                >
                  <option value="pcs">pcs</option>
                  <option value="box">box</option>
                  <option value="kg">kg</option>
                </select>
              </div>
            </div>
          </section>

          <section className="p1-drawer-section">
            <h4>Requested Delivery</h4>
            <div className="p1-form-row">
              <div className="p1-form-group">
                <label htmlFor="p1-input-delivery">Date & Time</label>
                <input
                  id="p1-input-delivery"
                  type="datetime-local"
                  value={deliveryAt}
                  onChange={e => setDeliveryAt(e.target.value)}
                  disabled={submitting}
                />
              </div>

              <div className="p1-form-group">
                <label htmlFor="p1-input-qualifier">Relation / Qualifier</label>
                <select
                  id="p1-input-qualifier"
                  value={qualifier}
                  onChange={e => setQualifier(e.target.value)}
                  disabled={submitting}
                >
                  <option value="EXACT">EXACT</option>
                  <option value="BEFORE">BEFORE / DEADLINE</option>
                  <option value="AFTER">AFTER</option>
                  <option value="DATE_ONLY">DATE_ONLY</option>
                </select>
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
            </div>
          </section>
        </div>

        <div className="p1-drawer-footer">
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
            className="p1-btn p1-btn-success"
            disabled={submitting}
            onClick={() => handleSubmit('ACCEPT_EXTRACTION')}
          >
            Accept Extraction
          </button>
          <button
            type="button"
            className="p1-btn p1-btn-warning"
            disabled={submitting}
            onClick={() => handleSubmit('REQUEST_MORE_INFO')}
          >
            Request More Info
          </button>
          <button
            type="button"
            className="p1-btn p1-btn-danger"
            disabled={submitting}
            onClick={() => handleSubmit('MARK_UNRESOLVED')}
          >
            Mark Unresolved
          </button>
        </div>
      </div>
    </div>
  );

  return typeof document !== 'undefined' ? createPortal(drawerContent, document.body) : drawerContent;
}

