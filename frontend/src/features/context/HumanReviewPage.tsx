import { useEffect, useMemo, useState } from 'react';
import { useAuth } from '../../shared/auth';
import { operationalApi } from './operationalApi';
import type {
  ContextReviewRequest,
  ExtractionAttemptRecord,
  MessageAssociationRecord,
  OrderContextRecord,
  RequestedItem,
  StoredMessage,
} from './types';
import { extractEvidenceItemGroups, reviewCandidates } from './reviewCandidates';
import { getSuggestedClarification } from './ReviewDrawer';
import { ExtractionProvenance } from './ExtractionProvenance';
import { WorkflowTabs } from '../../shared/WorkflowTabs';
import { determineHumanReviewCase } from './humanReviewCase';
import './humanReview.css';

export type ReviewFilterCategory = 'ALL' | 'UNRESOLVED' | 'FAILED_EXTRACTION';
type ReviewStage = 'evidence' | 'extraction' | 'amendments' | 'resolution';
const reviewStages: { id: ReviewStage; label: string }[] = [
  { id: 'evidence', label: 'Inquiry & Evidence' },
  { id: 'extraction', label: 'AI Extraction' },
  { id: 'amendments', label: 'Amendments' },
  { id: 'resolution', label: 'Resolution' },
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
  const [pendingSelection, setPendingSelection] = useState<string | null>(null);
  const [savedForm, setSavedForm] = useState('');

  // Selected item state
  const [selectedMessage, setSelectedMessage] = useState<StoredMessage | null>(null);
  const [selectedExtraction, setSelectedExtraction] = useState<ExtractionAttemptRecord | null>(null);
  const [selectedAssociation, setSelectedAssociation] = useState<MessageAssociationRecord | null>(null);
  const [selectedContext, setSelectedContext] = useState<OrderContextRecord | null>(null);
  const [contextLoading, setContextLoading] = useState(false);
  const [contextError, setContextError] = useState<string | null>(null);

  // Review form state
  const [items, setItems] = useState<RequestedItem[]>([]);
  const [deliveryAt, setDeliveryAt] = useState('');
  const [qualifier, setQualifier] = useState('');
  const [specialInstructions, setSpecialInstructions] = useState('');
  const [reviewerNote, setReviewerNote] = useState('');
  const [conflictsReviewed, setConflictsReviewed] = useState(false);
  const [catalog, setCatalog] = useState<{ sku: string; unit: string }[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [submitSuccess, setSubmitSuccess] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [conflictOccurred, setConflictOccurred] = useState(false);
  const currentForm = JSON.stringify([items, deliveryAt, qualifier, specialInstructions]);
  const hasUnsavedReview = !!reviewerNote.trim() || !!conflictsReviewed || (!!savedForm && currentForm !== savedForm);
  const selectInquiry = (id: string) => {
    if (id === selectedId) return;
    if (hasUnsavedReview) { setPendingSelection(id); return; }
    setSelectedId(id); setReviewStage('evidence'); setReviewerNote(''); setPendingSelection(null);
  };

  // The deployed context API supplies catalog validation; standalone v2.2 review tasks are not available here.
  useEffect(() => {
    operationalApi.getCatalog().then(cat => setCatalog(cat)).catch(() => setCatalog([]));
  }, []);

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
    setSubmitSuccess(null);
    setSubmitError(null);
    setConflictOccurred(false);

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
        initFormFromContext(ctx);
      } else {
        setSelectedContext(null);
        setItems([{ sku: '', quantity: '', unit: '' }]);
        setSavedForm(JSON.stringify([[{ sku: '', quantity: '', unit: '' }], '', '', '']));
      }
    }).catch(err => {
      if (active) setContextError(err instanceof Error ? err.message : 'Failed loading context');
    }).finally(() => {
      if (active) setContextLoading(false);
    });

    return () => { active = false; };
  }, [selectedId]);

  const initFormFromContext = (ctx: OrderContextRecord) => {
    const evidenceItemGroups = extractEvidenceItemGroups(ctx);
    const initialItems: RequestedItem[] = (ctx.requested_items && ctx.requested_items.length > 0)
      ? ctx.requested_items.map(it => ({ sku: it.sku || '', quantity: it.quantity || '', unit: it.unit || '' }))
      : (evidenceItemGroups.length > 0
        ? evidenceItemGroups.map(grp => ({
            sku: grp.validSku || '',
            quantity: grp.quantity || '',
            unit: grp.unit || '',
          }))
        : [{ sku: '', quantity: '', unit: '' }]);

    setItems(initialItems);
    setDeliveryAt(ctx.requested_delivery_at || '');
    setQualifier(ctx.delivery_qualifier || '');
    setSpecialInstructions(ctx.special_instructions || '');
    setConflictsReviewed(false);
    setSavedForm(JSON.stringify([initialItems, ctx.requested_delivery_at || '', ctx.delivery_qualifier || '', ctx.special_instructions || '']));
  };

  const handleCreateContext = async () => {
    if (!selectedId || selectedMessage?.processing_status !== 'PROCESSED' || selectedAssociation?.status !== 'LINK_VERIFIED' || !selectedAssociation.verified_order?.order_id) return;
    setContextLoading(true);
    setContextError(null);
    try {
      const created = await operationalApi.createContextFromMessage(selectedId);
      setSelectedContext(created);
      initFormFromContext(created);
      if (onContextUpdated) onContextUpdated(created);
    } catch (err) {
      setContextError(err instanceof Error ? err.message : 'Unable to initialize order context from message');
    } finally {
      setContextLoading(false);
    }
  };

  const handleReloadContext = async () => {
    if (!selectedContext) return;
    setContextLoading(true);
    try {
      const reloaded = await operationalApi.getContext(selectedContext.context_id);
      setSelectedContext(reloaded);
      initFormFromContext(reloaded);
      setConflictOccurred(false);
      setSubmitError(null);
    } catch (err) {
      setContextError(err instanceof Error ? err.message : 'Failed to reload context');
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
              <div className="hr-case-guidance" role="status"><div><strong>{reviewCase.title}</strong><p>{reviewCase.nextStep}</p></div><a className="hr-compact-action" href={messageUrl}>Open customer message</a></div>
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

              {/* Order Context & Multi-Item Field Correction Section */}
              <section className="hr-section hr-stage" data-active={reviewStage === 'amendments' || reviewStage === 'resolution'} aria-labelledby="hr-context-title">
                <div className="hr-section-title">
                  <h3 id="hr-context-title" style={{ margin: 0, fontSize: '15px' }}>
                    Order Context & Structured Draft {selectedContext ? `(v${selectedContext.context_version})` : ''}
                  </h3>
                  {selectedContext && (
                    <span className={`status-badge status-${selectedContext.status.toLowerCase()}`}>
                      {selectedContext.status}
                    </span>
                  )}
                </div>

                {contextError && (
                  <div className="p1-error-banner" role="alert" style={{ marginBottom: '12px' }}>
                    <strong>Context Error:</strong> {contextError}
                  </div>
                )}

                <div className="hr-stage" data-active={reviewStage === 'resolution'}><div className="hr-send-availability"><button type="button" className="hr-compact-action" disabled>Send customer update unavailable</button><p>A verified conversation, authorized reply and supported channel are required. Recording a need for information does not send a message.</p></div></div>

                {contextLoading ? (
                  <div style={{ padding: '16px', color: '#64748b' }}>Loading context data…</div>
                ) : !selectedContext ? (
                  <div style={{ padding: '16px', background: '#f8fafc', border: '1px dashed #cbd5e1', borderRadius: '6px', textAlign: 'center' }}>
                    <p style={{ margin: '0 0 8px 0', color: '#64748b' }}>{canInitializeContext ? 'This verified order has no context yet.' : 'A processed message and verified order link are required to initialize an order context.'}</p>
                    {canInitializeContext && <button
                      type="button"
                      className="p1-primary"
                      onClick={() => void handleCreateContext()}
                    >
                      Initialize Order Context from Message
                    </button>}
                    {!canInitializeContext && <a className="hr-compact-action" href={messageUrl}>Review message and identity link</a>}
                  </div>
                ) : (
                  <div>
                    {/* Conflict Banner if 409 occurred */}
                    {conflictOccurred && (
                      <div className="hr-version-banner" role="alert">
                        <span><strong>Version Conflict:</strong> The context was updated by another process.</span>
                        <button
                          type="button"
                          className="p1-btn-secondary"
                          style={{ fontSize: '11px', padding: '3px 8px' }}
                          onClick={() => void handleReloadContext()}
                        >
                          Reload Latest Context
                        </button>
                      </div>
                    )}

                    {submitError && !conflictOccurred && (
                      <div className="p1-error-banner" role="alert" style={{ marginBottom: '12px' }}>
                        <strong>Error:</strong> {submitError}
                      </div>
                    )}

                    {submitSuccess && (
                      <div style={{ background: '#f0fdf4', border: '1px solid #86efac', color: '#166534', padding: '8px 12px', borderRadius: '6px', marginBottom: '12px', fontSize: '12px' }}>
                        ✓ {submitSuccess}
                      </div>
                    )}

                    <div className="hr-stage" data-active={reviewStage === 'amendments'}>
                    {/* Candidate proposals banner */}
                    {candidateProposals.length > 0 && (
                      <div style={{ background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: '6px', padding: '10px 12px', marginBottom: '14px' }}>
                        <div style={{ fontSize: '12px', fontWeight: 700, color: '#15803d', marginBottom: '4px' }}>
                          Extraction Candidates
                        </div>
                        <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                          {candidateProposals.map(cp => (
                            <button
                              key={cp.key}
                              type="button"
                              className="p1-secondary"
                              style={{ fontSize: '11px', padding: '3px 8px' }}
                              disabled={cp.unverifiedProduct}
                              onClick={() => {
                                if (cp.field === 'sku') updateItem(0, 'sku', cp.value);
                                else if (cp.field === 'quantity') updateItem(0, 'quantity', cp.value);
                                else if (cp.field === 'unit') updateItem(0, 'unit', cp.value);
                                else if (cp.field === 'requested_delivery_at') setDeliveryAt(cp.value);
                              }}
                            >
                              {cp.unverifiedProduct ? 'Unverified product' : `Apply ${cp.field}`}: <strong>{cp.value}</strong>
                            </button>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Policy Conflicts if any */}
                    {selectedContext.conflicts && selectedContext.conflicts.length > 0 && (
                      <div style={{ background: '#fef2f2', border: '1px solid #fecaca', borderRadius: '6px', padding: '10px 12px', marginBottom: '14px' }}>
                        <h4 style={{ margin: '0 0 6px 0', color: '#991b1b', fontSize: '12px', fontWeight: 700 }}>
                          Policy & Terms Conflicts ({selectedContext.conflicts.length})
                        </h4>
                        <ul style={{ margin: 0, paddingLeft: '18px', color: '#b91c1c', fontSize: '11px' }}>
                          {selectedContext.conflicts.map((c, i) => (
                            <li key={i}>{c}</li>
                          ))}
                        </ul>
                        <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginTop: '8px', fontSize: '11px', color: '#7f1d1d', fontWeight: 600 }}>
                          <input
                            type="checkbox"
                            checked={conflictsReviewed}
                            onChange={e => setConflictsReviewed(e.target.checked)}
                          />
                          I reviewed and resolved all policy conflicts
                        </label>
                      </div>
                    )}

                    {/* Line Items List */}
                    <div style={{ marginBottom: '14px' }}>
                      <div className="hr-line-items-heading">
                        <span style={{ fontSize: '13px', fontWeight: 700 }}>Order Line Items ({items.length})</span>
                        <button type="button" className="hr-compact-action" onClick={addItem}>+ Add item</button>
                      </div>
                      <datalist id="hr-approved-skus">
                        {[...new Set(catalog.map(p => p.sku))].map(sku => (
                          <option key={sku} value={sku} />
                        ))}
                      </datalist>

                      {items.map((it, idx) => (
                        <div
                          key={idx}
                          className="hr-line-item-fields"
                        >
                          <div>
                            <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: '#475569', marginBottom: '2px' }}>
                              SKU / Product
                            </label>
                            <input
                              type="text"
                              list="hr-approved-skus"
                              className="hr-search-input"
                              placeholder="e.g. SOURDOUGH, BURGER"
                              value={it.sku}
                              onChange={e => updateItem(idx, 'sku', e.target.value)}
                            />
                          </div>
                          <div>
                            <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: '#475569', marginBottom: '2px' }}>
                              Quantity
                            </label>
                            <input
                              type="text"
                              className="hr-search-input"
                              placeholder="e.g. 50"
                              value={it.quantity}
                              onChange={e => updateItem(idx, 'quantity', e.target.value)}
                            />
                          </div>
                          <div>
                            <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: '#475569', marginBottom: '2px' }}>
                              Unit
                            </label>
                            <select
                              className="hr-search-input"
                              value={it.unit}
                              onChange={e => updateItem(idx, 'unit', e.target.value)}
                            >
                              <option value="">Select unit</option>
                              {[...new Set(['pcs', 'box', 'kg', ...catalog.map(p => p.unit), it.unit].filter(Boolean))].map(u => (
                                <option key={u} value={u}>{u}</option>
                              ))}
                            </select>
                          </div>
                          {items.length > 1 && (
                            <button
                              type="button"
                              className="p1-btn-subtle"
                              style={{ color: '#dc2626', fontSize: '11px', padding: '6px' }}
                              onClick={() => removeItem(idx)}
                              title="Remove item"
                            >
                              ✕
                            </button>
                          )}
                        </div>
                      ))}
                    </div>

                    {/* Delivery & Special Instructions */}
                    <div className="hr-delivery-fields">
                      <div>
                        <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: '#475569', marginBottom: '2px' }}>
                          Requested Delivery (ISO 8601 with offset)
                        </label>
                        <input
                          type="text"
                          className="hr-search-input"
                          placeholder="e.g. 2026-10-23T15:00:00+08:00"
                          value={deliveryAt}
                          onChange={e => setDeliveryAt(e.target.value)}
                        />
                      </div>
                      <div>
                        <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: '#475569', marginBottom: '2px' }}>
                          Timing Qualifier
                        </label>
                        <select
                          className="hr-search-input"
                          value={qualifier}
                          onChange={e => setQualifier(e.target.value)}
                        >
                          <option value="">Unresolved</option>
                          <option value="EXACT">EXACT</option>
                          <option value="DEADLINE">DEADLINE</option>
                          <option value="DATE_ONLY">DATE_ONLY</option>
                        </select>
                      </div>
                    </div>

                    <div style={{ marginBottom: '14px' }}>
                      <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: '#475569', marginBottom: '2px' }}>
                        Special Handling Notes
                      </label>
                      <input
                        type="text"
                        className="hr-search-input"
                        placeholder="Dietary or delivery constraints…"
                        value={specialInstructions}
                        onChange={e => setSpecialInstructions(e.target.value)}
                      />
                    </div>

                    </div>
                    <div className="hr-stage" data-active={reviewStage === 'resolution'}>
                    <p className="muted">Review the current context and resolve any remaining questions before recording an outcome.</p>
                    {(selectedContext.missing_fields?.length || selectedContext.conflicts?.length) ?
                      <div className="hr-issues-timeline-card" aria-label="Order context gaps">
                        <strong>Information requiring review</strong>
                        {!!selectedContext.missing_fields?.length && <p>Missing: {selectedContext.missing_fields.join(', ')}</p>}
                        {!!selectedContext.conflicts?.length && <ul>{selectedContext.conflicts.map((conflict, index) => <li key={index}>{conflict}</li>)}</ul>}
                      </div> : null}
                    <p className="hr-route-limit">Issue-by-issue clarification history, reminder counts and escalation status are unavailable without a linked conversation record. This message API supplies no conversation ID.</p>

                    {/* Clarification Preview & Note Adoption */}
                    {suggestedClarification && (
                      <div className="hr-clarification-card">
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <span style={{ fontSize: '12px', fontWeight: 700, color: '#1e40af' }}>Suggested clarification wording</span>
                          <span style={{ fontSize: '10px', background: '#dbeafe', color: '#1d4ed8', padding: '2px 6px', borderRadius: '4px', fontWeight: 600 }}>
                            Preview Only · Not Sent
                          </span>
                        </div>
                        <p>&ldquo;{suggestedClarification}&rdquo;</p>
                        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginTop: '8px' }}>
                          <button
                            type="button"
                            className="hr-adopt-btn"
                            onClick={() => setReviewerNote(suggestedClarification)}
                          >
                            Adopt as Clarification Note
                          </button>
                        </div>
                      </div>
                    )}

                    {/* Staff Reviewer Note */}
                    <div style={{ marginBottom: '16px' }}>
                      <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: '#475569', marginBottom: '2px' }}>
                        Audited Reviewer Reason & Notes
                      </label>
                      <textarea
                        rows={2}
                        className="hr-search-input"
                        style={{ height: 'auto' }}
                        placeholder="State reason for changes or clarification details…"
                        value={reviewerNote}
                        onChange={e => setReviewerNote(e.target.value)}
                      />
                    </div>

                    {/* Action Toolbar */}
                    <div className="hr-actions-toolbar">
                      <div className="hr-btn-group">
                        <button
                          type="button"
                          className="hr-btn-primary"
                          disabled={submitting}
                          onClick={() => void handleReviewAction('EDIT_FIELD')}
                        >
                          {submitting ? 'Submitting…' : 'Apply Field Edits'}
                        </button>
                        <button
                          type="button"
                          className="hr-btn-secondary"
                          disabled={submitting || !reviewCase.canAcceptExtraction || currentForm !== savedForm}
                          onClick={() => void handleReviewAction('ACCEPT_EXTRACTION')}
                        >
                          Accept Extraction
                        </button>
                      </div>
                      <div className="hr-btn-group">
                        {(reviewCase.kind === 'information_missing' || reviewCase.kind === 'context_conflict') && <button
                          type="button"
                          className="hr-btn-amber"
                          disabled={submitting}
                          onClick={() => void handleReviewAction('REQUEST_MORE_INFO')}
                        >
                          Record Need for More Info
                        </button>}
                        <button
                          type="button"
                          className="hr-btn-red"
                          disabled={submitting}
                          onClick={() => void handleReviewAction('MARK_UNRESOLVED')}
                        >
                          Mark Unresolved
                        </button>
                      </div>
                    </div>
                    </div>
                  </div>
                )}
              </section>
              </div>
              <div className="hr-stage-footer"><button type="button" className="p1-btn p1-btn-secondary" disabled={reviewStage === 'evidence'} onClick={() => setReviewStage(reviewStages[Math.max(0, reviewStages.findIndex(item => item.id === reviewStage) - 1)].id)}>Back</button><span>{reviewStages.findIndex(item => item.id === reviewStage) + 1} of {reviewStages.length}</span><button type="button" className="p1-btn p1-btn-secondary" disabled={reviewStage === 'resolution'} onClick={() => setReviewStage(reviewStages[Math.min(reviewStages.length - 1, reviewStages.findIndex(item => item.id === reviewStage) + 1)].id)}>Next</button></div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
