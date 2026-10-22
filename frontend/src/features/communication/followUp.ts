import type { ConfirmationView } from "./confirmationTypes";

// Display categories only. Never sent to the API or stored as lifecycle states.
export const attentionLabels = {
  awaiting: "Awaiting Response",
  expiring: "Expiring Soon",
  expired: "Expired — Needs Review",
  clarification: "Clarification Required",
  unresolved: "Unresolved — Needs Review",
  manual: "Revoked / Stale — Manual Review",
  terminal: "Terminal — No Pending Follow-Up",
  unknown: "Needs Review / Unknown",
} as const;
export type AttentionCategory = keyof typeof attentionLabels;
export const EXPIRING_WINDOW_MS = 24 * 60 * 60 * 1000;
const terminal = new Set(["ACCEPTED", "REJECTED", "COUNTEROFFER_RECEIVED"]);
const supported = new Set(["AWAITING_RESPONSE", ...terminal, "EXPIRED", "SUPERSEDED", "CLARIFICATION_REQUIRED", "UNRESOLVED"]);

export function classifyFollowUp(value: ConfirmationView, now: number): AttentionCategory {
  if (!supported.has(value.state) || !Number.isFinite(now) || !Number.isFinite(Date.parse(value.expires_at)) ||
    !Array.isArray(value.blocked_reasons) || value.blocked_reasons.some(code => typeof code !== "string") ||
    (value.revoked_at !== null && (typeof value.revoked_at !== "string" || !Number.isFinite(Date.parse(value.revoked_at)))) ||
    (value.consumed_at !== null && (typeof value.consumed_at !== "string" || !Number.isFinite(Date.parse(value.consumed_at))))) return "unknown";
  if (value.revoked_at !== null || value.state === "SUPERSEDED" ||
    value.blocked_reasons.some(code => /REVOKED|STALE|SUPERSEDED|PROPOSAL_CHANGED/.test(code))) return "manual";
  // A restriction we cannot interpret is never a clean/no-follow-up result.
  if (value.blocked_reasons.some(code => code !== "CONFIRMATION_EXPIRED")) return "unknown";
  if (terminal.has(value.state)) {
    return value.consumed_at !== null && !value.blocked_reasons.length ? "terminal" : "unknown";
  }
  if (value.state === "EXPIRED" || value.blocked_reasons.includes("CONFIRMATION_EXPIRED") || Date.parse(value.expires_at) <= now) return "expired";
  if (value.state === "CLARIFICATION_REQUIRED") return "clarification";
  if (value.state === "UNRESOLVED") return "unresolved";
  if (value.state === "AWAITING_RESPONSE") return Date.parse(value.expires_at) - now <= EXPIRING_WINDOW_MS ? "expiring" : "awaiting";
  return "unknown";
}

export type QueueSort = "expiry" | "created" | "proposal";
export interface QueueFilters { search: string; state: string; attention: string; sort: QueueSort; direction: "asc" | "desc" }
export const defaultQueueFilters: QueueFilters = { search: "", state: "", attention: "", sort: "expiry", direction: "asc" };
export function visibleFollowUps(values: readonly ConfirmationView[], filters: QueueFilters, now: number) {
  const search = filters.search.trim().toLowerCase();
  return values.filter(value => (!search || [value.confirmation_id, value.communication_id].some(id => id.toLowerCase().includes(search))) &&
    (!filters.state || value.state === filters.state) && (!filters.attention || classifyFollowUp(value, now) === filters.attention))
    .sort((left, right) => {
      const field = (value: ConfirmationView) => filters.sort === "proposal" ? value.reference.proposal_version :
        Date.parse(filters.sort === "created" ? value.created_at : value.expires_at);
      const a = field(left), b = field(right);
      if (!Number.isFinite(a)) return Number.isFinite(b) ? 1 : left.confirmation_id.localeCompare(right.confirmation_id);
      if (!Number.isFinite(b)) return -1;
      return (a - b) * (filters.direction === "asc" ? 1 : -1) || left.confirmation_id.localeCompare(right.confirmation_id);
    });
}
export function followUpCounts(values: readonly ConfirmationView[], now: number) {
  const categories = values.map(value => classifyFollowUp(value, now));
  return { total: values.length, awaiting: values.filter(value => value.state === "AWAITING_RESPONSE").length,
    attention: categories.filter(category => category !== "awaiting" && category !== "terminal").length,
    expiring: categories.filter(category => category === "expiring").length,
    terminal: categories.filter(category => category === "terminal").length };
}
