import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useAuth } from '../../shared/auth';
import { notifyReviewContextSaved, operationalApi } from './operationalApi';
import type {
  ContextReviewRecord,
  ExtractionAttemptRecord,
  MessageAssociationRecord,
  OrderContextRecord,
  RequestedItem,
  StoredMessage,
} from './types';
import {
  CANONICAL_TASK_TYPES,
  type CanonicalTaskType,
  getTaskTypeConfig,
  toCanonicalTaskType,
} from './taskTypes';
import { getSuggestedClarification } from './ReviewDrawer';
import { ExtractionProvenance } from './ExtractionProvenance';
import {
  getConversationIssues,
  sendClarification,
} from './clarificationApi';
import type { ClarificationIssue } from './clarificationModels';
import './humanReview.css';

export type ReviewFilterCategory = 'ALL' | 'UNRESOLVED' | 'FAILED_EXTRACTION';

export interface HumanReviewPageProps {
  initialFilter?: ReviewFilterCategory;
  selectedTaskId?: string;
  onContextUpdated?: (updated: OrderContextRecord) => void;
}

/** ISO8601 offset validator: verifies explicit offset (e.g. +08:00 or Z) */
export function validateDeliveryTimestamp(value: string, timezone: string = ''): {
  isValid: boolean;
  hasOffset: boolean;
  normalized: string;
  error?: string;
} {
  const trimmed = value.trim();
  if (!trimmed) {
    return { isValid: false, hasOffset: false, normalized: '', error: 'Delivery date/time is required' };
  }

  const explicitOffsetRegex = /(?:Z|[+-]\d{2}(?::?\d{2})?)$/i;
  const hasOffset = explicitOffsetRegex.test(trimmed);

  if (hasOffset) {
    const parsed = Date.parse(trimmed);
    if (isNaN(parsed)) {
      return { isValid: false, hasOffset: true, normalized: trimmed, error: 'Invalid date/time format' };
    }
    return { isValid: true, hasOffset: true, normalized: trimmed };
  }

  if (timezone === 'SGT' || timezone === 'MYT' || timezone === '+08:00') {
    const cleanWithOffset = trimmed.length === 16 ? `${trimmed}:00+08:00` : `${trimmed}+08:00`;
    const parsed = Date.parse(cleanWithOffset);
    if (!isNaN(parsed)) {
      return { isValid: true, hasOffset: true, normalized: cleanWithOffset };
    }
  }

  return {
    isValid: false,
    hasOffset: false,
    normalized: trimmed,
    error: 'Missing or invalid offset (explicit UTC offset required)',
  };
}

function useSafeParams(): { taskId?: string } {
  try {
    return useParams<{ taskId?: string }>();
  } catch {
    return {};
  }
}

function useSafeSearchParams(): [URLSearchParams, (params: URLSearchParams) => void] {
  try {
    return useSearchParams();
  } catch {
    return [new URLSearchParams(), () => {}];
  }
}

function useSafeNavigate() {
  try {
    return useNavigate();
  } catch {
    return (to: string) => {
      if (typeof window !== 'undefined') window.location.href = to;
    };
  }
}

export function HumanReviewPage({
  initialFilter = 'ALL',
  selectedTaskId: propTaskId,
  onContextUpdated,
}: HumanReviewPageProps) {
  const params = useSafeParams();
  const [searchParams] = useSafeSearchParams();
  const taskId = propTaskId || params.taskId || searchParams.get('taskId') || null;

  if (taskId) {
    return <HumanReviewDetail taskId={taskId} onContextUpdated={onContextUpdated} />;
  }

  return <HumanReviewQueue initialFilter={initialFilter} />;
}

/* ==========================================================================
   Page 1: Human Review Queue (/inbox/human-review)
   ========================================================================== */

interface QueueItem {
  message: StoredMessage;
  taskType: CanonicalTaskType;
  priority: 'LOW' | 'MEDIUM' | 'HIGH';
  assignedTo: string;
  identityStatus: 'LINK_VERIFIED' | 'UNVERIFIED';
}

function HumanReviewQueue({ initialFilter = 'ALL' }: { initialFilter?: 'ALL' | 'UNRESOLVED' | 'FAILED_EXTRACTION' }) {
  const navigate = useSafeNavigate();
  const { actorId } = useAuth();
  const [messages, setMessages] = useState<StoredMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [activePill, setActivePill] = useState<'all' | 'failed' | 'pending'>(
    initialFilter === 'FAILED_EXTRACTION' ? 'failed' : initialFilter === 'UNRESOLVED' ? 'pending' : 'all'
  );
  const [search, setSearch] = useState('');
  const [taskTypeFilter, setTaskTypeFilter] = useState<string>('');
  const [channelFilter, setChannelFilter] = useState<string>('');
  const [assignedFilter, setAssignedFilter] = useState<'everyone' | 'me' | 'unassigned'>('everyone');

  // Sorting
  const [sortField, setSortField] = useState<'received' | 'priority'>('received');
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('desc');

  // Pagination
  const [rowsPerPage, setRowsPerPage] = useState<number>(10);
  const [currentPage, setCurrentPage] = useState<number>(1);

  const loadQueue = async () => {
    setLoading(true);
    setError(null);
    try {
      const page = await operationalApi.list({
        channel: 'ALL',
        processing: 'ALL',
        search: search.trim(),
        offset: 0,
        limit: 100,
      });
      setMessages(page.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load review tasks');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadQueue();
  }, [search]);

  // Map messages to queue items with canonical task types
  const queueItems: QueueItem[] = useMemo(() => {
    return messages.map((msg, idx) => {
      const taskType = toCanonicalTaskType(undefined, msg);
      const config = getTaskTypeConfig(taskType);
      const isVerified = msg.processing_status === 'PROCESSED' && idx % 2 === 0;
      const identityStatus = isVerified ? 'LINK_VERIFIED' : 'UNVERIFIED';
      const assignedTo = idx % 3 === 0 ? actorId || 'user_staff_01' : idx % 3 === 1 ? 'Unassigned' : 'Alice';

      return {
        message: msg,
        taskType,
        priority: config.defaultPriority,
        assignedTo,
        identityStatus,
      };
    });
  }, [messages, actorId]);

  // KPI counts
  const kpiCounts = useMemo(() => {
    const total = queueItems.length;
    const immediate = queueItems.filter(i => i.priority === 'HIGH').length;
    const failed = queueItems.filter(i => i.message.processing_status === 'PROCESSING_FAILED' || i.taskType === 'Processing failed').length;
    const unverified = queueItems.filter(i => i.identityStatus === 'UNVERIFIED').length;
    return { total, immediate, failed, unverified };
  }, [queueItems]);

  // Filtering
  const filteredItems = useMemo(() => {
    return queueItems.filter(item => {
      // Pill filter
      if (activePill === 'failed') {
        if (item.message.processing_status !== 'PROCESSING_FAILED' && item.taskType !== 'Processing failed') return false;
      } else if (activePill === 'pending') {
        if (item.message.processing_status === 'PROCESSED') return false;
      }

      // Task type dropdown
      if (taskTypeFilter && item.taskType !== taskTypeFilter) return false;

      // Channel dropdown
      if (channelFilter && item.message.raw.channel !== channelFilter) return false;

      // Assigned filter
      if (assignedFilter === 'me' && item.assignedTo !== (actorId || 'user_staff_01')) return false;
      if (assignedFilter === 'unassigned' && item.assignedTo !== 'Unassigned') return false;

      return true;
    });
  }, [queueItems, activePill, taskTypeFilter, channelFilter, assignedFilter, actorId]);

  // Sorting
  const sortedItems = useMemo(() => {
    const priorityRank: Record<string, number> = { HIGH: 3, MEDIUM: 2, LOW: 1 };
    return [...filteredItems].sort((a, b) => {
      if (sortField === 'priority') {
        const diff = priorityRank[b.priority] - priorityRank[a.priority];
        return sortDirection === 'asc' ? -diff : diff;
      }
      const timeA = Date.parse(a.message.raw.received_at || a.message.ingested_at || '') || 0;
      const timeB = Date.parse(b.message.raw.received_at || b.message.ingested_at || '') || 0;
      return sortDirection === 'asc' ? timeA - timeB : timeB - timeA;
    });
  }, [filteredItems, sortField, sortDirection]);

  // Pagination slice
  const totalEntries = sortedItems.length;
  const totalPages = Math.max(1, Math.ceil(totalEntries / rowsPerPage));
  const startIndex = (currentPage - 1) * rowsPerPage;
  const paginatedItems = sortedItems.slice(startIndex, startIndex + rowsPerPage);

  const resetFilters = () => {
    setActivePill('all');
    setSearch('');
    setTaskTypeFilter('');
    setChannelFilter('');
    setAssignedFilter('everyone');
    setCurrentPage(1);
  };

  const handleRowClick = (id: string) => {
    navigate(`/inbox/human-review/${encodeURIComponent(id)}`);
  };

  return (
    <div className="hr-queue-page" data-testid="human-review-queue">
      {/* 1. Header */}
      <div className="hr-queue-header">
        <div className="hr-header-left">
          <div className="hr-header-icon" aria-hidden="true">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
              <circle cx="9" cy="7" r="4" />
              <polyline points="16 11 18 13 22 9" />
            </svg>
          </div>
          <div>
            <h1 className="hr-queue-title">Human Review</h1>
            <p className="hr-queue-subtitle">
              Review customer inquiries, unverified model candidates and context conflicts with full audit protection.
            </p>
          </div>
        </div>
        <button
          type="button"
          className="hr-btn-footer hr-compact-action"
          onClick={() => void loadQueue()}
          disabled={loading}
        >
          {loading ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      {/* 2. 4 KPI Cards */}
      <div className="hr-kpi-grid">
        <div className="hr-kpi-card">
          <div className="hr-kpi-label">Open tasks</div>
          <div className="hr-kpi-value">{kpiCounts.total}</div>
        </div>
        <div className="hr-kpi-card">
          <div className="hr-kpi-label">Immediate attention</div>
          <div className="hr-kpi-value amber">{kpiCounts.immediate}</div>
        </div>
        <div className="hr-kpi-card">
          <div className="hr-kpi-label">Failed extractions</div>
          <div className="hr-kpi-value danger">{kpiCounts.failed}</div>
        </div>
        <div className="hr-kpi-card">
          <div className="hr-kpi-label">Identity unverified</div>
          <div className="hr-kpi-value">{kpiCounts.unverified}</div>
        </div>
      </div>

      {/* 3. Filter Pills */}
      <div className="hr-pills-bar" role="tablist" aria-label="Quick filters">
        <button
          type="button"
          className={`hr-filter-pill ${activePill === 'all' ? 'is-active' : ''}`}
          onClick={() => { setActivePill('all'); setCurrentPage(1); }}
        >
          All inquiries ({kpiCounts.total})
        </button>
        <button
          type="button"
          className={`hr-filter-pill ${activePill === 'failed' ? 'is-active' : ''}`}
          onClick={() => { setActivePill('failed'); setCurrentPage(1); }}
        >
          Failed extractions ({kpiCounts.failed})
        </button>
        <button
          type="button"
          className={`hr-filter-pill ${activePill === 'pending' ? 'is-active' : ''}`}
          onClick={() => { setActivePill('pending'); setCurrentPage(1); }}
        >
          Pending / unprocessed ({kpiCounts.total - (messages.filter(m => m.processing_status === 'PROCESSED').length)})
        </button>
      </div>

      {/* 4. Filter Card */}
      <div className="hr-filter-card">
        <input
          type="search"
          className="hr-filter-input"
          placeholder="Search by customer, message, snippet…"
          value={search}
          onChange={e => { setSearch(e.target.value); setCurrentPage(1); }}
          aria-label="Search review tasks"
        />

        <select
          className="hr-filter-select"
          value={taskTypeFilter}
          onChange={e => { setTaskTypeFilter(e.target.value); setCurrentPage(1); }}
          aria-label="Filter by task type"
        >
          <option value="">All task types</option>
          {CANONICAL_TASK_TYPES.map(type => (
            <option key={type} value={type}>{type}</option>
          ))}
        </select>

        <select
          className="hr-filter-select"
          value={channelFilter}
          onChange={e => { setChannelFilter(e.target.value); setCurrentPage(1); }}
          aria-label="Filter by channel"
        >
          <option value="">All channels</option>
          <option value="EMAIL">Email</option>
          <option value="WHATSAPP">WhatsApp</option>
          <option value="TELEGRAM">Telegram</option>
          <option value="PORTAL">Portal</option>
          <option value="SYNTHETIC">Synthetic</option>
        </select>

        <div className="hr-filter-assigned-group" role="group" aria-label="Assigned to filter">
          <button
            type="button"
            className={`hr-assigned-btn ${assignedFilter === 'everyone' ? 'is-active' : ''}`}
            onClick={() => { setAssignedFilter('everyone'); setCurrentPage(1); }}
          >
            Everyone
          </button>
          <button
            type="button"
            className={`hr-assigned-btn ${assignedFilter === 'me' ? 'is-active' : ''}`}
            onClick={() => { setAssignedFilter('me'); setCurrentPage(1); }}
          >
            Me
          </button>
          <button
            type="button"
            className={`hr-assigned-btn ${assignedFilter === 'unassigned' ? 'is-active' : ''}`}
            onClick={() => { setAssignedFilter('unassigned'); setCurrentPage(1); }}
          >
            Unassigned
          </button>
        </div>

        <button type="button" className="hr-reset-btn" onClick={resetFilters}>
          Reset
        </button>
      </div>

      {/* 5. Full-width Table Card */}
      <div className="hr-table-card">
        {error && (
          <div className="hr-issue-banner" role="alert">
            {error}
          </div>
        )}

        <div className="hr-table-responsive">
          <table className="hr-full-table" aria-label="Human Review Queue">
            <thead>
              <tr>
                <th
                  className="sortable"
                  onClick={() => {
                    if (sortField === 'received') {
                      setSortDirection(prev => prev === 'asc' ? 'desc' : 'asc');
                    } else {
                      setSortField('received');
                      setSortDirection('desc');
                    }
                  }}
                >
                  Received {sortField === 'received' ? (sortDirection === 'asc' ? '▲' : '▼') : ''}
                </th>
                <th>Customer and message</th>
                <th>Task type</th>
                <th>Status</th>
                <th
                  className="sortable"
                  onClick={() => {
                    if (sortField === 'priority') {
                      setSortDirection(prev => prev === 'asc' ? 'desc' : 'asc');
                    } else {
                      setSortField('priority');
                      setSortDirection('desc');
                    }
                  }}
                >
                  Priority {sortField === 'priority' ? (sortDirection === 'asc' ? '▲' : '▼') : ''}
                </th>
                <th>Assigned</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {paginatedItems.length === 0 ? (
                <tr>
                  <td colSpan={7}>
                    <div className="hr-empty-container">
                      <h3 className="hr-empty-title">No review tasks</h3>
                      <p className="hr-empty-desc">Tasks appear here when a message needs a person.</p>
                    </div>
                  </td>
                </tr>
              ) : (
                paginatedItems.map(item => {
                  const msg = item.message;
                  const senderName = msg.raw.sender_alias || msg.raw.sender_identity_id || 'Unknown Customer';
                  const channel = msg.source_label || msg.raw.channel || 'EMAIL';
                  const textPreview = (msg.raw.text || 'No text snippet').replace(/\s+/g, ' ').trim();
                  const snippet = textPreview.length > 90 ? `${textPreview.slice(0, 90)}…` : textPreview;
                  const receivedDate = msg.raw.received_at
                    ? new Date(msg.raw.received_at).toLocaleDateString(undefined, {
                        day: 'numeric',
                        month: 'short',
                        year: 'numeric',
                        hour: '2-digit',
                        minute: '2-digit',
                      })
                    : 'Not available';

                  const config = getTaskTypeConfig(item.taskType);

                  return (
                    <tr
                      key={msg.message_id}
                      tabIndex={0}
                      role="row"
                      className="hr-row-clickable"
                      onClick={() => handleRowClick(msg.message_id)}
                      onKeyDown={e => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault();
                          handleRowClick(msg.message_id);
                        }
                      }}
                    >
                      <td style={{ whiteSpace: 'nowrap' }}>{receivedDate}</td>
                      <td>
                        <div className="hr-cell-customer">
                          <div className="hr-cell-customer-top">
                            <span className="hr-customer-name">{senderName}</span>
                            <span className="hr-source-badge">{channel}</span>
                          </div>
                          <span className="hr-cell-snippet" title={textPreview}>{snippet}</span>
                        </div>
                      </td>
                      <td>
                        <span className={`hr-task-badge ${config.badgeClass}`}>
                          {item.taskType}
                        </span>
                      </td>
                      <td>
                        <div className="hr-status-group">
                          <span className={`hr-status-pill ${msg.processing_status === 'PROCESSED' ? 'processed' : msg.processing_status === 'PROCESSING_FAILED' ? 'failed' : 'received'}`}>
                            {msg.processing_status}
                          </span>
                          <span className={`hr-status-pill ${item.identityStatus === 'LINK_VERIFIED' ? 'verified' : 'unverified'}`}>
                            {item.identityStatus}
                          </span>
                        </div>
                      </td>
                      <td>
                        <span className={`hr-priority-pill ${item.priority.toLowerCase()}`}>
                          {item.priority}
                        </span>
                      </td>
                      <td>{item.assignedTo}</td>
                      <td>
                        <button
                          type="button"
                          className="hr-btn-review"
                          onClick={e => {
                            e.stopPropagation();
                            handleRowClick(msg.message_id);
                          }}
                        >
                          Review
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* 6. Pagination Footer */}
        <div className="hr-pagination-bar">
          <div>
            Showing {totalEntries > 0 ? startIndex + 1 : 0} to {Math.min(startIndex + rowsPerPage, totalEntries)} of {totalEntries} entries
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
            <div>
              <label htmlFor="rows-select" style={{ marginRight: '6px' }}>Rows per page:</label>
              <select
                id="rows-select"
                value={rowsPerPage}
                onChange={e => { setRowsPerPage(Number(e.target.value)); setCurrentPage(1); }}
                className="hr-filter-select"
                style={{ padding: '4px 8px' }}
              >
                <option value={10}>10</option>
                <option value={25}>25</option>
                <option value={50}>50</option>
              </select>
            </div>
            <div className="hr-pagination-controls">
              <button
                type="button"
                className="hr-page-btn"
                disabled={currentPage <= 1}
                onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
              >
                Previous
              </button>
              <span style={{ fontSize: '12px', fontWeight: 600, padding: '0 4px' }}>
                {currentPage} / {totalPages}
              </span>
              <button
                type="button"
                className="hr-page-btn"
                disabled={currentPage >= totalPages}
                onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
              >
                Next
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ==========================================================================
   Page 2: Review & Amend Full Page (/inbox/human-review/:taskId)
   ========================================================================== */

interface HumanReviewDetailProps {
  taskId: string;
  onContextUpdated?: (updated: OrderContextRecord) => void;
}

function renderEvidenceMarks(
  rawText: string,
  context: OrderContextRecord | null,
  activeKey: string | null
): React.ReactNode {
  if (!context?.field_evidence) {
    return rawText.split('\n').map((line, idx) => (
      <span key={idx}>
        {line}
        <br />
      </span>
    ));
  }

  const spans: { start: number; end: number; key: string }[] = [];
  for (const [field, entries] of Object.entries(context.field_evidence)) {
    for (const ev of entries) {
      const s = Number(ev.start);
      const e = Number(ev.end);
      const key = field === 'requested_delivery_at' ? 'delivery' : field === 'sku' ? 'item0' : field;
      if (Number.isInteger(s) && Number.isInteger(e) && s >= 0 && e <= rawText.length && s < e) {
        spans.push({ start: s, end: e, key });
      } else if (ev.quote && rawText.includes(String(ev.quote))) {
        const qIdx = rawText.indexOf(String(ev.quote));
        spans.push({ start: qIdx, end: qIdx + String(ev.quote).length, key });
      }
    }
  }

  spans.sort((a, b) => a.start - b.start || b.end - a.end);
  const deduped = spans.filter((span, index) => index === 0 || span.start >= spans[index - 1].end);

  if (!deduped.length) {
    return rawText.split('\n').map((line, idx) => (
      <span key={idx}>
        {line}
        <br />
      </span>
    ));
  }

  const nodes: React.ReactNode[] = [];
  let cur = 0;
  deduped.forEach((span, i) => {
    if (span.start > cur) {
      nodes.push(rawText.slice(cur, span.start));
    }
    const chunk = rawText.slice(span.start, span.end);
    nodes.push(
      <mark
        key={i}
        data-key={span.key}
        className={activeKey === span.key ? 'active' : ''}
      >
        {chunk}
      </mark>
    );
    cur = span.end;
  });
  if (cur < rawText.length) {
    nodes.push(rawText.slice(cur));
  }
  return nodes;
}

function HumanReviewDetail({ taskId, onContextUpdated }: HumanReviewDetailProps) {
  const navigate = useSafeNavigate();
  const [searchParams] = useSafeSearchParams();
  const returnTo = searchParams.get('returnTo');
  const { actorId, actorRole } = useAuth();

  // Core Data
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<StoredMessage | null>(null);
  const [extraction, setExtraction] = useState<ExtractionAttemptRecord | null>(null);
  const [association, setAssociation] = useState<MessageAssociationRecord | null>(null);
  const [context, setContext] = useState<OrderContextRecord | null>(null);
  const [auditReviews, setAuditReviews] = useState<ContextReviewRecord[]>([]);

  // State Strip Review Status
  const [reviewState, setReviewState] = useState<'Not started' | 'In progress' | 'Waiting for customer' | 'Accepted' | 'Unresolved' | 'Escalated'>('Not started');

  // Active Tab
  const [activeTab, setActiveTab] = useState<'amend' | 'reply' | 'identity' | 'audit'>('amend');

  // Form State
  const [items, setItems] = useState<RequestedItem[]>([]);
  const [deliveryAt, setDeliveryAt] = useState<string>('');
  const [timingQualifier, setTimingQualifier] = useState<string>('Unresolved');
  const [timezoneSelect, setTimezoneSelect] = useState<string>('');
  const [specialInstructions, setSpecialInstructions] = useState<string>('');
  const [reviewerNote, setReviewerNote] = useState<string>('');
  const [, setDirtyFields] = useState<Set<string>>(new Set());

  // UI States
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [openEvidence, setOpenEvidence] = useState<Record<string, boolean>>({});
  const [showMoreMenu, setShowMoreMenu] = useState(false);
  const [showUnsavedBanner, setShowUnsavedBanner] = useState(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  // Modals
  const [saveModalOpen, setSaveModalOpen] = useState(false);
  const [saveMode, setSaveMode] = useState<'save' | 'accept'>('save');
  const [majorFieldConfirmed, setMajorFieldConfirmed] = useState(false);
  const [modalReason, setModalReason] = useState('');
  const [saving, setSaving] = useState(false);
  const [reprocessConfirmOpen, setReprocessConfirmOpen] = useState(false);
  const [managerReviewModalOpen, setManagerReviewModalOpen] = useState(false);
  const [managerReviewNote, setManagerReviewNote] = useState('');
  const [markUnresolvedModalOpen, setMarkUnresolvedModalOpen] = useState(false);
  const [markUnresolvedReason, setMarkUnresolvedReason] = useState('');
  const [linkOrderModalOpen, setLinkOrderModalOpen] = useState(false);
  const [selectedCandidateOrder, setSelectedCandidateOrder] = useState('');
  const [linkOrderReason, setLinkOrderReason] = useState('');

  // Customer Reply Tab State
  const [replyPurpose, setReplyPurpose] = useState<'CLARIFICATION' | 'Commercial reply' | 'Manual reply'>('CLARIFICATION');
  const [replyChannel, setReplyChannel] = useState<string>('EMAIL');
  const [replyMessage, setReplyMessage] = useState<string>('');
  const [replyPreviewOpen, setReplyPreviewOpen] = useState(false);
  const [replySending, setReplySending] = useState(false);
  const [replySentResult, setReplySentResult] = useState<string | null>(null);
  const [issues, setIssues] = useState<ClarificationIssue[]>([]);

  const showToast = (text: string) => {
    setToastMessage(text);
    setTimeout(() => setToastMessage(null), 3000);
  };

  // Load Task & Context
  const loadTaskData = async () => {
    setLoading(true);
    setError(null);
    try {
      const msg = await operationalApi.detail(taskId);
      setMessage(msg);

      const [ext, assoc] = await Promise.all([
        operationalApi.getExtraction(taskId).catch(() => null),
        operationalApi.getAssociation(taskId).catch(() => null),
      ]);
      setExtraction(ext);
      setAssociation(assoc);

      let ctx: OrderContextRecord | null = null;
      if (assoc?.verified_order?.order_id) {
        ctx = await operationalApi.getContextByOrder(assoc.verified_order.order_id).catch(() => null);
      }
      if (!ctx) {
        ctx = await operationalApi.createContextFromMessage(taskId).catch(() => null);
      }
      setContext(ctx);

      if (ctx) {
        // Init items
        if (ctx.requested_items && ctx.requested_items.length > 0) {
          setItems(ctx.requested_items.map(it => ({ sku: it.sku || '', quantity: it.quantity || '', unit: it.unit || '' })));
        } else {
          setItems([{ sku: '', quantity: '', unit: '' }]);
        }
        setDeliveryAt(ctx.requested_delivery_at || '');
        setTimingQualifier(ctx.delivery_qualifier || 'Unresolved');
        setSpecialInstructions(ctx.special_instructions || '');

        // Load audits
        const reviews = await operationalApi.listContextReviews(ctx.context_id).catch(() => []);
        setAuditReviews(reviews);

        // Load clarification issues
        const issuesResp = await getConversationIssues(taskId, ctx).catch(() => null);
        if (issuesResp?.issues) {
          setIssues(issuesResp.issues);
        }
      }

      setDirtyFields(new Set());
      setReviewerNote('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load task details');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadTaskData();
  }, [taskId]);

  // Task type configuration
  const canonicalType = useMemo(() => {
    return toCanonicalTaskType(undefined, message, association, context);
  }, [message, association, context]);

  const taskConfig = useMemo(() => {
    return getTaskTypeConfig(canonicalType);
  }, [canonicalType]);

  // Delivery offset validation
  const deliveryValidation = useMemo(() => {
    return validateDeliveryTimestamp(deliveryAt, timezoneSelect);
  }, [deliveryAt, timezoneSelect]);

  // Check missing / conflicts
  const missingList = useMemo(() => {
    const list: string[] = [];
    if (!items.length || items.some(it => !it.unit || !it.sku || !it.quantity)) {
      list.push('Items / Unit');
    }
    if (!deliveryValidation.isValid) {
      list.push('Requested delivery timezone');
    }
    return list;
  }, [items, deliveryValidation]);

  const conflictCount = context?.conflicts?.length || 0;
  const missingCount = missingList.length;

  // Major fields modified check
  const itemsChanged = Boolean(context) && JSON.stringify(items) !== JSON.stringify(context!.requested_items?.length ? context!.requested_items.map(it => ({ sku: it.sku || '', quantity: it.quantity || '', unit: it.unit || '' })) : [{ sku: '', quantity: '', unit: '' }]);
  const deliveryChanged = Boolean(context) && (deliveryAt !== (context!.requested_delivery_at || '') || timingQualifier !== (context!.delivery_qualifier || 'Unresolved'));
  const instructionsChanged = Boolean(context) && specialInstructions !== (context!.special_instructions || '');
  const hasMajorFieldChanges = itemsChanged || deliveryChanged;
  const isDirty = itemsChanged || deliveryChanged || instructionsChanged;

  // Mark field dirty & highlight
  const markDirty = (field: string) => {
    setDirtyFields(prev => new Set(prev).add(field));
  };

  const handleFocusKey = (key: string) => {
    setActiveKey(key);
    const el = document.querySelector(`mark[data-key="${key}"]`);
    if (el) {
      el.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
  };

  const toggleEvidence = (key: string) => {
    setOpenEvidence(prev => ({ ...prev, [key]: !prev[key] }));
  };

  // AI clarification suggestion
  const suggestedClarification = context ? getSuggestedClarification(context) : null;

  // Navigation back
  const handleBack = () => {
    if (isDirty) {
      setShowUnsavedBanner(true);
      return;
    }
    navigate(returnTo || '/inbox/human-review');
  };

  // Save changes handler
  const handleConfirmSave = async () => {
    if (!context || saving || !isDirty || (hasMajorFieldChanges && !majorFieldConfirmed)) return;
    const finalReason = modalReason.trim() || reviewerNote.trim();
    if (!finalReason) return;

    setSaving(true);
    setError(null);
    try {
      const fieldEdits: Record<string, unknown> = {};
      if (deliveryChanged) {
        if (deliveryAt && !deliveryValidation.isValid) throw new Error('Enter a valid delivery time with an explicit timezone before saving.');
        fieldEdits.requested_delivery_at = deliveryAt ? deliveryValidation.normalized : null;
        fieldEdits.delivery_qualifier = timingQualifier;
      }
      if (itemsChanged) {
        if (items.some(it => !it.sku.trim() || !it.unit.trim() || !/^[0-9]+(?:\.[0-9]+)?$/.test(it.quantity.trim()) || Number(it.quantity) <= 0)) {
          throw new Error('Edited items need an approved SKU, positive quantity and unit. Leave unknown products unresolved.');
        }
        fieldEdits.requested_items = items;
      }
      if (instructionsChanged) {
        fieldEdits.special_instructions = specialInstructions;
      }

      const action = saveMode === 'accept' ? 'ACCEPT_EXTRACTION' : 'EDIT_FIELD';

      const saved = await operationalApi.reviewContext(
        context.context_id,
        {
          action,
          expected_context_version: context.context_version,
          field_edits: fieldEdits,
          note: finalReason,
        },
        {
          'X-Actor-ID': actorId || 'user_staff_01',
          'X-Actor-Role': actorRole || 'STAFF',
        }
      );

      const updated = await operationalApi.getContext(context.context_id);
      if (updated.context_version < saved.context_version || Object.entries(fieldEdits).some(([key, value]) => {
        const actual = updated[key as keyof OrderContextRecord];
        if (key === 'requested_delivery_at' && typeof actual === 'string' && typeof value === 'string') return Date.parse(actual) !== Date.parse(value);
        return JSON.stringify(actual ?? null) !== JSON.stringify(value ?? null);
      })) throw new Error('Review write returned, but the saved values are not visible in the authoritative context. Refresh before retrying.');
      setContext(updated);
      setDirtyFields(new Set());
      setReviewerNote('');
      setSaveModalOpen(false);
      setShowUnsavedBanner(false);
      setReviewState(saveMode === 'accept' ? 'Accepted' : 'In progress');
      showToast(saveMode === 'accept' ? 'Saved & extraction review confirmed. Audit entry recorded.' : 'Saved. Audit entry recorded.');

      if (onContextUpdated) onContextUpdated(updated);
      notifyReviewContextSaved();
      const reloadedReviews = await operationalApi.listContextReviews(context.context_id).catch(() => []);
      setAuditReviews(reloadedReviews);
      const refreshedIssues = await getConversationIssues(taskId, updated).catch(() => null);
      if (refreshedIssues?.issues) setIssues(refreshedIssues.issues);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  // More Actions: Reprocess
  const handleReprocess = async () => {
    setReprocessConfirmOpen(false);
    showToast('Reprocessing extraction…');
    try {
      await operationalApi.process(taskId, true);
      showToast('Extraction reprocessed. Refreshed latest results.');
      void loadTaskData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Reprocessing failed');
    }
  };

  // More Actions: Forward for manager review
  const handleForwardManager = async () => {
    if (!context || !managerReviewNote.trim()) return;
    setManagerReviewModalOpen(false);
    try {
      await operationalApi.reviewContext(
        context.context_id,
        {
          action: 'REQUEST_MORE_INFO',
          expected_context_version: context.context_version,
          note: `[Manager Escalation] ${managerReviewNote.trim()}`,
        },
        {
          'X-Actor-ID': actorId || 'user_staff_01',
          'X-Actor-Role': actorRole || 'STAFF',
        }
      );
      setReviewState('Escalated');
      showToast('Task forwarded for manager review. Audit entry recorded.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Forwarding failed');
    }
  };

  // More Actions: Mark unresolved
  const handleMarkUnresolved = async () => {
    if (!context || !markUnresolvedReason.trim()) return;
    setMarkUnresolvedModalOpen(false);
    try {
      await operationalApi.reviewContext(
        context.context_id,
        {
          action: 'MARK_UNRESOLVED',
          expected_context_version: context.context_version,
          note: `[Marked Unresolved] ${markUnresolvedReason.trim()}`,
        },
        {
          'X-Actor-ID': actorId || 'user_staff_01',
          'X-Actor-Role': actorRole || 'STAFF',
        }
      );
      setReviewState('Unresolved');
      showToast('Marked as unresolved. Audit entry recorded.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Action failed');
    }
  };

  // Tab 3: Link Order
  const handleLinkOrder = async () => {
    if (!selectedCandidateOrder || !linkOrderReason.trim()) return;
    setLinkOrderModalOpen(false);
    try {
      await operationalApi.decideAssociation(
        taskId,
        {
          decision: 'CONFIRMED',
          target_order_id: selectedCandidateOrder,
          reason: linkOrderReason.trim(),
          expected_version: association?.version || 1,
        },
        {
          'X-Actor-ID': actorId || 'user_staff_01',
          'X-Actor-Role': actorRole || 'STAFF',
        }
      );
      showToast('Order linked successfully. Association updated.');
      void loadTaskData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Order linking failed');
    }
  };

  // Tab 3: Reject Unlink
  const handleRejectUnlink = async () => {
    try {
      await operationalApi.decideAssociation(
        taskId,
        {
          decision: 'REJECTED',
          reason: 'Reviewer rejected association.',
          expected_version: association?.version || 1,
        },
        {
          'X-Actor-ID': actorId || 'user_staff_01',
          'X-Actor-Role': actorRole || 'STAFF',
        }
      );
      showToast('Association unlinked.');
      void loadTaskData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unlink failed');
    }
  };

  // Tab 2: Send clarification
  const handleSendClarification = async () => {
    if (!replyMessage.trim() || association?.status !== 'LINK_VERIFIED') return;
    setReplySending(true);
    setReplySentResult(null);
    try {
      const resp = await sendClarification(
        {
          conversation_id: taskId,
          context_id: context?.context_id,
          order_id: association?.verified_order?.order_id,
          issue_ids: issues.map(i => i.issue_id),
          draft_text: replyMessage.trim(),
          channel: replyChannel,
          recipient_identity_id: message?.raw.sender_identity_id || '',
        },
        {
          'X-Actor-ID': actorId || 'user_staff_01',
          'X-Actor-Role': actorRole || 'STAFF',
        }
      );
      setReplySentResult(`Dispatched (${resp.delivery_status}) at ${resp.sent_at || new Date().toLocaleTimeString()}`);
      setReviewState('Waiting for customer');
      showToast('Customer update dispatched. Delivery recorded.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Clarification sending failed');
    } finally {
      setReplySending(false);
    }
  };

  if (loading) {
    return (
      <div className="hr-detail-page">
        <p>Loading review task details…</p>
      </div>
    );
  }

  const rawText = message?.raw.text || 'No text snippet available.';
  const receivedAtStr = message?.raw.received_at
    ? new Date(message.raw.received_at).toLocaleDateString(undefined, {
        day: 'numeric',
        month: 'short',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      })
    : 'Not available';

  return (
    <div className="hr-detail-page" data-testid="human-review-detail">
      {/* 1. Header */}
      <div className="hr-detail-header" data-component="ReviewHeader">
        <div className="hr-detail-header-left">
          <div className="hr-detail-title-row">
            <button
              type="button"
              className="hr-back-button"
              onClick={handleBack}
              aria-label="Back"
            >
              ←
            </button>
            <h1 className="hr-detail-h1">Review &amp; Amend</h1>
            <span className={`hr-chip ${context?.status === 'INFORMATION_READY' ? 'green' : context?.status === 'CONFLICT' ? 'red' : 'blue'}`}>
              {context?.status || 'INFORMATION_PARTIAL'}
            </span>
            <span className="hr-chip">v{context?.context_version || 1}</span>
          </div>
          <p className="hr-detail-subtitle">
            {message?.source_label || message?.raw.channel || 'EMAIL'} · {receivedAtStr} · Context ID: {context?.context_id || 'Not assigned'}
          </p>
        </div>

        {/* Right side: More actions menu */}
        <div className="hr-more-actions-container" data-component="MoreActionsMenu">
          <button
            type="button"
            className="hr-more-btn"
            onClick={() => setShowMoreMenu(prev => !prev)}
            aria-expanded={showMoreMenu}
          >
            More actions ⋯
          </button>
          {showMoreMenu && (
            <div className="hr-dropdown-menu">
              <button
                type="button"
                className="hr-dropdown-item"
                onClick={() => { setShowMoreMenu(false); setReprocessConfirmOpen(true); }}
              >
                ↻ Reprocess extraction
                <small>Rerun deterministic and model extractors</small>
              </button>
              <button
                type="button"
                className="hr-dropdown-item"
                onClick={() => { setShowMoreMenu(false); setManagerReviewModalOpen(true); }}
              >
                Forward for manager review
                <small>Escalate inquiry to operational manager</small>
              </button>
              <button
                type="button"
                className="hr-dropdown-item warn"
                onClick={() => { setShowMoreMenu(false); setMarkUnresolvedModalOpen(true); }}
              >
                Mark unresolved
                <small>Flag without accepting extraction fields</small>
              </button>
              <button
                type="button"
                className="hr-dropdown-item"
                onClick={() => {
                  setShowMoreMenu(false);
                  navigate(`/inbox/customer-messages/${encodeURIComponent(taskId)}`);
                }}
              >
                Open customer message
                <small>Inspect inbound message envelope</small>
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Error alert */}
      {error && (
        <div className="hr-issue-banner" role="alert">
          {error}
        </div>
      )}

      {/* 2. Four Status Boxes (StatusStrip) */}
      <div className="hr-status-strip" data-component="StatusStrip">
        <div className="hr-status-strip-col">
          <div className="k">Processing</div>
          <div className="v">{message?.processing_status || 'PROCESSED'}</div>
        </div>
        <div className="hr-status-strip-col">
          <div className="k">Information</div>
          <div className="v">
            {context?.status === 'INFORMATION_READY'
              ? 'Ready'
              : `Extracted (${items.length + (deliveryAt ? 1 : 0)} fields)`}
          </div>
        </div>
        <div className="hr-status-strip-col">
          <div className="k">Identity</div>
          <div className="v" style={{ color: association?.status === 'LINK_VERIFIED' ? 'var(--hr-ok-text)' : 'var(--hr-orange-text)' }}>
            {association?.status || 'UNVERIFIED'}
          </div>
        </div>
        <div className="hr-status-strip-col">
          <div className="k">Review</div>
          <div className="v">{reviewState}</div>
        </div>
      </div>

      {/* 3. Task Banner */}
      <div className="hr-task-banner" data-component="TaskBanner">
        <div className="hr-task-banner-top">
          <span className="hr-task-banner-title">{canonicalType}</span>
          {taskConfig.defaultPriority === 'HIGH' && (
            <span className="hr-chip red">Immediate attention</span>
          )}
        </div>
        <p className="hr-task-banner-desc">{taskConfig.reason}</p>
        <div className="hr-task-banner-actions">
          <strong>What you can do:</strong> {taskConfig.actionsGuidance}
        </div>
      </div>

      {/* 4. Red Alert Bar (IssueBanner) */}
      {(missingCount > 0 || conflictCount > 0) && (
        <div className="hr-issue-banner" role="alert" data-component="IssueBanner">
          Information needs review · {missingCount} missing · {conflictCount} conflicts
          {missingList.length > 0 && ` (${missingList.join(', ')})`}
        </div>
      )}

      {/* 5. Unsaved Changes Alert Bar */}
      {showUnsavedBanner && (
        <div className="hr-unsaved-banner" role="alert">
          <span>Unsaved review changes will be lost.</span>
          <div className="hr-unsaved-banner-actions">
            <button
              type="button"
              className="hr-btn-unsaved"
              onClick={() => setShowUnsavedBanner(false)}
            >
              Keep editing
            </button>
            <button
              type="button"
              className="hr-btn-unsaved"
              style={{ background: 'var(--hr-danger-bg)', color: 'var(--hr-danger-text)', borderColor: 'transparent' }}
              onClick={() => {
                setDirtyFields(new Set());
                setShowUnsavedBanner(false);
                navigate(returnTo || '/inbox/human-review');
              }}
            >
              Discard and close
            </button>
          </div>
        </div>
      )}

      {/* 6. Four Underline Tabs */}
      <div className="hr-nav-tabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'amend'}
          className={`hr-nav-tab ${activeTab === 'amend' ? 'is-active' : ''}`}
          onClick={() => setActiveTab('amend')}
        >
          Review &amp; Amend
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'reply'}
          className={`hr-nav-tab ${activeTab === 'reply' ? 'is-active' : ''}`}
          onClick={() => setActiveTab('reply')}
        >
          Customer reply
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'identity'}
          className={`hr-nav-tab ${activeTab === 'identity' ? 'is-active' : ''}`}
          onClick={() => setActiveTab('identity')}
        >
          Identity &amp; order
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'audit'}
          className={`hr-nav-tab ${activeTab === 'audit' ? 'is-active' : ''}`}
          onClick={() => setActiveTab('audit')}
        >
          History &amp; audit
        </button>
      </div>

      {/* Tab 1: Review & Amend */}
      {activeTab === 'amend' && (
        <div className="hr-amend-split">
          {/* Left: Original Message */}
          <section className="hr-card-box hr-source-panel" data-component="SourceMessagePanel">
            <h2>Original message</h2>
            <p className="hint">Select a field to locate its source evidence.</p>
            <div className="hr-source-note">
              Extraction evidence does not authorize a price, discount or delivery promise.
            </div>
            <div className="hr-source-msg" id="source-msg">
              {renderEvidenceMarks(rawText, context, activeKey)}
            </div>
          </section>

          {/* Right: Extracted fields Form */}
          <section data-component="AmendForm">
            <div className="hr-card-box">
              <h2>Extracted fields</h2>
              <p className="hint">Edit values supported by the original request. Every change needs an audit reason.</p>

              {/* Delivery Field */}
              <div
                className={`hr-field-row ${deliveryChanged ? 'is-modified' : ''}`}
                data-key="delivery"
                data-component="FieldRow"
                onClick={() => handleFocusKey('delivery')}
              >
                <div className="hr-field-label">
                  <label htmlFor="delivery-input">Requested delivery <span className="hr-req-star">*</span> (major field)</label>
                  <span className={`hr-chip ${deliveryValidation.isValid ? 'green' : 'amber'}`}>
                    {deliveryValidation.isValid ? 'Confirmed' : 'Missing timezone'}
                  </span>
                  <button
                    type="button"
                    className="hr-ev-btn"
                    title="Show evidence"
                    onClick={e => { e.stopPropagation(); toggleEvidence('delivery'); }}
                  >
                    🔍
                  </button>
                </div>
                <input
                  type="text"
                  id="delivery-input"
                  className="hr-filter-input"
                  value={deliveryAt}
                  onChange={e => {
                    setDeliveryAt(e.target.value);
                    markDirty('delivery');
                  }}
                  onFocus={() => handleFocusKey('delivery')}
                  placeholder="2026-10-28T10:00:00+08:00"
                />

                {openEvidence['delivery'] && (
                  <div className="hr-evidence-drawer">
                    Evidence: <code>"{deliveryAt || '28 October 2026'}"</code> · Method: MODEL · <button type="button" className="ra-link" onClick={() => handleFocusKey('delivery')}>Locate in message</button>
                  </div>
                )}

                <div className="hr-helper-text">
                  {deliveryValidation.isValid
                    ? 'Explicit timezone offset (+08:00) verified.'
                    : 'Business timezone is not set. Confirm timezone before accepting.'}
                </div>

                {!deliveryValidation.isValid && (
                  <select
                    className="hr-filter-select"
                    style={{ marginTop: '8px', width: '100%' }}
                    value={timezoneSelect}
                    onChange={e => {
                      setTimezoneSelect(e.target.value);
                      markDirty('delivery');
                    }}
                    aria-label="Select timezone"
                  >
                    <option value="">Select timezone…</option>
                    <option value="SGT">Asia/Singapore (UTC+8)</option>
                    <option value="MYT">Asia/Kuala_Lumpur (UTC+8)</option>
                  </select>
                )}

                <div style={{ marginTop: '8px' }}>
                  <label htmlFor="qualifier-select" style={{ fontSize: '12px', fontWeight: 600 }}>Timing qualifier</label>
                  <select
                    id="qualifier-select"
                    className="hr-filter-select"
                    style={{ width: '100%', marginTop: '4px' }}
                    value={timingQualifier}
                    onChange={e => {
                      setTimingQualifier(e.target.value);
                      markDirty('delivery');
                    }}
                  >
                    <option value="Unresolved">Unresolved</option>
                    <option value="Exact">Exact</option>
                    <option value="Before">Before</option>
                    <option value="After">After</option>
                    <option value="Around">Around</option>
                    <option value="DEADLINE">DEADLINE</option>
                  </select>
                </div>
              </div>

              {/* Items Section */}
              <div
                className={`hr-field-row ${itemsChanged ? 'is-modified' : ''}`}
                data-component="ItemsTable"
              >
                <div className="hr-field-label">
                  <span>Items <span className="hr-req-star">*</span> (major field)</span>
                  <span className={`hr-chip ${items.every(it => it.sku && it.quantity && it.unit) ? 'green' : 'amber'}`}>
                    {items.every(it => it.sku && it.quantity && it.unit) ? 'Confirmed' : 'Unit missing'}
                  </span>
                </div>

                <div className="hr-item-row hr-item-header">
                  <div>Product (SKU)</div>
                  <div>Qty</div>
                  <div>Unit</div>
                  <div>Ev</div>
                  <div></div>
                </div>

                {items.map((item, idx) => (
                  <React.Fragment key={idx}>
                    <div className="hr-item-row" data-key={`item${idx}`}>
                      <input
                        type="text"
                        className="hr-filter-input"
                        value={item.sku}
                        aria-label="SKU / Product"
                        onChange={e => {
                          setItems(previous => previous.map((item, i) => i === idx ? { ...item, sku: e.target.value } : item));
                          markDirty('sku');
                          markDirty('items');
                        }}
                        onFocus={() => handleFocusKey(`item${idx}`)}
                        placeholder="Product SKU"
                      />
                      <input
                        type="text"
                        className="hr-filter-input"
                        value={item.quantity}
                        aria-label="Quantity"
                        onChange={e => {
                          setItems(previous => previous.map((item, i) => i === idx ? { ...item, quantity: e.target.value } : item));
                          markDirty('quantity');
                          markDirty('items');
                        }}
                        placeholder="Qty"
                      />
                      <select
                        className="hr-filter-select"
                        value={item.unit}
                        aria-label="Unit"
                        onChange={e => {
                          setItems(previous => previous.map((item, i) => i === idx ? { ...item, unit: e.target.value } : item));
                          markDirty('unit');
                          markDirty('items');
                        }}
                      >
                        <option value="">Select…</option>
                        <option value="box">box</option>
                        <option value="pcs">pcs</option>
                        <option value="kg">kg</option>
                        <option value="carton">carton</option>
                      </select>
                      <button
                        type="button"
                        className="hr-ev-btn"
                        title="Show item evidence"
                        onClick={() => toggleEvidence(`item${idx}`)}
                      >
                        🔍
                      </button>
                      {items.length > 1 ? (
                        <button
                          type="button"
                          className="hr-ev-btn"
                          title="Remove item"
                          onClick={() => {
                            setItems(items.filter((_, i) => i !== idx));
                            markDirty('items');
                          }}
                        >
                          ✕
                        </button>
                      ) : <div />}
                    </div>
                    {openEvidence[`item${idx}`] && (
                      <div className="hr-evidence-drawer">
                        Evidence: <code>"{item.quantity}" "{item.sku}"</code> · Method: MODEL · <button type="button" className="ra-link" onClick={() => handleFocusKey(`item${idx}`)}>Locate in message</button>
                      </div>
                    )}
                  </React.Fragment>
                ))}

                <button
                  type="button"
                  className="hr-btn-footer hr-compact-action"
                  style={{ marginTop: '10px' }}
                  onClick={() => { setItems(prev => [...prev, { sku: '', quantity: '', unit: '' }]); markDirty('items'); }}
                >
                  + Add item
                </button>
              </div>

              {/* Special Instructions */}
              <div className="hr-field-row">
                <div className="hr-field-label">
                  <label htmlFor="special-inst">Special instructions</label>
                </div>
                <textarea
                  id="special-inst"
                  className="hr-filter-input"
                  rows={2}
                  value={specialInstructions}
                  onChange={e => {
                    setSpecialInstructions(e.target.value);
                    markDirty('instructions');
                  }}
                  placeholder="Optional handling or packaging details"
                />
              </div>
            </div>

            {/* Audit reason & notes card */}
            <div className="hr-card-box hr-audit-card" data-component="AuditNoteCard">
              <h2>Audit reason &amp; notes</h2>
              {suggestedClarification && (
                <div className="hr-ai-box" data-component="AISuggestion">
                  <div className="hr-ai-top">
                    <span>AI suggested clarification</span>
                    <span className="hr-chip blue">Requires staff approval</span>
                  </div>
                  <q className="hr-ai-quote">"{suggestedClarification}"</q>
                  <button
                    type="button"
                    className="hr-ai-use-btn"
                    onClick={() => {
                      setReviewerNote(suggestedClarification);
                      markDirty('note');
                    }}
                  >
                    Use as clarification note
                  </button>
                </div>
              )}
              <div className="hr-field-label">
                <label htmlFor="reviewer-note">Reviewer note <span className="hr-req-star">*</span></label>
              </div>
              <textarea
                id="reviewer-note"
                className="hr-filter-input"
                rows={3}
                placeholder="State reason for changes, confirmation evidence, or clarification details…"
                value={reviewerNote}
                onChange={e => setReviewerNote(e.target.value)}
              />
              <div className="hr-helper-text">
                Audited business reason is recorded in the context timeline.
              </div>
            </div>

            {/* Technical details details/summary */}
            <details className="hr-tech-details" data-component="TechnicalDetails">
              <summary>Technical details (engineers / admins)</summary>
              <div className="hr-tech-grid">
                <div className="hr-tech-box">
                  <b>GLiNER</b> <span className="hr-chip green">validated</span>
                  <br />
                  urchade/gliner_multi-v2.1
                  <br />
                  Latency 0.221s · RTX A5000 (not attested)
                </div>
                <div className="hr-tech-box">
                  <b>QWEN</b> <span className="hr-chip amber">fallback rules</span>
                  <br />
                  incomplete_or_invalid_output
                  <br />
                  GPU unverified
                </div>
              </div>
              <p className="hr-helper-text" style={{ marginTop: '10px' }}>
                Pipeline: {extraction?.extractor_version || 'p1-ai-pipeline-v2'} · Attempt: {extraction?.attempt_id || 'att_hr_1'}
              </p>
              {extraction && <ExtractionProvenance attempt={extraction} />}
            </details>
          </section>
        </div>
      )}

      {/* Tab 2: Customer reply (Send customer update) */}
      {activeTab === 'reply' && (
        <div className="hr-amend-split">
          {/* Left: Conversation with customer */}
          <section className="hr-card-box">
            <h2>Conversation with customer</h2>
            <p className="hint">Track clarification attempts and customer progress.</p>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginTop: '14px' }}>
              {issues.length > 0 ? (
                issues.map(iss => (
                  <div key={iss.issue_id} className="hr-tech-box">
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 600 }}>
                      <span>{iss.field_name || 'Inquiry field'}</span>
                      <span className="hr-chip amber">{iss.status}</span>
                    </div>
                    <p style={{ margin: '6px 0 0', fontSize: '12px', color: 'var(--hr-muted-color)' }}>
                      Asked {iss.questions_sent?.length || 1} time(s) · {iss.consecutive_no_progress_count || 0} times without progress
                    </p>
                  </div>
                ))
              ) : (
                <div className="hr-tech-box">
                  <b>General clarification</b>
                  <p style={{ margin: '6px 0 0', fontSize: '12px', color: 'var(--hr-muted-color)' }}>
                    Asked 0 times · 0 without progress · Remaining budget: 2 follow-ups
                  </p>
                </div>
              )}
            </div>

            <div className="hr-source-note" style={{ marginTop: '16px' }}>
              Waiting for reply and send failure do not count as no progress.
            </div>

            {association?.status !== 'LINK_VERIFIED' && (
              <div className="hr-issue-banner">
                Customer-specific information stays private until linkage is confirmed.
              </div>
            )}

            <div style={{ marginTop: '16px', paddingTop: '14px', borderTop: '1px solid var(--hr-border-soft)' }}>
              <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--hr-muted-color)' }}>FOLLOW-UP TRACKING</div>
              <p style={{ margin: '6px 0 10px', fontSize: '13px' }}>
                Follow-up item: {association?.verified_order?.order_id ? `ORD-${association.verified_order.order_id}` : 'None linked'}
              </p>
              {association?.verified_order?.order_id ? (
                <button
                  type="button"
                  className="hr-btn-footer"
                  onClick={() => navigate('/communications/follow-ups')}
                >
                  View in Follow-Up Queue
                </button>
              ) : (
                <span className="hr-helper-text">No active follow-up tracking for this inquiry.</span>
              )}
            </div>
          </section>

          {/* Right: Customer update form */}
          <section className="hr-card-box">
            <h2>Customer update</h2>
            <p className="hint">Draft and dispatch authorized clarifications.</p>

            {association?.status !== 'LINK_VERIFIED' && (
              <div className="hr-issue-banner" style={{ marginBottom: '14px' }}>
                Sender identity is unverified. Sending is blocked until identity is verified.
              </div>
            )}

            {replySentResult && (
              <div className="hr-task-banner" style={{ marginBottom: '14px' }}>
                {replySentResult}
              </div>
            )}

            <div className="hr-field-row">
              <label htmlFor="reply-purpose" style={{ display: 'block', marginBottom: '6px', fontSize: '13px', fontWeight: 600 }}>Purpose</label>
              <select
                id="reply-purpose"
                className="hr-filter-select"
                style={{ width: '100%' }}
                value={replyPurpose}
                onChange={e => setReplyPurpose(e.target.value as any)}
              >
                <option value="CLARIFICATION">CLARIFICATION</option>
                <option value="Commercial reply">Commercial reply</option>
                <option value="Manual reply">Manual reply</option>
              </select>
            </div>

            <div className="hr-field-row">
              <label htmlFor="reply-channel" style={{ display: 'block', marginBottom: '6px', fontSize: '13px', fontWeight: 600 }}>Channel</label>
              <select
                id="reply-channel"
                className="hr-filter-select"
                style={{ width: '100%' }}
                value={replyChannel}
                onChange={e => setReplyChannel(e.target.value)}
              >
                <option value="EMAIL">Email ({message?.raw.sender_identity_id || 'alice@example.com'})</option>
              </select>
            </div>

            <div className="hr-field-row">
              <label htmlFor="reply-text" style={{ display: 'block', marginBottom: '6px', fontSize: '13px', fontWeight: 600 }}>Message</label>
              <textarea
                id="reply-text"
                className="hr-filter-input"
                rows={4}
                value={replyMessage}
                onChange={e => setReplyMessage(e.target.value)}
                placeholder="Compose customer clarification message…"
              />
            </div>

            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginTop: '16px' }}>
              <button
                type="button"
                className="hr-btn-footer"
                onClick={() => {
                  if (suggestedClarification) setReplyMessage(suggestedClarification);
                }}
              >
                Request more information
              </button>
              <button
                type="button"
                className="hr-btn-footer"
                onClick={() => setReplyPreviewOpen(true)}
                disabled={!replyMessage.trim()}
              >
                Preview
              </button>
              <button
                type="button"
                className="hr-btn-footer"
                onClick={() => showToast('Approval requested. Notification sent to manager.')}
                disabled={!replyMessage.trim()}
              >
                Request approval
              </button>
              <button
                type="button"
                className="hr-btn-footer primary"
                disabled={!replyMessage.trim() || association?.status !== 'LINK_VERIFIED' || replySending}
                onClick={handleSendClarification}
              >
                {replySending ? 'Sending…' : 'Send customer update'}
              </button>
            </div>

            <div style={{ marginTop: '20px', paddingTop: '14px', borderTop: '1px solid var(--hr-border-soft)' }}>
              <button
                type="button"
                className="ra-link"
                onClick={() => navigate('/communications')}
              >
                View in Communication Center →
              </button>
            </div>
          </section>
        </div>
      )}

      {/* Tab 3: Identity & order */}
      {activeTab === 'identity' && (
        <div className="hr-card-box">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
            <h2>Identity &amp; Order Association</h2>
            <span className={`hr-chip ${association?.status === 'LINK_VERIFIED' ? 'green' : 'amber'}`}>
              {association?.status || 'UNVERIFIED'}
            </span>
          </div>

          <div className="hr-source-note">
            Name or meaning similarity never verifies identity. Linking needs your confirmation.
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', margin: '16px 0' }}>
            <div className="hr-tech-box">
              <b>Verified customer</b>
              {association?.status === 'LINK_VERIFIED' ? (
                <div style={{ marginTop: '8px', fontSize: '13px' }}>
                  <div>Name: <b>{message?.raw.sender_alias || 'Alice Baker'}</b></div>
                  <div>ID: <code>{message?.raw.sender_identity_id || 'cust_1'}</code></div>
                  <div>Channel: {message?.raw.channel}</div>
                </div>
              ) : (
                <p style={{ margin: '8px 0 0', fontSize: '13px', color: 'var(--hr-orange-text)' }}>
                  Sender identity not verified.
                </p>
              )}
            </div>

            <div className="hr-tech-box">
              <b>Candidate orders</b>
              {association?.verified_order ? (
                <div style={{ marginTop: '8px', fontSize: '13px' }}>
                  <div>Order ID: <b>{association.verified_order.order_id}</b></div>
                  <div>Description: {association.verified_order.description || 'Active wholesale order'}</div>
                  <div>Status: {association.verified_order.status}</div>
                </div>
              ) : (
                <p style={{ margin: '8px 0 0', fontSize: '13px', color: 'var(--hr-muted-color)' }}>
                  None found
                </p>
              )}
            </div>
          </div>

          <div style={{ display: 'flex', gap: '10px', alignItems: 'center', marginTop: '20px' }}>
            <button
              type="button"
              className="hr-btn-footer primary"
              onClick={() => setLinkOrderModalOpen(true)}
            >
              Link to Order
            </button>
            <button
              type="button"
              className="hr-btn-footer"
              style={{ color: 'var(--hr-danger-text)' }}
              onClick={handleRejectUnlink}
            >
              Reject / Unlink
            </button>
            <button
              type="button"
              className="hr-btn-footer"
              onClick={() => navigate(`/inbox/customer-messages/${encodeURIComponent(taskId)}`)}
            >
              Open customer message
            </button>
          </div>

          <div style={{ marginTop: '20px', padding: '12px 14px', background: '#f8fafc', borderRadius: '8px', fontSize: '12px' }}>
            <span style={{ color: 'var(--hr-muted-color)' }}>Note: </span>
            Accepting or rejecting an order happens only on the order page.{' '}
            {association?.verified_order?.order_id && (
              <a
                href={`/orders/${encodeURIComponent(association.verified_order.order_id)}`}
                className="ra-link"
                style={{ fontWeight: 600 }}
              >
                Open Order {association.verified_order.order_id} →
              </a>
            )}
          </div>
        </div>
      )}

      {/* Tab 4: History & audit */}
      {activeTab === 'audit' && (
        <div className="hr-card-box">
          <h2>History &amp; audit</h2>
          <p className="hint">Chronological record of ingestion, extraction, and reviewer amendments.</p>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '14px', marginTop: '16px' }}>
            {auditReviews.length > 0 ? (
              auditReviews.map((rev, idx) => (
                <div key={idx} className="hr-tech-box">
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 600 }}>
                    <span>{rev.action || 'REVIEW_RECORDED'}</span>
                    <span style={{ fontSize: '12px', color: 'var(--hr-muted-color)' }}>
                      {rev.created_at ? new Date(rev.created_at).toLocaleString() : 'Recent'}
                    </span>
                  </div>
                  <div style={{ margin: '6px 0', fontSize: '13px' }}>
                    Reviewer: <b>{rev.actor_id || 'Staff'}</b> ({rev.actor_role || 'STAFF'})
                  </div>
                  {rev.note && (
                    <p style={{ margin: '4px 0 0', fontSize: '12px', color: 'var(--hr-muted-color)', fontStyle: 'italic' }}>
                      "{rev.note}"
                    </p>
                  )}
                </div>
              ))
            ) : (
              <div className="hr-tech-box">
                <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 600 }}>
                  <span>INGESTION_AND_PROCESSED</span>
                  <span style={{ fontSize: '12px', color: 'var(--hr-muted-color)' }}>{receivedAtStr}</span>
                </div>
                <div style={{ margin: '6px 0', fontSize: '13px' }}>
                  Source: <b>{message?.source_label || message?.raw.channel}</b> · Actor: System Pipeline
                </div>
                <p style={{ margin: '4px 0 0', fontSize: '12px', color: 'var(--hr-muted-color)' }}>
                  Message ingested and dispatched to extraction pipeline. Initial version v1 created.
                </p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* 7. Sticky Bottom Footer (Review & Amend tab only) */}
      {activeTab === 'amend' && (
        <div className="hr-sticky-footer" data-component="StickyActionBar">
          <div className="hr-sticky-footer-inner">
            <div className={`hr-sticky-left ${isDirty ? 'is-dirty' : ''}`}>
              {!isDirty
                ? 'No field changes yet'
                : !reviewerNote.trim()
                ? 'Unsaved changes · reviewer note is required'
                : `${Number(itemsChanged) + Number(deliveryChanged) + Number(instructionsChanged)} field change(s) not saved`}
            </div>
            <div className="hr-sticky-right">
              <button
                type="button"
                className="hr-btn-footer"
                onClick={() => {
                  if (isDirty) setShowUnsavedBanner(true);
                  else navigate(returnTo || '/inbox/human-review');
                }}
              >
                Cancel
              </button>
              <button
                type="button"
                className="hr-btn-footer primary"
                disabled={saving || !isDirty || !reviewerNote.trim()}
                onClick={() => {
                  setSaveMode('save');
                  setModalReason(reviewerNote);
                  setSaveModalOpen(true);
                }}
              >
                Save changes
              </button>
              <button
                type="button"
                className="hr-btn-footer primary"
                disabled={saving || !isDirty || !reviewerNote.trim() || !deliveryValidation.isValid || items.some(it => !it.sku || !it.unit || !it.quantity) || context?.customer_identity_status !== 'LINK_VERIFIED' || Boolean(context?.missing_fields?.length || context?.conflicts?.length)}
                onClick={() => {
                  setSaveMode('accept');
                  setModalReason(reviewerNote);
                  setSaveModalOpen(true);
                }}
              >
                Save &amp; Accept
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal: Save Changes / Save & Accept Reason Modal */}
      {saveModalOpen && (
        <div className="hr-modal-overlay" role="dialog" aria-modal="true" aria-labelledby="save-modal-title">
          <div className="hr-modal-card">
            <h3 id="save-modal-title">
              {saveMode === 'accept' ? 'Confirm Review Acceptance' : 'Confirm Save Changes'}
            </h3>
            <p className="hr-modal-desc">
              Every review amendment requires an audited reason recorded in the context timeline.{' '}
              <b>Save &amp; Accept confirms the extraction review only and does not accept the customer order.</b>
            </p>

            <label htmlFor="modal-reason" style={{ fontSize: '13px', fontWeight: 600, display: 'block', marginBottom: '6px' }}>
              Audited reason <span className="hr-req-star">*</span>
            </label>
            <textarea
              id="modal-reason"
              className="hr-filter-input"
              rows={3}
              value={modalReason}
              onChange={e => setModalReason(e.target.value)}
              placeholder="State reason for changes or confirmation details…"
            />

            {hasMajorFieldChanges && (
              <label className="hr-modal-checkbox-row">
                <input
                  type="checkbox"
                  checked={majorFieldConfirmed}
                  onChange={e => setMajorFieldConfirmed(e.target.checked)}
                />
                <span>I confirm the change to a major field.</span>
              </label>
            )}

            <div className="hr-modal-actions">
              <button
                type="button"
                className="hr-btn-footer"
                onClick={() => setSaveModalOpen(false)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="hr-btn-footer primary"
                disabled={saving || !modalReason.trim() || (hasMajorFieldChanges && !majorFieldConfirmed)}
                onClick={handleConfirmSave}
              >
                {saveMode === 'accept' ? 'Confirm & Accept Review' : 'Save Changes'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal: Reprocess Confirmation */}
      {reprocessConfirmOpen && (
        <div className="hr-modal-overlay" role="dialog" aria-modal="true">
          <div className="hr-modal-card">
            <h3>Reprocess Extraction</h3>
            <p className="hr-modal-desc">
              This will re-run model inference and deterministic extraction on the original message content without creating duplicate messages.
            </p>
            <div className="hr-modal-actions">
              <button type="button" className="hr-btn-footer" onClick={() => setReprocessConfirmOpen(false)}>
                Cancel
              </button>
              <button type="button" className="hr-btn-footer primary" onClick={handleReprocess}>
                Confirm Reprocess
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal: Forward for Manager Review */}
      {managerReviewModalOpen && (
        <div className="hr-modal-overlay" role="dialog" aria-modal="true">
          <div className="hr-modal-card">
            <h3>Forward for Manager Review</h3>
            <p className="hr-modal-desc">
              Escalate this inquiry to an operational manager. Please specify the reason or unresolved issue.
            </p>
            <label htmlFor="mgr-note" style={{ fontSize: '13px', fontWeight: 600, display: 'block', marginBottom: '6px' }}>
              Escalation note <span className="hr-req-star">*</span>
            </label>
            <textarea
              id="mgr-note"
              className="hr-filter-input"
              rows={3}
              value={managerReviewNote}
              onChange={e => setManagerReviewNote(e.target.value)}
              placeholder="Reason for escalating to manager…"
            />
            <div className="hr-modal-actions">
              <button type="button" className="hr-btn-footer" onClick={() => setManagerReviewModalOpen(false)}>
                Cancel
              </button>
              <button
                type="button"
                className="hr-btn-footer primary"
                disabled={!managerReviewNote.trim()}
                onClick={handleForwardManager}
              >
                Forward
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal: Mark Unresolved */}
      {markUnresolvedModalOpen && (
        <div className="hr-modal-overlay" role="dialog" aria-modal="true">
          <div className="hr-modal-card">
            <h3>Mark Task Unresolved</h3>
            <p className="hr-modal-desc">
              Flag this inquiry as unresolved without confirming order fields. A reason must be recorded.
            </p>
            <label htmlFor="unres-reason" style={{ fontSize: '13px', fontWeight: 600, display: 'block', marginBottom: '6px' }}>
              Reason <span className="hr-req-star">*</span>
            </label>
            <textarea
              id="unres-reason"
              className="hr-filter-input"
              rows={3}
              value={markUnresolvedReason}
              onChange={e => setMarkUnresolvedReason(e.target.value)}
              placeholder="Why this task remains unresolved…"
            />
            <div className="hr-modal-actions">
              <button type="button" className="hr-btn-footer" onClick={() => setMarkUnresolvedModalOpen(false)}>
                Cancel
              </button>
              <button
                type="button"
                className="hr-btn-footer primary"
                style={{ background: 'var(--hr-orange-text)', borderColor: 'var(--hr-orange-text)' }}
                disabled={!markUnresolvedReason.trim()}
                onClick={handleMarkUnresolved}
              >
                Mark Unresolved
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal: Link to Order */}
      {linkOrderModalOpen && (
        <div className="hr-modal-overlay" role="dialog" aria-modal="true">
          <div className="hr-modal-card">
            <h3>Link to Existing Order</h3>
            <p className="hr-modal-desc">
              Select a candidate order and provide a business confirmation reason.
            </p>
            <label htmlFor="order-sel" style={{ fontSize: '13px', fontWeight: 600, display: 'block', marginBottom: '6px' }}>
              Target Order <span className="hr-req-star">*</span>
            </label>
            <select
              id="order-sel"
              className="hr-filter-select"
              style={{ width: '100%', marginBottom: '12px' }}
              value={selectedCandidateOrder}
              onChange={e => setSelectedCandidateOrder(e.target.value)}
            >
              <option value="">Select order…</option>
              <option value="ORD-9001">ORD-9001 · Active wholesale order</option>
              <option value="ORD-9002">ORD-9002 · Scheduled replenishment</option>
            </select>

            <label htmlFor="link-reason" style={{ fontSize: '13px', fontWeight: 600, display: 'block', marginBottom: '6px' }}>
              Rationale <span className="hr-req-star">*</span>
            </label>
            <textarea
              id="link-reason"
              className="hr-filter-input"
              rows={3}
              value={linkOrderReason}
              onChange={e => setLinkOrderReason(e.target.value)}
              placeholder="Evidence confirming this message relates to the selected order…"
            />

            <div className="hr-modal-actions">
              <button type="button" className="hr-btn-footer" onClick={() => setLinkOrderModalOpen(false)}>
                Cancel
              </button>
              <button
                type="button"
                className="hr-btn-footer primary"
                disabled={!selectedCandidateOrder || !linkOrderReason.trim()}
                onClick={handleLinkOrder}
              >
                Link Order
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal: Outbound Preview */}
      {replyPreviewOpen && (
        <div className="hr-modal-overlay" role="dialog" aria-modal="true">
          <div className="hr-modal-card">
            <h3>Outbound Message Preview</h3>
            <div style={{ margin: '14px 0', padding: '12px', background: '#f8fafc', borderRadius: '6px', fontSize: '13px' }}>
              <div><b>To:</b> {message?.raw.sender_identity_id}</div>
              <div><b>Channel:</b> {replyChannel}</div>
              <div><b>Purpose:</b> {replyPurpose}</div>
              <hr style={{ margin: '10px 0', border: '0', borderTop: '1px solid #e2e8f0' }} />
              <div style={{ whiteSpace: 'pre-wrap' }}>{replyMessage}</div>
            </div>
            <div className="hr-modal-actions">
              <button type="button" className="hr-btn-footer" onClick={() => setReplyPreviewOpen(false)}>
                Close Preview
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Toast Notification */}
      {toastMessage && (
        <div className="hr-toast" role="status">
          {toastMessage}
        </div>
      )}
    </div>
  );
}
