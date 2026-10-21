import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { RequestAuthHeaders } from "../../shared/api";
import { formatKLTimestamp } from "../../shared/date";
import { communicationKeys, getDraft, prepareDraft } from "./api";
import { channelText, communicationLabel, DisplayBadge, ErrorNotice, errorText, languages, reasonText } from "./presentation";
import { DraftPreview } from "./DraftPreview";
import type { CommunicationRequestView, DraftLanguage, MessageDraftView } from "./types";

interface Props {
  request: CommunicationRequestView;
  auth: RequestAuthHeaders;
  knownIds: string[];
  remember: (id: string, draftId: string) => void;
  checked: (id: string, value?: MessageDraftView, failed?: boolean) => void;
  now: number;
}

export function CommunicationDetails({ request, auth, knownIds, remember, checked, now }: Props) {
  const client = useQueryClient();
  const id = request.communication_id;
  const [language, setLanguage] = useState<DraftLanguage>("en");
  const [draftId, setDraftId] = useState(() => knownIds.at(-1) ?? "");
  const [enteredId, setEnteredId] = useState("");
  const [rechecking, setRechecking] = useState(false);
  const pending = useRef(false);
  const active = useRef(true);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => { active.current = true;
    return () => { active.current = false; controller.current?.abort(); }; }, []);
  const draft = useQuery({ queryKey: communicationKeys.draft(auth, id, draftId),
    queryFn: ({ signal }) => getDraft(request, draftId, auth, signal), enabled: !!draftId,
    retry: false, staleTime: 0, refetchOnMount: "always", refetchOnWindowFocus: true });
  const expired = !!draft.data && Date.parse(draft.data.expires_at) <= now;
  const validDraft = draft.isSuccess && !draft.isFetching && !rechecking && !expired ? draft.data : undefined;
  const reload = () => {
    // Hide old content synchronously; query notifications may be batched.
    setRechecking(true);
    void draft.refetch().finally(() => { if (active.current) setRechecking(false); });
  };
  const prepare = useMutation({
    mutationKey: [...communicationKeys.scope(auth), "prepare", id], retry: false,
    mutationFn: async () => {
      controller.current = new AbortController();
      return prepareDraft(request, { language, template_key: "delivery_change" }, auth, controller.current.signal);
    },
    onSuccess: value => {
      if (!active.current) return;
      remember(id, value.draft_id);
      setDraftId(value.draft_id);
      // Always GET the saved draft again, even if Prepare returned an existing ID.
      void client.invalidateQueries({ queryKey: communicationKeys.draft(auth, id, value.draft_id) });
      // Mark snapshots stale without remounting this in-flight mutation's owner.
      void client.invalidateQueries({ queryKey: communicationKeys.list(auth), refetchType: "none" });
      void client.invalidateQueries({ queryKey: communicationKeys.detail(auth, id), refetchType: "none" });
      void client.invalidateQueries({ queryKey: communicationKeys.summary(auth) });
    },
    onError: () => { if (active.current) {
      checked(id, undefined, true);
      void client.invalidateQueries({ queryKey: communicationKeys.summary(auth) });
    } },
    onSettled: () => { pending.current = false; },
  });
  useEffect(() => {
    if (validDraft && !prepare.isPending && !prepare.isError) {
      remember(id, validDraft.draft_id); checked(id, validDraft);
    } else checked(id, undefined, draft.isError || expired || prepare.isError);
  }, [id, validDraft, draft.isError, expired, prepare.isPending, prepare.isError, remember, checked]);
  useEffect(() => {
    if (draft.dataUpdatedAt || draft.errorUpdatedAt) {
      void client.invalidateQueries({ queryKey: communicationKeys.summary(auth) });
    }
  }, [client, auth, draft.dataUpdatedAt, draft.errorUpdatedAt, expired]);
  const runPrepare = () => {
    if (pending.current || prepare.isPending || request.request_status === "BLOCKED") return;
    pending.current = true;
    checked(id);
    prepare.mutate();
  };
  const blocked = request.request_status === "BLOCKED";
  const failed = draft.isError || expired || prepare.isError;
  const label = failed ? "Blocked" : communicationLabel(request.request_status, request.message_status, !!validDraft);
  const terms = request.proposed_terms;
  return <>
    <div className="cc-row"><div><p className="eyebrow">Request details</p><h3>{request.reference.commitment_id}</h3></div><DisplayBadge label={label} /></div>
    <dl className="cc-facts">
      <Fact label="Communication" value={id} />
      <Fact label="Proposal" value={`${request.reference.proposal_id} · v${request.reference.proposal_version}`} />
      <Fact label="Recovery plan" value={`${request.reference.plan_id} · v${request.reference.plan_version}`} />
      <Fact label="Commitment version" value={request.reference.commitment_version} />
      <Fact label="Channel" value={channelText(request.channel)} />
      <Fact label="Request state (snapshot)" value={request.request_status} />
      <Fact label="Created" value={formatKLTimestamp(request.created_at)} />
      <Fact label="Valid until (snapshot)" value={formatKLTimestamp(request.expires_at)} />
    </dl>
    {blocked && <div className="cc-error" role="note"><strong>Blocked</strong>
      {(request.blocking_reasons?.length ? request.blocking_reasons : ["REVIEW_REQUIRED"]).map(code =>
        <p key={code}>{reasonText(code)} <code>{code}</code></p>)}</div>}
    <section className="cc-section" aria-label="Terms snapshot"><h4>Proposed terms snapshot</h4>
      <p className="muted text-sm">Recorded at request creation. The server checks the current proposal and approval again before preparing or reading a draft.</p>
      {terms ? <dl className="cc-facts"><Fact label="SKU" value={terms.sku} />
        <Fact label="Quantity" value={terms.quantity == null ? undefined : `${terms.quantity} ${terms.unit ?? ""}`} />
        <Fact label="Delivery deadline" value={formatKLTimestamp(terms.deadline)} />
        {terms.special_instructions && <Fact label="Special instructions" value={terms.special_instructions} />}</dl> :
        <p className="muted">Terms were not provided.</p>}
    </section>
    <details className="cc-section"><summary>Verification and evidence snapshot</summary>
      <p className="muted text-sm">References indicate recorded evidence, not a guarantee of current authorization.</p>
      <dl className="cc-facts">
        <Fact label="Recipient evidence" value={request.recipient_identity_id && request.recipient_evidence_refs?.length ? "Recorded" : "Not recorded"} />
        <Fact label="Channel evidence" value={request.channel && request.channel !== "UNKNOWN" && request.channel_evidence_refs?.length ? "Recorded" : "Not recorded"} />
        <Fact label="Approval expires" value={formatKLTimestamp(request.approval_expires_at)} />
      </dl>
      <Evidence label="Approval evidence references" values={request.approval_evidence_refs} />
      <Evidence label="Proposal evidence references" values={request.proposal_evidence_refs} />
      <p className="muted text-sm">Source event: <code>{request.reference.source_event_id}</code></p>
    </details>
    <section className="cc-section" aria-label="Draft preparation"><h4>Prepare a draft</h4>
      <div className="cc-actions"><label>Draft language<select value={language} disabled={prepare.isPending}
        onChange={event => setLanguage(event.target.value as DraftLanguage)}>
        {Object.entries(languages).map(([value, text]) => <option key={value} value={value}>{text}</option>)}
      </select></label>
        <button className="btn btn-primary" onClick={runPrepare} disabled={blocked || prepare.isPending || draft.isFetching}>
          {prepare.isPending ? "Preparing draft…" : "Prepare draft"}</button></div>
      {blocked && <p className="muted text-sm">Resolve the blocked reasons and refresh this request before preparing a draft.</p>}
      <p className="muted text-sm">Preparation creates a preview. It does not approve or send a message.</p>
      {prepare.isPending && <p role="status">Preparing your draft…</p>}
      {prepare.isError && <div className="cc-error" role="alert"><p>{errorText(prepare.error, "draft")}</p>
        <button className="btn btn-secondary" onClick={runPrepare} disabled={blocked || prepare.isPending}>Retry preparation</button></div>}
    </section>
    <section className="cc-section" aria-label="Saved drafts"><h4>Saved drafts</h4>
      <p className="muted text-sm">Select a draft opened in this session, or enter a known draft ID. Full draft history is not available yet.</p>
      {knownIds.length > 0 && <label>Known drafts<select value={knownIds.includes(draftId) ? draftId : ""}
        disabled={prepare.isPending} onChange={event => { prepare.reset(); setDraftId(event.target.value); }}>
        <option value="">Select a draft</option>{knownIds.map(value => <option key={value}>{value}</option>)}
      </select></label>}
      <form className="cc-actions" onSubmit={event => {
        event.preventDefault(); if (!enteredId.trim() || prepare.isPending) return;
        prepare.reset(); const next = enteredId.trim(); setDraftId(next);
        if (next === draftId) reload();
      }}>
        <label>Draft ID<input value={enteredId} onChange={event => setEnteredId(event.target.value)} maxLength={256} placeholder="Enter an existing draft ID" /></label>
        <button className="btn btn-secondary" disabled={!enteredId.trim() || prepare.isPending}>Load draft</button>
      </form>
      {(draft.isFetching || rechecking) && <p role="status">Checking saved draft…</p>}
      {!draftId && <p className="muted">No draft available. Prepare a draft or open one by ID.</p>}
      {draft.isError && !prepare.isPending && <ErrorNotice error={draft.error} resource="draft" onRetry={reload} />}
      {expired && !draft.isFetching && <div role="alert" className="cc-error"><p>This draft has expired. Refresh and review the current proposal before preparing another draft.</p></div>}
      {validDraft && !prepare.isPending && !prepare.isError && <DraftPreview draft={validDraft} onReload={reload} />}
    </section>
  </>;
}

function Fact({ label, value }: { label: string; value?: string | number | null }) {
  return <div><dt>{label}</dt><dd>{value ?? "Not provided"}</dd></div>;
}
function Evidence({ label, values }: { label: string; values?: string[] }) {
  return <div className="cc-evidence"><p className="muted text-sm">{label}</p>
    {values?.length ? <ul>{values.map(value => <li key={value}><code>{value}</code></li>)}</ul> : <p className="muted">Not recorded</p>}</div>;
}
