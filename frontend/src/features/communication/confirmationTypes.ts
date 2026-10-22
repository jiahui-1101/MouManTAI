import type { CommunicationChannel, Confirmation, ISO8601 } from "../../shared/types";
import type { DraftReference } from "./types";

// Read DTOs mirror Commit 07 confirmation_schemas.py, not Core's Confirmation.
export interface ConfirmationView extends Pick<Confirmation, "confirmation_id" | "tenant_id" | "state" | "expires_at"> {
  communication_id: string;
  outbound_id: string;
  customer_id: string;
  channel: Exclude<CommunicationChannel, "UNKNOWN">;
  reference: DraftReference;
  terms_digest: string;
  content_hash: string;
  created_at: ISO8601;
  consumed_at: ISO8601 | null;
  revoked_at: ISO8601 | null;
  blocked_reasons: string[];
  core_transition_applied: false;
  evidence_scope: "P4_EVIDENCE_ONLY";
  integration_mode: "SYNTHETIC_ONLY";
}

export type ResponseIntent = "ACCEPT" | "REJECT" | "COUNTEROFFER" | "CLARIFICATION" | "UNKNOWN";
export interface ConfirmationAttemptView {
  attempt_id: string;
  confirmation_id: Confirmation["confirmation_id"];
  inbound_message_id: string;
  intent: ResponseIntent;
  reason: string;
  evidence_refs: Confirmation["response_evidence_refs"];
  proposed_changes: Partial<Record<"quantity" | "deadline" | "special_instructions", string>> | null;
  received_at: ISO8601;
}
