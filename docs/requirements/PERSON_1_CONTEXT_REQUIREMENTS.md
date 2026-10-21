# Person 1 — Omni-Channel Business Context Intelligence

> **Owner**: P1 · **Type**: Full-Stack (frontend + backend + AI + tests) · **Deadline**: 25 Oct 2026
> **Must read first**: `REQUIREMENTS_SYSTEM.md` + `AGENTS.md`; any conflicting local assumption must be escalated in `TEAM_LOG.md`.
> **Scope goal**: Convert fragmented customer/supplier inputs into a reliable, evolving **BusinessContext**. **Do not** promise delivery, verify payment from screenshots, modify confirmed commitments, or build a separate ERP.

## 1. Definition of Done / User Journey

A staff member receives a WhatsApp-like request, email, or Telegram-like message. They can see its source, AI-extracted information, validation/evidence, confidence or uncertainty, and proposed order association. They can correct fields or resolve ambiguity. The committed structured context is persisted, versioned, and published to the shared Commitment Core. A later message can update the same OrderContext without silently overriding already-confirmed terms.

**P0 acceptance**: With synthetic input, `I need 100 burgers tomorrow before 3pm` becomes a valid `BusinessContext` with `sku`, `quantity`, localized delivery time, source span, missing-field status; a follow-up for the same verified order updates the existing context; an ambiguous "same as last time" message must not be linked to a random order; corrections persist and are audited; frontend uses real backend API at integration time.

## 2. Frontend Ownership

**Routes**: `/inbox`, `/orders/:id` (add nested review drawer/panel if needed). Use shared App Shell, Query Client, reusable badges/dialog from P5.

### FE-01 Smart Inbox
- [ ] Synthetic channel tabs/filters: `ALL`, `WHATSAPP`, `EMAIL`, `TELEGRAM`, `UNKNOWN` (do not label adapter "live" if synthetic).
- [ ] Message list: channel, sender alias, date/time, processing status, related order (if verified), unread/review needed.
- [ ] Message detail: original text, attachment previews/evidence links, extracted fields, provider identifier, processing history.
- [ ] "Process / Reprocess" safely idempotent; show progress/loading/failure and backend diagnostic reason.
- [ ] Invalid/ambiguous status must be visible (never visually imply resolved).
- [ ] No permission to reveal other tenants' messages.

### FE-02 Structured Extraction Review
- [ ] Editable fields: customer reference, SKU/product, quantity, unit, requested delivery, special instructions, optional payment evidence metadata.
- [ ] For each extracted field display original value, source evidence, validation status, and who corrected it.
- [ ] Missing information list + conflict list, with explicit confirmation before applying a material correction.
- [ ] Order-match candidates with reasons; **manual confirm** for fuzzy/uncertain linking. Disable unsafe auto-link.
- [ ] Review actions `Accept Extraction`, `Edit Field`, `Request More Information`, `Link to Order`, `Mark Unresolved`; same backend enforcement.

### FE-03 Order Context Detail
- [ ] Consolidated current fields and source history, context version, last update, known/unverified identities, linked messages.
- [ ] Highlight differences between new message and current order context; keep older snapshots accessible.
- [ ] If matched order already has a confirmed commitment, route material term change as **proposed change** to Core instead of overwriting commitment.
- [ ] Loading/Empty/Error/Permission/Retry/Unresolved states; mobile-width usable with keyboard focus and labels.

## 3. Backend Ownership

**Suggested module**: `backend/app/context/` with `router.py`, `schemas.py`, `service.py`, `repository.py`, `ingestion.py`, `models/` (inference adapters), `tests/`. P5 owns shared database migration; P1 proposes domain tables in PR and coordinates migration.

### BE-01 Channel Ingestion
- [ ] Define provider-agnostic `RawMessageEnvelope` with tenant, channel, provider_message_id, sender identity, received_at, text, attachments.
- [ ] Adapter interface: `parse_webhook`, `fetch_attachment`, `acknowledge`; implement a **synthetic adapter** fully for P0; production channel adapters only P1 roadmap.
- [ ] In P0 validate a declared fake provider signature or explicitly mark mock; in production official signature/secret verification.
- [ ] Persist raw inbound record *before* processing; unique `(tenant_id, channel, provider_message_id)` constraint and safe duplicate handling.
- [ ] Preserve provider reply/thread reference, timestamp, language if known, and source metadata; never mix channels/tenants.
- [ ] Async processing may use outbox + worker; recovery and failed/retry state required.

### BE-02 Normalization
- [ ] Normalize text/attachments to Canonical Message Schema with UTC storage + offset-aware display; detect/normalize units and dates carefully (avoid interpreting "tomorrow" without message local timezone).
- [ ] Source provenance records: original content hash, message id, attachment id, text span/page, extraction method and version.
- [ ] Distinguish `INFORMATION_READY`, `INFORMATION_PARTIAL`, `CONFLICT`, `UNRESOLVED`, `PROCESSING_FAILED`.
- [ ] File validation: extension/MIME/size, safe PDF parsing, bounded OCR runtime, avoid raw file path injection.

### BE-03 Progressive Extraction Pipeline
- [ ] **L0 deterministic**: explicit order references, regular number/date formats, known SKU lookup, idempotent duplicate detection.
- [ ] **L1 specialized AI**: GLiNER multilingual entity extraction; optional XLM-RoBERTa **only if fine-tuned/evaluated** for the actual intent labels, else rules and measured fallback. Remember base model alone is not a classifier.
- [ ] OCR via PyMuPDF first for machine-readable PDF; PaddleOCR fallback only for scans/images. Record OCR failure/uncertain spans.
- [ ] **L2 selective Qwen3**: unclear or fragmented multi-message interpretation; strictly structured output validated by Pydantic; only selected context sent, no arbitrary tool execution.
- [ ] Data validators: positive quantity, known unit, SKU/customer domain lookup, nonpast delivery handling with business exceptions, conflicting edits, malformed currency.
- [ ] High-uncertainty/conflicting results remain proposed, not automatically promoted into confirmed records.
- [ ] Cache repeated extraction keyed by sanitized content hash + model version (P1 optional if deadline permits).

### BE-04 Identity and Order Association
- [ ] Distinguish `platform_identity`, `customer_account`, `verified_link` and `sender_name_similarity`.
- [ ] Deterministic match first: valid order reference + permission + verified identity or relevant thread mapping.
- [ ] Fuzzy candidate ranking may use multilingual E5 + pgvector or RapidFuzz but **cannot establish identity** or override hard conflicts.
- [ ] Multiple candidate orders, conflicting dates/products or unverified sender → `REVIEW_REQUIRED` / clarification.
- [ ] New message updates an existing OrderContext using optimistic concurrency; preserve `context_version` and field provenance.
- [ ] Confirmed Commitment terms cannot be directly mutated. Publish a proposed amendment or change request to P5.

### BE-05 Payment Evidence (Narrow Scope)
- [ ] Extract receipt image text, amount/reference/payment method with OCR when relevant; label `UNVERIFIED_EVIDENCE`.
- [ ] Trusted payment status may be read from a **synthetic trusted-transaction fixture**; never call receipt presence `PAID`.
- [ ] No real payment processing, payout, refund, bank identity assertion, or real provider integration for competition.

## 4. Contract & API Obligations

Use `BusinessContext` and `DomainEvent` from `REQUIREMENTS_SYSTEM.md`; coordinate exact generated types with P5.

**Suggested endpoints** (P5 to ratify names):

```text
POST /v1/messages/ingest                  # idempotent synthetic/adapter input
GET  /v1/messages                        # scoped/filterable inbox
GET  /v1/messages/{message_id}
POST /v1/messages/{message_id}/process
GET  /v1/contexts/{context_id}
PATCH /v1/contexts/{context_id}          # expected_context_version required
POST /v1/contexts/{context_id}/link-order
POST /v1/contexts/{context_id}/review
```

**Events**: `business.context_created`, `business.context_updated`, `business.context_review_required`, `business.proposed_amendment`, `payment.evidence_received`.

**Inputs needed from P5**: `tenant_id`, `UserRole`, `CommitmentRef`, `AuditEvent`, versioned context schema. **Outputs consumed by P2**: structured SKUs, quantities, proposed deadlines, linked order/commitment IDs, evidence and readiness.

**Cross-team blockers**: cannot finalize SKU validation without P2 inventory fixture; coordinate approved demo SKU list on Day 1. P1 does not own `/communications` or outbound confirmation state—that is P4.

## 5. Data Entities (P1 ownership; migration coordination with P5)

`channel_connections` (mock/production indicator), `inbound_messages`, `message_attachments`, `extracted_entities`, `field_evidence`, `customer_channel_identities`, `verified_identity_links`, `order_contexts`, `order_context_versions`, `context_reviews`, `payment_evidence`.

Rules: immutable original message; append changes/version; sensitive attachments in bounded private storage; never store user auth tokens in logs; tenant-scoped indexes.

## 6. Testing Requirements

**Unit tests**:
- Correct parse of products/quantities/localized dates; code-switching fixtures where possible.
- Missing product, malformed quantity, unknown SKU, OCR failure, ambiguous delivery date.
- Base XLM-R not silently claimed trained; inference unavailable → safe fallback/unresolved.
- Context version conflict → 409; wrong tenant → 403/404 policy.
- Same message delivered 2× → one logical inbound record.
- Same customer has 2 orders; fuzzy similarity alone does not autolink.
- Receipt screenshot without trusted provider → `UNVERIFIED_EVIDENCE`.

**Frontend tests**: source evidence renders, review/edit persistence, ambiguity banner, loading/error states, invalid link disabled.

**Integration test**: POST inbound message → persists normalized context → event consumed by P5/P2 → commitment request linked, evidence retrievable, audit recorded.

**Measurement**: provide labelled synthetic dataset; report intent accuracy and extracted field precision/recall with sample counts; calculate wrong-order auto-link rate separately. Do not inflate scores from tests using the same examples as prompts.

## 7. Timeline / Parallel Start

| Date | P1 exit criterion |
|---|---|
| 20 Oct | Routes/components/API mocks; ingestion and context fixtures; contract handshake with P2/P5 |
| 21 Oct | Backend extraction + frontend Smart Inbox; safe link/review path |
| 22 Oct | Live API integration, DB and correct `BusinessContext` event, corrections persisted |
| 23 Oct | Join full E2E; regression on multiple messages/conflicting order |
| 24 Oct | Finish tests, metrics and UX polish; freeze |
| 25 Oct | Bugfix only / submission support |

## 8. P0 vs Production Roadmap

**P0**: synthetic multi-channel envelopes, at least one integrated channel fixture, deterministic extraction + optional evaluated model, context matching/review, evidence/versioning, UI, events, tests.
**Production later**: Meta Cloud API real lifecycle, Gmail watch/history, Microsoft Graph delta, Telegram authorization, full OAuth, supplier OCR document types, model fine-tuning, large-scale language benchmarks.
**Do NOT build**: separate financial reconciliation product, real payment processing, direct Commitment state writes, self-training LLM.

## 9. Handoff Checklist

- [ ] Types compatible with `contracts/`; every API has sample request/response and an error example.
- [ ] F2 can consume a successful BusinessContext without additional manual conversion.
- [ ] P5 can link Context to Commitment safely; field corrections are audited.
- [ ] React routes reachable through shared navigation; backend services callable without browser hacks.
- [ ] Tests and README commands committed; no missing environment instructions.
- [ ] PR references `TEAM_LOG.md` updates and provides truthful implementation status.
