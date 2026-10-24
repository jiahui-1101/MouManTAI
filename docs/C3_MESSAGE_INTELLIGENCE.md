# C3 message intelligence — Phase 3 integration candidate

C3 analyzes current canonical P1 messages and existing attachment evidence. Its deterministic classifier produces strict, evidence-linked Customer Inquiry, Supplier Delay and Human Review candidates. Candidates are provisional; no P2 state, Core commitment, order acceptance, P4 send or provider receipt is written.

## Canonical pipeline

Verified C2 ingress → P1 persisted message/attachment evidence → C3 deterministic classifier → optional owner-approved P1 semantic gateway → strict C3 schema/source claim checks → typed candidates → verified read-only business adapters → Human Review where required.

`CurrentP1MessageReader` requires an injected authenticated tenant scope, reads the exact message, association and attachment/extraction records, verifies the content digest plus C1/C2 account-bound native message/authenticity provenance, and re-reads the same source before handoff. Message citations use exact Unicode offsets; document citations use existing P1 evidence IDs and pages. C3 uses P1's same-length external-provider masking policy. Masked evidence spans cannot support a model claim.

`MessageIntelligenceService.from_env()` has no independent Qwen/Gemini clients. The removed C3 HTTP/fallback implementation is superseded by `app.context.ai.provider_reliability`. P1 already has Qwen primary, Gemini on eligible technical/schema failure, bounded retries/response, redacted diagnostics and its extraction Human Review path. Its current schema emits extraction fields; a classification task extension needs P1/P5 owner review. Until then semantic C3 input is unavailable in production and unknown messages remain review-required. Synthetic fixture gateway tests check C3 schema and source validation; P1 fixture tests check Qwen/Gemini reliability. Neither is a live-provider result.

## Business handoffs

- **Customer Inquiry:** `draft_customer_inquiry` requires a current exact message, unchanged versioned verified customer association and injected approved public business fact with evidence/version. The draft includes source and business evidence and `send_authorized=false`. It makes no inference of assent or order acceptance.
- **Supplier Delay:** `validate_supplier_delay` requires verified supplier identity, exact delivery reference and reported ETA, plus a current tenant/supplier/reference-matched P2 snapshot and evidence. It compares the reported date with the expected date and returns `POTENTIAL_DELAY_REPORTED` or `UNRESOLVED`; both require review and mutate no state.
- **Human Review:** C3 creates a typed in-memory candidate with source hash, attachment evidence, reason codes and provider provenance. A durable generic task writer is not approved. P1's context correction reviews cannot be reused as a generic C3 queue without changing their contract.

P4 provider transports remain disconnected. Any future inquiry reply or notification must use the approved P4 verified recipient/channel, purpose consent, explicit authorization, current draft/source evidence, durable outbox/idempotency and provider receipt/unknown-outcome path. Real sends remain disabled.

See [Phase 3 integration report](reports/C3_P1_PHASE3_INTEGRATION_2026-10-25.md) for overlap, validation and blockers. Historical pre-integration C3 handoff remains in `docs/reports/C3_EARLY_BACKEND_AH_CONTRACT_HANDOFF.md`.

