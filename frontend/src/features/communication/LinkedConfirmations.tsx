import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import type { RequestAuthHeaders } from "../../shared/api";
import { confirmationKeys, listConfirmations } from "./confirmationApi";
import { ConfirmationBadge, ConfirmationError } from "./confirmationPresentation";

export function LinkedConfirmations({ communicationId, auth }: { communicationId: string; auth: RequestAuthHeaders }) {
  const query = useQuery({ queryKey: confirmationKeys.list(auth, communicationId),
    queryFn: ({ signal }) => listConfirmations(communicationId, auth, signal), retry: false,
    staleTime: 0, refetchOnMount: "always", refetchOnWindowFocus: true });
  return <section className="cc-section" aria-label="Linked confirmations">
    <div className="cc-row"><h4>Customer confirmations</h4>
      <button className="btn btn-secondary" disabled={query.isFetching} onClick={() => { void query.refetch(); }}>Refresh confirmations</button></div>
    <p className="muted text-sm">Each record applies only to its displayed proposal version. Message delivery does not establish acceptance.</p>
    {query.isFetching ? <p role="status">Loading linked confirmations…</p> : query.isError ?
      <ConfirmationError error={query.error} retry={() => { void query.refetch(); }} /> : query.data?.length ?
      <ul className="cw-linked-list">{query.data.map(value => <li key={value.confirmation_id}>
        <Link to={`/confirmations/${encodeURIComponent(value.confirmation_id)}`}>Open confirmation {value.confirmation_id}</Link>
        <p className="muted text-sm">{value.reference.proposal_id} · v{value.reference.proposal_version}</p>
        <ConfirmationBadge value={value} />
      </li>)}</ul> : <p className="muted">No linked confirmations. A sent message alone does not create customer acceptance.</p>}
  </section>;
}
