import { useEffect, useMemo, useState } from 'react';
import { useAuth } from '../../shared/auth';
import { operationalApi } from './operationalApi';
import type {
  ExtractionAttemptRecord,
  MessageAssociationRecord,
  OrderContextRecord,
  StoredMessage,
} from './types';
import { ReviewDrawer } from './ReviewDrawer';
import { ExtractionProvenance } from './ExtractionProvenance';
import { WorkflowTabs } from '../../shared/WorkflowTabs';
import { determineHumanReviewCase } from './humanReviewCase';
import './humanReview.css';

export type ReviewFilterCategory = 'ALL' | 'UNRESOLVED' | 'FAILED_EXTRACTION';
type ReviewStage = 'evidence' | 'extraction';
const reviewStages: { id: ReviewStage; label: string }[] = [
  { id: 'evidence', label: 'Inquiry & Evidence' },
  { id: 'extraction', label: 'AI Extraction' },
];

export interface HumanReviewPageProps {
  initialFilter?: ReviewFilterCategory;
  onContextUpdated?: (updated: OrderContextRecord) => void;
}

export function HumanReviewPage({ initialFilter = 'ALL', onContextUpdated }: HumanReviewPageProps) {
  const { tenantId, actorId, actorRole } = useAuth();
  const [messages, setMessages] = useState<StoredMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [filter, setFilter] = useState<ReviewFilterCategory>(initialFilter);
  const [search, setSearch] = useState('');
  const [reviewStage, setReviewStage] = useState<ReviewStage>('evidence');
  const [showAmendWorkspace, setShowAmendWorkspace] = useState(false);

  // Selected item state
  const [selectedMessage, setSelectedMessage] = useState<StoredMessage | null>(null);
  const [selectedExtraction, setSelectedExtraction] = useState<ExtractionAttemptRecord | null>(null);
  const [selectedAssociation, setSelectedAssociation] = useState<MessageAssociationRecord | null>(null);
  const [selectedContext, setSelectedContext] = useState<OrderContextRecord | null>(null);
  const [contextLoading, setContextLoading] = useState(false);
  const [contextError, setContextError] = useState<string | null>(null);

  const selectInquiry = (id: string) => {
    if (id === selectedId) return;
    setSelectedId(id); setReviewStage('evidence');
  };

  // Load review-relevant messages
  const loadMessages = async () => {
    setLoading(true);
    setError(null);
    try {
      const page = await operationalApi.list({
        channel: 'ALL',
        processing: 'ALL',
        search: search.trim(),
        offset: 0,
        limit: 50,
      });
      setMessages(page.items);
      const selected = page.items.find(item => item.message_id === selectedId);
      if (selected) setSelectedMessage(selected);
      if (page.items.length > 0 && !selectedId) {
        setSelectedId(page.items[0].message_id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load inquiry review items');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadMessages();
  }, [search]);

  // When selectedId changes, load details
  useEffect(() => {
    if (!selectedId) return;
    const msg = messages.find(m => m.message_id === selectedId);
    if (msg) setSelectedMessage(msg);

    let active = true;
    setContextLoading(true);
    setContextError(null);

    // Fetch extraction attempt, association, and linked context
    Promise.all([
      operationalApi.getExtraction(selectedId).catch(() => null),
      operationalApi.getAssociation(selectedId).catch(() => null),
    ]).then(([extraction, association]) => {
      if (!active) return;
      setSelectedExtraction(extraction);
      setSelectedAssociation(association);

      // Attempt to load order context
      const orderRef = association?.verified_order?.order_id;
      if (orderRef) {
        return operationalApi.getContextByOrder(orderRef);
      }
      return null;
    }).then(ctx => {
      if (!active) return;
      if (ctx) {
        setSelectedContext(ctx);
      } else {
        setSelectedContext(null);
      }
    }).catch(err => {
      if (active) setContextError(err instanceof Error ? err.message : 'Failed loading context');
    }).finally(() => {
      if (active) setContextLoading(false);
    });

    return () => { active = false; };
  }, [selectedId]);

  const handleCreateContext = async () => {
    if (!selectedId || selectedMessage?.processing_status !== 'PROCESSED' || selectedAssociation?.status !== 'LINK_VERIFIED' || !selectedAssociation.verified_order?.order_id) return;
    setContextLoading(true);
    setContextError(null);
    try {
      const created = await operationalApi.createContextFromMessage(selectedId);
      setSelectedContext(created);
      if (onContextUpdated) onContextUpdated(created);
    } catch (err) {
      setContextError(err instanceof Error ? err.message : 'Unable to initialize order context from message');
    } finally {
      setContextLoading(false);
    }
  };

  // Classify messages for review filters
  const classifiedMessages = useMemo(() => {
    return messages.map(msg => {
      const tags: { label: string; type: 'danger' | 'amber' | 'blue' | 'purple' }[] = [];
      if (msg.processing_status === 'PROCESSING_FAILED') {
        tags.push({ label: 'Extraction Failed', type: 'danger' });
      } else if (msg.processing_status === 'RECEIVED') {
        tags.push({ label: 'Unprocessed', type: 'amber' });
      }
      return { message: msg, tags };
    });
  }, [messages]);

  const filteredItems = useMemo(() => {
    return classifiedMessages.filter(({ message }) => {
      if (filter === 'ALL') return true;
      if (filter === 'FAILED_EXTRACTION') return message.processing_status === 'PROCESSING_FAILED';
      if (filter === 'UNRESOLVED') return message.processing_status !== 'PROCESSED';
      return true;
    });
  }, [classifiedMessages, filter]);

  const updateItem = (index: number, field: keyof RequestedItem, value: string) => {
    setItems(prev => {
      const next = [...prev];
      next[index] = { ...next[index], [field]: value };
      return next;
    });
  };

  const addItem = () => setItems(prev => [...prev, { sku: '', quantity: '', unit: '' }]);
  const removeItem = (idx: number) => {
    if (items.length <= 1) return;
    setItems(prev => prev.filter((_, i) => i !== idx));
  };

  const suggestedClarification = selectedContext ? getSuggestedClarification(selectedContext) : null;
  const candidateProposals = selectedContext ? reviewCandidates(selectedContext) : [];
  const reviewCase = determineHumanReviewCase(selectedMessage, selectedAssociation, selectedContext);
  const canInitializeContext = selectedMessage?.processing_status === 'PROCESSED' && selectedAssociation?.status === 'LINK_VERIFIED' && !!selectedAssociation.verified_order?.order_id;
  const messageUrl = selectedId ? `/inbox?message=${encodeURIComponent(selectedId)}` : '/inbox';

  const handleReviewAction = async (action: 'EDIT_FIELD' | 'ACCEPT_EXTRACTION' | 'REQUEST_MORE_INFO' | 'MARK_UNRESOLVED') => {
    if (!selectedContext) return;
    setSubmitting(true);
    setSubmitError(null);
    setSubmitSuccess(null);
    setConflictOccurred(false);

    try {
      const fieldEdits: Record<string, unknown> = {};
      if ((action === 'REQUEST_MORE_INFO' || action === 'MARK_UNRESOLVED') && !reviewerNote.trim()) {
        throw new Error('Add a reviewer reason before recording this outcome.');
      }

      if (action === 'EDIT_FIELD') {
        for (let i = 0; i < items.length; i++) {
          const it = items[i];
          if (!it.sku.trim() || !it.unit.trim() || !/^[0-9]+(?:\.[0-9]+)?$/.test(it.quantity.trim()) || Number(it.quantity) <= 0) {
            throw new Error(`Item #${i + 1}: Enter an explicit approved SKU, positive quantity, and standard unit.`);
          }
        }
        fieldEdits.requested_items = items.map(it => ({
          sku: it.sku.trim(),
          quantity: it.quantity.trim(),
          unit: it.unit.trim(),
        }));
        fieldEdits.delivery_qualifier = qualifier || undefined;

        if (deliveryAt) {
          if (!/(Z|[+-][0-9]{2}:[0-9]{2})$/.test(deliveryAt) || Number.isNaN(Date.parse(deliveryAt))) {
            throw new Error('Enter an ISO timestamp with explicit UTC offset (e.g., 2026-10-23T15:00:00+08:00).');
          }
          fieldEdits.requested_delivery_at = new Date(deliveryAt).toISOString();
        }

        if (specialInstructions) fieldEdits.special_instructions = specialInstructions;
        if (!selectedContext.conflicts?.length || conflictsReviewed) fieldEdits.conflicts = [];
      }

      const req: ContextReviewRequest = {
        expected_context_version: selectedContext.context_version,
        action,
        field_edits: fieldEdits,
        note: reviewerNote.trim() || undefined,
      };

      const updated = await operationalApi.reviewContext(selectedContext.context_id, req, {
        'X-Actor-ID': actorId || 'user_staff_01',
        'X-Actor-Role': actorRole || 'STAFF',
      });

      setSelectedContext(updated);
      initFormFromContext(updated);
      setReviewerNote('');
      setSubmitSuccess(`Review action "${action}" successfully recorded (v${updated.context_version}).`);
      if (onContextUpdated) onContextUpdated(updated);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Review action failed';
      if (msg.includes('version mismatch') || msg.includes('409') || msg.includes('StaleContextVersion')) {
        setConflictOccurred(true);
        setSubmitError('Version conflict: The order context was modified by another process. Please reload to inspect latest changes.');
      } else {
        setSubmitError(msg);
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="human-review-page" data-testid="human-review-workspace">
      <header className="hr-header">
        <div>
          <h2>Human Review Workspace</h2>
          <p>Review customer inquiries, unverified model candidates, and context conflicts with full audit protection.</p>
        </div>
        <div className="hr-meta-badges">
          <span className="p1-dim-badge">{tenantId}</span>
          <span className="p1-dim-badge">{actorId} · {actorRole}</span>
        </div>
      </header>

      {error && (
        <div className="p1-error-banner" role="alert" style={{ marginBottom: '16px' }}>
          <strong>Error:</strong> {error}
        </div>
      )}

      {/* Workspace Grid */}
      <div className="hr-workspace-grid">
        {/* Left Column: Queue List */}
        <div className="hr-queue-panel" aria-label="Inquiry review list">
          <div className="hr-queue-search"><label htmlFor="hr-queue-search">Search review queue</label><input id="hr-queue-search" type="search" className="hr-search-input" aria-label="Search inquiries" value={search} onChange={event => setSearch(event.target.value)} placeholder="Search inquiries…" /></div>
          <div className="hr-filter-pills" role="tablist" aria-label="Review filter categories">
            <button type="button" className={`hr-pill-btn ${filter === 'ALL' ? 'is-active' : ''}`} onClick={() => setFilter('ALL')} role="tab" aria-selected={filter === 'ALL'}>All Inquiries ({messages.length})</button>
            <button type="button" className={`hr-pill-btn ${filter === 'FAILED_EXTRACTION' ? 'is-active' : ''}`} onClick={() => setFilter('FAILED_EXTRACTION')} role="tab" aria-selected={filter === 'FAILED_EXTRACTION'}>Failed Extractions</button>
            <button type="button" className={`hr-pill-btn ${filter === 'UNRESOLVED' ? 'is-active' : ''}`} onClick={() => setFilter('UNRESOLVED')} role="tab" aria-selected={filter === 'UNRESOLVED'}>Pending / Unprocessed</button>
          </div>
          <div className="hr-queue-header">
            <span>Inquiry Queue ({filteredItems.length})</span>
            <button
              type="button"
              className="hr-compact-action"
              onClick={() => void loadMessages()}
              disabled={loading}
            >
              {loading ? 'Refreshing…' : 'Refresh'}
            </button>
          </div>
          <div className="hr-queue-items" role="list">
            {loading ? (
              <div style={{ padding: '24px', textAlign: 'center', color: '#64748b' }}>Loading inquiries…</div>
            ) : filteredItems.length === 0 ? (
              <div style={{ padding: '24px', textAlign: 'center', color: '#64748b' }}>No review inquiries found.</div>
            ) : (
              filteredItems.map(({ message, tags }) => (
                <div
                  key={message.message_id}
                  className={`hr-queue-item ${selectedId === message.message_id ? 'is-selected' : ''}`}
                  onClick={() => selectInquiry(message.message_id)}
                  role="listitem"
                  tabIndex={0}
                  onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectInquiry(message.message_id); } }}
                >
                  <div className="hr-item-top">
                    <span className="hr-sender">{message.raw?.sender_alias || 'Customer'}</span>
                    <span className="hr-time">
                      {message.raw?.received_at ? new Intl.DateTimeFormat('en-MY', { hour: 'numeric', minute: 'numeric', month: 'short', day: 'numeric' }).format(new Date(message.raw.received_at)) : ''}
                    </span>
                  </div>
                  <div className="hr-snippet">{message.raw?.text || 'No text content'}</div>
                  <div className="hr-tags">
                    <span className="p1-badge p1-neutral">{message.raw?.channel || 'SYNTHETIC'}</span>
                    <span className={`p1-badge ${message.processing_status === 'PROCESSED' ? 'p1-neutral' : 'p1-attention'}`}>
                      {message.processing_status}
                    </span>
                    {tags.map((t, idx) => (
                      <span key={idx} className={`hr-tag hr-tag-${t.type}`}>{t.label}</span>
                    ))}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Right Column: Detail & Review Workspace */}
        <div className="hr-detail-panel" aria-label="Inquiry detail and review controls">
          {pendingSelection && <div className="hr-unsaved-warning" role="alert"><span>Unsaved review changes will be lost.</span><button type="button" className="p1-btn p1-btn-secondary" onClick={() => setPendingSelection(null)}>Keep editing</button><button type="button" className="p1-btn p1-btn-subtle-red" onClick={() => { setSelectedId(pendingSelection); setReviewStage('evidence'); setReviewerNote(''); setConflictsReviewed(false); setPendingSelection(null); }}>Discard and switch</button></div>}
          {!selectedMessage ? (
            <div className="hr-detail-empty">Select an inquiry from the left panel to begin review.</div>
          ) : (
            <div>
              <div className="hr-detail-intro"><strong>{selectedMessage.raw?.sender_alias || 'Customer inquiry'}</strong><span>{selectedMessage.processing_status} · {selectedContext?.status || 'Context pending'}</span></div>
              <div className="hr-case-guidance" role="status"><div><strong>{reviewCase.title}</strong><p>{reviewCase.nextStep}</p></div><div className="hr-case-actions"><a className="hr-compact-action" href={messageUrl}>Open customer message</a>{selectedContext && <button type="button" className="hr-compact-action" onClick={() => setShowAmendWorkspace(true)}>Review &amp; Amend</button>}</div></div>
              <WorkflowTabs stages={reviewStages} active={reviewStage} onChange={setReviewStage} label="Review stages" className="hr-review-tabs" />
              <div className="hr-stage-content">
              {/* Evidence Section */}
              <section className="hr-section hr-stage" data-active={reviewStage === 'evidence'} aria-labelledby="hr-evidence-title">
                <div className="hr-section-title">
                  <h3 id="hr-evidence-title" style={{ margin: 0, fontSize: '15px' }}>Original Evidence</h3>
                  <span className="p1-dim-badge">{selectedMessage.provider || 'SYNTHETIC'}</span>
                </div>
                <div className="hr-evidence-box">
                  {selectedMessage.raw?.text || 'No message text'}
                </div>
                <div className="hr-metadata-grid">
                  <div className="hr-meta-item">
                    <strong>Sender Identity</strong>
                    <span>{selectedMessage.raw?.sender_identity_id || selectedMessage.raw?.sender_alias || 'Unknown'}</span>
                  </div>
                  <div className="hr-meta-item">
                    <strong>Channel / Provider</strong>
                    <span>{selectedMessage.raw?.channel || 'EMAIL'} · {selectedMessage.raw?.provider_message_id || 'N/A'}</span>
                  </div>
                  <div className="hr-meta-item">
                    <strong>Ingested At</strong>
                    <span>{selectedMessage.ingested_at ? new Intl.DateTimeFormat('en-MY', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(selectedMessage.ingested_at)) : 'N/A'}</span>
                  </div>
                  <div className="hr-meta-item">
                    <strong>Identity Link Status</strong>
                    <span>{selectedAssociation?.status || 'UNLINKED'}</span>
                  </div>
                  <div className="hr-meta-item">
                    <strong>Extraction SHA-256</strong>
                    <span style={{ fontFamily: 'monospace', fontSize: '10px' }}>{selectedMessage.content_sha256 ? selectedMessage.content_sha256.substring(0, 16) + '…' : 'None'}</span>
                  </div>
                </div>

                {/* Attachments if any */}
                {selectedMessage.raw?.attachments && selectedMessage.raw.attachments.length > 0 && (
                  <div style={{ marginTop: '12px' }}>
                    <h4 style={{ margin: '0 0 6px 0', fontSize: '12px' }}>Attachments ({selectedMessage.raw.attachments.length})</h4>
                    <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                      {selectedMessage.raw.attachments.map((att, idx) => (
                        <div key={idx} style={{ padding: '6px 10px', background: '#f1f5f9', borderRadius: '4px', fontSize: '11px' }}>
                          📄 {att.filename || `Attachment ${idx + 1}`} ({att.media_type || 'application/octet-stream'})
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </section>

              {/* AI Understanding & Extraction Section */}
              {selectedExtraction && (
                <section className="hr-section hr-stage" data-active={reviewStage === 'extraction'} aria-labelledby="hr-ai-title">
                  <div className="hr-section-title">
                    <h3 id="hr-ai-title" style={{ margin: 0, fontSize: '15px' }}>AI Understanding & Model Telemetry</h3>
                    <span className="p1-dim-badge">v: {selectedExtraction.extractor_version}</span>
                  </div>
                  <p className="muted">{selectedContext?.requested_items?.length || 0} structured item(s) · {selectedContext?.missing_fields?.length || 0} missing field(s) · {selectedContext?.conflicts?.length || 0} conflict(s)</p>
                  <details><summary>Advanced model telemetry and evidence</summary><ExtractionProvenance attempt={selectedExtraction} /></details>
                </section>
              )}
              {!selectedExtraction && <section className="hr-section hr-stage" data-active={reviewStage === 'extraction'}><h3>AI Extraction</h3><p>No extraction attempt is available for this inquiry.</p></section>}

              {contextError && <div className="p1-error-banner" role="alert">{contextError}</div>}
              {contextLoading && <p className="muted">Loading order context…</p>}
              {!contextLoading && !selectedContext && <div className="hr-context-route">
                <p>{canInitializeContext ? 'This verified order has no context yet.' : 'A processed message and verified order link are required before context review.'}</p>
                {canInitializeContext ? <button type="button" className="hr-compact-action" onClick={() => void handleCreateContext()}>Initialize Order Context from Message</button> : <a className="hr-compact-action" href={messageUrl}>Review message and identity link</a>}
              </div>}
              {selectedContext && <div className="hr-context-route"><p>Order context v{selectedContext.context_version} · {selectedContext.status}. Review fields and record outcomes in the shared workspace.</p><button type="button" className="hr-compact-action" onClick={() => setShowAmendWorkspace(true)}>Review &amp; Amend</button></div>}
              </div>              <div className="hr-stage-footer"><button type="button" className="p1-btn p1-btn-secondary" disabled={reviewStage === 'evidence'} onClick={() => setReviewStage('evidence')}>Back</button><span>{reviewStages.findIndex(item => item.id === reviewStage) + 1} of {reviewStages.length}</span><button type="button" className="p1-btn p1-btn-secondary" disabled={reviewStage === 'extraction'} onClick={() => setReviewStage('extraction')}>Next</button></div>
            </div>
          )}
        </div>
      </div>
      {showAmendWorkspace && selectedContext && <ReviewDrawer context={selectedContext} sourceMessage={selectedMessage?.raw?.text} message={selectedMessage} extraction={selectedExtraction} isOpen={showAmendWorkspace} onClose={() => setShowAmendWorkspace(false)} onUpdated={updated => { setSelectedContext(updated); initFormFromContext(updated); onContextUpdated?.(updated); }} actorId={actorId} actorRole={actorRole} />}
    </div>
  );
}

