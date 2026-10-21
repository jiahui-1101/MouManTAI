import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import type {
  ContextReviewRecord,
  OrderContextRecord,
  OrderContextVersionRecord,
} from './types';
import { operationalApi } from './operationalApi';
import { ReviewDrawer } from './ReviewDrawer';

export interface OrderContextDetailProps {
  orderId?: string;
  contextId?: string;
  onClose?: () => void;
}

export function OrderContextDetail({ orderId: propOrderId, contextId: propContextId, onClose }: OrderContextDetailProps) {
  const params = useParams<{ id: string }>();
  const effectiveOrderId = propOrderId || params.id;
  const effectiveContextId = propContextId;

  const [context, setContext] = useState<OrderContextRecord | null>(null);
  const [versions, setVersions] = useState<OrderContextVersionRecord[]>([]);
  const [reviews, setReviews] = useState<ContextReviewRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isReviewOpen, setIsReviewOpen] = useState(false);
  const [showHistory, setShowHistory] = useState(false);

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      let ctx: OrderContextRecord;
      if (effectiveContextId) {
        ctx = await operationalApi.getContext(effectiveContextId);
      } else if (effectiveOrderId) {
        ctx = await operationalApi.getContextByOrder(effectiveOrderId);
      } else {
        throw new Error('No order reference or context ID provided');
      }
      setContext(ctx);

      const [vers, revs] = await Promise.all([
        operationalApi.listContextVersions(ctx.context_id).catch(() => []),
        operationalApi.listContextReviews(ctx.context_id).catch(() => []),
      ]);
      setVersions(vers);
      setReviews(revs);
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError('Failed to load order context');
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [effectiveOrderId, effectiveContextId]);

  if (loading) {
    return (
      <div className="p1-context-loading" role="status">
        <div className="p1-spinner" />
        <p>Loading Order Context...</p>
      </div>
    );
  }

  if (error || !context) {
    return (
      <div className="p1-context-error-card" role="alert">
        <h3>Order Context Unavailable</h3>
        <p>{error || 'Context record not found.'}</p>
        <button type="button" className="p1-btn p1-btn-primary" onClick={loadData}>
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="p1-context-container">
      <header className="p1-context-header">
        <div className="p1-context-title-group">
          <h2>Order Context: {context.order_id || 'Pending Link'}</h2>
          <div className="p1-badge-group">
            <span className={`p1-badge p1-badge-${context.status.toLowerCase()}`}>{context.status}</span>
            <span className="p1-dim-badge">v{context.context_version}</span>
            <span className={`p1-identity-badge p1-identity-${context.customer_identity_status.toLowerCase()}`}>
              {context.customer_identity_status}
            </span>
          </div>
        </div>

        <div className="p1-context-actions">
          <button
            type="button"
            className="p1-btn p1-btn-primary"
            onClick={() => setIsReviewOpen(true)}
          >
            Review & Amend
          </button>
          <button
            type="button"
            className="p1-btn p1-btn-outline"
            onClick={() => setShowHistory(!showHistory)}
          >
            {showHistory ? 'Hide History' : 'Version History'}
          </button>
          {onClose && (
            <button type="button" className="p1-btn-subtle" onClick={onClose} aria-label="Close">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <line x1="18" y1="6" x2="6" y2="18"></line>
                <line x1="6" y1="6" x2="18" y2="18"></line>
              </svg>
            </button>
          )}
        </div>
      </header>

      {/* Critical Conflicts Banner */}
      {(context.conflicts?.length ?? 0) > 0 && (
        <div className="p1-conflict-box" role="alert">
          <h4>Security / Term Conflicts Detected</h4>
          <ul>
            {(context.conflicts ?? []).map((conf, idx) => (
              <li key={idx}>{conf}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Missing Information Banner */}
      {(context.missing_fields?.length ?? 0) > 0 && (
        <div className="p1-missing-box" role="alert">
          <h4>Information Partial — Missing Fields</h4>
          <p>The following fields are required before commitment readiness:</p>
          <ul>
            {(context.missing_fields ?? []).map((field, idx) => (
              <li key={idx}><code>{field}</code></li>
            ))}
          </ul>
        </div>
      )}

      {/* Summary Dimensions */}
      <section className="p1-dimensions-card">
        <div className="p1-dim-item">
          <span className="p1-dim-label">Customer</span>
          <span className="p1-dim-val">{context.customer_id || 'Unidentified'}</span>
        </div>
        <div className="p1-dim-item">
          <span className="p1-dim-label">Delivery Date</span>
          <span className="p1-dim-val">
            {context.requested_delivery_at
              ? new Date(context.requested_delivery_at).toLocaleString()
              : 'Not specified'}
          </span>
        </div>
        <div className="p1-dim-item">
          <span className="p1-dim-label">Qualifier</span>
          <span className="p1-dim-val">{context.delivery_qualifier || 'EXACT'}</span>
        </div>
        <div className="p1-dim-item">
          <span className="p1-dim-label">Last Reviewer</span>
          <span className="p1-dim-val">
            {context.last_reviewed_by
              ? `${context.last_reviewed_by} (${context.last_reviewed_role || 'STAFF'})`
              : 'Initial Ingest'}
          </span>
        </div>
      </section>

      {/* Requested Items Table */}
      <section className="p1-section-card">
        <h3>Requested Products</h3>
        <table className="p1-items-table">
          <thead>
            <tr>
              <th>SKU</th>
              <th>Quantity</th>
              <th>Unit</th>
              <th>Evidence Quotes</th>
            </tr>
          </thead>
          <tbody>
            {(context.requested_items ?? []).map((item, idx) => {
              const skuEvidence = context.field_evidence?.sku ?? [];
              const qtyEvidence = context.field_evidence?.quantity ?? [];
              return (
                <tr key={idx}>
                  <td><strong>{item.sku}</strong></td>
                  <td>{item.quantity}</td>
                  <td>{item.unit}</td>
                  <td>
                    {skuEvidence.concat(qtyEvidence).map((ev, evIdx) => (
                      <span key={evIdx} className="p1-evidence-tag">
                        "{String(ev.quote ?? '')}"
                      </span>
                    ))}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>

        {context.special_instructions && (
          <div className="p1-instructions-box">
            <strong>Special Instructions:</strong> {context.special_instructions}
          </div>
        )}
      </section>

      {/* Source Messages Panel */}
      <section className="p1-section-card">
        <h3>Contributing Source Messages</h3>
        <div className="p1-message-tags">
          {(context.source_message_ids ?? []).map((mid, idx) => (
            <span key={idx} className="p1-message-badge">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={{ marginRight: '5px', verticalAlign: '-1px' }}>
                <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"></path>
                <polyline points="22,6 12,13 2,6"></polyline>
              </svg>
              {mid}
            </span>
          ))}
        </div>
      </section>

      {/* Version History Drawer / Timeline */}
      {showHistory && (
        <section className="p1-section-card p1-history-timeline" aria-label="Version History">
          <h3>Version History & Audit Log</h3>
          {versions.length === 0 ? (
            <p>No historical versions recorded.</p>
          ) : (
            <div className="p1-timeline-list">
              {versions.map(ver => (
                <div key={ver.version_id} className="p1-timeline-item">
                  <div className="p1-timeline-header">
                    <span className="p1-timeline-version">Version {ver.context_version}</span>
                    <span className="p1-timeline-action">{ver.change_type}</span>
                    <span className="p1-timeline-time">{new Date(ver.created_at).toLocaleString()}</span>
                  </div>
                  <div className="p1-timeline-meta">
                    <span>Actor: {ver.actor_id || 'System'}</span>
                    {ver.reason && <span> · Reason: {ver.reason}</span>}
                  </div>
                </div>
              ))}
            </div>
          )}

          {reviews.length > 0 && (
            <div style={{ marginTop: '16px' }}>
              <h4>Human Review History ({reviews.length})</h4>
              <div className="p1-timeline-list">
                {reviews.map(rev => (
                  <div key={rev.review_id} className="p1-timeline-item">
                    <div className="p1-timeline-header">
                      <span className="p1-badge p1-blue">{rev.action}</span>
                      <span className="p1-timeline-version">v{rev.context_version_before} → v{rev.context_version_after}</span>
                      <span className="p1-timeline-time">{new Date(rev.created_at).toLocaleString()}</span>
                    </div>
                    <div className="p1-timeline-meta">
                      <span>Reviewer: {rev.actor_id} ({rev.actor_role})</span>
                      {rev.note && <span> · Note: "{rev.note}"</span>}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </section>
      )}

      {/* Nested Review Drawer */}
      <ReviewDrawer
        context={context}
        isOpen={isReviewOpen}
        onClose={() => setIsReviewOpen(false)}
        onUpdated={updated => setContext(updated)}
      />
    </div>
  );
}
