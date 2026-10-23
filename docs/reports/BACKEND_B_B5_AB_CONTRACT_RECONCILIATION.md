# Backend B B5 — PR #50 A/B contract reconciliation

**2026-10-24 SGT. Disposition:** PR #50 is a useful pure candidate-preparation contract, not a persisted AcceptanceCandidate, customer agreement, P2 target or authorization. No Backend B runtime or shared contract was changed. This report reconciles it against the existing [A/B handoff](BACKEND_AB_CONTRACT_HANDOFF.md) and prepares P2/P5 review.

## 1. Git and dependency map

Existing B worktree `MouManTAI-backend-b-b1-readiness`, branch `feat/backend-b-b1-readiness`, HEAD and fetched `origin/main` `3efa7f23fc2842664f1164cc1dce363f7371bdd3`. PR #48 `741976d3cdd59352d66a30c5712ce9eca5d3bc16`; separate PR #49 `62040da02b4ec3532ea02d734567e0913996ec2b`; PR #50 `0d0bf8c850e6b72e0e1c2d18a15fcfb7e5269c5c`, merge-base with #48 exactly `741976d3`. #50 adds `backend/app/orders/context_mapping.py`, `backend/tests/v2_2/test_context_mapping.py`, `docs/BACKEND_A_B_INTEGRATION_CONTRACT.md` plus docs; it is stacked on #48, not #49. All are unmerged relative to main. PR #50 source was read from its exact ref and tested in a **new detached read-only review worktree** `MouManTAI-pr50-b5-review`; other worktrees and all B1–B4 uncommitted files/reports remain untouched. No merge, commit, push, reset, stash or clean.

Normative target: six-file v2.2 pack, especially `REQUIREMENTS_BACKEND.md` BE-FEA-01/BE-ORD-ACC-01, `REQUIREMENTS_SYSTEM.md` §13.1 and `IMPLEMENTATION_BLUEPRINT.md` §§3.1–3.3/5.1. Previous B2–B4 findings apply to current main: P2 `evaluate` requires a confirmed Core target; there is no approved provisional-target evaluator. S1 was explicitly approved by this user earlier in the chat, but #50's historical docs say S1–S5 pending; P5/Backend A should record the approval in their durable decision trail. S2–S5 remain unratified here.

## 2. Exact PR #50 AcceptanceCandidate inventory

`context_mapping.py:135-164` defines the immutable `AcceptanceCandidate`; `:166-213` checks terms/hash, tenant/customer/request/revision, association and disclosure bindings. `map_order_context` at `:342+` consumes **supplied** P1 records and `OrderCommercialEvidence`, then `_make_candidate` at `:~260-339` produces the DTO. The mapper explicitly emits `agreement_basis="UNKNOWN"`, `proposal_id=None`, `proposal_version=None`, `customer_assent_evidence=()` (`:331-334`). It does not authenticate the supplying adapter or persist/re-read sources. In the table, **R/O** means type required/optional; tuple defaults are structurally optional. “Source” is the proposed authoritative persisted owner, **not proof that a current server reader exists**. For every row B must re-read current tenant-scoped source and compare identity/version before consequential use; failure is no decision and no reservation.

| Exact field and Python type | R/O; producing source | B re-read/currentness and fail-closed result | Review |
|---|---|---|---|
| `tenant_id: Text` | R; P1 OrderContext tenant | Verified principal + current P1 context/request tenant; mismatch → not found/tenant conflict | A/P1/P5 |
| `order_request_id: Text \| None` | O; internal commercial adapter, future durable OrderRequest | Exact current persisted request ID is **absent today**; missing → INCOMPLETE, never use context/order ID as substitute | A/P5 |
| `source_context_id: Text` | R; P1 OrderContext | Re-read exact tenant/context row; missing → source conflict | A/P1 |
| `source_context_version: int` | R ≥1; P1 OrderContext | Match current context version and immutable version snapshot; stale → STALE_SOURCE | A/P1 |
| `source_context_version_record_id: Text \| None` | O; P1 OrderContextVersionRecord | Re-read exact version row ID and payload; absent/stale → STALE_SOURCE | A/P1 |
| `context_review_actor_id: Text \| None` | O; P1 context review | Re-read current review actor and authorized review action; absent/mismatch → REVIEW_REQUIRED | A/P1/P5 |
| `context_review_actor_role: Text \| None` | O; P1 context review | Re-read role at review time; **not** SME accept role | A/P1/P5 |
| `context_reviewed_at: AwareDatetime \| None` | O; P1 context review | Match aware current review time/version; naïve or stale → REVIEW_REQUIRED | A/P1 |
| `existing_order_id: Text \| None` | O; verified P1 order association | Re-read association; never equate with durable `order_request_id` or Core link | A/P1/P5 |
| `terms_revision: int \| None` | O ≥1; commercial adapter/PR #48 terms | Re-read immutable current terms revision; mismatch → TERMS_VERSION_CONFLICT | A/P5 |
| `terms_hash: Text \| None` | O; computed PR #48 canonical terms | Recompute from authoritative revision; mismatch → TERMS_MISMATCH; equality is not assent | A/P4/P5 |
| `canonical_terms: OrderTerms \| None` | O; PR #48 contract from supplied commercial evidence | Re-read exact persisted offer/terms and source/version/disclosure; missing → INCOMPLETE | A/P4/P5 |
| `customer_id: Text \| None` | O; P1 verified identity link | Re-read current tenant/customer association and source sender; unverified → IDENTITY_UNVERIFIED | A/P1/P5 |
| `customer_identity_evidence: tuple[Text, ...]` | O empty; P1 association IDs | Resolve every association ID/version and message/customer/tenant binding; mismatch → REVIEW_REQUIRED/TERMS_CONFLICT | A/P1 |
| `customer_identity_associations: tuple[CustomerIdentityAssociationEvidence, ...]` | O empty; P1 versioned association snapshots | Re-read `association_id/version/message_id/tenant_id/customer_id/updated_at`; changed → stale/identity conflict | A/P1 |
| `source_message_ids: tuple[Text, ...]` | O empty; P1 OrderContext | Re-read exact message set, tenant and evidence source IDs; missing → INCOMPLETE | A/P1 |
| `source_evidence_refs: tuple[Text, ...]` | O empty; P1 field/review/version refs plus validated commercial refs | Resolve each to tenant/source/field; nonempty string is not verified provenance | A/P1/P5 |
| `price_source_ref: Text \| None` | O; validated commercial `price_source.source_id` | Re-read approved catalog/quote **ID and version** from canonical terms/source authority; source ID alone inadequate | A/P5 |
| `price_disclosure_evidence: tuple[PriceDisclosureEvidence, ...]` | O empty; internal adapter disclosure assertions | Re-read real record and authority; verify tenant/customer/context/version/request/revision/hash/source ID+version/time, full offer/fees; absent → PRICE_SOURCE_UNVERIFIED | A/P4/P5 |
| `agreement_basis: AgreementBasis` | R default `UNKNOWN`; P1/P4 future agreement authority | Mapper always `UNKNOWN`; re-read original explicit offer or exact verified proposal assent later; UNKNOWN → agreement unverified | A/P4/P5 |
| `proposal_id: Text \| None` | O; future P4 exact proposal | Currently None; re-read active proposal ID, identity/digest/expiry; missing for changed terms → proposal required | A/P4/P5 |
| `proposal_version: int \| None` | O ≥1; future P4 proposal | Currently None; compare active persisted version; stale → proposal conflict | A/P4/P5 |
| `customer_assent_evidence: tuple[Text, ...]` | O empty; future P4 verified response | Currently empty; independently verify inbound identity, proposal ID/version/hash/expiry; generic reply/empty → no assent | A/P4/P5 |
| `readiness_status: MappingReadiness` | R; pure mapper result | Re-map from current authoritative inputs; `READY_FOR_VALIDATION` is only preparatory, never SME decision or P2 feasible | A/P1/B |
| `validation_reason_codes: tuple[Text, ...]` | O empty; mapper diagnostics | Recompute on current inputs; map to missing/stale/conflict without authorizing | A/B |
| `missing_fields: tuple[Text, ...]` | O empty; mapper diagnostics | Current missing evidence → INCOMPLETE/NOT_EVALUATED | A/B |
| `conflict_fields: tuple[Text, ...]` | O empty; mapper diagnostics | Current conflict → review/terms conflict, no evaluation promotion | A/B |

Nested `PriceDisclosureEvidence` (`:70-86`) includes exact context/request/terms/source ID+version, `disclosed_at`, `verification_status` and `authority_ref`. These are **adapter claims** until real source records are independently read. Nested `CustomerIdentityAssociationEvidence` (`:89-98`) preserves association version; the tuple of IDs alone would lose that version. `OrderCommercialEvidence` (`:103-132`) is an internal supplied input, not an approved catalog/quote reader. All “VERIFIED” fields are only as trustworthy as that missing server adapter. A successful `AcceptanceCandidate` validator proves internal consistency, not source freshness, sender authenticity or permission to act.

## 3. Reconciliation against B2–B4 handoff

| Earlier proposed field/behavior | PR #50 reality and status |
|---|---|
| Persisted `order_request_id`, `request_version`, `created_at/updated_at`, `correlation_id` | Candidate has optional supplied `order_request_id`; **no request version, durable request store or reader, candidate timestamps or correlation ID**. `source_context_version` is a different P1 version. **BLOCKED**, A/P5 design. |
| `source_context_id/version` plus exact version record | Implemented structurally with `source_context_version_record_id`, review and message/association snapshots. Current authoritative re-read after mapping remains **BLOCKED** until A/P1 adapter. |
| Exact `canonical_terms`, revision/hash | Implemented in #50 using #48's sole OrderTerms; validator binds tenant/customer/request/revision/hash. Source authenticity/current version and the known #48 contract corrections remain **REQUIRES REVIEW**. |
| Approved price source ID/version and full-offer disclosure | `price_source_ref` exposes only ID; source version is nested in `canonical_terms.price_source` and structured disclosure rows. Mapper checks internal binding, but catalog/quote and disclosure lookup authority is **BLOCKED**. |
| Customer original-offer or proposal assent status/hash/evidence | `agreement_basis` type has future choices but mapper always UNKNOWN; proposal fields None and assent tuple empty. No separate `assent_terms_hash`. **BLOCKED** for acceptance; P4/P1 approval needed. |
| Candidate readiness/negative diagnostics | **IMPLEMENTED on PR #50 branch:** `READY_FOR_VALIDATION`, `INCOMPLETE`, `REVIEW_REQUIRED`, `STALE_SOURCE`, `IDENTITY_UNVERIFIED`, `TERMS_CONFLICT`, `PRICE_SOURCE_UNVERIFIED` plus reasons/missing/conflicts. Not merged and not an SME/P2 decision. |
| P2 operational target/snapshot | Candidate carries no operational snapshot ID/version, material-use/warehouse or production plan. That separation is appropriate; B must load current P2 evidence. Provisional P2 type remains **BLOCKED** on P2 review. |

PR #50 tests cover missing request ID, stale context snapshot, foreign identity/commercial/disclosure refs, missing/unverified price/disclosure, current review time, exact terms mismatch and no side effects. They do not establish live persistence/authentication, explicit original-offer or customer assent, a P2 projection or reservation. PR #49 supplier quotation is not stock or approved price authority by itself.

## 4. Proposed Backend B → A OrderDecision

No shared DTO or route was published. Status below is relative to **this main-based B worktree**, not #50's unmerged branch.

| Dimension / fields | State and authority | Implementation status |
|---|---|---|
| Candidate validation: tenant/request/customer, request/context/terms/proposal refs and versions, readiness/reasons/evidence | A/P1/P4 source; B re-reads before use. `READY_FOR_VALIDATION` remains preparatory. | **PROPOSED**, #50 pure DTO exists unmerged; durable reader **BLOCKED** |
| P2 feasibility: snapshot ID/version, checked time, target/scenario ID, `FEASIBLE/INFEASIBLE/UNKNOWN/UNSUPPORTED/STALE`, constraints/evidence, assessment ID | P2 owns advisory result; existing B1/B3 only confirmed target/baseline. | Confirmed-only **IMPLEMENTED**; pending target **BLOCKED** on P2 review |
| SME decision: verified principal, role/scope, `NOT_DECIDED/APPROVED/REJECTED`, decision ID/time | Separate authenticated human command, not candidate readiness. | **BLOCKED** on P5 Auth/OrderRequest design |
| Reservation: `NONE/PENDING/UNKNOWN/CONFIRMED/FAILED/RELEASED`, operation ID, idempotency key, provider mode, bound receipt ref | Provider/P5 verified authority and reconciliation; no synthetic receipt promotion. | **BLOCKED** on port and durable intent review |
| Core: commitment ID/version, authoritative agreement/lifecycle state and audit/outbox refs | Core service only; A/B read projection, no duplicated mutable `ACCEPTED`. | Existing legacy Core **IMPLEMENTED**; request↔Core integration **BLOCKED** on P5 |

For current B5, pending candidate `feasibility_status=NOT_EVALUATED`, `sme_decision_status=NOT_DECIDED`, `reservation_status=NONE`, and Core request-link fields absent. The exact final DTO vocabulary is **REQUIRES REVIEW** by A/P1/P2/P4/P5. Separate `UNKNOWN`, `STALE`, `UNSUPPORTED` and `MISSING_EVIDENCE`; no false FEASIBLE/ACCEPTED state.

## 5. P2/P5 review package and GO/NO-GO

**P2 questions:** Approve a separate `PROJECTED/ADVISORY` single-line target keyed by tenant/request/terms/snapshot versions, never a fake confirmed Core row? Which exact BOM/ATP/capacity kernel extraction lets it compete with fixed confirmed commitments and protected active reservations? How are material-use time, warehouse, unit/variant and explicit production plan derived without guesswork? Which missing process/job ledger/current source returns UNKNOWN versus UNSUPPORTED? How is whole-batch validation performed so two individually feasible orders cannot both consume one lot or machine? B4's unchanged-kernel contention test proves that risk for synthetic confirmed-demand fixtures.

**P5 questions:** Which durable OrderRequest/request-version and verified SME principal are authoritative? How will B re-read latest P1 context/version/review/associations, price/disclosure and P4 assent in one tenant-safe decision boundary? Which current operational snapshot token is locked/rechecked against reservation? Which resource system owns all-material/capacity reservation, exact receipt source/binding, idempotent operation and partial/pending/unknown reconciliation? How are an accepted request and one Core Commitment linked with audit/outbox atomically or durably reconciled? What is the Core lock order and subscriber requirement? Existing local P3 `reserve_resource` is not this order-level authority.

**Approval status:** No documented P2 approval for shared semantic changes or P5 approval for request/Auth/Core/reservation integration was found in the inspected refs/reports. Backend A's #50 integration doc explicitly says owner review required. **GO for contract review and pure existing-boundary tests. NO-GO for a read-only provisional-target evaluator on current main without P2 review/approved representation; NO-GO for persistence, reservation or acceptance integration without A/P1/P4/P5 source/authority design.**

## 6. Validation and smallest safe P0 next slice

PR #50 exact-head detached worktree, Python 3.14, SQLite in-memory env and no providers: `python -m pytest -p no:cacheprovider tests/v2_2/test_context_mapping.py tests/v2_2/test_terms.py -q -o addopts= --disable-warnings --tb=short --basetemp=.../moumantai_b5_pr50_exact` → **75 passed, 0 failed/errors/skipped, 4 warnings**. Existing B worktree: `python -m pytest -p no:cacheprovider app/feasibility/tests/test_readiness.py app/feasibility/tests/test_pending_boundary.py app/feasibility/tests/test_portfolio_readiness.py app/feasibility/tests/test_projected_review_gate.py -q -o addopts= --disable-warnings --tb=short --basetemp=.../moumantai_b5_backend_b_focus` → **28 passed, 0 failed/errors/skipped**. B5 added no tests or runtime source. B4's 357-pass broad regression is earlier evidence, not rerun here. No PostgreSQL, full suite, live provider, PR #49 tests or end-to-end acceptance ran.

**Smallest next P0 slice:** Backend A/P1/P5 agree and implement a tenant-scoped **read-only authoritative candidate source adapter** for PR #50's existing DTO, with durable request identity/version design and real approved catalog/quote/disclosure lookups; P4 specifies exact original-offer/proposal assent proof. In parallel, P2/P5 review the B4 pure provisional-target proposal. Once those review gates are recorded, B can add a single-line read-only evaluator with negative tests. No acceptance/reservation/Core transition until those inputs and authorities are independently verified.
