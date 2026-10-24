import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { RequestAuthHeaders } from "../../shared/api";
import { formatKLTimestamp } from "../../shared/date";
import { communicationKeys, getOutboundHistory, getSendEligibility, sendMessage } from "./api";
import { errorText } from "./presentation";
import type { MessageDraftView } from "./types";
import { ApiErrorReference, P4ErrorPanel } from "./P4Feedback";
import { useInlineConfirmationFocus } from "./useInlineConfirmationFocus";

export function OutboundPanel({ communicationId, draft, auth, now, view = 'all' }: {
  communicationId: string; draft?: MessageDraftView; auth: RequestAuthHeaders; now: number; view?: 'all' | 'send' | 'history';
}) {
  const client = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const busy = useRef(false), key = useRef<string | null>(null), active = useRef(true);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => { active.current = true; return () => { active.current = false; controller.current?.abort(); }; }, []);
  const history = useQuery({ queryKey: communicationKeys.outbound(auth, communicationId),
    queryFn: ({ signal }) => getOutboundHistory(communicationId, auth, signal), retry: false, staleTime: 0, refetchOnMount: "always" });
  const eligibility = useQuery({
    queryKey: draft ? communicationKeys.eligibility(auth, draft) : [...communicationKeys.scope(auth), "no-send-draft", communicationId],
    queryFn: ({ signal }) => getSendEligibility(draft!, auth, signal), enabled: !!draft, retry: false,
    staleTime: 0, refetchOnMount: "always", refetchOnWindowFocus: true,
  });
  const canSend = !!draft && eligibility.isSuccess && !eligibility.isFetching && eligibility.data.can_send &&
    !!eligibility.data.expires_at && Date.parse(eligibility.data.expires_at) > now && Date.parse(draft.expires_at) > now &&
    history.isSuccess && !history.isFetching && !history.data.some(row => row.draft_id === draft.draft_id);
  const focus = useInlineConfirmationFocus(confirming && canSend);
  const mutation = useMutation({ retry: false,
    mutationFn: async () => {
      if (!draft || !canSend) throw new Error("Sending eligibility must be checked again");
      controller.current = new AbortController(); key.current ??= crypto.randomUUID();
      return sendMessage(draft, key.current, auth, controller.current.signal);
    },
    onSuccess: async () => {
      if (!active.current) return;
      setConfirming(false);
      await Promise.all([
        communicationKeys.outbound(auth, communicationId), communicationKeys.summary(auth),
        communicationKeys.list(auth), communicationKeys.detail(auth, communicationId),
        ...(draft ? [communicationKeys.eligibility(auth, draft)] : []),
      ].map(queryKey => client.invalidateQueries({ queryKey })));
    }, onSettled: () => { busy.current = false; },
  });
  const submit = () => { if (busy.current || mutation.isPending || !canSend) return; busy.current = true; mutation.mutate(); };
  return <section ref={focus.regionRef} tabIndex={-1} className="cc-section cc-outbound" aria-label="Mock sending">
    <div className="cc-outbound-part" data-active={view !== 'history'}>
    <h4>Mock Sending</h4><p className="muted text-sm">Local simulation only. Sending does not mean delivered, accepted or fulfilled.</p>
    {!draft && <p>Load a current draft to check sending eligibility.</p>}
    {draft && eligibility.isFetching && <p role="status">Checking sending eligibility…</p>}
    {draft && !canSend && !eligibility.isFetching && <p className="cc-error">Sending blocked: current backend authorization and verified contact are required.
      {eligibility.isSuccess && eligibility.data.blocked_reason && <span> ({eligibility.data.blocked_reason})</span>}</p>}
    {eligibility.isError && <P4ErrorPanel error={eligibility.error} message={errorText(eligibility.error, "send")} retry={() => { void eligibility.refetch(); }} />}
    {draft && <button ref={focus.triggerRef} className="btn btn-primary" disabled={!canSend || mutation.isPending} onClick={() => setConfirming(true)}>Send Message</button>}
    {confirming && canSend && <fieldset className="cc-review-confirm" onKeyDown={event => {
      if (event.key === "Escape" && !mutation.isPending) { event.preventDefault(); setConfirming(false); }
    }}><legend>Confirm mock send</legend>
      <p>Send this exact approved draft via {draft?.channel}? This only uses a local Mock Provider.</p>
      <button ref={focus.confirmRef} className="btn btn-primary" disabled={mutation.isPending} onClick={submit}>Confirm Send Message</button>
      <button className="btn btn-secondary" disabled={mutation.isPending} onClick={() => setConfirming(false)}>Cancel send</button>
    </fieldset>}
    {mutation.isPending && <p role="status">Sending mock message…</p>}
    {mutation.isError && <div role="alert" className="cc-error"><p>{errorText(mutation.error, "send")} Check sending history before retrying.</p><ApiErrorReference error={mutation.error} /></div>}
    {mutation.data?.status === "DELIVERY_UNKNOWN" && <p role="alert">Sending outcome is unknown. Do not resend; manual reconciliation is required.</p>}
    </div>
    <div className="cc-outbound-part" data-active={view !== 'send'}>
    <h5>Sending History</h5>
    <button className="btn btn-secondary" disabled={history.isFetching} onClick={() => {
      void history.refetch(); if (draft) void eligibility.refetch(); }}>Refresh sending history</button>
    {history.isFetching ? <p role="status">Loading sending history…</p> : history.isError ?
      <P4ErrorPanel error={history.error} message={errorText(history.error, "send")} retry={() => { void history.refetch(); }} /> : history.data?.length ?
      <ul className="cc-outbound-history">{history.data.map(row => <li key={row.outbound_id}>
        <strong>{row.channel} · {row.status === "QUEUED" ? "Sending" : row.status}</strong>
        {row.status === "SENT" && <p role="status">Mock message sent successfully.</p>}
        <p>Draft: <code>{row.draft_id}</code></p>
        {row.provider_reference && <p>Provider reference: <code>{row.provider_reference}</code></p>}
        <p>Updated: {formatKLTimestamp(row.updated_at)}</p>
        {row.sent_at && <p>Sent: {formatKLTimestamp(row.sent_at)}</p>}
        {row.failed_at && <p>Failed: {formatKLTimestamp(row.failed_at)}</p>}
        {row.last_error_code && <p>Reason: {row.last_error_code}</p>}
        {row.status === "DELIVERY_UNKNOWN" && <p>Outcome unconfirmed. Do not resend; manual reconciliation is required.</p>}
        {row.status === "FAILED" && <p>Provider confirmed failure. This exact draft cannot be resubmitted.</p>}
        {row.status === "QUEUED" && <p>Submission is pending. Do not submit this draft again.</p>}
        <details><summary>Attempt history</summary>{row.attempts.map(attempt => <p key={attempt.attempt_number}>
          Attempt {attempt.attempt_number}: {attempt.status} {attempt.error_code ?? ""}</p>)}</details>
      </li>)}</ul> : <p>No outbound messages.</p>}
    </div>
  </section>;
}
