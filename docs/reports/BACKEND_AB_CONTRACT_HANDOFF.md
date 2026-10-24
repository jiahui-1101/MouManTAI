# Backend A ↔ Backend B pending-order contract handoff (proposed)

**Status:** Review draft, 2026-10-24 SGT. No shared schema, persistence model, API or acceptance command is implemented by this document. Backend A owns the candidate and canonical terms; Backend B owns the operational evaluation. The current P2 evaluator has no valid pending-order target representation. [B2 findings](BACKEND_B_B2_PENDING_ORDER_FEASIBILITY.md) explain why.

## 1. AcceptanceCandidate: proposed read contract

The consumer should obtain a **persisted, versioned projection** through a tenant-scoped server-side reader, ideally `read_current_candidate(verified_principal, order_request_id, expected_request_version)`. A browser/LLM payload may contain lookup IDs and optimistic version tokens, never the authoritative candidate. Candidate state must be `PENDING_ACCEPTANCE` or the explicitly reviewed proposal-assent equivalent; a P1 context or a legacy Core `REQUESTED/CONFIRMED` record is not a substitute. P5 should agree the ownership and lock order before a transactional implementation.

The table is the proposed minimum interface. “Re-read” means resolve the cited persisted authority independently at evaluation/decision time; it is not enough to echo fields from a DTO. `R` = required for a complete original-offer candidate; `C` = conditional for a proposal, source type or decision stage. All field names and persistence locations require Backend A/P5 review because PR #48 contains no persisted OrderRequest/AcceptanceCandidate. A conflict in any identity/version field fails closed and returns no FEASIBLE pending-order decision.

| Field | Owner and authoritative source | Req. | Backend B re-read and freshness/version rule | Review |
|---|---|---|---|---|
| `tenant_id` | A request store under verified tenant principal; P5 identity boundary | R | Query scoped by authenticated tenant; never accept client header as production identity; mismatch → `NOT_FOUND`/`TENANT_MISMATCH` | A/P5 |
| `order_request_id` | A OrderRequest primary identity | R | Load exact persisted row; no Core `order_id` alias by assumption; wrong ID → `NOT_FOUND` | A/P5 |
| `customer_id` | A customer identity link backed by P1 verified source | R | Re-read request/customer link and verified inbound identity; wrong/ambiguous customer → `IDENTITY_UNVERIFIED` | A/P1/P5 |
| `request_version` | A versioned OrderRequest row | R | Compare supplied expected version to current locked/read version; change → `REQUEST_VERSION_CONFLICT` | A/P5 |
| `terms_revision` | A canonical persisted terms revision | R | Require current revision and proposal relation; mismatch → `TERMS_VERSION_CONFLICT` | A/P5 |
| `terms_hash` | A canonical `app.orders.terms.OrderTerms.terms_hash` | R | Recompute from authoritative terms; hash match proves equality only; mismatch → `TERMS_MISMATCH` | A/P5 |
| `canonical_terms_ref` **or immutable terms** | A canonical OrderTerms persisted revision, PR #48 type after fixes | R | Load immutable exact revision; compare tenant/request/customer and binding fields; do not define B-owned OrderTerms | A/P4/P5 |
| `source_context_id` | P1 persisted OrderContext / A request lineage | R | Re-read tenant-scoped context; absent/changed mapping → `SOURCE_CONTEXT_CONFLICT` | A/P1 |
| `source_context_version` | P1 versioned context row | R | Compare recorded version and source spans; changed → `SOURCE_CONTEXT_CONFLICT` | A/P1 |
| `source_evidence_refs` | P1 preserved inbound evidence and A request linkage | R | Resolve each reference to tenant/request/customer/field/source record; arbitrary nonempty string is insufficient; missing → `EVIDENCE_INCOMPLETE` | A/P1/P5 |
| `customer_assent_status` | A agreement evidence state, with P4 verified confirmation for counteroffers | R | Original explicit offer must be evidenced; proposal requires explicit exact assent; `UNKNOWN` → `ASSENT_UNVERIFIED` | A/P4/P5 |
| `customer_assent_evidence_refs` | A/P4 inbound verified message/confirmation rows | R | Re-read sender/identity/channel, time, exact offer context; no generic “OK”, outbound SENT or LLM extraction | A/P4/P5 |
| `assent_terms_hash` | A/P4 exact acknowledged offer/proposal digest | R | Match current canonical hash and proposal/version; equality alone never authenticates sender | A/P4/P5 |
| `proposal_id` | A/P4 persisted proposal | C | Required for changed terms; load exact active proposal and reject stale/superseded ID | A/P4/P5 |
| `proposal_version` | A/P4 persisted proposal version | C | Compare current active version/digest/expiry; conflict → `PROPOSAL_VERSION_CONFLICT` | A/P4/P5 |
| `price_source_id` | Approved catalog/quote source controlled by business/P5 port, referenced by A terms | R | Re-read approved source, tenant, item scope and exact amount/fees; missing/unapproved → `PRICE_SOURCE_UNVERIFIED` | A/P5 |
| `price_source_version` | Immutable catalog/quote revision | R | Compare current approved or historically valid disclosed version; changed → `PRICE_SOURCE_VERSION_CONFLICT` | A/P5 |
| `price_disclosure_evidence_refs` | A/P4 preserved whole-offer disclosure/acknowledgment | R | Resolve receipt to identified customer and exact full offer, including fees; absent → `PRICE_DISCLOSURE_UNVERIFIED` | A/P4/P5 |
| `created_at`, `updated_at` | A immutable creation and versioned update timestamps | R | Require aware timestamps; useful for audit/currentness, not a substitute for row version; anomalous order → `CANDIDATE_INVALID` | A/P5 |
| `correlation_id` | A request lineage / P5 event envelope | R | Carry through reads/evaluation; never use as identity or idempotency authority | A/P5 |

The table specifies **authoritative checks**, not a claim that those tables or ports exist on main. Backend A should publish a persisted read interface and examples for unchanged original offer, exact counteroffer assent, incomplete disclosure and conflicting extraction. PR #48's current `terms.py` supplies a pure type but no authenticated source lookup. Its known evidence-ref, proposed-revision and timezone/DST issues remain A-owned; the recorded S1 approval in this chat should be added to the shared decision trail before workflow activation.

## 2. Operational target handoff and supported scope

Required, reviewed adapter input after candidate verification: tenant/request/customer IDs and versions; canonical terms hash/revision; **each** normalized SKU, variant, Decimal quantity/unit, deadline/window with zone, fulfilment location; source context and disclosure/assent refs; selected P2 operational snapshot ID/version/current token; a **verified** mapping to a P2 SKU/BOM, material-use time/warehouse and production plan where needed. A missing mapping remains `UNKNOWN/REVIEW_REQUIRED`. Price/cost is an agreement check, not a stock or capacity input. Supplier quote is never inventory.

Main's `service.evaluate` requires a `Commitment` with `agreement_state=CONFIRMED` and a matching row in `OperationalSnapshot.confirmed_commitments`, then one line and matching Core terms (`service.py:101-134`). `bom.explode_bom`, `inventory.calculate_atp` and `capacity.check_capacity` iterate those confirmed rows; production plans are keyed by commitment/line. A pending order cannot safely be inserted there and described as confirmed. B2 supports **snapshot readiness characterization only**, no FEASIBLE pending-order result. Multi-line is unsupported for the current legacy target adapter; it must not be collapsed to one line. A future P2-owned provisional-target extension should keep confirmed demand fixed and compute the joint projection with the same ATP/BOM/capacity kernels and explicit allocation policy. It needs P2/P5 review and tests for competition, missing mapping, deadlines and identity.

## 3. Proposed OrderDecision response

Return separate dimensions, with no writable duplicate of Core state:

```text
tenant_id, order_request_id, request_version, correlation_id
evaluated_terms_hash, terms_revision
operational_snapshot_id, operational_snapshot_version, evaluation_timestamp
readiness_status: INCOMPLETE | CURRENT | STALE | UNSUPPORTED
missing_evidence[], blocking_reasons[], evidence_tier
feasibility_status: NOT_EVALUATED | FEASIBLE | INFEASIBLE | UNKNOWN | CONDITIONAL
constraint_results[], evaluation_id, evaluator_version
sme_decision_status: NOT_DECIDED | APPROVED | REJECTED       (future, verified human command)
reservation_status: NONE | PENDING | CONFIRMED | FAILED | UNKNOWN | RELEASED
reservation_operation_id, reservation_receipt_ref, reservation_mode  (future)
commitment_id, authoritative_core_status                    (Core projection only)
```

`CURRENT` means evidence is complete enough to run a supported evaluator, **not** commercially agreed, SME approved or reserved. `FEASIBLE` is an advisory P2 calculation, never `ACCEPTED`. For B2, `feasibility_status=NOT_EVALUATED` on every pending order because the approved provisional mapping is absent; do not output `CURRENT` as a pending evaluation claim. `sme_decision_status=NOT_DECIDED`, `reservation_status=NONE`, and Core fields absent. Future dimensions C/D/E require separate P5 reviewed authority. A future assessment ID must bind inputs and be persisted/verified if used as a decision precondition; the present P2 `p2-local-` identity is only a hash of supplied input.

## 4. Error and stale-version semantics

| Condition | Result | Side effects |
|---|---|---|
| Tenant/request/customer identity cannot be verified | `NOT_FOUND` or `IDENTITY_UNVERIFIED`; no candidate disclosed across tenant | None |
| Request, terms, proposal, price source or source-context version changed | `*_VERSION_CONFLICT` / `TERMS_MISMATCH`; client reloads authoritative version | None |
| Snapshot absent, source missing, current token absent/stale or wrong tenant | `SNAPSHOT_UNAVAILABLE`, `EVIDENCE_INCOMPLETE`, `SNAPSHOT_VERSION_CONFLICT`, or `UNKNOWN` | None |
| Known insufficiency from same P2 kernel | `INFEASIBLE` with exact hard constraints, only after complete supported input | None |
| Unknown stock/capacity, unverified receipt, incomplete BOM/plan, uncertain allocation | `UNKNOWN` or `UNSUPPORTED`; never silently zero/free | None |
| Multi-line or pending target with current evaluator | `UNSUPPORTED_PENDING_TARGET` / `UNSUPPORTED_MULTI_LINE`; no FEASIBLE projection | None |
| Assent or price disclosure unverified | `ASSENT_UNVERIFIED` / `PRICE_DISCLOSURE_UNVERIFIED`; operational diagnostic may be shown separately but never acceptance-ready | None |

The exact HTTP mapping is a later shared API decision; these are contract-level codes. A version token checked during a read can become stale before reservation; the future decision must recheck under the authoritative transaction/operation.

## 5. Proposed reservation state machine (future, no B2 implementation)

`NONE → PENDING/ACCEPTING → CONFIRMED → Core accepted` only after authenticated, tenant/request/key/terms hash/snapshot-scoped receipt verification. `PENDING → UNKNOWN` on timeout until operation-status reconciliation; `PENDING/UNKNOWN → FAILED` only with authoritative failure evidence. `CONFIRMED → RELEASED` requires an approved compensation policy if Core commit cannot complete. A partial multi-resource outcome cannot become confirmed; it needs a durable operation ID, per-resource reconciliation and release/retry policy. Idempotency is tenant + request + exact terms/version + operation scope, with replay returning the same authoritative intent/result. No local `resource.reserved` synthetic ref is a live Orbyte receipt. P5 owns state/outbox and acceptance; provider port owns real resource status. Do not infer a transition from a client-submitted `ReservationReceipt` object.

## 6. Shared-owner decisions required before persistence/API

1. **Backend A/P1/P4/P5:** publish the canonical persisted candidate, exact original-offer and proposal-assent evidence reader, current version semantics and customer identity verification. Resolve PR #48 evidence-currentness, proposed-revision and timezone/DST gaps on its branch. Which disclosure record proves the entire price/fees offer was shown to this customer?
2. **P2/P5:** agree a provisional target type and current snapshot read/lock token, with no mislabelled confirmed row; map item variants/units, delivery window to exact production/material-use and capacity plan, multi-line policy and no displacement of accepted demand. Are eligible incoming receipts actually received/confirmed?
3. **P5/Auth/Orbyte:** establish verified SME principal, source authentication, all-resource reservation semantics, idempotent operation ID, receipt verification, unknown/partial/compensation policy, and Core/outbox transaction/lock order. Which system owns current stock and capacity reservations?
4. **Product/shared owners:** record S1 approval already given in this chat in the durable decision trail; S2–S5 remain unratified here. Set any further material price/fee, snapshot freshness and evidence policy required for activation.

PR #49 is stacked on #48 and adds supplier comparison; it provides no pending-order mapper or OrderRequest authority. Its supplier quotes must remain claims until independently verified and must not be injected into P2 stock. No PR #48/#49 code was copied, merged or changed in B2.

## 7. B3 update for Backend A — shareable review request

**Refs checked 2026-10-24:** main `3efa7f23`, PR #48 `741976d3`, PR #49 `62040da0`; none advanced in this fetch. The field and authority table in §1 is unchanged. Please review it as a proposed **read** contract, not a request to add shared DTOs immediately.

Backend B needs one persisted, tenant-scoped `AcceptanceCandidate` with exact `tenant_id`, `order_request_id`, `customer_id`, `request_version`, `terms_revision`, `terms_hash`, canonical terms revision/ref, P1 context ID/version and source evidence refs, customer original-offer or exact proposal assent state/hash/evidence, conditional proposal ID/version, approved price source ID/version and full-offer disclosure refs, aware creation/update times and correlation ID. Backend A should name each authoritative row/reader and which values are immutable. B will re-read current records and evidence, check tenant/customer/request/terms/source/proposal versions and independently verify assent/disclosure. A matching hash or nonempty ref is not authorization. Missing evidence → `INCOMPLETE/UNKNOWN`; stale versions → `*_VERSION_CONFLICT`; unsupported P2 mapping → `UNSUPPORTED/NOT_EVALUATED`; known insufficiency only after a valid shared P2 evaluation → `INFEASIBLE`.

Proposed `OrderDecision` keeps **readiness**, **P2 feasibility**, **SME decision**, **reservation**, and **Core state** separate (§3). B3's new `PortfolioInputReadiness` evaluates only the **existing confirmed-demand baseline**; with any pending request IDs it returns `PENDING_TARGET_UNSUPPORTED`, even if baseline stock/capacity is covered. It never ranks, reserves or accepts. `profit_strategy_available=false` because P2 has no vetted price/cost basis; `expiry_strategy_available=false` because the objective, lot provenance and allocation policy are not agreed. These fields are not new AcceptanceCandidate fields. Please do not map a pending request to a fake confirmed Core commitment.

**Requested reviews:** Backend A/P1: persisted candidate, identity and exact terms/price-disclosure/assent evidence, plus per-line SKU/variant/unit and delivery window; P2: material-use time, warehouse, BOM and production plan mapping for each line and a provisional-target interface; P5: current snapshot read/version token, verified principal, lock order, reservation receipt/Core/outbox authority. Unresolved: line-level price source for mixed catalog/quote orders; whether unknown expiry makes an expiry objective unavailable; verified cost components for Profit; portfolio FCFS time basis; how accepted reservations and candidate allocations are jointly represented. PR #48 evidence-currentness, revision and timezone/DST fixes remain Backend A-owned. S1 was approved explicitly in this chat; S2–S5 remain unratified here. No shared schema or API should change solely on this draft.

## 8. B4 review note for Meishuet — provisional feasibility is still advisory

Main `3efa7f23`, PR #48 `741976d3` and PR #49 `62040da0` were unchanged on the 2026-10-24 fetch. No revised persisted AcceptanceCandidate or P1 mapper was found in those inspected refs. The §1 fields remain proposed, with no silent revision. Please identify the authoritative tenant-scoped OrderRequest/canonical terms row, request and terms versions, customer identity/assent record, source-context ID/version and source spans, approved price ID/version and full-offer disclosure receipt. Backend B must reload each current source and bind it to the same tenant, request, customer, hash and proposal version; missing or stale evidence returns `MISSING_EVIDENCE`, `UNKNOWN`, `STALE` or `UNSUPPORTED`, never accepted.

For a **single provisional line**, B additionally needs an explicit trusted SKU/variant/unit mapping, Decimal quantity, warehouse/material-use instant, delivery deadline/window and named-zone interpretation, production process/plan/job horizon and current P2 snapshot ID/version. This is operational projection input, **not** customer agreement or a confirmed Core commitment. No owner-approved provisional P2 interface exists yet. A proposed `OrderDecision` must keep readiness (`READY_FOR_EVALUATION` or blocker), feasibility (`FEASIBLE/INFEASIBLE/UNKNOWN/UNSUPPORTED/STALE`), human SME decision, reservation outcome and Core state as five separate dimensions. FEASIBLE would be advisory only. A/B/P2/P5 need joint review of the candidate→provisional mapping, single-line scope, snapshot reader/currentness and exact error codes before any shared DTO/API or persisted integration. B4 changes no Backend A module.

## 9. B5 dated reconciliation with PR #50 — 2026-10-24 SGT

PR #50 HEAD `0d0bf8c850e6b72e0e1c2d18a15fcfb7e5269c5c` is stacked directly on #48 `741976d3`; #49 `62040da0` is separate. Main remains `3efa7f23`. The [full field-by-field reconciliation](BACKEND_B_B5_AB_CONTRACT_RECONCILIATION.md) supersedes **only the assumption in §1 that no typed candidate exists**: #50 now implements a pure immutable `AcceptanceCandidate` in `backend/app/orders/context_mapping.py`. It is unmerged and not persisted. All §1 authority and re-read requirements remain proposed and active; no older field proposal was silently removed.

**For Meishuet:** B can use the proposed candidate shape after review: tenant/request/customer; current P1 context ID/version/**version record ID**, review and versioned message associations; canonical #48 terms/revision/hash; price source ID plus **nested source version** and structured disclosure records; agreement/proposal/assent fields; readiness and reason codes. Current #50 mapper always emits `agreement_basis=UNKNOWN`, no proposal/assent, and `READY_FOR_VALIDATION` means preparation only. It does not supply `request_version`, a persisted OrderRequest reader, candidate timestamps/correlation, independent catalog/disclosure authority, or current P2 snapshot/plan. Please identify the durable request/version and trusted tenant-scoped source adapter; confirm which P1/P4 evidence proves an explicit original offer or exact proposal assent. B will re-read rather than trust the DTO.

**For P2/P5:** P2 review is needed for an explicit single-line provisional target using unchanged ATP/BOM/capacity semantics against confirmed demand and protected reservations; missing plan/job/current source must remain UNKNOWN/UNSUPPORTED. P5 review is needed for verified SME identity, latest source/snapshot revalidation, all-resource reservation authority and receipt, pending/unknown reconciliation, one Core lifecycle and audit/outbox atomicity. Until those are approved, proposed `OrderDecision` keeps candidate readiness, P2 feasibility, human decision, reservation and Core state separate, with pending-order feasibility `NOT_EVALUATED`, decision `NOT_DECIDED`, reservation `NONE` and no Core link. S1 approval was explicit in this chat; S2–S5 remain unratified here. No DTO/API/schema/acceptance change was made by B5.

## 10. Post-review correction — 2026-10-24 SGT

Sections 1–9 are dated design and B1–B5 observations. The 13 Backend B files are now committed in two commits (`e7dd0ae`, `cc7aad8`) and pushed as open Draft PR #53 at `cc7aad8e05ee3bd2233d9ead314a6db94909d233`; they are no longer local-only untracked files. Main at this reconciliation is `67627cb782a02c7e47bd0812d861f55ff8bb5982`. The selected local checkpoint suite passed 357 tests with 4 warnings. GitHub Actions run `39998815566` completed successfully on the same PR head, including the PostgreSQL job; its counts and scope are recorded in the [P0 post-review compatibility appendix](BACKEND_B_P0_INTEGRATION_REVIEW_PACKAGE.md#post-review-compatibility-2026-10-24-sgt). These are distinct validation runs.

The B5 comparison in §9 remains historical at PR #50 `0d0bf8c8`. The current PR #50 head is `fd7be2e2dae0b3275ea344f9f4d567b836c93cb1`; it adds disclosure currentness and binding checks. PR #52 `8d7ca20c0651db947092dec34510fe1b0b63aaaa` independently proposes OrderTerms foundation hardening on PR #48. PR #48 itself remains at `741976d3` and does not contain #52's changes. The compatibility appendix gives the current MATCH / CHANGE REQUIRED / OWNER DECISION REQUIRED matrix, separate status vocabulary, two customer agreement evidence paths and seven distinct version tokens. It supersedes §1's blanket requirement for a second proposal-assent receipt/hash on an unchanged, verified original customer offer and the mixed readiness/feasibility labels in §§3 and 8. It does not alter the historical test observations.

The statement above that S1 was approved in a chat is a historical report of wording, not a verified Product Owner/P5 decision record. Current shared status is **SIGNOFF-EVIDENCE-REQUIRED** until the authorized decision, scope, date and reviewed policy/version are entered in the durable decision trail. S2–S5 remain unratified. The five A/B ownership points are agreed in principle only; no persistence, projected evaluation, acceptance, reservation or Core implementation is authorized by this handoff.
