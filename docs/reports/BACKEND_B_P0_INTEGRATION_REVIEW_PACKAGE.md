# Backend B P0 integration review package

**Review date: 2026-10-24 SGT. Decision requested:** approve the source-reader and provisional-target contracts below. **Current gate: NO-GO for projected evaluator, persistence, acceptance or reservation integration.** No documented P2/P5 implementation approval was found in B5 or the inspected refs; Backend A's integration document is explicitly proposed. Record owner, decision, date and reviewed SHA against each row before dependent coding.

**Verified Git refs:** `origin/main` and Backend B HEAD `3efa7f23fc2842664f1164cc1dce363f7371bdd3`; PR #48 `741976d3cdd59352d66a30c5712ce9eca5d3bc16`; PR #50 `0d0bf8c850e6b72e0e1c2d18a15fcfb7e5269c5c`. Fresh fetch found no advance from B5. #50's merge-base with #48 is #48's exact head; #50 depends on #48 and remains outside main. Existing B worktree: `C:/Users/User/OneDrive/Documents/sdc hackathon 2026/MouManTAI-backend-b-b1-readiness`, branch `feat/backend-b-b1-readiness`. Tracked staged/unstaged changes: **0**; existing untracked B1–B5 files: **12**. Only this package is added by this review; no tests or application files changed. [B5 detailed evidence](BACKEND_B_B5_AB_CONTRACT_RECONCILIATION.md), [latest A/B handoff](BACKEND_AB_CONTRACT_HANDOFF.md).

## A. Backend A decisions

**Implemented typed fields in PR #50:** `backend/app/orders/context_mapping.py:135-164`, extracted from the fetched head. `Text` is PR #48's validated string type; `?` below means optional with default None, tuples default empty. The four required fields are `tenant_id`, `source_context_id`, `source_context_version` and `readiness_status`.

```text
tenant_id: Text
order_request_id: Text | None
source_context_id: Text
source_context_version: int (>=1)
source_context_version_record_id: Text | None
context_review_actor_id: Text | None
context_review_actor_role: Text | None
context_reviewed_at: AwareDatetime | None
existing_order_id: Text | None
terms_revision: int | None (>=1)
terms_hash: Text | None
canonical_terms: OrderTerms | None
customer_id: Text | None
customer_identity_evidence: tuple[Text, ...]
customer_identity_associations: tuple[CustomerIdentityAssociationEvidence, ...]
source_message_ids: tuple[Text, ...]
source_evidence_refs: tuple[Text, ...]
price_source_ref: Text | None
price_disclosure_evidence: tuple[PriceDisclosureEvidence, ...]
agreement_basis: AgreementBasis = "UNKNOWN"
proposal_id: Text | None
proposal_version: int | None (>=1)
customer_assent_evidence: tuple[Text, ...]
readiness_status: MappingReadiness
validation_reason_codes: tuple[Text, ...]
missing_fields: tuple[Text, ...]
conflict_fields: tuple[Text, ...]
```

`MappingReadiness` = `READY_FOR_VALIDATION | INCOMPLETE | REVIEW_REQUIRED | STALE_SOURCE | IDENTITY_UNVERIFIED | TERMS_CONFLICT | PRICE_SOURCE_UNVERIFIED`. `AgreementBasis` = `UNKNOWN | CUSTOMER_ORIGINAL_OFFER | MATERIAL_AMENDED_PROPOSAL | CUSTOMER_ASSENTED_PROPOSAL`; the **mapper emits only UNKNOWN**, with no proposal or assent (`:331-334`). `:166-213` validates internal terms/hash/identity/disclosure bindings. This is implemented on #50's branch, not an authenticated persisted authority. Price source version is nested in `canonical_terms.price_source` and structured disclosure evidence; `price_source_ref` is only the source ID. Association snapshots retain ID/version/message/tenant/customer/update time. Disclosure snapshots retain context/request/terms/source versions and hash, disclosure time and adapter authority assertion.

| ID / unresolved item | Exact existing implementation | Missing requirement or authority | Proposed decision for review | Owner | Implementation blocked? |
|---|---|---|---|---|---|
| A1 Durable request identity/version | Optional supplied `order_request_id`; no `request_version` in #50 DTO; `existing_order_id` is a P1 association | Durable request store/version, immutable offer revision and Core link contract | A/P5 designate one OrderRequest authority and optimistic request token; context version, terms revision and request version stay distinct. Do not synthesize request ID from context/order ID. | A/P1/P5 | Yes, durable request integration |
| A2 Tenant-scoped reader | `map_order_context(:342+)` checks supplied P1 context/version/message/association/review records and commercial snapshot | Trusted current server reader, tenant/principal enforcement, approved catalog/quote and disclosure lookup | A/P1 implement a reviewed read-only source adapter; B independently reloads sources. Return missing/conflict/unknown if authority is unavailable; a DTO or `VERIFIED` flag is insufficient. | A/P1/P5; P4 disclosure | Yes, authoritative candidate consumption |
| A3 Terms/source/disclosure currentness | #48 OrderTerms hash; #50 current context snapshot/association versions and exact structured disclosure bindings | Current approved source lookup, offer/disclosure version policy; existing #48 evidence/revision/timezone follow-ups | Bind source IDs+versions, full price/fee disclosure and exact terms revision/hash to customer/request; reject stale or substituted evidence, re-map on changes. A owns fixes; B adds no terms type. | A/P1/P4/P5 | Yes, trusted commercial validation |
| A4 Original offer versus assent | Mapper emits `agreement_basis=UNKNOWN`, proposal None, assent tuple empty | Explicit customer-originated offer attribution or verified P4 response bound to proposal/version/hash/identity/expiry | P1/P4 define two evidence paths. UNKNOWN blocks acceptance; `READY_FOR_VALIDATION` never establishes SME approval or assent. | A/P1/P4/P5 | Yes, agreement/acceptance integration |
| A5 Freshness and revalidation | Context/version-record IDs, review time, associations and source refs preserved; pure function cannot re-read after return | Agreed source read token/version set, invalidation rules and retry consistency | Any referenced source change invalidates derived candidate; B reloads request, context/version/review/messages/associations, canonical offer, catalog/disclosure and applicable proposal/assent before decision. Choose consistent read and later transaction recheck with P5. | A/P1/P4/P5/B | Yes, current candidate authority |

**OrderDecision proposal for joint review:** carry tenant/request/customer refs and expected versions, evaluated terms revision/hash, source-context refs, snapshot ID/version, assessment ID/time, reasons/evidence. Keep five dimensions: (1) candidate validation/readiness; (2) P2 advisory feasibility; (3) authorized SME decision; (4) authoritative reservation operation/receipt; (5) Core ID/version/state projection. Only (1) has a pure unmerged #50 candidate implementation; B1/B3 implement (2) for confirmed targets/baselines only. Pending feasibility is `NOT_EVALUATED`, SME decision `NOT_DECIDED`, reservation `NONE`, and Core link absent today. Exact final DTO/state names remain proposed. No second mutable `ACCEPTED` field or customer-facing exposure of internal evidence without owner policy.

## B. P2 decisions

| ID / unresolved item | Exact existing implementation | Missing requirement or authority | Proposed decision for review | Owner | Implementation blocked? |
|---|---|---|---|---|---|
| B1 Provisional single-line target | `feasibility/service.py:101-134` requires matching confirmed Core target and single line; snapshot ledger is `confirmed_commitments` | Explicit provisional representation and documented semantic review | Approve a distinct PROJECTED/ADVISORY target keyed by tenant/request/terms versions and one SKU/variant/Decimal quantity/unit, material-use/warehouse, delivery window/zone and explicit production plan. Never fake CONFIRMED. | P2, A/P1 mapping, P5 | Yes, projected evaluator |
| B2 Kernel reuse | `bom.explode_bom`, `inventory.calculate_atp`, `capacity.check_capacity` enumerate confirmed demand; fixed jobs require production evidence | Reviewed pure scenario input/kernel extraction | Reuse the same formulas and constraints through a P2-reviewed scenario boundary; no separate allocator/calculator. Missing process/plan/job horizon must not disappear. | P2/P5 | Yes, semantic extension |
| B3 Fixed demand/reservations | ATP protects active reservation ownership and all confirmed competing demand; capacity checks booked exclusive intervals | Provisional demand treatment and displacement policy | Confirm fixed accepted demand/reservations cannot be released or displaced by a candidate; compare projected batch against baseline. Unknown competing evidence keeps result UNKNOWN. | P2/P5 | Yes, projected allocation semantics |
| B4 Snapshot freshness | `persisted_sources.read_snapshot:123+` and `currentness.require_current_snapshot:11+`; source validity checked at explicit time | Approved reader authenticity, freshness policy and decision-time lock/token | Require trusted tenant snapshot ID/version/current token and evidence bounds; version drift is STALE/conflict and requires reload, not reuse of a prior green result. | P2/P5 | Yes, live/read integration |
| B5 Outcome distinctions | P2 FEASIBLE/INFEASIBLE/UNKNOWN; fixed-plan failure scoped to that plan; boundary rejects unsupported mapping | Agreed mapping of boundary versus calculation outcomes | Missing/uncertain evidence → UNKNOWN/MISSING_EVIDENCE; unmodelled line/routing → UNSUPPORTED; supported hard proof with sufficient evidence → INFEASIBLE. FEASIBLE is advisory, never assent, reserved stock, accepted Core or guaranteed delivery. | P2/B, A/P5 response review | Yes, new shared response |
| B6 Joint contention | B4 test: two 60-unit confirmed-demand fixtures each covered alone, joint batch short against the same 100-unit stock | Whole projected candidate-set validation and attestations | Validate entire shared projection and each selected target under the same allocations. Independent FEASIBLE results cannot be combined. Mismatch suppresses recommendation. | P2/P5 | Yes, multi-order projection |

## C. P5 decisions

| ID / unresolved item | Exact existing implementation | Missing requirement or authority | Proposed decision for review | Owner | Implementation blocked? |
|---|---|---|---|---|---|
| C1 SME principal | `core/dependencies.py:46-66` gates demo actor headers behind synthetic mode | Authenticated production SME/tenant and command scope | P5 provide trusted principal and tenant membership/permission resolver; P1 extraction-review actor is a different authority. | P5/Auth, B consumer | Yes, consequential commands |
| C2 Resource operation/receipt | `core/reservations.py:226+` is local P3 plan/action reserve primitive; #48 `business_ports.py` defines structural command/receipt | Order-level all-material/capacity reservation provider and authentic receipt | Designate authority; bind operation/key/request version/terms hash/snapshot and per-resource result. Verify receipt origin/provider mode; local synthetic audit ref proves no live Orbyte result. | P5/resource owner/P2/B | Yes, reservation integration |
| C3 Pending/failed/unknown | Existing local reserve returns active row or raises; proposed external receipt statuses exist only as seam | Durable intent, status query, partial outcome and compensation/reconciliation policy | Keep acceptance pending until verified success; UNKNOWN requires status lookup before retry. Define release/reconcile for partial reserve or successful reserve followed by failed Core commit. | P5/resource owner/B | Yes, acceptance workflow |
| C4 Core authority | Core service owns lifecycle/proposals; no v2.2 accepted-request transition/link | One guarded accepted-request↔Core link and decision boundary | P5 approve one Core service transition after exact agreement, authenticated SME, current P2 and successful reserve. A/B consume authoritative state projection; no duplicate commitment/accepted authority. | P5, A/P4/B | Yes, accepted-request integration |
| C5 Audit/outbox atomicity | Core service appends state/audit/outbox; dispatcher has mandatory subscribers, dedup/retry | New accepted-order event/transaction/lock order and external-operation gap | Local state/audit/outbox commit together. External reservation uses durable intent/reconciliation; agree required subscribers and event/version envelope before activation. | P5, affected consumers | Yes, new transition/event |
| C6 Retry/idempotency/staleness | P3 unique tenant/idempotency key and conditional stock update; P5 event dedup | Version-bound order-command replay and currentness across retry | Same operation key must bind same request/terms/snapshot intent; reject conflicting reuse, reload stale source, reconcile ambiguous receipt before reissue. Confirm cross-worker DB guarantees separately. | P5/resource owner/B | Yes, order command/retry |

**Approval state:** A1–A5, B1–B6 and C1–C6 remain open on inspected evidence; the block is scoped to the dependent implementation in each row. S1 was explicitly approved by the user in this chat for exact customer-agreed terms/price disclosure/proposal assent; owners should record it in the shared decision trail. S2–S5 are not inferred from A/B ownership. Review-package preparation is complete and needs no additional approval.

**ONE recommended next coding slice after A2/A3/A5 approval:** Backend A/P1 implements a tenant-scoped **read-only candidate source adapter around PR #50's existing mapper**, with P5-reviewed identity/source-read boundary and P4-reviewed disclosure record lookup. Load current context/version/review/messages/association versions and approved commercial/disclosure records; return the existing candidate or explicit missing/stale/identity/price conflict. Keep absent durable request identity INCOMPLETE and agreement UNKNOWN; introduce no OrderRequest table, request-ID minting, shared DTO, P2 evaluator or acceptance operation. Negative tests: cross-tenant/customer/message links, stale context/version snapshot/review or association version, missing catalog/disclosure authority, source-version/hash substitution, unknown request ID, unverified assent, source changes between read and use, and no DB flush/reserve/Core/outbox/provider effects. This slice establishes source authenticity; durable request/version and projected evaluation remain separately owner-gated. Backend B consumes this adapter only after review, with no duplicate A-owned mapper or authority.

### Preserved work and test evidence

All paths below are relative to the Backend B worktree; each was **untracked**, with no staged/tracked edits at inventory. B1–B5 content is preserved byte-for-byte (SHA-256 inventory verified before/after package creation). These are not commits or backups; the files remain local and uncommitted.

| Preserved file | Scope / recorded coverage |
|---|---|
| `backend/app/feasibility/readiness.py` | B1 pure existing-confirmed-target readiness; covered by 12 cases below |
| `backend/app/feasibility/portfolio_readiness.py` | B3 confirmed baseline precondition; covered by 12 cases below; pending IDs unsupported |
| `backend/app/feasibility/tests/test_readiness.py` | 12: current/missing/stale/tenant/version/provenance, unsupported target, contention, no reservation authority, deterministic unchanged inputs |
| `backend/app/feasibility/tests/test_pending_boundary.py` | 3: requested/offered/absent target rejected before P2 calculation |
| `backend/app/feasibility/tests/test_portfolio_readiness.py` | 12: baseline/source/version/stock/capacity/lot blockers, pending omission guard, unavailable strategies and input immutability |
| `backend/app/feasibility/tests/test_projected_review_gate.py` | 1: individual stock coverage does not imply joint batch coverage; confirmed fixtures only |
| `docs/reports/BACKEND_B_FEASIBILITY_RESERVATION_READINESS.md` | B1 report; historical selected regression 341 passed |
| `docs/reports/BACKEND_B_B2_PENDING_ORDER_FEASIBILITY.md` | B2 report; historical selected regression 344 passed |
| `docs/reports/BACKEND_B_B3_CONSTRAINT_OPTIMIZATION_READINESS.md` | B3 report; historical selected regression 356 passed |
| `docs/reports/BACKEND_B_B4_PROJECTED_FEASIBILITY.md` | B4 review/design; historical selected regression 357 passed |
| `docs/reports/BACKEND_B_B5_AB_CONTRACT_RECONCILIATION.md` | B5 report: 75 exact-head #50 terms/mapper tests and 28 B focused cases passed |
| `docs/reports/BACKEND_AB_CONTRACT_HANDOFF.md` | Append-only handoff through B5; proposals and unresolved authority decisions |

Tests above are **recorded prior results**, with 0 failed/skipped in the cited selected runs, not fresh execution in this Markdown-only task. #50 was tested at `0d0bf8c8` in clean detached worktree `C:/Users/User/OneDrive/Documents/sdc hackathon 2026/MouManTAI-pr50-b5-review`; it stays at that SHA. Local tests use synthetic fixtures/in-memory SQLite, not real operational accuracy. No PostgreSQL, live source, cross-worker acceptance, or provider behavior is proven. The original P3 and Phase 0/0.1/Phase 1A/reconciliation worktrees are not modified. Final Backend B state: same branch/HEAD, **13 untracked files** including this package, **0 staged changes and 0 tracked working-tree changes**. No commit, push or merge.

## Post-review compatibility — 2026-10-24 SGT

This appendix updates the current review position without rewriting the historical B1–B5 observations above. Verified refs: main `67627cb782a02c7e47bd0812d861f55ff8bb5982`; PR #48 `741976d3cdd59352d66a30c5712ce9eca5d3bc16`; PR #50 `fd7be2e2dae0b3275ea344f9f4d567b836c93cb1`; PR #52 `8d7ca20c0651db947092dec34510fe1b0b63aaaa`; PR #53 `cc7aad8e05ee3bd2233d9ead314a6db94909d233`. All four PRs were open Draft at verification. PR #53's 13 files are committed and pushed in `e7dd0ae` and `cc7aad8`, not untracked. Its branch remains review-gated. Backend A's dated reconciliation was compared with fetched source, not treated as an implementation authority.

**Validation scope:** Local PR #53 checkpoint on final source: selected `app/feasibility/tests`, resource reservations, P5 integration recovery and outbox tests — **357 passed, 0 failed, 0 skipped, 0 errors, 4 warnings** (Windows, synthetic/in-memory SQLite). GitHub Actions [run 39998815566](https://github.com/jiahui-1101/MouManTAI/actions/runs/39998815566) completed successfully on the same PR head: backend job **1148 passed, 146 skipped, 79 warnings**; separate nonblocking feature job **756 passed, 115 skipped, 72 warnings**; authoritative PostgreSQL job **431 passed, 0 skipped, 40 warnings**, with the zero-unapproved-skip verifier passing. Frontend and hygiene jobs also succeeded. These are separate jobs with overlapping tests, not additive counts or proof of live provider/acceptance behavior. B5's **75** PR #50 tests were run only at old `0d0bf8c8`; Backend B did not rerun them at `fd7be2e`. PR #52's own validation record reports a PR #50 compatibility overlay, but that is A-side evidence, not a test run by Backend B.

### Compatibility decisions for PR #53

| Interface point | MATCH | CHANGE REQUIRED | OWNER DECISION REQUIRED |
|---|---|---|---|
| Canonical terms and price | PR #48 `OrderTerms` is the single canonical commercial value type; #50 carries terms revision/hash and price-source ID, with version nested in `canonical_terms.price_source.source_version`. | #50 now checks supplied disclosure currentness and exact bindings; B's older opaque-reference language must consume structured `PriceDisclosureEvidence`. A trusted persisted reader and full-fee disclosure proof remain absent. #52 hardening is separate from unchanged #48. | A/P1/P4/P5 decide source authority, version/currentness policy and reviewed integration order for #48/#50/#52. |
| Request and source identity | #50 keeps tenant, optional request/customer IDs, context ID/version/version-record ID, review provenance, message IDs and versioned customer associations. | Future decision requires a durable request ID, independent `request_version`, current tenant-scoped lookup and re-read of association versions. Optional preparation fields are not authoritative request state. | A/P1/P5 approve the OrderRequest owner, reader, optimistic token and trust boundary. |
| Customer agreement | #50 keeps `agreement_basis=UNKNOWN`, with no proposal or assent evidence emitted. Hash equality proves commercial equality only. | Distinguish exact original customer offer from materially changed proposal; the earlier blanket requirement for a second assent receipt/hash on every original offer is superseded. | A/P1/P4/P5/Product define source/identity, full-price disclosure, proposal ID/version/hash and expiry proof. |
| Readiness and feasibility | #50's `MappingReadiness` is preparation; B1's `OperationalReadiness` and B3's `PortfolioInputReadiness` apply only to existing confirmed targets/baselines. P2 `FeasibilityState` remains separate. | Namespace both readiness fields. Map prior draft `NOT_EVALUATED` to P2's existing `NOT_ASSESSED`; keep UNSUPPORTED/STALE/MISSING_EVIDENCE in evaluation preconditions, never actual `INFEASIBLE`. | A/B/P2/P5 approve a versioned response vocabulary and diagnostics/API mapping. |
| P2 and P5 action boundary | Existing P2 `evaluate` requires a matching confirmed Core target; Core remains the sole Commitment lifecycle writer. | No valid pending provisional target, whole-batch allocation proof, live reservation operation or accepted-request transition exists in these PRs. | P2 approves target/kernel semantics, fixed demand/reservations and snapshot freshness; P5 approves SME principal, durable reservation intent/receipt/reconciliation, Core/audit/outbox and retry authority. |

### Proposed names and exact status mapping — **PROPOSED, NOT IMPLEMENTED**

Do not rename A's or P2's current enums without their owners. A future read projection should use these six distinct fields:

| Proposed field | Proposed values and mapping | Current authority |
|---|---|---|
| `candidate_readiness_status` | Copy A's `MappingReadiness`: `READY_FOR_VALIDATION | INCOMPLETE | REVIEW_REQUIRED | STALE_SOURCE | IDENTITY_UNVERIFIED | TERMS_CONFLICT | PRICE_SOURCE_UNVERIFIED`. `READY_FOR_VALIDATION` means only supplied candidate preparation. | A `AcceptanceCandidate.readiness_status` in PR #50; not a persisted source reader. |
| `evaluation_readiness_status` | `NOT_EVALUATED | READY_FOR_EVALUATION | EVALUATED | MISSING_EVIDENCE | STALE_SOURCE | UNSUPPORTED_TARGET`. B1 `READY_FOR_REVIEW` is an existing confirmed-target advisory result, not a direct alias for pending `READY_FOR_EVALUATION`; B3 `BASELINE_COMPLETE` covers confirmed demand only. B3 `PENDING_TARGET_UNSUPPORTED` maps to `UNSUPPORTED_TARGET`. | Future B/P2 read projection; no shared enum yet. |
| `feasibility_status` | Reuse P2/Core `FeasibilityState`: `NOT_ASSESSED | FEASIBLE | CONDITIONAL | INFEASIBLE | UNKNOWN`. Earlier draft `NOT_EVALUATED` maps to `NOT_ASSESSED`. `CONDITIONAL` only when P2 returns it. Stale/unsupported/missing evidence never map to `INFEASIBLE`; no calculation gives `NOT_ASSESSED`, and an executed calculation with uncertain facts may give `UNKNOWN`. | P2 assessment for a supported target only. |
| `sme_decision_status` | Proposed `NOT_DECIDED | APPROVED | REJECTED`; `APPROVED` requires a verified authorized SME command and is not Core confirmation. | Future P5/Auth-approved human decision authority. |
| `reservation_status` | Proposed `NONE | PENDING | CONFIRMED | FAILED | UNKNOWN | PARTIAL | RELEASED`; `CONFIRMED` requires an authoritative all-resource receipt. Unknown or partial remains unresolved and blocks acceptance. | Future P5/resource operation authority. |
| `core_status` | `ABSENT` if no linked Core Commitment; otherwise read the actual Core agreement state with `commitment_id` and `core_commitment_version`. Do not create a second writable accepted state. | Existing Core projection only; accepted-request link not implemented. |

Examples: (1) #50 `INCOMPLETE` with absent request evidence → candidate `INCOMPLETE`, evaluation `NOT_EVALUATED`, feasibility `NOT_ASSESSED`, SME `NOT_DECIDED`, reservation `NONE`, Core `ABSENT`. (2) A fully prepared candidate with a pending target on current P2 → candidate `READY_FOR_VALIDATION`, evaluation `UNSUPPORTED_TARGET`, feasibility `NOT_ASSESSED`; no operational action. (3) A current, supported future target with a proven material shortage → evaluation `EVALUATED`, P2 feasibility `INFEASIBLE`; SME and reservation remain separate. (4) A stale disclosure or snapshot → candidate `PRICE_SOURCE_UNVERIFIED` or evaluation `STALE_SOURCE`, respectively, and no current pending feasibility result. These examples are response-design proposals, not running pending-order behavior.

### Customer agreement and version authority

Two distinct evidence paths are required. **Original customer offer:** verified customer-originated exact terms, verified source identity and full price/fee disclosure, current tenant/request/source binding; no second proposal-assent click is intrinsically required. **Materially changed proposal:** exact current proposal ID/version and acknowledged terms hash, verified customer identity and authoritative P4 response before expiry. Neither path follows from a matching hash, an extraction result or an adapter-supplied `VERIFIED` flag. #50 currently emits `UNKNOWN`; A/P1/P4 own the evidence implementation, with P5 trust review.

| Token | Meaning and owner | Proposed decision-time rule |
|---|---|---|
| `request_version` | Future durable OrderRequest optimistic token; Backend A/P5. Absent from #50. | Compare current request version to the command's expected version; conflict reloads and blocks consequential work. |
| `terms_revision` | Binding commercial offer revision; Backend A. Hash deliberately omits revision/evidence refs in `order-terms-v1`. | Re-read exact immutable revision and validate hash plus independent proof/currentness; changed proposal is a separate path. |
| `source_context_version` | P1 extraction/review context revision, with exact version-record ID; P1. | Re-read context, review, messages and source evidence at that revision; drift invalidates candidate. |
| `proposal_version` | Optional material-proposal version; P4/Core owner decision. | Verify current proposal ID/version/hash, customer response and expiry; reject superseded assent. |
| `association_version` | P1 message/customer/order identity-link revision. | Re-read every referenced association ID/version and tenant/customer/message binding. |
| `operational_snapshot_version` | P2 operational facts/current token. | Re-read tenant-scoped snapshot and source freshness; lock/recheck selected version before reservation. |
| `core_commitment_version` | Authoritative Core lifecycle version; P5. | Require exact expected Core version for any future transition; state, audit and outbox follow one guarded authority. |

The proposed flow takes a consistent current read of request/terms/context/associations/disclosure/assent and P2 snapshot, records the version vector on an assessment/decision attempt, then revalidates it at SME decision and before any reservation/Core transition. P5 must decide transaction and external-operation ordering, including idempotent retry after an unknown receipt; a prior green read is not a lock. No persistence or API is added by this appendix.

### Open authority and signoff gates

- **A/P1/P4:** durable request/version and trusted tenant-scoped current source reader; approved catalog/quote and full-fee disclosure currentness; exact original-offer or P4 proposal-assent evidence. The three version domains `request_version`, `terms_revision` and `source_context_version` stay independent.
- **P2:** explicit provisional target, shared ATP/BOM/capacity behavior, protected accepted demand and active reservations, joint contention, snapshot authority/freshness and UNKNOWN versus proven INFEASIBLE semantics. Current B4 confirmed-demand fixtures do not implement a projected evaluator.
- **P5:** authenticated SME principal, durable all-resource reservation intent and receipt, unknown/partial outcome reconciliation, one Core transition, local audit/outbox atomicity and version-bound retry/idempotency. Existing synthetic reservation refs are not live receipts.
- **Shared vocabulary:** the six-field table above remains **PROPOSED** pending A/B/P2/P5 agreement. The five A/B ownership/interface points are agreed in principle, not implementation approval.
- **S1:** Earlier B text states chat approval, but this distributed evidence does not establish the Product Owner's authority, exact reviewed decision/version or durable shared record. Status for this review is **SIGNOFF-EVIDENCE-REQUIRED** until Product Owner/P5/A verify and record those facts. S2–S5 are unratified. No acceptance, reservation or production activation follows from this review.

PR #53 impact: documentation appendix only; its two read-only modules and four tests remain unchanged, Draft and review-gated. The smallest next action is A/B/P2/P5 review of this vocabulary and source/target boundaries, alongside PR #48/#50/#52 integration ownership. No merge, B6 or action workflow is authorized by this documentation checkpoint.
