import { useCallback, useEffect, useState } from 'react';
import { Link, useInRouterContext, useParams } from 'react-router-dom';
import type {
  ContextReviewRecord,
  OrderContextRecord,
  OrderContextVersionRecord,
} from './types';
import { getReviewCatalog, operationalApi } from './operationalApi';
import { ReviewDrawer } from './ReviewDrawer';

export interface OrderContextDetailProps {
  orderId?: string;
  contextId?: string;
  onClose?: () => void;
  onContextUpdated?: (updated: OrderContextRecord) => void;
  requestHeaders?: Record<string, string>;
  onContextLoaded?: (context: OrderContextRecord) => void;
}

export function OrderContextDetail({
  orderId: propOrderId,
  contextId: propContextId,
  onClose,
  onContextUpdated,
  requestHeaders,
  onContextLoaded,
}: OrderContextDetailProps) {
  const inRouter = useInRouterContext();
  const params = useParams<{ id: string }>();
  const effectiveOrderId = propOrderId || params.id;
  const effectiveContextId = propContextId;
  const catalogLoader = useCallback(() => requestHeaders ? getReviewCatalog(requestHeaders) : getReviewCatalog(), [requestHeaders]);

  const [context, setContext] = useState<OrderContextRecord | null>(null);
  const [versions, setVersions] = useState<OrderContextVersionRecord[]>([]);
  const [reviews, setReviews] = useState<ContextReviewRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isReviewOpen, setIsReviewOpen] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [isPublishing, setIsPublishing] = useState(false);
  const [publishError, setPublishError] = useState<string | null>(null);
  const [publishSuccess, setPublishSuccess] = useState<string | null>(null);

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      let ctx: OrderContextRecord;
      if (effectiveContextId) {
        ctx = await operationalApi.getContext(effectiveContextId, ...(requestHeaders ? [requestHeaders] : []));
      } else if (effectiveOrderId) {
        ctx = await operationalApi.getContextByOrder(effectiveOrderId, ...(requestHeaders ? [requestHeaders] : []));
      } else {
        throw new Error('No order reference or context ID provided');
      }
      if (requestHeaders?.['X-Tenant-ID'] && ctx.tenant_id !== requestHeaders['X-Tenant-ID']) {
        throw new Error('Order context tenant does not match the current session');
      }
      setContext(ctx);
      onContextLoaded?.(ctx);

      const [vers, revs] = await Promise.all([
        operationalApi.listContextVersions(ctx.context_id, ...(requestHeaders ? [requestHeaders] : [])).catch(() => []),
        operationalApi.listContextReviews(ctx.context_id, ...(requestHeaders ? [requestHeaders] : [])).catch(() => []),
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

  const handlePublishToCore = async () => {
    if (!context) return;
    setIsPublishing(true);
    setPublishError(null);
    setPublishSuccess(null);
    try {
      const updated = await operationalApi.publishContext(context.context_id, ...(requestHeaders ? [requestHeaders] : []));
      setContext(updated);
      setPublishSuccess(`Successfully published to Core commitment ${updated.core_commitment_id}`);
      onContextUpdated?.(updated);
    } catch (err: unknown) {
      if (err instanceof Error) {
        setPublishError(err.message);
      } else {
        setPublishError('Failed to publish context to Core');
      }
    } finally {
      setIsPublishing(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [effectiveOrderId, effectiveContextId, requestHeaders]);

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
            {context.core_commitment_id && (
              <span
                className="p1-badge p1-badge-ready"
                title={context.published_to_core_at ? `Published to Core at ${new Date(context.published_to_core_at).toLocaleString()}` : 'Published to Core'}
              >
                Core: {context.core_commitment_id}
              </span>
            )}
          </div>
        </div>

        <div className="p1-context-actions">
          {context.core_commitment_id && (inRouter ? (
            <Link className="p1-btn p1-btn-outline" to={`/commitments/${encodeURIComponent(context.core_commitment_id)}`}>View feasibility</Link>
          ) : (
            <a className="p1-btn p1-btn-outline" href={`/commitments/${encodeURIComponent(context.core_commitment_id)}`}>View feasibility</a>
          ))}
          <button
            type="button"
            className={`p1-btn ${context.core_commitment_id ? 'p1-btn-outline' : 'p1-btn-success'}`}
            disabled={isPublishing}
            onClick={handlePublishToCore}
          >
            {isPublishing
              ? 'Publishing to Core...'
              : context.core_commitment_id
                ? 'Re-publish to Core'
                : 'Publish to Core'}
          </button>
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

      {/* Publish Alerts */}
      {publishError && (
        <div className="p1-conflict-box" role="alert">
          <h4>Publish to Core Ineligible / Failed</h4>
          <p>{publishError}</p>
        </div>
      )}

      {publishSuccess && (
        <div className="p1-missing-box" role="status" style={{ borderLeftColor: '#10b981', background: '#ecfdf5', color: '#065f46' }}>
          <h4 style={{ color: '#065f46' }}>Published to Core</h4>
          <p>{publishSuccess}</p>
        </div>
      )}

      {/* Critical Conflicts Banner */}
      {(context.conflicts?.length ?? 0) > 0 && (
        <div className="p1-conflict-box" role="alert">
          <h4>Security / Term Conflicts Detected</h4>
          <p style={{ margin: '2px 0 6px 0', fontSize: '12px', color: '#7f1d1d' }}>
            Pending authorization, rescheduling policy, and term review constraints:
          </p>
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
            {Boolean(
              (context.field_evidence?.requested_delivery_at?.[0]?.normalization_metadata as Record<string, string> | undefined)?.extraction_correctness === 'CONFIRMED_PARSED' ||
              (context.field_evidence?.requested_delivery_at?.[0]?.normalization_metadata as Record<string, string> | undefined)?.rescheduling === 'true'
            ) && (
              <span className="p1-dim-badge" style={{ marginLeft: '6px', background: '#e0f2fe', color: '#0369a1', fontSize: '11px' }}>
                Parsed, Pending Authorization
              </span>
            )}
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
        {(!context.requested_items || context.requested_items.length === 0) ? (
          (context.field_evidence?.sku?.length || context.field_evidence?.quantity?.length) ? (
            <div className="p1-unmapped-candidates-alert" style={{ padding: '12px 14px', background: '#fffbeb', border: '1px solid #fde68a', borderRadius: '6px', marginBottom: '8px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#b45309', fontWeight: 600, marginBottom: '6px' }}>
                <span className="p1-orbyte-status-badge is-attention">Awaiting Mapping</span>
                <span>Unverified item candidates detected from source text:</span>
              </div>
              <ul style={{ margin: '4px 0 8px 18px', padding: 0, color: '#78350f', fontSize: '13px' }}>
                {context.field_evidence?.sku?.map((ev, i) => {
                  const meta = ev.normalization_metadata as Record<string, unknown> | undefined;
                  const gid = String(meta?.group_id ?? ev.group_id ?? '');
                  const matchedQtyEv = (gid
                    ? context.field_evidence?.quantity?.find(q => String((q.normalization_metadata as Record<string, unknown> | undefined)?.group_id ?? q.group_id ?? '') === gid)
                    : undefined) ?? context.field_evidence?.quantity?.[i];
                  const matchedUnitEv = (gid
                    ? context.field_evidence?.unit?.find(u => String((u.normalization_metadata as Record<string, unknown> | undefined)?.group_id ?? u.group_id ?? '') === gid)
                    : undefined) ?? context.field_evidence?.unit?.[i];
                  const qty = matchedQtyEv?.normalized_value ?? matchedQtyEv?.quote ?? '';
                  const unit = matchedUnitEv?.normalized_value ?? matchedUnitEv?.quote ?? '';
                  return (
                    <li key={i}>
                      <strong>"{String(ev.normalized_value ?? ev.quote ?? '')}"</strong>
                      {qty ? ` — Quantity: ${qty}` : ''}
                      {unit ? ` ${unit}` : ''}
                      <span style={{ color: '#92400e', fontSize: '11px', marginLeft: '6px' }}>
                        [{String(ev.start ?? '?')}:{String(ev.end ?? '?')}] ({String(ev.method ?? '')})
                      </span>
                    </li>
                  );
                })}
              </ul>
              <span style={{ fontSize: '12px', color: '#92400e' }}>
                These items are not yet mapped to authorized catalog SKUs. Click <strong>Review &amp; Amend</strong> to map them to catalog products.
              </span>
            </div>
          ) : (
            <p className="p1-subtle-text" style={{ padding: '8px 0', color: '#64748b' }}>No products identified in this context.</p>
          )
        ) : (
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
        )}

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
        requestHeaders={requestHeaders}
        catalogLoader={catalogLoader}
        context={context}
        isOpen={isReviewOpen}
        onClose={() => setIsReviewOpen(false)}
        onUpdated={updated => {
          setContext(updated);
          setPublishError(null);
          setPublishSuccess(null);
          onContextUpdated?.(updated);
        }}
      />
    </div>
  );
}
