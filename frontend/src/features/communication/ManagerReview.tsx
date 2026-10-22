import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { RequestAuthHeaders } from "../../shared/api";
import { formatKLTimestamp } from "../../shared/date";
import { communicationKeys, getDraftReview, submitDraftReview } from "./api";
import { ErrorNotice, errorText } from "./presentation";
import type { DraftReviewCommand, MessageDraftView } from "./types";

export function ManagerReview({ draft, auth, now }: { draft: MessageDraftView; auth: RequestAuthHeaders; now: number }) {
  const client = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const [reason, setReason] = useState("");
  const [savedAction, setSavedAction] = useState("");
  const keys = useRef(new Map<string, string>());
  const busy = useRef(false);
  const active = useRef(true);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => { active.current = true; return () => { active.current = false; controller.current?.abort(); }; }, []);
  const review = useQuery({ queryKey: communicationKeys.review(auth, draft),
    queryFn: ({ signal }) => getDraftReview(draft, auth, signal), retry: false,
    staleTime: 0, refetchOnMount: "always", refetchOnWindowFocus: true });
  const expired = review.data?.review_state === "APPROVED" && !!review.data.decision && Date.parse(review.data.decision.expires_at) <= now;
  useEffect(() => {
    if (expired) void client.invalidateQueries({ queryKey: communicationKeys.review(auth, draft) });
  }, [expired, client, auth, draft]);
  const mutation = useMutation({ retry: false,
    mutationFn: ({ action, command }: { action: "approve" | "reject"; command: DraftReviewCommand }) => {
      controller.current = new AbortController();
      return submitDraftReview(draft, action, command, auth, controller.current.signal);
    },
    onSuccess: async (_value, variables) => {
      if (!active.current) return;
      setConfirming(false); setSavedAction(variables.action);
      await client.invalidateQueries({ queryKey: communicationKeys.review(auth, draft) });
      void client.invalidateQueries({ queryKey: communicationKeys.summary(auth) });
    },
    onError: () => { if (active.current) {
      setSavedAction("");
      void client.invalidateQueries({ queryKey: communicationKeys.review(auth, draft) });
    } },
    onSettled: () => { busy.current = false; },
  });
  const current = review.isSuccess && !review.isFetching && !expired ? review.data : undefined;
  const canApprove = current?.review_state === "PENDING" && current.allowed_actions.includes("APPROVE_DRAFT");
  const canReject = current?.review_state === "PENDING" && current.allowed_actions.includes("REJECT_DRAFT");
  const submit = (action: "approve" | "reject") => {
    if (busy.current || mutation.isPending || (action === "approve" ? !canApprove : !canReject)) return;
    if (action === "reject" && (!reason.trim() || reason.length > 1000)) return;
    const signature = JSON.stringify([action, draft.content_hash, action === "reject" ? reason.trim() : null]);
    if (!keys.current.has(signature)) keys.current.set(signature, crypto.randomUUID());
    busy.current = true;
    mutation.mutate({ action, command: { request_key: keys.current.get(signature)!, expected_content_hash: draft.content_hash,
      ...(action === "reject" ? { reason: reason.trim() } : {}) } });
  };
  return <section className="cc-section cc-review" aria-label="Manager Review">
    <h4>Manager Review</h4>
    <p className="muted text-sm">Review this exact message. Message approval is separate from recovery proposal approval and does not send anything.</p>
    {review.isFetching && <p role="status">Checking manager review…</p>}
    {review.isError && <ErrorNotice error={review.error} resource="review" onRetry={() => { void review.refetch(); }} />}
    {expired && !review.isFetching && <p className="cc-error">This review has expired. Refresh the review before using it.</p>}
    {current && <>
      <p><strong>Review status:</strong> {current.review_state === "PENDING" ? "Pending Review" : current.review_state}</p>
      {savedAction === "approve" && current.effective_approval && <p role="status">Draft approved. The message has not been sent.</p>}
      {savedAction === "reject" && current.review_state === "REJECTED" && <p role="status">Draft rejected. No message was sent.</p>}
      {current.review_state === "INVALIDATED" && <p className="cc-error">This review is invalidated. It cannot authorize a send. {current.invalidation_code}</p>}
      {current.review_state === "PENDING" && !canApprove && !canReject && <p className="muted">Read-only: no manager review permission was granted for this draft.</p>}
      {(canApprove || canReject) && <div className="cc-review-controls">
        {canApprove && !confirming && <button className="btn btn-primary" disabled={mutation.isPending} onClick={() => setConfirming(true)}>Approve Draft</button>}
        {canApprove && confirming && <fieldset className="cc-review-confirm"><legend>Confirm draft approval</legend>
          <p>Approve draft {draft.draft_id} for {draft.recipient_identity_id} on {draft.channel}? This does not send the message.</p>
          <div className="cc-actions"><button className="btn btn-primary" disabled={mutation.isPending} onClick={() => submit("approve")}>Confirm Approve Draft</button>
            <button className="btn btn-secondary" disabled={mutation.isPending} onClick={() => setConfirming(false)}>Cancel approval</button></div>
        </fieldset>}
        {canReject && <form className="cc-review-reject" onSubmit={event => { event.preventDefault(); submit("reject"); }}>
          <label>Rejection reason<textarea value={reason} maxLength={1000} disabled={mutation.isPending}
            onChange={event => setReason(event.target.value)} placeholder="Explain why this message draft needs revision" /></label>
          <p className="muted text-sm">{reason.length}/1000 characters. Rejecting this message does not reject the recovery proposal.</p>
          <button className="btn btn-secondary" disabled={!reason.trim() || reason.length > 1000 || mutation.isPending}>Reject Draft</button>
        </form>}
      </div>}
      {current.decision && <details className="cc-section" open><summary>Review history</summary>
        <dl className="cc-facts"><div><dt>Reviewer</dt><dd>{current.decision.reviewer_id} · {current.decision.reviewer_role}</dd></div>
          <div><dt>Original decision</dt><dd>{current.decision.action}</dd></div>
          <div><dt>Reviewed</dt><dd>{formatKLTimestamp(current.decision.reviewed_at)}</dd></div>
          <div><dt>Valid until</dt><dd>{formatKLTimestamp(current.decision.expires_at)}</dd></div>
          <div><dt>Content hash</dt><dd>{current.decision.content_hash}</dd></div>
          <div><dt>Audit reference</dt><dd>{current.decision.audit_id}</dd></div></dl>
        {current.decision.reason && <p>Rejection reason: {current.decision.reason}</p>}
        {current.invalidated_at && <p>Invalidated: {formatKLTimestamp(current.invalidated_at)} · {current.invalidation_audit_id}</p>}
        <p className="muted text-sm">Authorization evidence: {current.decision.authorization_evidence_refs.join(", ")}</p>
      </details>}
    </>}
    {mutation.isPending && <p role="status">Saving draft review…</p>}
    {mutation.isError && <div className="cc-error" role="alert"><p>{errorText(mutation.error, "review")}</p>
      <p className="muted text-sm">No sending action was requested. Recheck the review before retrying.</p></div>}
  </section>;
}
