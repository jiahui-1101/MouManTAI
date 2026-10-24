import { useCallback, useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useAuth } from "../../shared/auth";
import { ApiError, apiRequest, authHeaders, type RequestAuthHeaders } from "../../shared/api";
import { formatKLTimestamp } from "../../shared/date";
import { communicationKeys, getCommunication, getCommunicationSummary, listCommunications, prepareDraft } from "./api";
import {
  communicationLabel,
  channelText,
  DisplayBadge,
  ErrorNotice,
  errorText,
  OriginBadge,
  DeliveryModeBadge,
  reasonText,
  languages,
} from "./presentation";
import { CommunicationDetails } from "./CommunicationDetails";
import { RecipientPreferences, type RuntimeCapabilities, type RecipientPreference } from "./RecipientPreferences";
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
  commitment_id: string;
  proposal_id: string;
  proposal_version: number;
  status: "WAITING" | "BLOCKED" | "DISPATCHING" | "CANCELLED" | "ESCALATED";
  reminders_sent: number;
  next_due_at: string | null;
  escalation_at: string;
  last_reminder_at: string | null;
  policy: { max_reminders: number; response_sla_seconds: number };
}

function CommunicationSession({ auth }: { auth: RequestAuthHeaders }) {
  const client = useQueryClient();
  const [activeNav, setActiveNav] = useState<NavSection>("needs_action");
  const [actionFilter, setActionFilter] = useState<ActionPill>("all");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [channel, setChannel] = useState("");
  const [selected, setSelected] = useState("");
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

  // 4. Runtime Capabilities
  const capabilities = useQuery({
    queryKey: [...communicationKeys.scope(auth), "runtime-capabilities"],
    queryFn: async ({ signal }) => {
      const res = await apiRequest<RuntimeCapabilities>(`${base}/runtime-capabilities`, {
        headers: authHeaders(auth),
        signal,
      });
      return res;
    },
    retry: false,
    staleTime: 0,
  });

  // 5. Confirmations list (Track -> Customer Confirmations & review replies)
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
    void client.invalidateQueries({ queryKey: communicationKeys.scope(auth) });
    void client.invalidateQueries({ queryKey: confirmationKeys.scope(auth) });
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
  const followUpsCount = (followUps.data?.length ?? 0) + needsActionFollowUpCount;
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

      {/* 2. Capability Status Banner */}
      {capabilities.isError ? (
        <div className="cc-capability-banner" role="note">
          <div className="cc-capability-banner-content">
            <strong>Capability status not available</strong>
            <p>
              Request failed ({capabilities.error instanceof ApiError ? capabilities.error.status : 404}). Actions stay disabled until it loads.
            </p>
          </div>
        </div>
      ) : capabilities.data && (capabilities.data.mode !== "SYNTHETIC" || (capabilities.data.blockers && capabilities.data.blockers.length > 0)) ? (
        <div className="cc-capability-banner" role="note">
          <div className="cc-capability-banner-content">
            <strong>Capability status restricted</strong>
            <p>{capabilities.data.label || "Production authority unavailable — actions remain blocked"}</p>
            {capabilities.data.blockers && capabilities.data.blockers.length > 0 && (
              <details className="p4-helper">
                <summary>Blocked authority reasons</summary>
                <ul>
                  {capabilities.data.blockers.map(code => (
                    <li key={code}>{reasonText(code)}</li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        </div>
      ) : null}

      {/* 3. 4 KPI Cards */}
      <section aria-label="Dashboard statistics">
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
          <>
            <p className="muted text-sm">All requests in this workspace · Checked {formatKLTimestamp(summary.data.checked_at)}</p>
            {summary.data.drafted === null && (
              <p className="muted text-sm">Drafted — Not available: current drafts could not be reliably verified.</p>
            )}
            {summary.data.sent === null && (
              <p className="muted text-sm">Sent — Not available: verified sending records are not connected.</p>
            )}
            {summary.data.unavailable_reasons.needs_attention && (
              <p className="muted text-sm">Needs Attention — Not available: sending failures could not be reliably counted.</p>
            )}
          </>
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
                <label>
                  Search references
                  <input
                    type="search"
                    value={search}
                    onChange={event => setSearch(event.target.value)}
                    placeholder="Commitment, communication or proposal"
                  />
                </label>
                <label>
                  Status
                  <select value={status} onChange={event => setStatus(event.target.value)}>
                    <option value="">All statuses</option>
                    {["Pending", "Drafted", "Sent", "Blocked"].map(value => (
                      <option key={value}>{value}</option>
                    ))}
                  </select>
                </label>
                <label>
                  Channel
                  <select value={channel} onChange={event => setChannel(event.target.value)}>
                    <option value="">All channels</option>
                    {[...new Set(requests.map(r => r.channel ?? "UNKNOWN"))].map(value => (
                      <option key={value} value={value}>
                        {channelText(value)}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  className="btn btn-ghost"
                  type="button"
                  onClick={() => {
                    setSearch("");
                    setStatus("");
                    setChannel("");
                  }}
                >
                  Clear filters
                </button>
              </form>
              <p className="muted text-sm cc-filter-note">Search and filters apply to the {requests.length} loaded requests.</p>

              <section className="cc-list cc-full-table-section" aria-label="Communication requests">
                <div className="cc-table-heading-row">
                  <h3>
                    Requests <span className="muted">({visible.length})</span>
                  </h3>
                </div>
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
                  <div className="cc-table-container">
                    <table className="cc-table cc-master-table">
                      <thead>
                        <tr>
                          <th>Commitment</th>
                          <th>Communication ID</th>
                          <th>Proposal & Version</th>
                          <th>Case & Mode</th>
                          <th>Status</th>
                          <th>Channel</th>
                          <th>Created</th>
                          <th>Action</th>
                        </tr>
                      </thead>
                      <tbody>
                        {visible.map(request => (
                          <tr
                            key={request.communication_id}
                            className={selected === request.communication_id ? "row-selected" : ""}
                          >
                            <td>
                              <button
                                type="button"
                                className="cc-table-link-btn"
                                aria-pressed={selected === request.communication_id}
                                onClick={() => selectRequest(request.communication_id)}
                              >
                                <strong>{request.reference.commitment_id}</strong>
                              </button>
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
                              <DisplayBadge label={label(request)} />
                            </td>
                            <td>{channelText(request.channel)}</td>
                            <td>
                              <time>{formatKLTimestamp(request.created_at)}</time>
                            </td>
                            <td>
                              <button
                                type="button"
                                className="btn btn-secondary btn-sm"
                                onClick={() => selectRequest(request.communication_id)}
                              >
                                Inspect
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>

              {/* Detail Drawer: slides in from right when selected; hidden offscreen when unselected */}
              {selected && (
                <div className="cc-drawer-backdrop" onClick={() => setSelected("")} />
              )}
              <section
                className={`cc-drawer cc-panel ${selected ? "active" : ""}`}
                aria-label="Communication details"
              >
                {!selected ? (
                  <div className="cc-state">
                    <h3>Select a request</h3>
                    <p className="muted">Review its proposal and prepare a draft.</p>
                  </div>
                ) : detail.isFetching ? (
                  <P4Loading>Loading communication details…</P4Loading>
                ) : detail.isError ? (
                  <ErrorNotice
                    error={detail.error}
                    resource="detail"
                    onRetry={() => {
                      void detail.refetch();
                    }}
                  />
                ) : detail.data ? (
                  <>
                    <div className="cc-drawer-header">
                      <div className="cc-row">
                        <div>
                          <p className="eyebrow">Request details</p>
                          <h3>{detail.data.reference.commitment_id}</h3>
                        </div>
                        <button
                          type="button"
                          className="cc-drawer-close"
                          aria-label="Close details"
                          onClick={() => setSelected("")}
                        >
                          ✕
                        </button>
                      </div>
                    </div>
                    <div className="cc-drawer-body">
                      {/* 4 Independent State Cards: Never Merged */}
                      <div className="cc-four-states-grid" aria-label="Independent workflow states">
                        <div className="cc-state-box">
                          <div className="cc-state-box-label">Message sent</div>
                          <div
                            className={`cc-state-box-value ${
                              detail.data.outbound_status === "SENT"
                                ? "val-good"
                                : detail.data.outbound_status === "FAILED"
                                ? "val-bad"
                                : "val-neutral"
                            }`}
                          >
                            {detail.data.outbound_status === "SENT"
                              ? "SENT"
                              : detail.data.outbound_status === "QUEUED"
                              ? "SENDING"
                              : detail.data.outbound_status === "FAILED"
                              ? "FAILED"
                              : "NOT SENT"}
                          </div>
                        </div>
                        <div className="cc-state-box">
                          <div className="cc-state-box-label">Terms accepted</div>
                          <div className="cc-state-box-value val-neutral">NOT ACCEPTED</div>
                        </div>
                        <div className="cc-state-box">
                          <div className="cc-state-box-label">Action completed</div>
                          <div className="cc-state-box-value val-neutral">PENDING</div>
                        </div>
                        <div className="cc-state-box">
                          <div className="cc-state-box-label">Fulfilled</div>
                          <div className="cc-state-box-value val-neutral">UNFULFILLED</div>
                        </div>
                      </div>

                      <CommunicationDetails
                        key={selected}
                        request={detail.data}
                        auth={auth}
                        knownIds={known[selected] ?? []}
                        remember={remember}
                        checked={checked}
                        onDirtyChange={setDetailDirty}
                        now={now}
                      />
                    </div>
                  </>
                ) : null}
              </section>
            </div>
          )}
        </div>
      </div>

      {/* New Draft Modal */}
      {newDraftOpen && (
        <NewDraftModal
          requests={requests}
          auth={auth}
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
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#2563eb" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="2" y="4" width="20" height="16" rx="2" />
            <path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7" />
          </svg>
        )}
        {type === "awaiting" && (
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#d97706" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M5 22h14" />
            <path d="M5 2h14" />
            <path d="M17 22v-4.172a2 2 0 0 0-.586-1.414L12 12l-4.414 4.414A2 2 0 0 0 7 17.828V22" />
            <path d="M7 2v4.172a2 2 0 0 0 .586 1.414L12 12l4.414-4.414A2 2 0 0 0 17 6.172V2" />
          </svg>
        )}
        {type === "sent" && (
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#0284c7" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="20 6 9 17 4 12" />
          </svg>
        )}
        {type === "attention" && (
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#0284c7" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="12" y1="8" x2="12" y2="12" />
            <line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
        )}
      </div>
      <div className="cc-metric-info">
        <span className="muted">{displayTitle}</span>
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
                  <th>Action</th>
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
                    <td>
                      <button
                        type="button"
                        className="btn btn-secondary btn-sm"
                        onClick={() => onSelect(item.confirmation_id)}
                      >
                        Inspect
                      </button>
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

  const runDue = async () => {
    setRunningDue(true);
    try {
      await apiRequest<FollowUpView[]>("/v1/follow-ups/run-due", {
        method: "POST",
        headers: authHeaders(auth),
      });
      void client.invalidateQueries({ queryKey: [...communicationKeys.scope(auth), "follow-ups-list"] });
    } finally {
      setRunningDue(false);
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

  const items = confirmations.data ?? [];
  const awaiting = items.filter(c => c.state === "AWAITING_RESPONSE");
  const expiring = awaiting.filter(c => Date.parse(c.expires_at) - now <= 24 * 60 * 60 * 1000);
  const expired = items.filter(c => c.state === "EXPIRED" || Date.parse(c.expires_at) <= now);

  return (
    <div className="cc-section cc-panel cc-full-width">
      <div className="cc-row">
        <div>
          <h3>Follow-Up Queue</h3>
          <p className="muted">Send reminders and escalate late replies for awaiting confirmations.</p>
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
                <th>Confirmation ID</th>
                <th>Customer</th>
                <th>Proposal Version</th>
                <th>State</th>
                <th>Expires At</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {items.map(c => (
                <tr key={c.confirmation_id}>
                  <td>
                    <code>{c.confirmation_id}</code>
                  </td>
                  <td>{c.customer_id}</td>
                  <td>
                    {c.reference.proposal_id} · v{c.reference.proposal_version}
                  </td>
                  <td>
                    <ConfirmationBadge value={c} />
                  </td>
                  <td>{formatKLTimestamp(c.expires_at)}</td>
                  <td>
                    <Link className="btn btn-secondary btn-sm" to={`/confirmations/${encodeURIComponent(c.confirmation_id)}`}>
                      Inspect
                    </Link>
                  </td>
                </tr>
              ))}
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
  onClose,
  onCreated,
}: {
  requests: CommunicationRequestView[];
  auth: RequestAuthHeaders;
  onClose: () => void;
  onCreated: (commId: string) => void;
}) {
  const [commId, setCommId] = useState(requests[0]?.communication_id ?? "");
  const [language, setLanguage] = useState<DraftLanguage>("en");
  const [busy, setBusy] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");

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
          Prepare an outbound message draft bound to an approved recovery proposal version.
        </p>

        {errorMsg && (
          <div className="cc-error" role="alert">
            <p>{errorMsg}</p>
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <label>
            Proposal reference / Communication
            <select value={commId} onChange={e => setCommId(e.target.value)} required>
              {requests.map(r => (
                <option key={r.communication_id} value={r.communication_id}>
                  {r.reference.commitment_id} ({r.reference.proposal_id} · v{r.reference.proposal_version})
                </option>
              ))}
            </select>
          </label>

          <label>
            Recipient Contact
            <input
              type="text"
              value={selectedRequest?.recipient_identity_id ?? "Verified recipient required"}
              readOnly
              disabled
            />
          </label>

          <label>
            Channel
            <input
              type="text"
              value={selectedRequest?.channel ? channelText(selectedRequest.channel) : "No channel assigned"}
              readOnly
              disabled
            />
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
