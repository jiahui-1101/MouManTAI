# Backend A ↔ Backend B integration contract — proposal

Status: **PROPOSED; owner review required.** This is a typed, side-effect-free data boundary for Backend B to validate an order candidate. It is not an acceptance command, event schema, authorization token, reservation receipt, or approval of S1–S5.

The code representation is `AcceptanceCandidate` in `backend/app/orders/context_mapping.py`. It contains the existing canonical `OrderTerms` from `backend/app/orders/terms.py`; it does not redefine terms.

## Authority and source of truth

- P1 remains authoritative for inbound messages, provider/channel identifiers, extraction/evidence, customer/order associations, OrderContext, context versions, and human review evidence.
- A trusted Backend A server adapter must retrieve these records tenant-scoped and construct `OrderCommercialEvidence` only from an authoritative approved catalog/quote and disclosure/policy source. The mapper checks that the supplied commercial evidence is bound to the same tenant, customer, context and context version, and that the supplied source-authority evidence matches the source ID/version. A pure function cannot authenticate that adapter's claims or guarantee the records remain current after it returns.
- PR #48's immutable `OrderTerms` is the one canonical binding-terms contract. Its v1 hash and `compare_terms()` establish binding commercial-value equality only. The v1 hash intentionally excludes revision and evidence-reference IDs for compatibility and provenance correction; matching hashes do not prove that disclosure exists, is current, unrevoked, tenant-scoped, related to the terms, or acknowledged by the customer.
- Disclosure proof/currentness is a separate trusted server-side evidence boundary. The adapter must resolve the exact disclosure record and a currentness lookup for that exact disclosure, tenant and customer, and return verified authority references and a checked-at time. The pure mapper checks these bindings/statuses and fails closed on missing, stale, revoked, unknown, unrelated or cross-tenant evidence; it cannot authenticate adapter claims or establish a freshness TTL. Backend B must independently reread persisted evidence before any decision.
- A legitimate provenance-reference correction may change evidence refs while preserving the same binding `order-terms-v1` hash. It is valid only when the trusted adapter resolves the corrected refs to current evidence for the exact same terms. A change to binding commercial values requires a separate versioned proposal workflow.
- A future durable OrderRequest is a separate P1/P5-reviewed persistence slice. The mapper does not mint an `order_request_id`; absent request identity keeps the result incomplete.
- Backend B owns operational snapshots, feasibility, SME actor authority, decision and reservation orchestration, reservation receipts, and guarded Core transitions. Backend B must independently reread authoritative persisted records and revalidate before acting.
- P4 remains the authority for communication transport/consent and verified inbound customer responses. This mapper does not send messages or create assent evidence.

## AcceptanceCandidate fields

The implemented candidate contains:

| Field | Meaning |
|---|---|
| `tenant_id` | Tenant on the P1 context; all loaded sources and terms must bind to it. |
| `order_request_id` | Optional existing ID from a trusted internal adapter. No ID is synthesized. |
| `source_context_id`, `source_context_version`, `source_context_version_record_id` | P1 context identity and exact version record used for this snapshot. |
| `context_review_actor_id`, `context_review_actor_role`, `context_reviewed_at` | Provenance from a matching current P1 review; not SME acceptance authority. |
| `existing_order_id` | Existing P1 verified order association, if present. |
| `terms_revision`, `terms_hash`, `canonical_terms` | Revisioned canonical PR #48 OrderTerms and its deterministic hash; populated only after mapping and validation succeed. |
| `customer_id`, `customer_identity_evidence`, `customer_identity_associations` | P1 customer linkage; association IDs and immutable snapshots of the association version, message, tenant, customer and update timestamp used by the mapper. |
| `source_message_ids`, `source_evidence_refs` | P1 source messages, version/review/evidence/association and accepted commercial evidence references. |
| `price_source_ref`, `price_disclosure_evidence` | Price-source ID and structured disclosure records. Each record binds tenant/customer/context/version, OrderRequest ID, terms revision/hash, source ID/version, disclosure time, evidence ref and verification authority. Currentness additionally binds status, checked-at time, lookup ref, exact disclosure ref and currentness authority. Hash equality does not substitute for these checks. |
| `agreement_basis` | Currently always `UNKNOWN`; the mapper does not infer agreement from review or a terms hash. |
| `proposal_id`, `proposal_version`, `customer_assent_evidence` | Reserved optional fields for a future P1/P4 exact proposal response contract; currently empty. |
| `readiness_status`, `validation_reason_codes`, `missing_fields`, `conflict_fields` | Preparation result and precise, non-lifecycle reasons. |

The code also uses `OrderCommercialEvidence` as an internal adapter input for exact lines, fulfillment method/location/window/timezone, currency, fees/tax/discount/total, price source/version/authority, structured disclosure records and binding policy. This is not an external API schema. Missing currentness defaults to `UNKNOWN` and fails closed. `STALE`, `REVOKED`, `UNKNOWN`, missing lookup metadata, a lookup for another disclosure, a lookup before disclosure, or mismatched tenant/customer/context/terms/source fails closed. No max-age/TTL is invented here; the trusted adapter must apply an approved freshness policy, and Backend B must reread current evidence. The authority refs remain adapter assertions until such a trusted adapter is wired.

Failed candidates do not echo the existing order ID, commercial request ID, terms revision, price-source ID, or disclosure records from an unverified association or otherwise unvalidated commercial snapshot. These identifiers and details are exposed only for `READY_FOR_VALIDATION` with validated canonical terms. Even if canonical `OrderTerms` validation fails before disclosure binding, the failure result carries only trusted P1 base references, not unverified commercial source/disclosure refs. Current P1 review timestamps must be timezone-aware; naïve or mixed-naïve review records return `REVIEW_REQUIRED` without attempting to sort them.

## Readiness semantics

`READY_FOR_VALIDATION` means only that this pure mapper validated the supplied, internally consistent snapshot and built canonical terms. It does not mean `FEASIBLE`, accepted, reserved, confirmed, or guaranteed to fulfill.

Other outcomes are explicit preparation results:

- `INCOMPLETE`: required source, review, commercial field, evidence, request reference, or binding term is missing.
- `REVIEW_REQUIRED`: human resolution is needed for ambiguity, unsupported pickup mapping, association/order-link state, or current Core revalidation.
- `STALE_SOURCE`: current context version/snapshot is missing or inconsistent.
- `IDENTITY_UNVERIFIED`: the context or message associations do not establish a verified customer link.
- `TERMS_CONFLICT`: the supplied sources disagree, tenant/customer/version bindings fail, evidence conflicts, or canonical terms fail validation.
- `PRICE_SOURCE_UNVERIFIED`: approved source authority evidence is missing or does not match tenant/customer/source ID/version.

These are candidate preparation statuses only. They do not add a shared Commitment lifecycle state.

## Mapping and fail-closed rules

The mapper checks that:

1. The supplied P1 version record matches tenant, context ID, version and exact serialized context snapshot.
2. Source message IDs are unique and exactly correspond to supplied message records; messages and evidence source references bind to the context tenant/source set.
3. Each message has a verified association to the expected customer/order. Ambiguous, conflicting, absent or mismatched association does not auto-resolve.
4. A current P1 `ACCEPT_EXTRACTION` or `EDIT_FIELD` review matches the context version and stored review actor/time.
5. Required context fields have evidence references. Context conflicts, unresolved status or missing fields are not mapped as complete terms.
6. Commercial evidence binds to the same tenant/customer/context/version; SKU, quantity string value and unit match P1 exactly; no unit conversion or inferred price occurs.
7. A source authority record explicitly binds the approved source ID and version to the tenant/customer. At least one disclosure record must be verified and current through the trusted adapter. Its tenant/customer/context/version/request/terms revision/hash/source ID/version/disclosure time must match the exact canonical terms; its disclosure ref must belong to the declared price-source evidence; and its currentness lookup must name that exact disclosure and carry a checked-at time no earlier than disclosure. Missing, stale, revoked, unknown, unverified, unrelated or mismatched disclosure data fails closed even when the commercial hash matches.
8. Delivery requires a complete canonical window and valid timezone. Non-UTC local timestamps must use the named zone's actual offset. A matching explicit offset selects one fold of a repeated local hour; a missing/mismatched offset or nonexistent wall time fails closed. An explicit UTC instant is accepted and canonicalizes to the same UTC value as its equivalent local representation. The P1 requested value must be an explicit `DEADLINE` exactly equal to the supplied window end. Relative/ambiguous dates fail review. P1's current context does not model pickup; pickup returns review-required.
9. PR #48 `OrderTerms.model_validate` validates currency, amounts, totals, timezone/offset consistency, policy, source messages and evidence. `require_exact_terms()` additionally requires the proposed revision to equal the authoritative original revision on the unchanged-original-offer path. Revision equality is not assent; changed offers require a separately verified proposal/version/customer-assent workflow. Existing Core terms, if supplied, must match binding commercial values or the candidate returns a conflict that requires a new proposal path.

P1 context currently does not supply approved commercial prices, price-source versions, disclosure proof, currency, fees, tax, discount, total, fulfillment method/location, full delivery window/timezone, or a durable request ID. The mapper never fills those gaps with defaults or generated values. Every verified message association's ID and version are preserved in the candidate so Backend B can re-read the exact identity-link state it validates.

## Agreement and lifecycle distinctions

The conceptual agreement basis distinguishes:

- `CUSTOMER_ORIGINAL_OFFER`: exact customer-originated terms, with source evidence.
- `MATERIAL_AMENDED_PROPOSAL`: a distinct, versioned proposal that changes binding terms.
- `CUSTOMER_ASSENTED_PROPOSAL`: explicit P4-verified assent to the exact proposal ID/version/terms hash/identity before expiry.
- `UNKNOWN`: available evidence does not establish one of the above.

Only `UNKNOWN` is emitted today. Original offer attribution and exact assent remain a future P1/P4 contract. A matching hash never creates a disclosure validation result or assent receipt. `require_exact_terms()` guards an unchanged original revision and likewise does not establish customer assent. `REQUESTED`, `FEASIBLE`, `APPROVED`, `RESERVED`, `SENT`, `ACCEPTED`, and `FULFILLED` remain distinct states/evidence under their owning authorities; this candidate causes no transition.

## Backend B consumption requirements

Before a decision or consequential operation, Backend B must load current tenant-scoped state and revalidate:

- tenant, customer and order-request binding;
- latest P1 context/version/review and source-message associations;
- latest canonical terms revision/hash and any existing Core commitment/proposal;
- customer agreement or P4 exact proposal-assent evidence, including identity, proposal ID/version/hash and expiry;
- verified SME actor/role and authorized decision scope;
- current P2 operational snapshot and feasibility result;
- idempotency key, actual reservation result and durable provider receipt/status;
- Core transition preconditions and audit/outbox work in the same guarded transaction as applicable.

A candidate is stale immediately if any referenced source changes. It is unsuitable as a durable authorization or retry token.

Backend B must return unknown/pending/error distinctly when an authoritative read or reservation outcome cannot be verified. It must not infer acceptance from feasibility or a successful enqueue, infer fulfillment from a send, or treat a local stock sample as live Orbyte evidence.

## Future Backend B → Backend A read-only boundary

Backend A needs a customer-scoped projection for customer status and a separate operational decision projection for internal use. Backend B/Core remain authoritative writers. A future typed read response should reference, rather than duplicate, the authorities:

- tenant, order-request, commitment, source context/version and terms revision/hash references;
- Backend B decision/assessment ID, status, snapshot/version and evaluated timestamp;
- reservation operation/receipt reference and status, with provider/source and freshness when available;
- Core commitment state/version and audit/event references;
- customer-visible milestone/status, its source evidence and freshness;
- explicit `UNKNOWN`, `PENDING`, `FAILED`, or `STALE` where a result is not authoritative.

Exact DTO field names and status vocabulary are **pending Backend B, P1, P4 and P5 review**. Backend A may display or explain a returned projection but cannot author it, convert a backend decision into Core state, or claim customer acceptance/fulfillment from an intermediate status. The response should omit internal operational details from customer-facing projections unless approved policy allows their disclosure.

## Review questions / pending decisions

1. Backend B: confirm its persisted source lookup and revalidation boundary; whether it consumes the Python DTO directly or a versioned API/event contract; which request and decision identifiers it owns.
2. P1: confirm current context/version/review/message/association provenance and whether exact source evidence IDs are sufficient for future adapters.
3. P5: confirm Core commitment/proposal references and expected audit/outbox boundary; confirm source context's existing `core_commitment_id` handling.
4. P4: define the verified inbound assent evidence shape, sender identity binding, exact proposal/hash/version binding and expiry.
5. Product owner/P5: ratify or leave S1–S5 open; no policy is approved by this proposal.
6. Backend B/P2: define authoritative snapshot freshness and reservation receipt semantics, including unknown timeout reconciliation.
7. PR #48/P5/P1: review the foundation hardening on the stacked Backend A branch: unchanged-original revision equality guard; strict named-timezone/offset validation with explicit fold selection; and trusted disclosure-currentness evidence separate from hash equality. The `order-terms-v1` hash definition is unchanged, but previously accepted local timestamps with incorrect offsets may now fail validation. See PR #50 and the 2026-10-24 handoff checkpoint.

No migration, route, acceptance/decision engine, live provider operation, or shared lifecycle contract is introduced by this proposal.
