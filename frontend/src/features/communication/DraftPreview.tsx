import { formatKLTimestamp } from "../../shared/date";
import type { MessageDraftView } from "./types";
import { channelText, languages } from "./presentation";

export function DraftPreview({ draft, onReload }: { draft: MessageDraftView; onReload: () => void }) {
  return <article className="cc-preview" aria-label="Message draft preview">
    <div className="cc-row"><h4>Message preview</h4><span className="cc-draft-note">Draft Only — Not Sent</span></div>
    <p className="muted text-sm">{languages[draft.language]} · {channelText(draft.channel)} · Template v{draft.template_version} · Proposal v{draft.reference.proposal_version}</p>
    {draft.subject && <p className="cc-subject"><strong>Subject:</strong> {draft.subject}</p>}
    <pre className="cc-message">{draft.body}</pre>
    <dl className="cc-facts">
      <div><dt>Draft ID</dt><dd>{draft.draft_id}</dd></div>
      <div><dt>Order reference</dt><dd>{draft.order_id}</dd></div>
      <div><dt>Recipient identity</dt><dd>{draft.recipient_identity_id}</dd></div>
      <div><dt>Template</dt><dd>{draft.template_key}</dd></div>
      <div><dt>Status</dt><dd>{draft.status}</dd></div>
      <div><dt>Created</dt><dd>{formatKLTimestamp(draft.created_at)}</dd></div>
      <div><dt>Expires</dt><dd>{formatKLTimestamp(draft.expires_at)}</dd></div>
    </dl>
    <details><summary>Approved proposal terms at validation</summary>
      <p>{draft.approved_terms.sku} · {draft.approved_terms.quantity} {draft.approved_terms.unit}</p>
      <p>Deadline: {formatKLTimestamp(draft.approved_terms.deadline)}</p>
      {draft.approved_terms.special_instructions && <p>{draft.approved_terms.special_instructions}</p>}
    </details>
    <p className="muted text-sm">This preview is read-only. Preparing or reviewing it does not send a message.</p>
    <button className="btn btn-secondary" onClick={onReload}>Recheck draft</button>
  </article>;
}
