# C2 → P4 provider boundary — PROPOSED, owner approval pending

Frozen Main: `1c34b8dbcdd944b60c856ceb7a5dd7ada890564f`. Owner decision requested from Jiahui on [#96](https://github.com/jiahui-1101/MouManTAI/pull/96#issuecomment-6388431518). This document creates no runtime authority or approved schema. #95 remains separately owned; its pending milestone intent is NOT_SENT and is not permission to call a provider.

## Authoritative outbound envelope

P4 must resolve every field server-side, using existing request/draft/review/outbound/send-attempt records. C2 must not accept an HTTP/client claim of approval, role, contact verification or consent. Proposed port input:

| Field group | Required evidence / owner |
|---|---|
| `tenant_id`, authenticated principal, authorized action/scope, correlation ID | P4/P5 authorization, not adapter configuration |
| source event ID/type/schema/version, Commitment/proposal/version where applicable | Existing business authority; no adapter-generated milestone |
| approved draft ID/version, exact content hash and required disclosures | P4 approved draft, current review and redaction |
| verified contact identity/version, verification evidence/time/freshness policy | Trusted P1 contact source; a provider-authenticated message is not a verified human |
| purpose-specific consent/preference ID/version, effective time and revocation state | P4 consent authority; revised-terms consent is not ORDER_STATUS_UPDATE consent |
| exact recipient, channel/provider/account identity, originating native parent ID and conversation | P4 resolves against contact and C1 evidence, never sender/Reply-To inference |
| durable outbound intent ID, stable idempotency key, payload fingerprint, authorization expiry | Existing P4 persistence, single-submission/UNKNOWN reconciliation guards |

Recheck action permission, approved content/version, contact freshness/recipient binding, purpose consent and account/channel readiness immediately before dispatch. Revocation, stale terms, changed recipient/content or unknown contact blocks dispatch. Configuration/test allowlists are additional restrictions, never authorization. Emergency approval, order acceptance and supplier selection grant no unrelated communication authority.

## Transport and receipt mapping

The current `OutboundProvider` is mock-only and returns SENT/FAILED/DELIVERY_UNKNOWN. Do not silently map a real provider's HTTP acceptance into SENT. Jiahui/P4 must approve any additive status/port change before implementation.

| C2 observation | Meaning / required P4 treatment |
|---|---|
| ACCEPTED with provider ID | Request accepted by provider; retain submission evidence, not proof of delivery/assent |
| REJECTED with classified error | Known refusal; persist failure reason and apply P4-approved retry policy |
| UNKNOWN, timeout, malformed 2xx or ambiguous acknowledgement | Persist uncertainty; reconcile provider status before deliberate retry; never automatic POST retry |
| Authenticated SENT / DELIVERED / READ / FAILED callback | Append deduplicated transport observation; not customer agreement or fulfilment |

Proposed durable receipt fields: tenant, outbound intent ID, provider, provider account, provider message ID, provider event ID (or approved deterministic digest), original status, normalized status, provider event time (nullable if invalid), ingest time, raw evidence reference/permitted digest, correlation ID and authentication/account verification evidence. Bind callbacks to the exact existing outbound intent by tenant/provider/account/provider ID. Unknown/cross-account callbacks are unresolved, not guessed. Reject forged signatures; preserve out-of-order events and derive a safe status projection without overwriting immutable evidence.

Use existing P4 outbound/send-attempt/audit ownership, not a second message/receipt authority. Any additive persistence mapping requires entity-level reuse mapping and designated review. Current `ProviderStatusReceipt` lacks durable event/account/evidence correlation and is not an approved durable port. Telegram has no universal delivery/read callback; do not invent one. Resend and WhatsApp callbacks are fixture-normalized only. Process-local idempotency cache does not survive restart/eviction and cannot replace durable P4 intent.

## Resend canonical source proposal

P1 currently derives EMAIL provider as GMAIL_API. Requested additive `RawMessageEnvelope.source_provider` enum, channel/provider validation, repository/read-label change and an additive constraint migration allowing RESEND in the same `p1_dev.inbound_messages` store. Absent field preserves historical behavior; no guessed backfill or Gmail rewriting. Public ingest remains SYNTHETIC. Existing account/native unique indexes and exact-parent queries remain authoritative. Downgrade must refuse before DDL if RESEND evidence remains. Changes to shared envelope/repository/test repository/constraint await Jiahui approval; none are implemented here.

C2 now requires `RESEND_ACCOUNT_ID` to be an explicitly configured receiving mailbox included in `RESEND_INBOUND_ADDRESSES`. It cross-checks signed-event and API recipient routing and provider-native ID, preserving RFC Message-ID separately. Until the shared change is approved, Resend ingress returns `503 RESEND_CANONICAL_PROVIDER_CONTRACT_UNAPPROVED` before retrieval/persistence. Parsed envelopes remain UNVERIFIED for canonical ingestion, preventing a direct-ingestion bypass. No false GMAIL_API source is written.

## Decisions required

Jiahui: approve/reject the precise Resend additive proposal; nominate the approved P4 contact/freshness/consent rules and durable receipt/status mapping; review #95 compatibility separately. Final integration HEAD review, Ready-for-Review process and explicit merge authorization remain separate gates. No live outbound is enabled by this proposal.
