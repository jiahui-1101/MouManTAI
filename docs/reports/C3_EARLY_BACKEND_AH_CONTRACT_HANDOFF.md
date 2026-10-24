# C3 early Backend A–H contract handoff

Date: 2026-10-25
Branch baseline: `codex/c3-message-intelligence` was created from `origin/main` at `7c5ac1531e71bc5d1f762d098af69eaf3dd3785d`; before PR creation it is refreshed onto latest `origin/main` at `cd6c64efdc1d0e3e91dd175a095d2434d705e8d8`.
Status: **C3 proposal for owner review; no shared API, canonical model, migration, or authorization change is requested here.**

This handoff is intentionally early. It records current-main contracts separately from proposed C3 outputs and from contracts in unmerged C1/C2 work. Candidate outputs are analysis evidence only. They cannot create an OrderRequest, customer assent, supplier authority, inventory update, P2 event, Recovery action, or permission to send.

## Current integration boundary

| Area | Current main evidence | Status and C3 boundary |
|---|---|---|
| Inbound message | `backend/app/context/schemas.py:RawMessageEnvelope` has `tenant_id`, channel, provider message ID, sender identity ID and alias, received/message timestamps, text, attachment evidence refs, thread/reply IDs, and `adapter_mode`. `backend/app/context/router.py` exposes `POST /v1/messages/ingest`; storage exposes tenant-filtered message and extraction reads. | **IMPLEMENTED, provisional P1-local.** C3 consumes an already tenant-scoped immutable message snapshot and its content hash. It does not add another inbound store or weaken authentication. `sender_alias` is descriptive; it is not identity proof. |
| Deterministic order extraction | `backend/app/context/deterministic_extraction.py` plus `request_intent.py`; extraction outputs `ExtractedField` and exact Unicode code-point `FieldEvidence` spans. It is deliberately conservative and may leave intent `UNCLASSIFIED`. | **IMPLEMENTED, provisional P1-local.** Reuse for explicit order fields and inquiry guards. C3 does not reimplement or promote these fields into an accepted order. |
| AI extraction | `backend/app/context/ai/protocol.py`, `service.py`, and `endpoint.py` support strict evidence-grounded GLiNER/Qwen order observations. `P1_AI_ENABLED` is opt-in; endpoint configuration uses `P1_AI_ENDPOINT_URL`, `P1_AI_API_KEY`, `P1_AI_ENDPOINT_MODE`, and `P1_AI_TIMEOUT_SECONDS`. No Gemini fallback or general inquiry/supplier-delay contract exists in current main. | **IMPLEMENTED but limited to provisional P1 extraction.** C3 may call through a new isolated provider boundary; it must not change P1 protocol or assume the current endpoint is a general semantic classification API. |
| Attachments | `POST /v1/attachments/upload`, tenant-scoped content/metadata/page reads, and `POST /v1/attachments/{evidence_ref}/extract` return `DocumentExtractionResult` with status, type, extracted time and `DocumentEvidence` references including `evidence_ref`, attachment ID, page, exact quote, method and method version. The parser supports PDF text and image OCR under P1 ownership. | **IMPLEMENTED, P1-owned.** C3 accepts existing extracted text/evidence only. For this slice it does not edit OCR code, dependencies, schemas, routes, or acceptance tests, and does not send image/PDF bytes to an AI provider. `FAILED`, `PARTIAL`, `UNSUPPORTED`, empty, or ungrounded results require review. |
| Customer association / review | P1-local context, message-association and review records exist under `backend/app/context`; identity states include `LINK_VERIFIED`, `UNVERIFIED`, and `AMBIGUOUS`. | **IMPLEMENTED, provisional.** C3 binds a candidate to source tenant/message and carries identity state/evidence refs. It cannot decide identity from a model, alias, or message text. An absent/currentness-unverified association means review. |
| Backend A → B order candidate | `docs/BACKEND_A_B_INTEGRATION_CONTRACT.md` proposes a pure `AcceptanceCandidate` mapper in `backend/app/orders/context_mapping.py`. `backend/app/orders/p1_source_reader.py` is a P1 source reader, but the durable authoritative OrderRequest/request-version source is absent on current main and the integrated path remains incomplete. The mapper does not accept, reserve, or confirm. | **PROPOSED / INCOMPLETE.** C3 inquiry and supplier-delay candidates are separate and do not populate `AcceptanceCandidate` or bypass its source/readiness requirements. Current-main A–B is not a usable persistence API. |
| Supplier delay / P2 | `SupplierDelayRequest` requires an `OperationalChange` with exactly one supplier-delivery key, advancing snapshot versions, and matching tenant-scoped `ETA_CHANGE` `SupplierDeliveryEvidence`. `/v1/operations/events/supplier-delay` is defined in the P2 router; the repository handoff says it is unmounted in the app and has no authoritative transactional processor/outbox, so it returns 503 when unavailable. | **CONTRACT IMPLEMENTED; production integration unavailable.** A C3 candidate cannot be converted directly into this event. A trusted source adapter must independently resolve supplier, delivery, old/new authoritative ETA, snapshot IDs/versions/currentness, and evidence before a separately authorized Backend B/P2 call. |
| P4 outbound | `backend/app/communication/OutboundService` persists a one-submission intent, revalidates SEND_MESSAGE authorization and approved draft state, uses idempotency, and records `SENT`, `FAILED`, or `DELIVERY_UNKNOWN`. `backend/app/communication/providers.py` currently implements `LocalMockProvider`; its accepted channels are `MOCK_EMAIL`, `MOCK_WHATSAPP`, and `MOCK_TELEGRAM`. Current communication request intake is tied to a `recovery.communication_requested` event and does not define a customer-inquiry reply request. | **IMPLEMENTED, authorization-gated, mock-only.** C3 may return an unsent, evidence-linked reply-draft candidate. It must not call P4 send or invent a communication request/consent path. Any future real-transport wiring must enter through the existing P4 owner-approved authorization/service boundary. |
| Real provider transports | The C2 implementation is an independent unmerged Draft PR; its internal provider clients are not part of `origin/main` and have no P4 authorization integration. | **UNAVAILABLE on this branch.** C3 has no dependency on C2 code. Any later composition requires review of the landed P4/C2 contracts and explicit owner approval. |

## Proposed C3 handoff payloads

These are proposed Backend A–H handoff payload shapes mapped from the side-effect-free internal C3 result. They are not direct serializations of current Python models, HTTP bodies, event schemas, persistence models, or shared canonical APIs. All IDs below refer to existing source records; C3 must not synthesize source evidence IDs or claim authority from a syntactically valid payload.

### `CustomerInquiryCandidate` (proposed v1)

```json
{
  "contract": "customer_inquiry_candidate.v1",
  "tenant_id": "tenant from authenticated P1 source read",
  "source": {
    "message_id": "existing P1 message ID",
    "channel": "existing source channel",
    "provider_message_id": "existing provider message ID",
    "content_sha256": "stored source digest",
    "received_at": "offset-aware source timestamp",
    "message_at": "original provider timestamp or null",
    "thread_ref": "existing channel thread/chat ID or null",
    "reply_to_provider_message_id": "exact provider parent ID or null",
    "attachment_evidence_refs": ["existing P1 attachment evidence refs"],
    "attachment_sources": [{
      "attachment_id": "existing P1 attachment ID",
      "evidence_ref": "existing P1 evidence ref",
      "media_type": "application/pdf",
      "size_bytes": 123,
      "content_sha256": "existing tenant-scoped attachment digest",
      "attachment_created_at": "offset-aware P1 timestamp",
      "extraction_status": "SUCCESS",
      "extracted_at": "offset-aware extraction timestamp",
      "evidence_ids": ["existing DocumentEvidence IDs"],
      "extraction_method_versions": ["P1 method version"]
    }]
  },
  "classification": {
    "kind": "PRICE | AVAILABILITY | DELIVERY | PRODUCT_INFO | OTHER | UNKNOWN",
    "evidence": [{"evidence_ref": "source ref", "quote": "exact source span", "start": 0, "end": 12}],
    "provider": "RULE | QWEN | GEMINI | NONE",
    "provider_version": "rule/model identifier when available"
  },
  "identity": {
    "status": "LINK_VERIFIED | UNVERIFIED | AMBIGUOUS",
    "association_id": "existing MessageAssociationRecord ID or null",
    "association_version": 2,
    "association_updated_at": "offset-aware source timestamp or null",
    "customer_id": "verified tenant-scoped customer ID or null"
  },
  "review": {"required": true, "reasons": ["UNKNOWN_CLASSIFICATION"]},
  "candidate_only": true
}
```

An inquiry answer/draft is a separate non-authoritative output and must cite the allowed business facts it uses. Classification does not establish approved public knowledge, customer terms, assent, recipient consent, or send authority. Unknown/contradictory classification or unverified sender linkage sets `review.required=true`.

### `SupplierDelaySignalCandidate` (proposed v1)

```json
{
  "contract": "supplier_delay_signal_candidate.v1",
  "tenant_id": "tenant from authenticated P1 source read",
  "source": {
    "message_id": "existing P1 message ID",
    "channel": "existing source channel",
    "provider_message_id": "existing provider message ID",
    "content_sha256": "stored source digest",
    "received_at": "offset-aware source timestamp",
    "message_at": "original provider timestamp or null",
    "thread_ref": "existing channel thread/chat ID or null",
    "reply_to_provider_message_id": "exact provider parent ID or null",
    "attachment_evidence_refs": ["existing P1 attachment evidence refs"],
    "attachment_sources": [{"attachment_id": "existing P1 ID", "evidence_ref": "existing P1 ref",
      "content_sha256": "existing digest", "extraction_status": "SUCCESS",
      "extracted_at": "offset-aware time", "evidence_ids": ["existing P1 evidence ID"],
      "extraction_method_versions": ["P1 method version"]}]
  },
  "supplier_identity": {
    "supplier_id": "supplier ID only from a trusted verified source reader",
    "status": "VERIFIED",
    "version": 4,
    "checked_at": "offset-aware identity registry timestamp",
    "verification_evidence_refs": ["existing registry evidence ref"]
  },
  "delivery_reference": "PO-123",
  "delivery_reference_evidence": {"evidence_ref": "existing source ref", "quote": "PO-123", "start": 0, "end": 6},
  "reported_eta_text": "2026-10-28",
  "reported_eta_evidence": {"evidence_ref": "existing source ref", "quote": "until 2026-10-28", "start": 0, "end": 16},
  "evidence": [{"evidence_ref": "existing source ref", "quote": "delayed", "start": 0, "end": 7}],
  "provider": {"name": "RULE | QWEN | GEMINI | NONE", "version": "identifier"},
  "review": {"required": true, "reasons": ["AUTHORITY_NOT_ESTABLISHED"]},
  "candidate_only": true
}
```

“Verified” is allowed only when an existing trusted identity/source reader resolves this message identity to a tenant-scoped supplier and supplies its evidence refs. Even then the ETA is a reported candidate, not a confirmed delivery change. The P2 API additionally requires authoritative before/after snapshots, snapshot versions, exact delivery identity/supply binding, ETA-change evidence linked to P2 sources, freshness and transactional deduplication/outbox. C3 cannot supply those facts from language-model output.

### `HumanReviewCandidate` (proposed v1)

The internal C3 result now includes a typed `HumanReviewCandidate` whenever analysis is unknown, failed, conflicting, or otherwise review-required. An approved Backend adapter should map it into the owning review queue with the exact tenant/source snapshot, evidence links, reason codes, and provider/rule provenance:

```json
{
  "contract": "message_intelligence_review_candidate.v1",
  "tenant_id": "tenant from authenticated P1 source read",
  "source": {"message_id": "existing P1 ID", "content_sha256": "stored digest",
    "channel": "source channel", "provider_message_id": "source provider ID",
    "thread_ref": "source thread or null", "reply_to_provider_message_id": "exact parent or null"},
  "intent": "UNKNOWN",
  "review_reasons": ["AI_OUTPUT_INVALID"],
  "evidence": [],
  "provenance": {"provider": "NONE", "version": "unavailable"},
  "analyzed_at": "offset-aware timestamp",
  "candidate_only": true
}
```

The candidate is not a persisted review task and C3 does not write it to a queue. Backend ownership must decide the durable review record, idempotency key, freshness/version check, and permissioned assignment flow.

### P4 reply handoff (proposed, no new API)

C3 may provide an internal `ReplyDraftCandidate` containing tenant, exact source message ID/channel/provider ID/thread/reply parent, verified recipient identity/evidence, source content hash, draft text/subject, fact evidence refs, generator/provenance, expiry/currentness, and `review_required`. It remains unsent. The current P4 `MessageDraftView` requires a P4 `RecoveryCommunicationReference`, approved terms, authorization evidence, verified recipient and channel evidence; current intake is recovery-event scoped. There is no implemented P4 request contract for inquiry replies. Jiahui/P4 must decide whether to extend the existing request authority for inquiries and how inbound sender consent, same-channel routing, source version, and draft review should be bound. No direct call to `OutboundService.send` is allowed from C3.

## Shared invariants and validation rules

- Tenant is supplied by the authenticated server-side source reader, never inferred from the model or accepted from untrusted message text. Every referenced message, attachment, association, identity and evidence record must match that tenant.
- Preserve provider/channel message IDs, original content digest, source timestamp, thread/reply parent IDs, attachment evidence refs, and exact spans. Text spans use Unicode code-point offsets into the immutable original text. Document citations use existing `DocumentEvidence` page/quote/evidence IDs; do not fabricate document offsets.
- An association must be unambiguous and bound to the same source message and tenant. Preserve its existing association ID, version and update timestamp. The current P1 `MessageAssociationRecord` does not expose separate association evidence refs. Sender alias or model-extracted name is not identity evidence. Identity failure, missing currentness, or cross-tenant references fail closed to Human Review.
- Deterministic rules run first. Qwen may return only a strict typed proposal. Invalid schema, incompatible claim kinds, unsupported fields, ungrounded spans, contradictions with deterministic evidence, timeout, provider error, or exhausted budget can invoke one bounded Gemini fallback. A valid Qwen result ends provider evaluation; C3 does not run both providers for consensus. If both attempts fail or validate as conflicting output, the result is an explicit Human Review candidate. Neither output becomes a business fact without the owner’s existing authority.
- Candidate freshness binds source message digest, attachment extraction IDs/versions and extracted timestamps, association version/evidence, rule version, provider/model version, and `analyzed_at`. A changed digest, association, or attachment extraction makes the result stale and requires reevaluation. No freshness TTL is invented by this handoff.
- Provider status should distinguish `AVAILABLE`, `INVALID_OUTPUT`, `TIMEOUT`, `RATE_LIMITED`, `PROVIDER_ERROR`, `BUDGET_EXCEEDED`, and `NOT_CONFIGURED`; the public handoff to Backend is a candidate/review result, not a provider exception or success assertion.
- Logs contain request correlation and safe error classification only. Do not log message text, attachment contents, prompt, API key, recipient address, phone number, or raw provider body. Minimize data sent to providers and exclude sender identity/contact metadata unless strictly necessary and explicitly configured.
- A supplier delay is never written to `p2_supplier_delay_events`, an operational snapshot, commitment, stock record, or Core incident by C3. A customer inquiry never sets OrderRequest state or agreement evidence. A reply draft never means approval, send, delivery, customer assent, or fulfillment.

## Owner decisions and integration dependencies

1. **Jiahui / Backend A–H:** approve the proposed v1 candidate contracts and identify the owning ingestion/Message Intelligence port, candidate review queue and durable evidence reference scheme. No shared A–H route/model is edited by this C3 slice.
2. **P1 owner:** confirm which current source reads provide trusted tenant identity, current message/attachment versions, verified supplier/customer associations, and human review insertion. Current P1-local routes are not evidence of production authentication or stable shared contracts.
3. **Backend B / P2 owner:** define an approved adapter that resolves reported supplier delivery references and ETAs against current authoritative snapshots and returns a version-bound decision; define idempotency and unknown-result reconciliation. The existing P2 route returns unavailable without P5 processor/outbox.
4. **Jiahui / P4 owner:** define whether inquiry drafting is in scope for P4, the authorized request evidence, consent/recipient binding, channel restriction, and how the source candidate binds to existing review/send. Current P4 mock flow is recovery-scoped; C2 real transports are unmerged and internal-only.
5. **Product/security owner:** approve Qwen/Gemini data handling, region/endpoint, retention, token and cost limits, allowed source fields, fallback policy, and any verified sender registry. Provider credentials and provider terms are operational prerequisites; lack of credentials means fixture-only evidence.
6. **C1 owner:** confirm final canonical persistence/source-evidence interfaces after C1 lands. C3 must adapt through an approved reader rather than copy unmerged schema/persistence code.

## C3 implementation promise

The C3 branch adds only a side-effect-free analysis/provider package, typed candidate contracts, fixture-based contract tests and integration documentation. It consumes current P1 extraction/attachment evidence through adapters. It adds no migrations, persistence tables, mounted routes, shared A–H changes, OCR changes, P2 mutation calls, or P4 authorization/send paths. Any dependency unavailable in current main remains explicitly blocked for integration and is not represented as live. See [C3 message intelligence setup and evidence status](../C3_MESSAGE_INTELLIGENCE.md).
