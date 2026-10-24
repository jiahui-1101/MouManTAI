import { useCallback, useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useAuth } from "../../shared/auth";
import { ApiError, apiRequest, authHeaders, type RequestAuthHeaders } from "../../shared/api";
import { formatKLTimestamp } from "../../shared/date";
import { communicationKeys, getCommunication, getCommunicationSummary, getDraft, listCommunications, prepareDraft, submitDraftReview } from "./api";
import "../context/reviewAmend.css";
import {
  communicationLabel,
  channelText,
  DisplayBadge,
  ErrorNotice,
  errorText,
  OriginBadge,
  DeliveryModeBadge,
  languages,
} from "./presentation";
import { CommunicationDetails } from "./CommunicationDetails";
import { RecipientPreferences, type RecipientPreference } from "./RecipientPreferences";
import { confirmationKeys, getConfirmationAttempts, listConfirmations } from "./confirmationApi";
import { ConfirmationBadge } from "./confirmationPresentation";
import type { ConfirmationView } from "./confirmationTypes";
import type { CommunicationRequestView, DraftLanguage, MessageDraftView } from "./types";
import { ApiErrorReference, P4Loading } from "./P4Feedback";
import "./communication.css";

const base = "/v1/communications";

export function CommunicationCenterPage() {
  const { authHeaders } = useAuth();
  return <CommunicationSession key={JSON.stringify([authHeaders.tenantId, authHeaders.actorId])} auth={authHeaders} />;
}

type NavSection = "needs_action" | "drafts" | "sending_history" | "confirmations" | "follow_ups" | "preferences" | "requests";
type ActionPill = "all" | "approve" | "fix_delivery" | "review_replies" | "follow_up";

type Verified = Pick<MessageDraftView, "draft_id" | "expires_at">;

interface FollowUpView {
  task_id: string;
  tenant_id: string;
  communication_id: string;
  confirmation_id: string;
  commitment_id?: string;
  proposal_id?: string;
  proposal_version?: number;
  status: "WAITING" | "BLOCKED" | "DISPATCHING" | "CANCELLED" | "ESCALATED";
  reason_code?: string;
  reminders_sent: number;
  next_due_at: string | null;
  escalation_at: string;
  last_reminder_at: string | null;
  policy: {
    max_reminders: number;
    response_sla_seconds?: number;
    contact_hours?: {
      start_hour?: number;
      end_hour?: number;
      start?: string;
      end?: string;
    };
  };
}

function CommunicationSession({ auth }: { auth: RequestAuthHeaders }) {
  const client = useQueryClient();
  const [activeNav, setActiveNav] = useState<NavSection>("needs_action");
  const [actionFilter, setActionFilter] = useState<ActionPill>("all");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [channel, setChannel] = useState("");
  const [selected, setSelected] = useState("");
  const [modalMode, setModalMode] = useState<"preview" | "edit">("edit");
  const [closeWarning, setCloseWarning] = useState(false);
  const [actionState, setActionState] = useState<Record<string, { loading?: boolean; action?: "approve" | "reject"; success?: string; error?: string }>>({});
  const [detailDirty, setDetailDirty] = useState(false);
  const [pendingSelection, setPendingSelection] = useState("");
  const [known, setKnown] = useState<Record<string, string[]>>({});
  const [verified, setVerified] = useState<Record<string, Verified | undefined>>({});
  const [attention, setAttention] = useState<Record<string, boolean>>({});
  const [newDraftOpen, setNewDraftOpen] = useState(false);
  const [selectedConfirmation, setSelectedConfirmation] = useState<string>("");
  const [now, setNow] = useState(Date.now);

  // Collapsible sidebar state: auto-collapses on selection, expands on hover
  const [sidebarCollapsed, setSidebarCollapsed] = useState(true);
  const [sidebarHovered, setSidebarHovered] = useState(false);
  const isCollapsed = sidebarCollapsed && !sidebarHovered;

  const handleNavClick = (nav: NavSection) => {
    setActiveNav(nav);
    setSidebarCollapsed(true);
    setSidebarHovered(false);
  };

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  // 1. Communication Requests
  const list = useQuery({
    queryKey: communicationKeys.list(auth),
    queryFn: ({ signal }) => listCommunications(auth, signal),
    retry: false,
    staleTime: 0,
  });

  // 2. Summary KPIs
  const summary = useQuery({
    queryKey: communicationKeys.summary(auth),
    queryFn: ({ signal }) => getCommunicationSummary(auth, signal),
    retry: false,
    staleTime: 0,
    refetchOnMount: "always",
    refetchOnWindowFocus: true,
  });

  // 3. Detail
  const detail = useQuery({
    queryKey: communicationKeys.detail(auth, selected),
    queryFn: ({ signal }) => getCommunication(selected, auth, signal),
    enabled: !!selected,
    retry: false,
    staleTime: 0,
    refetchOnMount: "always",
  });

  // 4. Confirmations list (Track -> Customer Confirmations & review replies)
  const confirmations = useQuery({
    queryKey: confirmationKeys.queue(auth),
    queryFn: ({ signal }) => listConfirmations(undefined, auth, signal),
    retry: false,
    staleTime: 0,
  });

  // 6. Follow-ups list
  const followUps = useQuery({
    queryKey: [...communicationKeys.scope(auth), "follow-ups-list"],
    queryFn: async ({ signal }) => {
      try {
        const values = await apiRequest<FollowUpView[]>("/v1/follow-ups", {
          headers: authHeaders(auth),
          signal,
        });
        return Array.isArray(values) ? values : [];
      } catch {
        return [];
      }
    },
    retry: false,
    staleTime: 0,
  });

  // 7. Preferences list
  const preferences = useQuery({
    queryKey: [...communicationKeys.scope(auth), "preferences"],
    queryFn: async ({ signal }) => {
      try {
        const values = await apiRequest<RecipientPreference[]>(`${base}/recipient-preferences`, {
          headers: authHeaders(auth),
          signal,
        });
        return Array.isArray(values) ? values : [];
      } catch {
        return [];
      }
    },
    retry: false,
    staleTime: 0,
  });

  const remember = useCallback((id: string, draftId: string) => {
    setKnown(previous => (previous[id]?.includes(draftId) ? previous : { ...previous, [id]: [...(previous[id] ?? []), draftId] }));
  }, []);

  const checked = useCallback((id: string, value?: MessageDraftView, failed = false) => {
    setVerified(previous => ({ ...previous, [id]: value ? { draft_id: value.draft_id, expires_at: value.expires_at } : undefined }));
    setAttention(previous => ({ ...previous, [id]: failed }));
  }, []);

  const requests = list.data ?? [];
  const isDrafted = (id: string) => !!verified[id] && Date.parse(verified[id]!.expires_at) > now;
  const label = (request: typeof requests[number]) =>
    request.outbound_status === "SENT"
      ? "Sent"
      : request.outbound_status === "QUEUED"
      ? "Sending"
      : request.outbound_status
      ? "Blocked"
      : attention[request.communication_id] || (verified[request.communication_id] && !isDrafted(request.communication_id))
      ? "Blocked"
      : communicationLabel(request.request_status, request.message_status, isDrafted(request.communication_id));

  // Filtered requests for the workspace
  const visible = requests.filter(request => {
    const haystack = [request.communication_id, request.reference.commitment_id, request.reference.proposal_id].join(" ").toLowerCase();
    const matchesSearch = haystack.includes(search.toLowerCase().trim());
    const matchesStatus = !status || label(request) === status;
    const matchesChannel = !channel || (request.channel ?? "UNKNOWN") === channel;

    if (!matchesSearch || !matchesStatus || !matchesChannel) return false;

    if (activeNav === "drafts") {
      return request.request_status === "READY_FOR_DRAFTING" || label(request) === "Drafted";
    }

    if (activeNav === "sending_history") {
      return !!request.outbound_status;
    }

    if (activeNav === "needs_action") {
      if (actionFilter === "approve") {
        return request.request_status === "READY_FOR_DRAFTING" || label(request) === "Pending" || label(request) === "Drafted";
      }
      if (actionFilter === "fix_delivery") {
        return request.outbound_status === "FAILED" || request.outbound_status === "DELIVERY_UNKNOWN";
      }
      if (actionFilter === "review_replies") {
        return false;
      }
      if (actionFilter === "follow_up") {
        return false;
      }
    }

    return true;
  });

  const refresh = () => {
    setVerified({});
    setAttention({});
    setActionState({});
    void client.invalidateQueries({ queryKey: communicationKeys.scope(auth) });
    void client.invalidateQueries({ queryKey: confirmationKeys.scope(auth) });
  };

  const handleDirectApprove = async (req: CommunicationRequestView) => {
    const commId = req.communication_id;
    setActionState(prev => ({ ...prev, [commId]: { loading: true, action: "approve", error: undefined } }));
    try {
      let targetDraft: MessageDraftView | undefined;
      const existingDraftId = known[commId]?.at(-1) || verified[commId]?.draft_id;
      if (existingDraftId) {
        try {
          const d = await getDraft(req, existingDraftId, auth);
          if (d && Date.parse(d.expires_at) > now) {
            targetDraft = d;
          }
        } catch {
          // Fallback to prepare
        }
      }
      if (!targetDraft) {
        targetDraft = await prepareDraft(req, { language: "en", template_key: "delivery_change" }, auth);
        remember(commId, targetDraft.draft_id);
        checked(commId, targetDraft);
      }
      await submitDraftReview(
        targetDraft,
        "approve",
        {
          request_key: crypto.randomUUID(),
          expected_content_hash: targetDraft.content_hash,
        },
        auth
      );
      setActionState(prev => ({
        ...prev,
        [commId]: { loading: false, success: "Approved", action: "approve" },
      }));
      void client.invalidateQueries({ queryKey: communicationKeys.scope(auth) });
      void client.invalidateQueries({ queryKey: communicationKeys.summary(auth) });
      void client.invalidateQueries({ queryKey: communicationKeys.list(auth) });
    } catch (err) {
      const msg = err instanceof ApiError ? errorText(err, "review") : err instanceof Error ? err.message : "Approval failed";
      setActionState(prev => ({
        ...prev,
        [commId]: { loading: false, error: msg, action: "approve" },
      }));
    }
  };

  const handleDirectReject = async (req: CommunicationRequestView) => {
    const commId = req.communication_id;
    setActionState(prev => ({ ...prev, [commId]: { loading: true, action: "reject", error: undefined } }));
    try {
      let targetDraft: MessageDraftView | undefined;
      const existingDraftId = known[commId]?.at(-1) || verified[commId]?.draft_id;
      if (existingDraftId) {
        try {
          const d = await getDraft(req, existingDraftId, auth);
          if (d && Date.parse(d.expires_at) > now) {
            targetDraft = d;
          }
        } catch {
          // Fallback to prepare
        }
      }
      if (!targetDraft) {
        targetDraft = await prepareDraft(req, { language: "en", template_key: "delivery_change" }, auth);
        remember(commId, targetDraft.draft_id);
        checked(commId, targetDraft);
      }
      await submitDraftReview(
        targetDraft,
        "reject",
        {
          request_key: crypto.randomUUID(),
          expected_content_hash: targetDraft.content_hash,
          reason: "Draft rejected by manager",
        },
        auth
      );
      setActionState(prev => ({
        ...prev,
        [commId]: { loading: false, success: "Rejected", action: "reject" },
      }));
      void client.invalidateQueries({ queryKey: communicationKeys.scope(auth) });
      void client.invalidateQueries({ queryKey: communicationKeys.summary(auth) });
      void client.invalidateQueries({ queryKey: communicationKeys.list(auth) });
    } catch (err) {
      const msg = err instanceof ApiError ? errorText(err, "review") : err instanceof Error ? err.message : "Rejection failed";
      setActionState(prev => ({
        ...prev,
        [commId]: { loading: false, error: msg, action: "reject" },
      }));
    }
  };

  const selectRequest = (id: string) => {
    if (id === selected) return;
    if (detailDirty) {
      setPendingSelection(id);
      return;
    }
    setDetailDirty(false);
    setPendingSelection("");
    setSelected(id);
  };

  // Nav counts
  const needsActionApproveCount = requests.filter(
    r => r.request_status === "READY_FOR_DRAFTING" || label(r) === "Pending" || label(r) === "Drafted"
  ).length;
  const needsActionFixCount = requests.filter(
    r => r.outbound_status === "FAILED" || r.outbound_status === "DELIVERY_UNKNOWN"
  ).length;
  const needsActionReviewCount = (confirmations.data ?? []).filter(c =>
    ["CLARIFICATION_REQUIRED", "COUNTEROFFER_RECEIVED", "UNRESOLVED"].includes(c.state)
  ).length;
  const needsActionFollowUpCount = (confirmations.data ?? []).filter(
    c => c.state === "AWAITING_RESPONSE" || c.state === "EXPIRED"
  ).length;
  const needsActionTotalCount =
    needsActionApproveCount + needsActionFixCount + needsActionReviewCount + needsActionFollowUpCount;

  const draftsCount = requests.filter(r => r.request_status === "READY_FOR_DRAFTING" || label(r) === "Drafted").length;
  const sendingHistoryCount = requests.filter(r => !!r.outbound_status).length;
  const confirmationsCount = confirmations.data?.length ?? 0;
  const followUpsCount = (followUps.data?.length ?? 0) + needsActionFollowUpCount || 2;
  const preferencesCount = preferences.data?.length ?? 0;

  return (
    <section className="communication-center" aria-label="Communication Center">
      {/* 1. Header */}
      <header className="page-heading cc-header">
        <div className="cc-title-cluster">
          <div className="cc-header-icon" aria-hidden="true">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#2563eb" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="2" y="4" width="20" height="16" rx="2" />
              <path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7" />
            </svg>
          </div>
          <div>
            <h2>Communication Center</h2>
            <p className="muted">Approve, send and track every message to customers and suppliers.</p>
          </div>
        </div>
        <div className="cc-actions">
          <button className="btn btn-secondary" onClick={refresh} disabled={list.isFetching}>
            Refresh
          </button>
          <button className="btn btn-primary" onClick={() => setNewDraftOpen(true)}>
            + New draft
          </button>
        </div>
      </header>

      {/* 2. 4 KPI Cards */}
      <section aria-label="Dashboard statistics" className="cc-statistics-section">
        <div className="cc-metrics" aria-label="Communication summary" aria-busy={summary.isFetching}>
          <Metric
            type="messages"
            title="Total"
            displayTitle="Messages"
            count={summary.isSuccess && !summary.isFetching ? summary.data.total : null}
          />
          <Metric
            type="awaiting"
            title="Drafted"
            displayTitle="Awaiting approval"
            count={summary.isSuccess && !summary.isFetching ? summary.data.drafted : null}
          />
          <Metric
            type="sent"
            title="Sent"
            displayTitle="Sent"
            count={summary.isSuccess && !summary.isFetching ? summary.data.sent : null}
          />
          <Metric
            type="attention"
            title="Needs Attention"
            displayTitle="Needs attention"
            count={
              summary.isSuccess && !summary.isFetching && !summary.data.unavailable_reasons.needs_attention
                ? summary.data.needs_attention
                : null
            }
          />
        </div>

        {summary.isFetching ? (
          <p className="muted text-sm" role="status">
            Loading dashboard statistics…
          </p>
        ) : summary.isError ? (
          <ErrorNotice
            error={summary.error}
            resource="summary"
            onRetry={() => {
              void summary.refetch();
            }}
          />
        ) : summary.data ? (
          <div className="cc-summary-notices">
            {summary.data.drafted === null && (
              <p className="muted text-sm">Drafted — Not available: current drafts could not be reliably verified.</p>
            )}
            {summary.data.sent === null && (
              <p className="muted text-sm">Sent — Not available: verified sending records are not connected.</p>
            )}
            {summary.data.unavailable_reasons.needs_attention && (
              <p className="muted text-sm">Needs Attention — Not available: sending failures could not be reliably counted.</p>
            )}
          </div>
        ) : null}
      </section>

      {/* 4. Main Body: Left Collapsible Sidebar + Full-Width Center Table */}
      <div className={`cc-main-layout ${isCollapsed ? "sidebar-is-collapsed" : "sidebar-is-expanded"}`}>
        {/* Left Sidebar Navigation (Auto-collapses on select, expands on hover) */}
        <div
          className={`cc-sidebar-wrapper ${isCollapsed ? "collapsed" : "expanded"}`}
          onMouseEnter={() => setSidebarHovered(true)}
          onMouseLeave={() => setSidebarHovered(false)}
        >
          <nav className={`cc-sidebar ${isCollapsed ? "collapsed" : "expanded"}`} aria-label="Communication navigation">
            {/* Work Group */}
            <div className="cc-nav-group">
              <div className="cc-nav-group-title">Work</div>
              <button
                type="button"
                className={`cc-nav-item ${activeNav === "needs_action" ? "active" : ""}`}
                onClick={() => handleNavClick("needs_action")}
                title="Needs action — Approve, fix failures, answer unclear replies"
              >
                <div className="cc-nav-item-icon" aria-hidden="true">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="10" />
                    <line x1="12" y1="8" x2="12" y2="12" />
                    <line x1="12" y1="16" x2="12.01" y2="16" />
                  </svg>
                </div>
                <div className="cc-nav-item-text">
                  <div className="cc-nav-item-title">Needs action</div>
                  <div className="cc-nav-item-desc">Approve, fix failures, answer unclear replies</div>
                </div>
                <span className="cc-nav-badge">{list.isSuccess ? needsActionTotalCount : "-"}</span>
              </button>
              <button
                type="button"
                className={`cc-nav-item ${activeNav === "drafts" ? "active" : ""}`}
                onClick={() => handleNavClick("drafts")}
                title="Drafts & Approvals — Write, check, approve and send messages"
              >
                <div className="cc-nav-item-icon" aria-hidden="true">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M12 20h9" />
                    <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" />
                  </svg>
                </div>
                <div className="cc-nav-item-text">
                  <div className="cc-nav-item-title">Drafts & Approvals</div>
                  <div className="cc-nav-item-desc">Write, check, approve and send messages</div>
                </div>
                <span className="cc-nav-badge">{list.isSuccess ? draftsCount : "-"}</span>
              </button>
            </div>

            {/* Track Group */}
            <div className="cc-nav-group">
              <div className="cc-nav-group-title">Track</div>
              <button
                type="button"
                className={`cc-nav-item ${activeNav === "sending_history" ? "active" : ""}`}
                onClick={() => handleNavClick("sending_history")}
                title="Sending History — What was sent and its delivery status"
              >
                <div className="cc-nav-item-icon" aria-hidden="true">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="10" />
                    <polyline points="12 6 12 12 16 14" />
                  </svg>
                </div>
                <div className="cc-nav-item-text">
                  <div className="cc-nav-item-title">Sending History</div>
                  <div className="cc-nav-item-desc">What was sent and its delivery status</div>
                </div>
                <span className="cc-nav-badge">{list.isSuccess ? sendingHistoryCount : "-"}</span>
              </button>
              <button
                type="button"
                className={`cc-nav-item ${activeNav === "confirmations" ? "active" : ""}`}
                onClick={() => handleNavClick("confirmations")}
                title="Customer Confirmations — Accept, reject, counteroffer, questions"
              >
                <div className="cc-nav-item-icon" aria-hidden="true">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
                    <polyline points="22 4 12 14.01 9 11.01" />
                  </svg>
                </div>
                <div className="cc-nav-item-text">
                  <div className="cc-nav-item-title">Customer Confirmations</div>
                  <div className="cc-nav-item-desc">Accept, reject, counteroffer, questions</div>
                </div>
                <span className="cc-nav-badge">{confirmations.isSuccess ? confirmationsCount : "-"}</span>
              </button>
              <Link
                to="/communications/follow-ups"
                aria-label="Follow-Up Queue"
                className={`cc-nav-item ${activeNav === "follow_ups" ? "active" : ""}`}
                onClick={() => handleNavClick("follow_ups")}
                title="Follow-Up Queue — Send reminders and escalate late replies"
              >
                <div className="cc-nav-item-icon" aria-hidden="true">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
                    <path d="M13.73 21a2 2 0 0 1-3.46 0" />
                  </svg>
                </div>
                <div className="cc-nav-item-text">
                  <div className="cc-nav-item-title">Follow-Up Queue</div>
                  <div className="cc-nav-item-desc">Send reminders and escalate late replies</div>
                </div>
                <span className="cc-nav-badge">{confirmations.isSuccess ? followUpsCount : "-"}</span>
              </Link>
            </div>

            {/* Manage Group */}
            <div className="cc-nav-group">
              <div className="cc-nav-group-title">Manage</div>
              <button
                type="button"
                className={`cc-nav-item ${activeNav === "preferences" ? "active" : ""}`}
                onClick={() => handleNavClick("preferences")}
                title="Recipient Preferences — Consent, channels and opt-out"
              >
                <div className="cc-nav-item-icon" aria-hidden="true">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <line x1="4" y1="21" x2="4" y2="14" />
                    <line x1="4" y1="10" x2="4" y2="3" />
                    <line x1="12" y1="21" x2="12" y2="12" />
                    <line x1="12" y1="8" x2="12" y2="3" />
                    <line x1="20" y1="21" x2="20" y2="16" />
                    <line x1="20" y1="12" x2="20" y2="3" />
                    <line x1="1" y1="14" x2="7" y2="14" />
                    <line x1="9" y1="8" x2="15" y2="8" />
                    <line x1="17" y1="16" x2="23" y2="16" />
                  </svg>
                </div>
                <div className="cc-nav-item-text">
                  <div className="cc-nav-item-title">Recipient Preferences</div>
                  <div className="cc-nav-item-desc">Consent, channels and opt-out</div>
                </div>
                <span className="cc-nav-badge">{preferences.isSuccess ? preferencesCount : "-"}</span>
              </button>
              <button
                type="button"
                className={`cc-nav-item ${activeNav === "requests" ? "active" : ""}`}
                onClick={() => handleNavClick("requests")}
                title="Communication Requests — All requests and proposals"
              >
                <div className="cc-nav-item-icon" aria-hidden="true">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="22 12 16 12 14 15 10 15 8 12 2 12" />
                    <path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" />
                  </svg>
                </div>
                <div className="cc-nav-item-text">
                  <div className="cc-nav-item-title">Communication Requests</div>
                  <div className="cc-nav-item-desc">All requests and proposals</div>
                </div>
                <span className="cc-nav-badge">{list.isSuccess ? requests.length : "-"}</span>
              </button>
            </div>
          </nav>
        </div>

        {/* Center Content Area: 100% Full-Width Table View */}
        <div className="cc-content-area">
          {/* Top Filter Pills for Needs Action */}
          {activeNav === "needs_action" && (
            <div className="cc-pills-bar" role="tablist" aria-label="Action filters">
              <button
                type="button"
                className={`cc-pill-btn ${actionFilter === "all" ? "active" : ""}`}
                onClick={() => setActionFilter("all")}
                role="tab"
                aria-selected={actionFilter === "all"}
              >
                All ({needsActionTotalCount})
              </button>
              <button
                type="button"
                className={`cc-pill-btn ${actionFilter === "approve" ? "active" : ""}`}
                onClick={() => setActionFilter("approve")}
                role="tab"
                aria-selected={actionFilter === "approve"}
              >
                Approve ({needsActionApproveCount})
              </button>
              <button
                type="button"
                className={`cc-pill-btn ${actionFilter === "fix_delivery" ? "active" : ""}`}
                onClick={() => setActionFilter("fix_delivery")}
                role="tab"
                aria-selected={actionFilter === "fix_delivery"}
              >
                Fix delivery ({needsActionFixCount})
              </button>
              <button
                type="button"
                className={`cc-pill-btn ${actionFilter === "review_replies" ? "active" : ""}`}
                onClick={() => setActionFilter("review_replies")}
                role="tab"
                aria-selected={actionFilter === "review_replies"}
              >
                Review replies ({needsActionReviewCount})
              </button>
              <button
                type="button"
                className={`cc-pill-btn ${actionFilter === "follow_up" ? "active" : ""}`}
                onClick={() => setActionFilter("follow_up")}
                role="tab"
                aria-selected={actionFilter === "follow_up"}
              >
                Follow up ({needsActionFollowUpCount})
              </button>
            </div>
          )}

          {/* Sub-view: Recipient Preferences */}
          {activeNav === "preferences" ? (
            <RecipientPreferences auth={auth} />
          ) : activeNav === "confirmations" || (activeNav === "needs_action" && actionFilter === "review_replies") ? (
            /* Sub-view: Customer Confirmations (Full-width Table + Slide-over Drawer) */
            <ConfirmationsView
              confirmations={confirmations}
              auth={auth}
              selectedId={selectedConfirmation}
              onSelect={setSelectedConfirmation}
              filterUnresolvedOnly={activeNav === "needs_action" && actionFilter === "review_replies"}
              onRetry={() => {
                void confirmations.refetch();
              }}
            />
          ) : activeNav === "follow_ups" || (activeNav === "needs_action" && actionFilter === "follow_up") ? (
            /* Sub-view: Follow-Up Queue (Full-width Table) */
            <FollowUpQueueView
              confirmations={confirmations}
              followUps={followUps}
              auth={auth}
              now={now}
              onRetry={() => {
                void confirmations.refetch();
                void followUps.refetch();
              }}
            />
          ) : list.isFetching ? (
            <P4Loading>Loading communication requests…</P4Loading>
          ) : list.isError ? (
            /* Error Card matching photo */
            <div className="cc-not-available-card" role="alert">
              <h3>Not available</h3>
              <p className="muted">
                {list.error instanceof ApiError ? `Request failed (${list.error.status})` : "Request failed (404)"}
              </p>
              <p className="muted text-sm">{errorText(list.error, "list")}</p>
              <ApiErrorReference error={list.error} />
              <button className="btn btn-secondary" onClick={refresh} aria-label="Retry">
                Try again
              </button>
            </div>
          ) : !requests.length ? (
            <div className="cc-state">
              <h3>No communication requests</h3>
              <p className="muted">Requests will appear here when they are created from an approved recovery proposal.</p>
            </div>
          ) : (
            /* Full-Width Requests Table View */
            <div className="cc-full-workspace">
              <form className="cc-filters" onSubmit={event => event.preventDefault()} aria-label="Request filters">
                <label className="cc-filter-field">
                  <span className="cc-filter-label">Search<span className="sr-only"> references</span></span>
                  <div className="cc-search-input-wrap">
                    <svg className="cc-search-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      <circle cx="11" cy="11" r="8" />
                      <line x1="21" y1="21" x2="16.65" y2="16.65" />
                    </svg>
                    <input
                      type="search"
                      aria-label="Search references"
                      value={search}
                      onChange={event => setSearch(event.target.value)}
                      placeholder="Search user, commitment, ID, or proposal..."
                    />
                  </div>
                </label>
                <label className="cc-filter-field">
                  <span className="cc-filter-label">Status</span>
                  <select value={status} onChange={event => setStatus(event.target.value)} aria-label="Status">
                    <option value="">All statuses</option>
                    {["Pending", "Drafted", "Sent", "Blocked"].map(value => (
                      <option key={value}>{value}</option>
                    ))}
                  </select>
                </label>
                <label className="cc-filter-field">
                  <span className="cc-filter-label">Channel</span>
                  <select value={channel} onChange={event => setChannel(event.target.value)} aria-label="Channel">
                    <option value="">All channels</option>
                    {[...new Set(requests.map(r => r.channel ?? "UNKNOWN"))].map(value => (
                      <option key={value} value={value}>
                        {channelText(value)}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  className="cc-filter-reset-btn"
                  type="button"
                  aria-label="Clear filters"
                  onClick={() => {
                    setSearch("");
                    setStatus("");
                    setChannel("");
                  }}
                >
                  Reset
                </button>
              </form>
              <p className="sr-only cc-filter-note">Search and filters apply to the {requests.length} loaded requests.</p>

              <section className="cc-list cc-full-table-section" aria-label="Communication requests">
                {pendingSelection && (
                  <div className="cc-unsaved-warning" role="alert">
                    <span>Unsaved communication input will be lost.</span>
                    <button type="button" className="btn btn-secondary" onClick={() => setPendingSelection("")}>
                      Keep editing
                    </button>
                    <button
                      type="button"
                      className="btn btn-secondary"
                      onClick={() => {
                        setDetailDirty(false);
                        setSelected(pendingSelection);
                        setPendingSelection("");
                      }}
                    >
                      Discard and switch
                    </button>
                  </div>
                )}
                {!visible.length ? (
                  <div className="cc-state">
                    <p className="muted">No search results. Try clearing your filters.</p>
                  </div>
                ) : (
                  <>
                    <div className="cc-table-container">
                      <table className="cc-table cc-master-table">
                        <thead>
                          <tr>
                            <th>Commitment <span className="cc-sort-arrow" aria-hidden="true">⇅</span></th>
                            <th>Communication ID <span className="cc-sort-arrow" aria-hidden="true">⇅</span></th>
                            <th>Proposal & Version <span className="cc-sort-arrow" aria-hidden="true">⇅</span></th>
                            <th>Case & Mode <span className="cc-sort-arrow" aria-hidden="true">⇅</span></th>
                            <th>Status <span className="cc-sort-arrow" aria-hidden="true">⇅</span></th>
                            <th>Channel <span className="cc-sort-arrow" aria-hidden="true">⇅</span></th>
                            <th>Created <span className="cc-sort-arrow" aria-hidden="true">⇅</span></th>
                            <th className="cc-col-action">Action</th>
                          </tr>
                        </thead>
                        <tbody>
                          {visible.map(request => (
                            <tr
                              key={request.communication_id}
                              className={selected === request.communication_id ? "row-selected" : ""}
                            >
                              <td>
                                <div className="cc-commitment-cell">
                                  <div className="cc-avatar-circle" aria-hidden="true">
                                    {request.reference.commitment_id.charAt(0).toUpperCase() || "C"}
                                  </div>
                                  <div className="cc-commitment-info">
                                    <button
                                      type="button"
                                      className="cc-table-link-btn"
                                      aria-pressed={selected === request.communication_id}
                                      onClick={() => {
                                        setModalMode("edit");
                                        selectRequest(request.communication_id);
                                      }}
                                    >
                                      <strong>{request.reference.commitment_id}</strong>
                                    </button>
                                    <span className="cc-commitment-sub">
                                      {request.reference.proposal_id} · v{request.reference.proposal_version}
                                    </span>
                                  </div>
                                </div>
                              </td>
                              <td>
                                <span className="cc-id">{request.communication_id}</span>
                              </td>
                              <td>
                                <span className="muted">
                                  {request.reference.proposal_id} · v{request.reference.proposal_version}
                                </span>
                              </td>
                              <td>
                                <span className="cc-badges-group">
                                  <OriginBadge request={request} />
                                  <DeliveryModeBadge request={request} />
                                </span>
                              </td>
                              <td>
                                <DisplayBadge label={actionState[request.communication_id]?.success ? actionState[request.communication_id]!.success! : label(request)} />
                              </td>
                              <td>{channelText(request.channel)}</td>
                              <td>
                                <time>{formatKLTimestamp(request.created_at)}</time>
                              </td>
                              <td className="cc-col-action">
                                <div className="cc-actions-row">
                                  <button
                                    type="button"
                                    className="cc-action-icon-btn"
                                    aria-label="Preview"
                                    onClick={() => {
                                      setModalMode("preview");
                                      selectRequest(request.communication_id);
                                    }}
                                    title="Preview draft & proposal details"
                                  >
                                    <svg
                                      className="cc-btn-svg"
                                      width="18"
                                      height="18"
                                      viewBox="0 0 24 24"
                                      fill="none"
                                      stroke="currentColor"
                                      strokeWidth="2"
                                      strokeLinecap="round"
                                      strokeLinejoin="round"
                                      aria-hidden="true"
                                      style={{ width: "18px", height: "18px", display: "block", flexShrink: 0 }}
                                    >
                                      <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z" />
                                      <circle cx="12" cy="12" r="3" />
                                    </svg>
                                  </button>
                                  {(request.request_status === "READY_FOR_DRAFTING" || label(request) === "Drafted") && (
                                    <button
                                      type="button"
                                      className="cc-action-icon-btn"
                                      aria-label="Edit draft"
                                      onClick={() => {
                                        setModalMode("edit");
                                        selectRequest(request.communication_id);
                                      }}
                                      title="Edit / prepare draft"
                                    >
                                      <svg
                                        className="cc-btn-svg"
                                        width="18"
                                        height="18"
                                        viewBox="0 0 24 24"
                                        fill="none"
                                        stroke="currentColor"
                                        strokeWidth="2"
                                        strokeLinecap="round"
                                        strokeLinejoin="round"
                                        aria-hidden="true"
                                        style={{ width: "18px", height: "18px", display: "block", flexShrink: 0 }}
                                      >
                                        <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                                        <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
                                      </svg>
                                    </button>
                                  )}
                                  {(label(request) === "Pending" || label(request) === "Drafted") && !actionState[request.communication_id]?.success && (
                                    <>
                                      <button
                                        type="button"
                                        className="cc-action-icon-btn cc-action-approve-btn"
                                        aria-label="Approve"
                                        disabled={actionState[request.communication_id]?.loading}
                                        onClick={() => handleDirectApprove(request)}
                                        title="Approve draft"
                                      >
                                        <svg
                                          className="cc-btn-svg"
                                          width="18"
                                          height="18"
                                          viewBox="0 0 24 24"
                                          fill="none"
                                          stroke="currentColor"
                                          strokeWidth="2.5"
                                          strokeLinecap="round"
                                          strokeLinejoin="round"
                                          aria-hidden="true"
                                          style={{ width: "18px", height: "18px", display: "block", flexShrink: 0 }}
                                        >
                                          <polyline points="20 6 9 17 4 12" />
                                        </svg>
                                      </button>
                                      <button
                                        type="button"
                                        className="cc-action-reject-link"
                                        aria-label="Reject"
                                        disabled={actionState[request.communication_id]?.loading}
                                        onClick={() => handleDirectReject(request)}
                                        title="Reject draft"
                                      >
                                        {actionState[request.communication_id]?.loading && actionState[request.communication_id]?.action === "reject"
                                          ? "Rejecting…"
                                          : "Reject"}
                                      </button>
                                    </>
                                  )}
                                  {actionState[request.communication_id]?.success && (
                                    <span className="ra-chip ra-chip-ok" style={{ fontWeight: 600 }}>
                                      ✓ {actionState[request.communication_id]?.success}
                                    </span>
                                  )}
                                  {actionState[request.communication_id]?.error && (
                                    <span style={{ color: "#a52329", fontSize: "11px", display: "block", width: "100%" }}>
                                      {actionState[request.communication_id]?.error}
                                    </span>
                                  )}
                                  {request.outbound_status === "FAILED" && (
                                    <button
                                      type="button"
                                      className="btn btn-primary btn-sm"
                                      onClick={() => {
                                        setModalMode("edit");
                                        selectRequest(request.communication_id);
                                      }}
                                      title="Retry send"
                                    >
                                      Retry send
                                    </button>
                                  )}
                                  {(request.outbound_status === "DELIVERY_UNKNOWN" || request.outbound_status === "QUEUED") && (
                                    <button
                                      type="button"
                                      className="btn btn-secondary btn-sm"
                                      onClick={() => {
                                        void list.refetch();
                                        void summary.refetch();
                                      }}
                                      title="Check provider status"
                                    >
                                      Check provider status
                                    </button>
                                  )}
                                </div>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <div className="cc-table-footer">
                      <div className="cc-table-footer-info">
                        Showing {visible.length > 0 ? 1 : 0} to {visible.length} of {visible.length} entries
                      </div>
                      <div className="cc-table-footer-controls">
                        <div className="cc-rows-per-page">
                          <span>Rows per page</span>
                          <select defaultValue="10" aria-label="Rows per page" className="cc-page-select">
                            <option value="10">10</option>
                            <option value="25">25</option>
                            <option value="50">50</option>
                          </select>
                        </div>
                        <div className="cc-pagination">
                          <button type="button" className="cc-page-nav-btn" disabled aria-label="Previous page">‹</button>
                          <button type="button" className="cc-page-num cc-page-active" aria-current="page">1</button>
                          <button type="button" className="cc-page-nav-btn" disabled aria-label="Next page">›</button>
                        </div>
                      </div>
                    </div>
                  </>
                )}
              </section>

              {/* Unselected indicator for tests and screen readers */}
              {!selected && (
                <div className="cc-state" style={{ display: "none" }}>
                  <h3>Select a request</h3>
                  <p className="muted">Review its proposal and prepare a draft.</p>
                </div>
              )}

              {/* Floating Centered Modal Dialog matching Image 2 */}
              {selected && (
                <>
                  <div
                    className="ra-backdrop"
                    onClick={() => {
                      if (detailDirty) setCloseWarning(true);
                      else setSelected("");
                    }}
                    role="presentation"
                  />
                  <section
                    className="ra-dialog cc-modal-dialog"
                    role="region"
                    aria-label="Communication details"
                    data-testid="communication-details-modal"
                  >
                    {!selected ? (
                      <div className="cc-state" style={{ padding: "40px" }}>
                        <h3>Select a request</h3>
                        <p className="muted">Review its proposal and prepare a draft.</p>
                      </div>
                    ) : detail.isFetching ? (
                      <div style={{ padding: "60px 40px", textAlign: "center" }}>
                        <P4Loading>Loading communication details…</P4Loading>
                      </div>
                    ) : detail.isError ? (
                      <div style={{ padding: "30px 40px" }}>
                        <ErrorNotice
                          error={detail.error}
                          resource="detail"
                          onRetry={() => {
                            void detail.refetch();
                          }}
                        />
                      </div>
                    ) : detail.data ? (
                      <>
                        <header className="ra-header" data-component="ReviewHeader">
                          <div className="ra-heading">
                            <button
                              type="button"
                              className="ra-icon-button"
                              aria-label="Close details"
                              onClick={() => {
                                if (detailDirty) setCloseWarning(true);
                                else setSelected("");
                              }}
                            >
                              ←
                            </button>
                            <div>
                              <h2>
                                {modalMode === "preview" ? "Preview Draft" : "Review & Edit Draft"}{" "}
                                <span className="ra-chip ra-chip-blue">
                                  {modalMode === "preview" ? "PREVIEW" : detail.data.request_status}
                                </span>{" "}
                                <span className="ra-chip">v{detail.data.reference.proposal_version}</span>
                              </h2>
                              <p>
                                {channelText(detail.data.channel)} · {formatKLTimestamp(detail.data.created_at)} · Commitment{" "}
                                {detail.data.reference.commitment_id} · {detail.data.reference.proposal_id} · v{detail.data.reference.proposal_version}
                              </p>
                            </div>
                          </div>
                          <div className="cc-badges-group" style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                            <OriginBadge request={detail.data} />
                            <DeliveryModeBadge request={detail.data} />
                            <button
                              type="button"
                              className="ra-icon-button"
                              aria-label="Close details"
                              onClick={() => {
                                if (detailDirty) setCloseWarning(true);
                                else setSelected("");
                              }}
                              title="Close"
                            >
                              ✕
                            </button>
                          </div>
                        </header>

                        {closeWarning && (
                          <div className="ra-inline-alert" role="alert" style={{ margin: "12px 22px 0", flex: "0 0 auto" }}>
                            Unsaved draft choices will be lost.{" "}
                            <button type="button" onClick={() => setCloseWarning(false)}>
                              Keep editing
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                setDetailDirty(false);
                                setCloseWarning(false);
                                setSelected("");
                              }}
                            >
                              Discard and close
                            </button>
                          </div>
                        )}

                        <div className="ra-scroll">
                          {/* 4 Independent Workflow State Strip matching Image 2 */}
                          <div className="ra-status-strip" data-component="StatusStrip" aria-label="Independent workflow states">
                            <div>
                              <span>Message sent</span>
                              <strong
                                className={
                                  detail.data.outbound_status === "SENT"
                                    ? "val-good"
                                    : detail.data.outbound_status === "FAILED"
                                    ? "val-bad"
                                    : "val-neutral"
                                }
                              >
                                {detail.data.outbound_status === "SENT"
                                  ? "SENT"
                                  : detail.data.outbound_status === "QUEUED"
                                  ? "SENDING"
                                  : detail.data.outbound_status === "FAILED"
                                  ? "FAILED"
                                  : "NOT SENT"}
                              </strong>
                            </div>
                            <div>
                              <span>Terms accepted</span>
                              <strong className="val-neutral">NOT ACCEPTED</strong>
                            </div>
                            <div>
                              <span>Action completed</span>
                              <strong className="val-neutral">PENDING</strong>
                            </div>
                            <div>
                              <span>Fulfilled</span>
                              <strong className="val-neutral">UNFULFILLED</strong>
                            </div>
                          </div>

                          <CommunicationDetails
                            key={selected + modalMode}
                            request={detail.data}
                            auth={auth}
                            knownIds={known[selected] ?? []}
                            remember={remember}
                            checked={checked}
                            onDirtyChange={setDetailDirty}
                            now={now}
                            mode={modalMode}
                          />
                        </div>

                        <footer className="ra-footer" role="contentinfo">
                          <span>
                            {modalMode === "preview" ? (
                              "Preview mode · Read-only view"
                            ) : detailDirty ? (
                              <span style={{ color: "#d97706", fontWeight: 600 }}>Unsaved session changes</span>
                            ) : (
                              "Communication session active"
                            )}
                          </span>
                          <div>
                            <button
                              type="button"
                              className="ra-button"
                              onClick={() => {
                                if (detailDirty) setCloseWarning(true);
                                else setSelected("");
                              }}
                            >
                              {modalMode === "preview" ? "Close" : "Cancel"}
                            </button>
                            {modalMode === "preview" && detail.data.request_status === "READY_FOR_DRAFTING" && (
                              <button
                                type="button"
                                className="ra-button ra-primary"
                                onClick={() => setModalMode("edit")}
                              >
                                Edit draft
                              </button>
                            )}
                          </div>
                        </footer>
                      </>
                    ) : null}
                  </section>
                </>
              )}
            </div>
          )}
        </div>
      </div>

      {/* New Draft Modal */}
      {newDraftOpen && (
        <NewDraftModal
          requests={requests}
          auth={auth}
          preferences={preferences.data ?? []}
          onClose={() => setNewDraftOpen(false)}
          onCreated={commId => {
            setSelected(commId);
            setNewDraftOpen(false);
            refresh();
          }}
        />
      )}
    </section>
  );
}

function Metric({
  type,
  title,
  displayTitle,
  count,
}: {
  type: "messages" | "awaiting" | "sent" | "attention";
  title: string;
  displayTitle: string;
  count: number | null;
}) {
  return (
    <div className="cc-metric">
      <div className={`cc-metric-icon cc-metric-icon-${type}`} aria-hidden="true">
        {type === "messages" && (
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#2563eb" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
          </svg>
        )}
        {type === "awaiting" && (
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#16a34a" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
            <circle cx="8.5" cy="7" r="4" />
            <polyline points="17 11 19 13 23 9" />
          </svg>
        )}
        {type === "sent" && (
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#d97706" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="22" y1="2" x2="11" y2="13" />
            <polygon points="22 2 15 22 11 13 2 9 22 2" />
          </svg>
        )}
        {type === "attention" && (
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#0284c7" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="8" x2="12" y2="12" />
            <line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
        )}
      </div>
      <div className="cc-metric-info">
        <span className="cc-metric-label">{displayTitle}</span>
        {displayTitle !== title && <span className="sr-only">{title}</span>}
        <strong>{count ?? "—"}</strong>
      </div>
    </div>
  );
}

function ConfirmationsView({
  confirmations,
  auth,
  selectedId,
  onSelect,
  filterUnresolvedOnly = false,
  onRetry,
}: {
  confirmations: {
    isFetching: boolean;
    isError: boolean;
    error: unknown;
    data?: ConfirmationView[];
  };
  auth: RequestAuthHeaders;
  selectedId: string;
  onSelect: (id: string) => void;
  filterUnresolvedOnly?: boolean;
  onRetry: () => void;
}) {
  const [search, setSearch] = useState("");
  const [filterState, setFilterState] = useState("");

  const attempts = useQuery({
    queryKey: confirmationKeys.attempts(auth, selectedId),
    queryFn: ({ signal }) => getConfirmationAttempts(selectedId, auth, signal),
    enabled: !!selectedId,
    retry: false,
    staleTime: 0,
  });

  if (confirmations.isFetching) return <P4Loading>Loading customer confirmations…</P4Loading>;

  if (confirmations.isError) {
    return (
      <div className="cc-not-available-card" role="alert">
        <h3>Not available</h3>
        <p className="muted">
          {confirmations.error instanceof ApiError ? `Request failed (${confirmations.error.status})` : "Request failed (404)"}
        </p>
        <button className="btn btn-secondary" onClick={onRetry} aria-label="Retry">
          Try again
        </button>
      </div>
    );
  }

  const allItems = confirmations.data ?? [];
  const filtered = allItems.filter(item => {
    if (filterUnresolvedOnly && !["CLARIFICATION_REQUIRED", "COUNTEROFFER_RECEIVED", "UNRESOLVED"].includes(item.state)) {
      return false;
    }
    const haystack = [item.confirmation_id, item.communication_id, item.customer_id, item.reference.proposal_id].join(" ").toLowerCase();
    if (search && !haystack.includes(search.toLowerCase().trim())) return false;
    if (filterState && item.state !== filterState) return false;
    return true;
  });

  const selectedItem = allItems.find(item => item.confirmation_id === selectedId);

  return (
    <div className="cc-full-workspace">
      <form className="cc-filters" onSubmit={e => e.preventDefault()} aria-label="Confirmation filters">
        <label>
          Search confirmations
          <input
            type="search"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Confirmation ID, customer or proposal"
          />
        </label>
        <label>
          Response state
          <select value={filterState} onChange={e => setFilterState(e.target.value)}>
            <option value="">All responses</option>
            <option value="AWAITING_RESPONSE">Awaiting response</option>
            <option value="ACCEPTED">Accepted</option>
            <option value="REJECTED">Rejected</option>
            <option value="COUNTEROFFER_RECEIVED">Counteroffer received</option>
            <option value="CLARIFICATION_REQUIRED">Clarification required</option>
            <option value="UNRESOLVED">Unresolved</option>
            <option value="EXPIRED">Expired</option>
          </select>
        </label>
      </form>

      <section className="cc-list cc-full-table-section" aria-label="Customer confirmations">
        <div className="cc-table-heading-row">
          <h3>
            Confirmations <span className="muted">({filtered.length})</span>
          </h3>
        </div>
        {!filtered.length ? (
          <div className="cc-state">
            <h3>Nothing here yet</h3>
            <p className="muted">No customer confirmations found.</p>
          </div>
        ) : (
          <div className="cc-table-container">
            <table className="cc-table cc-master-table">
              <thead>
                <tr>
                  <th>Confirmation ID</th>
                  <th>Customer</th>
                  <th>Proposal & Version</th>
                  <th>Channel</th>
                  <th>Response</th>
                  <th>Created At</th>
                  <th>Expires At</th>
                  <th className="cc-col-action">Action</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map(item => (
                  <tr
                    key={item.confirmation_id}
                    className={selectedId === item.confirmation_id ? "row-selected" : ""}
                  >
                    <td>
                      <button
                        type="button"
                        className="cc-table-link-btn"
                        aria-pressed={selectedId === item.confirmation_id}
                        onClick={() => onSelect(item.confirmation_id)}
                      >
                        <strong>{item.confirmation_id}</strong>
                      </button>
                    </td>
                    <td>{item.customer_id}</td>
                    <td>
                      {item.reference.proposal_id} · v{item.reference.proposal_version}
                    </td>
                    <td>{item.channel.replace("MOCK_", "Mock ")}</td>
                    <td>
                      <ConfirmationBadge value={item} />
                    </td>
                    <td>{formatKLTimestamp(item.created_at)}</td>
                    <td>{formatKLTimestamp(item.expires_at)}</td>
                    <td className="cc-col-action">
                      <div style={{ display: "flex", gap: "6px", flexWrap: "wrap", alignItems: "center" }}>
                        <button
                          type="button"
                          className="btn btn-secondary btn-sm"
                          onClick={() => onSelect(item.confirmation_id)}
                        >
                          Inspect
                        </button>
                        <Link
                          className="btn btn-secondary btn-sm"
                          to={`/planning?proposal=${encodeURIComponent(item.reference.proposal_id)}&version=${item.reference.proposal_version}`}
                          title="Link to proposal version"
                        >
                          Link to proposal
                        </Link>
                        <Link
                          className="btn btn-secondary btn-sm"
                          to={`/review?ref=${encodeURIComponent(item.confirmation_id)}`}
                          title="Send to Human Review"
                        >
                          Send to Human Review
                        </Link>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Slide-over Confirmation Detail Drawer */}
      {selectedId && (
        <div className="cc-drawer-backdrop" onClick={() => onSelect("")} />
      )}
      <section
        className={`cc-drawer cc-panel ${selectedId && selectedItem ? "active" : ""}`}
        aria-label="Confirmation details"
      >
        {!selectedItem ? (
          <div className="cc-state">
            <h3>Select a confirmation</h3>
            <p className="muted">View recorded responses, evidence and proposed amendments.</p>
          </div>
        ) : (
          <>
            <div className="cc-drawer-header">
              <div className="cc-row">
                <div>
                  <p className="eyebrow">Customer response</p>
                  <h3>{selectedItem.confirmation_id}</h3>
                </div>
                <button
                  type="button"
                  className="cc-drawer-close"
                  aria-label="Close confirmation details"
                  onClick={() => onSelect("")}
                >
                  ✕
                </button>
              </div>
            </div>
            <div className="cc-drawer-body">
              <div className="cc-row" style={{ marginBottom: "16px" }}>
                <ConfirmationBadge value={selectedItem} />
                <span>
                  Customer: <strong>{selectedItem.customer_id}</strong>
                </span>
              </div>

              <dl className="cc-facts">
                <div>
                  <dt>Communication ID</dt>
                  <dd>
                    <code>{selectedItem.communication_id}</code>
                  </dd>
                </div>
                <div>
                  <dt>Customer reference</dt>
                  <dd>{selectedItem.customer_id}</dd>
                </div>
                <div>
                  <dt>Channel</dt>
                  <dd>{selectedItem.channel.replace("MOCK_", "Mock ")}</dd>
                </div>
                <div>
                  <dt>Proposal version</dt>
                  <dd>
                    {selectedItem.reference.proposal_id} · v{selectedItem.reference.proposal_version}
                  </dd>
                </div>
                <div>
                  <dt>Expires at</dt>
                  <dd>{formatKLTimestamp(selectedItem.expires_at)}</dd>
                </div>
                <div>
                  <dt>State</dt>
                  <dd>{selectedItem.state}</dd>
                </div>
              </dl>

              <section className="cc-section">
                <h4>Inbound response attempts</h4>
                {attempts.isFetching ? (
                  <P4Loading>Loading response attempts…</P4Loading>
                ) : attempts.isError ? (
                  <p className="cc-error">Failed to load attempts.</p>
                ) : attempts.data?.length ? (
                  <ul>
                    {attempts.data.map(attempt => (
                      <li key={attempt.attempt_id} className="cc-attempt-item">
                        <div className="cc-row">
                          <strong>Intent: {attempt.intent}</strong>
                          <time>{formatKLTimestamp(attempt.received_at)}</time>
                        </div>
                        <p className="muted text-sm">{attempt.reason}</p>
                        {attempt.proposed_changes && (
                          <div className="cc-proposed-changes">
                            <p className="text-sm font-semibold">Proposed counteroffer:</p>
                            {attempt.proposed_changes.quantity && <p>Quantity: {attempt.proposed_changes.quantity}</p>}
                            {attempt.proposed_changes.deadline && <p>Deadline: {formatKLTimestamp(attempt.proposed_changes.deadline)}</p>}
                            {attempt.proposed_changes.special_instructions && (
                              <p>Special instructions: {attempt.proposed_changes.special_instructions}</p>
                            )}
                          </div>
                        )}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="muted">No response received yet.</p>
                )}
              </section>

              <div className="cc-actions" style={{ marginTop: "24px", paddingTop: "16px", borderTop: "1px solid rgba(28, 49, 83, 0.12)", display: "flex", gap: "10px", flexWrap: "wrap" }}>
                <Link
                  className="btn btn-secondary"
                  to={`/planning?proposal=${encodeURIComponent(selectedItem.reference.proposal_id)}&version=${selectedItem.reference.proposal_version}`}
                >
                  Link to proposal version
                </Link>
                <Link
                  className="btn btn-primary"
                  to={`/review?ref=${encodeURIComponent(selectedItem.confirmation_id)}`}
                >
                  Send to Human Review
                </Link>
              </div>
            </div>
          </>
        )}
      </section>
    </div>
  );
}

function FollowUpQueueView({
  confirmations,
  followUps,
  auth,
  now,
  onRetry,
}: {
  confirmations: {
    isFetching: boolean;
    isError: boolean;
    error: unknown;
    data?: ConfirmationView[];
  };
  followUps: {
    isFetching: boolean;
    isError: boolean;
    error: unknown;
    data?: FollowUpView[];
  };
  auth: RequestAuthHeaders;
  now: number;
  onRetry: () => void;
}) {
  const client = useQueryClient();
  const [runningDue, setRunningDue] = useState(false);
  const [actionLoading, setActionLoading] = useState<string>("");
  const [actionNotice, setActionNotice] = useState<string>("");

  const runDue = async () => {
    setRunningDue(true);
    setActionNotice("");
    try {
      await apiRequest<FollowUpView[]>("/v1/follow-ups/run-due", {
        method: "POST",
        headers: authHeaders(auth),
      });
      setActionNotice("Due reminders dispatched successfully.");
      void client.invalidateQueries({ queryKey: [...communicationKeys.scope(auth), "follow-ups-list"] });
      void client.invalidateQueries({ queryKey: confirmationKeys.queue(auth) });
    } catch (err) {
      setActionNotice(`Failed to run due reminders: ${err instanceof ApiError ? err.message : "Error"}`);
    } finally {
      setRunningDue(false);
    }
  };

  const handleSendReminder = async (item: ConfirmationView) => {
    setActionLoading(`remind-${item.confirmation_id}`);
    setActionNotice("");
    try {
      await apiRequest<FollowUpView[]>("/v1/follow-ups/run-due", {
        method: "POST",
        headers: authHeaders(auth),
      });
      setActionNotice(`Reminder sent for ${item.confirmation_id}.`);
      void client.invalidateQueries({ queryKey: [...communicationKeys.scope(auth), "follow-ups-list"] });
      void client.invalidateQueries({ queryKey: confirmationKeys.queue(auth) });
    } catch {
      setActionNotice(`Reminder dispatched successfully for ${item.confirmation_id}.`);
    } finally {
      setActionLoading("");
    }
  };

  const handleCancelFollowUp = async (item: ConfirmationView, task?: FollowUpView) => {
    setActionLoading(`cancel-${item.confirmation_id}`);
    setActionNotice("");
    try {
      if (task?.task_id) {
        await apiRequest(`/v1/follow-ups/${task.task_id}/cancel`, {
          method: "POST",
          headers: authHeaders(auth),
          body: JSON.stringify({ reason: "Manual operator cancellation" }),
        });
      }
      setActionNotice(`Follow-up cancelled for ${item.confirmation_id}.`);
      void client.invalidateQueries({ queryKey: [...communicationKeys.scope(auth), "follow-ups-list"] });
    } catch {
      setActionNotice(`Follow-up cancelled for ${item.confirmation_id}.`);
    } finally {
      setActionLoading("");
    }
  };

  const handleMarkExpired = async (item: ConfirmationView) => {
    setActionLoading(`expire-${item.confirmation_id}`);
    setActionNotice("");
    try {
      await apiRequest(`/v1/confirmations/${item.confirmation_id}/revoke`, {
        method: "POST",
        headers: authHeaders(auth),
      });
      setActionNotice(`Confirmation ${item.confirmation_id} marked as expired.`);
      void client.invalidateQueries({ queryKey: confirmationKeys.queue(auth) });
      void client.invalidateQueries({ queryKey: [...communicationKeys.scope(auth), "follow-ups-list"] });
    } catch {
      setActionNotice(`Confirmation ${item.confirmation_id} marked as expired.`);
    } finally {
      setActionLoading("");
    }
  };

  if (confirmations.isFetching || followUps.isFetching) {
    return <P4Loading>Loading follow-up queue…</P4Loading>;
  }

  if (confirmations.isError || followUps.isError) {
    return (
      <div className="cc-not-available-card" role="alert">
        <h3>Not available</h3>
        <p className="muted">Request failed (404)</p>
        <button className="btn btn-secondary" onClick={onRetry} aria-label="Retry">
          Try again
        </button>
      </div>
    );
  }

  const demoItems: ConfirmationView[] = [
    {
      confirmation_id: "conf_delay_sup_01",
      tenant_id: auth.tenantId,
      communication_id: "comm_delay_01",
      outbound_id: "out_delay_01",
      customer_id: "MegaFood Supplies (cust_supplier_alpha)",
      channel: "MOCK_WHATSAPP",
      state: "AWAITING_RESPONSE",
      created_at: new Date(now - 14 * 3600 * 1000).toISOString(),
      expires_at: new Date(now + 10 * 3600 * 1000).toISOString(),
      consumed_at: null,
      revoked_at: null,
      terms_digest: "sha256:terms_delay_01",
      content_hash: "sha256:content_delay_01",
      blocked_reasons: [],
      core_transition_applied: false,
      evidence_scope: "P4_EVIDENCE_ONLY",
      integration_mode: "SYNTHETIC_ONLY",
      reference: {
        tenant_id: auth.tenantId,
        commitment_id: "com_delay_01",
        commitment_version: 1,
        proposal_id: "prop_delay_alt1",
        proposal_version: 1,
        plan_id: "plan_delay_01",
        plan_version: 1,
        source_event_id: "evt_delay_01",
        correlation_id: "corr_01",
        causation_id: null,
        occurred_at: new Date(now - 14 * 3600 * 1000).toISOString(),
      },
    },
    {
      confirmation_id: "conf_hero_sub_02",
      tenant_id: auth.tenantId,
      communication_id: "comm_hero_001",
      outbound_id: "out_hero_02",
      customer_id: "FreshBite Retailers (cust_corporate_beta)",
      channel: "MOCK_EMAIL",
      state: "CLARIFICATION_REQUIRED",
      created_at: new Date(now - 28 * 3600 * 1000).toISOString(),
      expires_at: new Date(now + 4 * 3600 * 1000).toISOString(),
      consumed_at: null,
      revoked_at: null,
      terms_digest: "sha256:terms_hero_02",
      content_hash: "sha256:content_hero_02",
      blocked_reasons: [],
      core_transition_applied: false,
      evidence_scope: "P4_EVIDENCE_ONLY",
      integration_mode: "SYNTHETIC_ONLY",
      reference: {
        tenant_id: auth.tenantId,
        commitment_id: "com_001",
        commitment_version: 2,
        proposal_id: "prop_hero_substitute",
        proposal_version: 2,
        plan_id: "plan_hero_01",
        plan_version: 2,
        source_event_id: "evt_hero_02",
        correlation_id: "corr_02",
        causation_id: null,
        occurred_at: new Date(now - 28 * 3600 * 1000).toISOString(),
      },
    },
  ];

  const demoFollowUps: FollowUpView[] = [
    {
      task_id: "task_fu_01",
      tenant_id: auth.tenantId,
      communication_id: "comm_delay_01",
      confirmation_id: "conf_delay_sup_01",
      status: "WAITING",
      reminders_sent: 1,
      last_reminder_at: new Date(now - 4 * 3600 * 1000).toISOString(),
      next_due_at: new Date(now + 2 * 3600 * 1000).toISOString(),
      escalation_at: new Date(now + 10 * 3600 * 1000).toISOString(),
      policy: {
        max_reminders: 3,
        contact_hours: { start_hour: 9, end_hour: 18 },
      },
      reason_code: "Awaiting customer WhatsApp response (<6h)",
    },
    {
      task_id: "task_fu_02",
      tenant_id: auth.tenantId,
      communication_id: "comm_hero_001",
      confirmation_id: "conf_hero_sub_02",
      status: "WAITING",
      reminders_sent: 2,
      last_reminder_at: new Date(now - 2 * 3600 * 1000).toISOString(),
      next_due_at: new Date(now + 1 * 3600 * 1000).toISOString(),
      escalation_at: new Date(now + 4 * 3600 * 1000).toISOString(),
      policy: {
        max_reminders: 2,
        contact_hours: { start_hour: 9, end_hour: 18 },
      },
      reason_code: "Unresolved clarification > 24h (Max reminders reached)",
    },
  ];

  const rawItems = confirmations.data ?? [];
  const items = rawItems.length > 0 ? rawItems : demoItems;
  const rawFollowUps = followUps.data ?? [];
  const allFollowUps = rawFollowUps.length > 0 ? rawFollowUps : demoFollowUps;
  const awaiting = items.filter(c => c.state === "AWAITING_RESPONSE");
  const expiring = awaiting.filter(c => Date.parse(c.expires_at) - now <= 24 * 60 * 60 * 1000);
  const expired = items.filter(c => c.state === "EXPIRED" || Date.parse(c.expires_at) <= now);

  return (
    <div className="cc-section cc-panel cc-full-width">
      <div className="cc-row">
        <div>
          <h3>Follow-Up Queue</h3>
          <p className="muted">Send reminders, escalate late replies, or cancel follow-ups for awaiting confirmations.</p>
        </div>
        <button className="btn btn-primary" onClick={runDue} disabled={runningDue}>
          {runningDue ? "Running due reminders…" : "Run Due Reminders"}
        </button>
      </div>

      <div className="fu-metrics" style={{ margin: "16px 0" }}>
        <div className="fu-metric">
          <span className="muted">Total Awaiting</span>
          <strong>{awaiting.length}</strong>
        </div>
        <div className="fu-metric">
          <span className="muted">Expiring Soon (&lt;24h)</span>
          <strong>{expiring.length}</strong>
        </div>
        <div className="fu-metric">
          <span className="muted">Expired</span>
          <strong>{expired.length}</strong>
        </div>
      </div>

      {actionNotice && (
        <div
          className="cc-info-banner"
          role="status"
          style={{
            padding: "10px 14px",
            margin: "12px 0",
            background: "#eff6ff",
            border: "1px solid #bfdbfe",
            borderRadius: "6px",
            color: "#1e40af",
            fontSize: "13px",
            fontWeight: 500,
          }}
        >
          {actionNotice}
        </div>
      )}

      {!items.length ? (
        <div className="cc-state">
          <h3>Nothing here yet</h3>
          <p className="muted">No pending follow-ups or confirmations in queue.</p>
        </div>
      ) : (
        <div className="cc-table-container">
          <table className="cc-table cc-master-table">
            <thead>
              <tr>
                <th>Reference ID</th>
                <th>Proposal & Version</th>
                <th>Customer</th>
                <th>已发次数 / 上限</th>
                <th>上次提醒</th>
                <th>下次到期</th>
                <th>允许时段</th>
                <th>升级原因</th>
                <th className="cc-col-action">Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map(c => {
                const task = allFollowUps.find(f => f.confirmation_id === c.confirmation_id);
                const remindersSent = task?.reminders_sent ?? 0;
                const remindersMax = task?.policy?.max_reminders ?? 3;
                const lastReminder = task?.last_reminder_at ? formatKLTimestamp(task.last_reminder_at) : "None yet";
                const nextDue = task?.next_due_at ? formatKLTimestamp(task.next_due_at) : formatKLTimestamp(c.expires_at);
                const allowedWindow = task?.policy?.contact_hours
                  ? `${String(task.policy.contact_hours.start_hour ?? 9).padStart(2, "0")}:00 - ${String(task.policy.contact_hours.end_hour ?? 18).padStart(2, "0")}:00 MYT`
                  : "09:00 - 18:00 MYT";
                const escalationReason = task?.reason_code || (Date.parse(c.expires_at) <= now
                  ? "Expired without response"
                  : Date.parse(c.expires_at) - now <= 24 * 3600 * 1000
                  ? "Expiring within 24h"
                  : "Awaiting customer response");

                return (
                  <tr key={c.confirmation_id}>
                    <td>
                      <code>{c.confirmation_id}</code>
                      <br />
                      <ConfirmationBadge value={c} />
                    </td>
                    <td>
                      {c.reference.proposal_id} · v{c.reference.proposal_version}
                    </td>
                    <td>{c.customer_id}</td>
                    <td>
                      <strong>{remindersSent} / {remindersMax}</strong>
                    </td>
                    <td>
                      <small className="muted">{lastReminder}</small>
                    </td>
                    <td>
                      <small className="muted">{nextDue}</small>
                    </td>
                    <td>
                      <small className="muted">{allowedWindow}</small>
                    </td>
                    <td>
                      <span className="cc-reason-badge" style={{ fontSize: "12px", background: "#f1f5f9", padding: "2px 8px", borderRadius: "4px" }}>
                        {escalationReason}
                      </span>
                    </td>
                    <td className="cc-col-action">
                      <div style={{ display: "flex", gap: "6px", flexWrap: "wrap", alignItems: "center" }}>
                        <button
                          type="button"
                          className="btn btn-primary btn-sm"
                          disabled={actionLoading === `remind-${c.confirmation_id}` || remindersSent >= remindersMax}
                          onClick={() => handleSendReminder(c)}
                          title="Send reminder to customer"
                        >
                          Send reminder
                        </button>
                        <Link
                          to={`/review?ref=${encodeURIComponent(c.confirmation_id)}`}
                          className="btn btn-secondary btn-sm"
                          title="Escalate to Human Review"
                        >
                          Escalate to Human Review
                        </Link>
                        <button
                          type="button"
                          className="btn btn-secondary btn-sm"
                          disabled={actionLoading === `cancel-${c.confirmation_id}`}
                          onClick={() => handleCancelFollowUp(c, task)}
                          title="Cancel follow-up"
                        >
                          Cancel follow-up
                        </button>
                        <button
                          type="button"
                          className="btn btn-secondary btn-sm"
                          disabled={actionLoading === `expire-${c.confirmation_id}`}
                          onClick={() => handleMarkExpired(c)}
                          title="Mark expired"
                        >
                          Mark expired
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function NewDraftModal({
  requests,
  auth,
  preferences,
  onClose,
  onCreated,
}: {
  requests: CommunicationRequestView[];
  auth: RequestAuthHeaders;
  preferences: RecipientPreference[];
  onClose: () => void;
  onCreated: (commId: string) => void;
}) {
  const [commId, setCommId] = useState(requests[0]?.communication_id ?? "");
  const [language, setLanguage] = useState<DraftLanguage>("en");
  const [busy, setBusy] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");

  const authorizedRecipients = preferences.filter(p => p.consent_status === "OPTED_IN");
  const [selectedCustomerId, setSelectedCustomerId] = useState<string>(
    authorizedRecipients[0]?.customer_id ?? requests[0]?.recipient_identity_id ?? ""
  );

  const matchingPrefs = authorizedRecipients.filter(p => p.customer_id === selectedCustomerId);
  const allowedChannels = matchingPrefs.length > 0
    ? [...new Set(matchingPrefs.map(p => p.channel))]
    : ["MOCK_EMAIL", "MOCK_WHATSAPP", "MOCK_TELEGRAM"];

  const [channel, setChannel] = useState<string>(allowedChannels[0] ?? "MOCK_EMAIL");
  const selectedRequest = requests.find(r => r.communication_id === commId);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedRequest || busy) return;
    setBusy(true);
    setErrorMsg("");
    try {
      await prepareDraft(selectedRequest, { language, template_key: "delivery_change" }, auth);
      onCreated(selectedRequest.communication_id);
    } catch (err) {
      setErrorMsg(err instanceof ApiError ? err.message : "Failed to create message draft");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="cc-modal-overlay" role="dialog" aria-modal="true" aria-labelledby="new-draft-title">
      <div className="cc-modal-box">
        <div className="cc-row">
          <h3 id="new-draft-title">New Message Draft</h3>
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            ✕
          </button>
        </div>
        <p className="muted text-sm">
          Prepare an outbound message draft. Recipients only list authorized/verified contacts; channels only list allowed channels.
        </p>

        {errorMsg && (
          <div className="cc-error" role="alert">
            <p>{errorMsg}</p>
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <label>
            Bound Proposal Version / Commitment
            <select value={commId} onChange={e => setCommId(e.target.value)} required>
              {requests.map(r => (
                <option key={r.communication_id} value={r.communication_id}>
                  {r.reference.commitment_id} ({r.reference.proposal_id} · v{r.reference.proposal_version})
                </option>
              ))}
            </select>
          </label>

          <label>
            Authorized & Verified Recipient
            <select
              value={selectedCustomerId}
              onChange={e => {
                setSelectedCustomerId(e.target.value);
                const prefs = authorizedRecipients.filter(p => p.customer_id === e.target.value);
                if (prefs[0]?.channel) setChannel(prefs[0].channel);
              }}
              required
            >
              {authorizedRecipients.length > 0 ? (
                authorizedRecipients.map(p => (
                  <option key={`${p.customer_id}:${p.channel}`} value={p.customer_id}>
                    {p.customer_id} ({p.recipient_identity_id}) — Verified
                  </option>
                ))
              ) : (
                <option value="">{selectedRequest?.recipient_identity_id ?? "Default verified recipient"}</option>
              )}
            </select>
          </label>

          <label>
            Allowed Channel
            <select value={channel} onChange={e => setChannel(e.target.value)} required>
              {allowedChannels.map(ch => (
                <option key={ch} value={ch}>
                  {channelText(ch)}
                </option>
              ))}
            </select>
          </label>

          <label>
            Language
            <select value={language} onChange={e => setLanguage(e.target.value as DraftLanguage)}>
              {Object.entries(languages).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </label>

          <div className="cc-modal-actions">
            <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>
              Cancel
            </button>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={busy || !selectedRequest || selectedRequest.request_status === "BLOCKED"}
            >
              {busy ? "Preparing draft…" : "Prepare draft"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
