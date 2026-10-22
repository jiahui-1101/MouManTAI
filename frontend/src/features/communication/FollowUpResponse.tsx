import { useQuery } from "@tanstack/react-query";
import type { RequestAuthHeaders } from "../../shared/api";
import { formatKLTimestamp } from "../../shared/date";
import { confirmationKeys, getConfirmationAttempts } from "./confirmationApi";
import { ConfirmationError, responseLabels } from "./confirmationPresentation";

// Mounted only for the item deliberately opened by the user. Not an N+1 list fetch.
export function FollowUpResponse({ id, auth, proposalId, proposalVersion }: {
  id: string; auth: RequestAuthHeaders; proposalId: string; proposalVersion: number;
}) {
  const query = useQuery({ queryKey: confirmationKeys.attempts(auth, id),
    queryFn: ({ signal }) => getConfirmationAttempts(id, auth, signal), retry: false,
    staleTime: 0, refetchOnMount: "always", refetchOnWindowFocus: true });
  const values = query.isSuccess && !query.isFetching ? query.data : [];
  const latest = values.reduce((time, value) => Math.max(time, Date.parse(value.received_at)), -Infinity);
  return <section className="fu-response" aria-label={`Latest response for ${id}`}>
    <h4>Latest customer response</h4>
    {query.isFetching || query.isPending ? <p role="status">Loading response evidence…</p> : query.isError ?
      <ConfirmationError error={query.error} retry={() => { void query.refetch(); }} /> : !values.length ?
      <p className="muted">No response attempts recorded.</p> : <>
        <p className="muted text-sm">Latest timestamp returned, bound to {proposalId} · v{proposalVersion}. Current identity verification is unavailable in this read API.</p>
        {values.filter(value => Date.parse(value.received_at) === latest).map(value => <article key={value.attempt_id}>
          <strong>{responseLabels[value.intent]}</strong> · <time dateTime={value.received_at}>{formatKLTimestamp(value.received_at)}</time>
          <p className="muted text-sm">Attempt: <code>{value.attempt_id}</code> · Reason: <code>{value.reason}</code></p>
          <ul>{value.evidence_refs.map((ref, index) => <li key={`${index}:${ref}`}><code>{ref}</code></li>)}</ul>
        </article>)}
      </>}
    <p className="muted text-sm">Open View Confirmation for the full persisted response history. No reminder or escalation has been executed by this queue.</p>
  </section>;
}
