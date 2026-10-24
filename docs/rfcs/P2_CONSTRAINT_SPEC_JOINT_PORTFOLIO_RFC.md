# P2 Contract RFC: Canonical ConstraintSpec and Joint Portfolio Verification

**Status:** PROPOSED / NOT RATIFIED — contract design only
**Date:** 2026-10-24 (Asia/Kuala_Lumpur)
**Scope:** P2-owned immutable constraint input and read-only joint verifier for pending OrderRequests; compatibility with Backend H PR #62.
**Decision authority:** P1 for request/source identity, P2 for feasibility semantics, P5 for Core/snapshot/reservation trust and integration. This document is not an owner approval.

## 1. Scope and invariants

This RFC proposes the typed contract and behavior needed for a solver to submit one complete multi-order allocation and schedule to P2 for independent validation. It does not authorize accepting an OrderRequest, reserving stock/capacity, changing Core state, or enabling a live provider/verifier. All proposed contracts remain pending P1/P2/P5 review. Pending OrderRequests are not Core Commitments. Solver feasibility does not equal P2 certification. Synthetic tests do not prove live authority. Backend H PR #62 is provisional.

These identities are independent and must never be equated or substituted:

| Identity | Meaning | Binding rule |
|---|---|---|
| request_version | Version of the pending OrderRequest record | Can advance while terms stay unchanged. |
| terms_revision | Version of that OrderRequest’s exact commercial terms | Independent of request_version. |
| terms_hash | Canonical digest of those exact terms | Must match the trusted P1/P5 terms source. It is not an identity version. |
| snapshot_id + operational_snapshot_version | One frozen P2 operational input | Both must match; equal version numbers from different snapshot IDs are not interchangeable. PR #48 names the corresponding receipt field snapshot_version; this proposed alias mapping awaits owner review. |
| assessment_id + assessment_watermark | P2 assessment identity and its input/source watermark | Both bind the spec and verification receipt. |
| core_commitment_version | Version of an already accepted Core Commitment | Protected accepted demand carries this version. It is null for a pending candidate; never synthesize a Core Commitment for optimization. |

A reservation receipt used by a later acceptance path must bind the exact tenant_id, order_request_id, operation/idempotency identity, request_version, terms_revision, terms_hash, snapshot_id, snapshot_version, and assessment_id. PR #48 is now merged into main; its structurally bound snapshot_version field is proposed to map to the P2 operational_snapshot_version identity. The mapping remains pending because the P1/P5/Backend B approvals of #48 do not explicitly ratify this RFC alias. Matching terms alone is insufficient, and a structurally matching receipt does not establish provider authenticity, currentness, or P2 verification authority.

## 2. Source authority inventory

The repository was inspected in an isolated worktree at base feat/p2-7b4b-confirmed-consumer / 638ffbec0d79e59dcbabdff793232abf60c54c34. The working tree was clean before this RFC. The authority files and open changes below were read at their observed refs; files on open branches are evidence about proposals, not merged authority.

| Source | Observed state | Relevance to this RFC |
|---|---|---|
| docs/REQUIREMENTS_SYSTEM.md and docs/requirements/PERSON_2_FEASIBILITY_REQUIREMENTS.md | Read from the inspected P2 source ref feat/p2-7b4b-confirmed-consumer at 638ffbec0d79e59dcbabdff793232abf60c54c34 | System contract requires deterministic ATP/BOM/capacity, UNKNOWN distinct from INFEASIBLE, no unconfirmed supply, immutable evidence-backed snapshots, and P3 reuse of P2 pure evaluator. P2 owner requirements call for time-phased ATP, reservations, BOM, capacity, and side-effect-free hypothetical evaluation. |
| AGENTS.md | Present and also supplied in the task | P2 owns feasibility semantics; P5 owns shared contracts, Core, audit, and reservations. Shared contracts need owner review. Pending is not confirmed; solver results do not authorize side effects. |
| REQUIREMENTS_BACKEND.md, IMPLEMENTATION_BLUEPRINT.md, REVIEW_DECISIONS.md | Read from PR #48 review head 741976d3cdd59352d66a30c5712ce9eca5d3bc16; not present at those root paths on the inspected P2 source ref | Backend section 6 says reuse one pure calculation kernel. Section 7 requires one versioned P2 constraint definition, joint post-solve validation, exact evidence, fixed accepted commitments/reservations, and no acceptance from a portfolio result. Blueprint section 5.1 requires whole-projection and per-order checks on that same projection. REVIEW_DECISIONS.md labels the v2.2 document an engineering proposal awaiting owner review; it is not itself P2 ratification. Current PR #48 reservation code was rechecked separately at head 568e5deff97a29244944ae31b5d138fa910a4042 below. |
| docs/TEAM_LOG.md | Read on the inspected P2 source ref; latest P2-specific entries cover Phase 7B-4B/4E on 2026-10-22 | Existing P2 evaluator is confirmed-demand focused; source authority and P5 snapshot lock/recheck remain integration concerns. No canonical pending portfolio spec/verifier was recorded as ratified. |
| PR #48 | Merged into `main` at merge commit `de3483499accd11cfed718147911cdbaab214837`; corrected head `568e5deff97a29244944ae31b5d138fa910a4042` is in current `main` | `request_version` and `terms_revision` are independent; `ReservationReceipt` requires terms revision, snapshot ID/version and assessment ID; `require_receipt_binding()` compares those plus tenant/order/operation/idempotency/request version/exact terms hash. P1, P5 and Backend B approved the corrected head; exact-head CI run `40054989068` passed five jobs, including PostgreSQL. The separate proposed alias from `snapshot_version` to `operational_snapshot_version` is not explicitly ratified by those scoped approvals and remains pending. Structural binding does not prove provider authenticity or live P2 authority. |
| PR #53 | Open, Draft, head ea2a5df275256b84528feceebbbe8f0b4fd83f76 | Backend B read-only readiness uses existing P2 calculation results and explicitly keeps pending targets unsupported. It does not add pending-order projection or joint verification. Its review does not ratify the P2 portfolio contract. |
| PR #62 | Open, Draft, corrected head `26bff7b94a2f8939a7c0a7f79501e771699e01e5` | Backend H provides provisional DTOs, CP-SAT optimization and a synthetic fixture verifier only. Its `_verify()` checks fixture projection/receipt bindings described in §6 and rejects LIVE mode with `P2_JOINT_VERIFIER_UNAVAILABLE`. P2 approval covers the advisory solver and fixture scope only; it does not ratify P2 authority or enable LIVE verification. Exact-head PR and push CI passed, including PostgreSQL and real CP-SAT jobs. |

The inspected P2 source ref does not contain backend/app/optimization. That code exists on PR #62 open branch.
## 3. Existing P2 behavior that can be reused

| Existing symbol | Reusable semantics | Boundary / gap |
|---|---|---|
| backend/app/feasibility/inventory.py::calculate_atp() | Exact Decimal, tenant-checked material ATP over an OperationalSnapshot; revalidates frozen inputs; expands BOM; checks source freshness; accounts for active reservations, lots, warehouse scope, expiry at material use, and confirmed receipts available by material-use/logistics cutoff. Returns UNKNOWN for incomplete evidence and SHORTAGE only with known shortage. | Demand is derived from snapshot.confirmed_commitments. It does not accept pending OrderRequests or a proposed joint allocation. Unconfirmed incoming delivery is never allocated. |
| backend/app/feasibility/bom.py::explode_bom() and OperationalSnapshot.quantity_in_base() | Recursive BOM explosion, waste multiplier, exact unit conversion, cycle/missing-BOM diagnostics, evidence refs, deterministic ordering. | Current expansion walks confirmed commitments only. A pending candidate must remain a separate demand input; it cannot be inserted as a Core Commitment just to call this function. |
| backend/app/feasibility/capacity.py::check_capacity() | Validates supplied fixed production plans against exact working windows, fixed jobs, exclusive resource overlap, process/setup/transit durations, dispatch cutoffs and commitment deadlines. Missing/stale evidence yields UNKNOWN. | It validates supplied schedules for existing confirmed commitments. It does not choose or jointly schedule new candidate tasks. It explicitly does not prove all alternative schedules impossible. |
| backend/app/feasibility/service.py::evaluate() | Pure confirmed-target evaluator composed from ATP and capacity; validates tenant, exact Core commitment version/terms and snapshot membership; supports a bounded hypothetical change for one confirmed target; returns constraints, assumptions, evidence, and snapshot-bound status. | Requires an existing confirmed single-line Core Commitment in the snapshot. It is not a pending-order portfolio verifier. evaluation_identity() is a content identity, not source authentication or a signed receipt. |
| backend/app/feasibility/currentness.py::require_current_snapshot() | Rejects missing current-version authority and stale operational snapshot version. | Checks version only; a future portfolio contract must bind and compare both snapshot ID and version, and bind an assessment identity. |
| backend/app/feasibility/models.py, production.py | Frozen P2-local OperationalSnapshot contains snapshot ID/version, tenant, source evidence, catalog, BOM, lots, reservations, incoming deliveries, capacity calendars, confirmed commitments, logistics cutoff and conversions. EvaluationSnapshot adds production sources/resources/processes/plans/jobs and a current snapshot version. Lots include warehouse and expiry; incoming deliveries include confirmation evidence. | These are P2-local calculation models, not a shared persisted P5 snapshot contract. InventoryLot has no modeled quality attributes/policy. Production structures describe known plans/jobs, not candidate scheduling. |
| PR #53 assess_operational_readiness() / inspect_portfolio_inputs() | Read-only readiness wrappers around evaluate(), calculate_atp() and check_capacity(); useful for baseline readiness. | On PR #53 only; not merged into the selected base. PENDING_TARGET_UNSUPPORTED is the intended result for pending targets. Neither helper performs joint allocation or schedule verification. |

**Reusable P2 functions:** calculate_atp(), check_capacity(), evaluate(), explode_bom(), OperationalSnapshot.quantity_in_base(), source_issues(), evidence_for(), and require_current_snapshot(). Reuse means retaining these semantics and their regression coverage. The portfolio extension needs a shared P2 calculation seam that accepts a pending-demand overlay; it must not create a second set of ATP/BOM/capacity rules.

## 4. Missing P2 contracts and capabilities

1. No P2-owned immutable ConstraintSpec, canonical builder version, source watermark, or ConstraintSpecProvider exists on the selected base.
2. No P2 mapping contract binds a trusted pending OrderRequest to its separate request, terms, source identity, and evidence versions.
3. No pure P2 projection input represents pending demand separately from accepted Core Commitments.
4. No contract expresses exact joint lot allocations, protected accepted allocations, shared resource schedules, or a canonical projection digest.
5. No P2 verifier validates all selected pending candidates together against one frozen snapshot and returns a receipt bound to that projection.
6. Lot quality policy is not represented by current P2 InventoryLot; if a required quality attribute is absent or cannot be proven, the candidate must be UNKNOWN until P1/P2 agree on a source and semantics.
7. Current P2 source models have per-source observation/freshness fields, but no portfolio assessment identity/watermark or per-candidate terms_revision binding. Currentness is not a durable P5 reader/lock contract.
8. P2 has no policy-approved conversion from CP-SAT integer minutes to P2’s exact interval semantics. Current check_capacity() validates offset-aware instants and exact microsecond durations. Any lower solver granularity that rounds a boundary is unsupported until P2 explicitly accepts it.
9. No receipt authenticity/replay contract defines how a P2 validation result is trusted across the Backend H/P5 boundary.

## 5. Proposed contract (PROPOSED / NOT RATIFIED)

### 5.1 Request and identity DTOs

The following names are proposed, not implemented. Types are descriptive; final Pydantic details and aliases require P1/P2/P5 approval.

    CandidateIdentity {
      tenant_id: str                         # resolved from authenticated server context
      order_request_id: str
      request_version: positive-int
      terms_revision: positive-int
      terms_hash: str                        # opaque canonical P1/P5 hash
      source_identity_ref: str               # P1-verified identity link
      source_context_id: str
      source_context_version: positive-int
      core_commitment_version: positive-int | null  # null for pending candidate
    }

    PendingCandidate {
      identity: CandidateIdentity
      state: PENDING_ACCEPTANCE
      received_at: offset-aware datetime | null
      received_at_verified: bool
      lines: [CandidateLine]
      source_evidence_refs: [str]
    }

    CandidateLine {
      line_id: str
      sku_id: str
      requested_quantity: Decimal
      requested_unit: str
      material_use_at: offset-aware datetime
      order_deadline: offset-aware datetime
      dispatch_cutoff_at: offset-aware datetime
      required_warehouse_id: str | null
      quality_requirements: structured policy ref | null
      terms_revision: positive-int
      terms_hash: str
      source_evidence_refs: [str]
    }

The terms_revision and terms_hash on a line, if carried, must equal the enclosing CandidateIdentity; they never equal request_version by rule. P1/P5 resolves the OrderRequest and terms server-side; a client-provided actor_scope_verified=true, source_identity_ref, or candidate state is not proof. A candidate with an accepted Core Commitment is not a pending candidate. Core versions for accepted demand are carried in protected-demand rows.

PortfolioBuildRequest contains portfolio_run_id, authenticated tenant_id, exact candidate identities/lines and evaluated_at. It may carry expected_snapshot_id and expected_operational_snapshot_version as compare-only guards. It does not accept caller-authoritative constraint_spec_version, assessment_id, or assessment_watermark; P2 issues those. If an expected snapshot is supplied and is not current, build returns REJECTED/STALE_SNAPSHOT.

### 5.2 ConstraintSpec

ConstraintSpec is immutable and created by P2 from exactly one tenant-scoped frozen operational snapshot and one exact candidate set. It contains:

| Field group | Required content |
|---|---|
| Contract identity | constraint_spec_id, spec_schema_version, constraint_spec_version (P2 semantic/ruleset version), tenant_id. Schema version and ruleset version are distinct. |
| Frozen input binding | snapshot_id, operational_snapshot_version, snapshot_digest, captured_at, assessment_id, assessment_watermark, built_at, and valid_through. |
| Candidate binding | One exact CandidateIdentity for each eligible pending candidate, plus source identity/evidence refs. No candidate omitted, duplicated, or promoted to Core. |
| Normalization policy | SKU/base-unit mapping, exact conversion factors and conversion version, Decimal precision/scale/overflow limits, BOM/waste policy, supported time precision, and business timezone. No binary-float arithmetic or silent rounding. |
| BOM-expanded requirements | Candidate/order/line identity, component path, material SKU, normalized required quantity and unit, material-use instant, required warehouse/location policy, quality requirement, compatible lot/supply IDs, and evidence refs. |
| Lot inventory | Lot ID, SKU, source quantity/unit, normalized quantity, warehouse/location, quality attributes and verification state, expiry instant, source refs, observation/freshness. A missing required quality proof is an unsupported diagnostic, not assumed compatible. |
| Confirmed incoming supply | Delivery ID, SKU, normalized quantity/unit, expected availability instant, warehouse, explicit confirmed status/time, confirmation evidence, source freshness. Unconfirmed ETA/prediction never appears as allocatable supply. |
| Protected accepted demand | Exact accepted commitment_id and core_commitment_version, normalized demand, material-use/deadline, and protected baseline allocations. These rows are fixed throughout the projection. |
| Protected reservations | Exact active reservation ID, owner commitment/version, lot, normalized quantity, and evidence. Released/consumed reservations are not active supply holds. No reservation may be displaced or counted twice. |
| Production | Resource IDs, exclusive/shared capacity rule, complete calendar windows and timezone, fixed accepted jobs with exact intervals, existing accepted plans, candidate task process/setup duration, allowed resource set, earliest start, latest finish, dispatch cutoff, order deadline, and evidence/freshness. |
| Diagnostics and proof inputs | Per-source observed_at, valid_through, freshness state and evidence refs; coverage state; structured unsupported-input diagnostics; canonical source watermark. |

The base P2 source models do not currently contain lot quality. Until an owner-approved quality source/policy is added to the P2 input contract, a request that depends on quality compatibility returns UNKNOWN/LOT_QUALITY_UNMODELED; this RFC does not invent quality values.
### 5.3 Pending portfolio projection

ProjectedPortfolio is an in-memory, read-only overlay over the original immutable ConstraintSpec. It carries:

- portfolio_run_id, tenant, snapshot ID/version, spec ID/version, assessment ID/watermark;
- the exact selected CandidateIdentity[] (including request_version, terms_revision, and terms_hash);
- allocation rows with order/request/terms identity, line ID, BOM component path, material SKU, lot or confirmed-delivery ID, exact Decimal quantity/unit, material-use instant and evidence refs;
- scheduled candidate tasks with task/order identity, request/terms versions, resource IDs, start/end instants, setup/process duration, dispatch cutoff and order deadline; and
- projection_digest_version and projection_digest, computed over the exact identity vector, sorted allocation rows, and sorted schedule rows.

Digest canonicalization is versioned: sort rows by stable composite identity; encode Decimal values as canonical decimal strings; encode instants as UTC with exact supported precision; include tenant, portfolio run, candidate versions/hashes, snapshot/spec/assessment bindings, all allocated supply IDs/quantities and every scheduled resource/interval. A changed allocation or schedule changes the digest. Solver IDs alone are not a digest.

The original OperationalSnapshot is never mutated. Pending candidates remain PENDING_ACCEPTANCE and are represented in a separate projection type; do not append them to confirmed_commitments or create synthetic Core versions. Existing accepted commitments, active reservations, confirmed deliveries and fixed jobs remain present and protected. Candidate demand is layered on the remaining eligible supply/capacity and is jointly consumed by all selected candidates. Unsupported units, quality rules, supply states, schedule granularity or incomplete evidence fail closed as UNKNOWN.

### 5.4 Provider and verifier ports

    ConstraintSpecProvider.build_for_portfolio(
        request: PortfolioBuildRequest
    ) -> ConstraintSpec

    JointPortfolioVerifier.verify(
        request: PortfolioVerificationRequest,
        constraint_spec: ConstraintSpec,
        candidate: ProjectedPortfolio
    ) -> PortfolioVerificationReceipt

These are the proposed P2-owned methods. Backend H may retain the method names, but its request/result DTOs and verifier call must change to carry the P2-issued spec identity and exact projection. The provider resolves current P1 request identity and P2/P5 operational inputs; the verifier revalidates the complete candidate portfolio jointly. The verifier never trusts a solver feasibility flag as proof.

### 5.5 Joint verification algorithm

1. Revalidate DTOs at the P2 boundary, derive/confirm tenant from trusted server context, and resolve every order_request_id to the exact current P1/P5 pending row. Compare request version, terms revision/hash, source identity, line terms and evidence refs independently.
2. Load the exact immutable snapshot by (tenant_id, snapshot_id, operational_snapshot_version). Confirm it is current when currentness is required. A wrong or stale snapshot ID/version is REJECTED/STALE_SNAPSHOT, even when terms match. Recompute/check snapshot digest, assessment ID and watermark.
3. Check each source’s evidence and freshness at verification time. Missing authority, incomplete source coverage, or expired/unknown source freshness is UNKNOWN; it cannot validate a solver result.
4. Recompute the P2 baseline for existing accepted commitments/reservations using shared P2 BOM/ATP/capacity semantics. Lock their allocations and schedules as protected constraints. A known existing hard violation is surfaced; P2 must not repair it by stealing protected resources for pending candidates.
5. Expand every selected candidate’s BOM using the same P2 conversion/waste/eligibility policy used for ordinary evaluation. Validate eligible lot/confirmed supply against exact material-use time, quality, warehouse/location, quantity, expiry and evidence. Sum all selected demand by actual lot/delivery ID; reject any joint over-allocation.
6. Validate the full proposed schedule against the same calendars, fixed accepted jobs and protected accepted plans. Check exclusive-resource overlap, working-window coverage, setup/process durations, material availability at use, dispatch cutoffs and order deadlines. Intervals are exact offset-aware instants at P2-supported precision; do not round H’s integer-minute schedule into apparent feasibility.
7. Independently verify the full portfolio and each included candidate against this same shared allocation/schedule projection. Do not re-run each order against the original unprojected snapshot. A subset may be individually feasible while the joint set is infeasible.
8. Compare solver claims with P2’s result. A solver FEASIBLE projection rejected by P2 is REJECTED/SOLVER_P2_DISAGREEMENT; an unresolved solver/P2 input or evidence gap is UNKNOWN. P2 validates feasibility of the supplied projection, not solver optimality or the strategy’s business preference.
9. Recompute the canonical projection digest inside the trusted P2 boundary, create the receipt only for that digest and exact candidate/version vector, and return it without database writes or operational permission.

### 5.6 Receipt and replay binding

PortfolioVerificationReceipt contains:

| Field | Meaning |
|---|---|
| status | P2_VALIDATED, REJECTED, or UNKNOWN |
| portfolio_validation_id, portfolio_run_id, tenant_id | Unique validation identity and call scope |
| validated_candidates | Exact CandidateIdentity set: IDs, request versions, terms revisions/hashes, source identity refs |
| snapshot_id, operational_snapshot_version | Exact frozen snapshot identity |
| constraint_spec_id, constraint_spec_version | Exact P2 contract/ruleset identity |
| assessment_id, assessment_watermark | Exact P2 assessment and source-input identity |
| projection_digest_version, projection_digest | Canonical digest of exact allocations and schedule |
| evidence_refs, reason_codes | Evidence and structured candidate/resource/constraint diagnostics |
| coverage_diagnostics, freshness_diagnostics | Per-material/per-resource coverage and per-source freshness |
| verified_at, valid_through | Offset-aware verification time and optional expiry |
| issuer, issuer_proof | P2 verifier identity/version and authenticated in-process result or signed canonical envelope when crossing a process boundary |

P2_VALIDATED is possible only when all fields bind to the request and P2-computed projection. Consumers compare the receipt tenant, portfolio run, entire candidate identity set, snapshot ID/version, spec ID/version, assessment ID/watermark and projection digest with their own expected values. A status string, owner="P2", matching order IDs, or matching terms alone is never sufficient. A changed allocation or schedule fails the digest check. A receipt from another portfolio run or expired receipt cannot be replayed as validation for the current run. For cross-process transport, P2/P5 must ratify a signing/key or authoritative receipt-lookup mechanism before use; this RFC does not implement that trust mechanism.

P2_VALIDATED means only that P2 validated this exact hypothetical projection on its stated evidence/snapshot. It does not mean the order is accepted, reserved, guaranteed feasible in the future, or authorized for any side effect.
## 6. Compatibility with Backend H PR #62

PR #62’s useful boundary names are ConstraintSpecProvider.build_for_portfolio() and JointPortfolioVerifier.verify(). Keep CP-SAT search as a consumer of P2 semantics, but adjust these provisional H DTOs before any LIVE wiring:

| PR #62 provisional field/behavior | Required P2 contract adjustment |
|---|---|
| PortfolioRequest supplies snapshot_id, snapshot_version, constraint_spec_version, and assessment_watermark | P2 owns and emits these values. H may pass expected snapshot guards, but cannot assert P2’s current snapshot/spec/assessment authority. Add exact assessment_id. |
| actor_scope_verified: bool | Replace with server-authenticated context/registered P5 adapter; a boolean in a DTO is not authentication. |
| PendingOrderCandidate and CandidateBinding already carry separate request version, terms revision and hash | Preserve these as independent identities; keep candidate lines and all projection rows bound to them. Do not map request_version to terms_revision. |
| P2ConstraintSpec.owner accepts P2 or SYNTHETIC_TEST_FIXTURE | Fixture mode remains test-only. A payload label is not P2 authority; only the registered P2 provider plus trusted receipt proof can attest a live result. |
| accepted_reservations_protected: bool | Replace/augment with exact protected reservation and accepted-demand/allocation records plus evidence. A boolean cannot prove which lots/quantities are protected. |
| AuthorizedLot.free_quantity, warehouse, minute offsets, expiry offsets and refs | Add source quantity/unit, exact normalized quantity, quality verification/policy, source freshness, actual time instants, protected allocations and exact source/evidence bindings. Unsupported quality remains UNKNOWN. |
| MaterialRequirement references candidate ID/line/SKU/quantity/unit/compatible lots | Bind each requirement to the full candidate identity, BOM component path, material-use instant, location/quality policy, and source evidence/freshness. |
| ProjectedPortfolio.selected_order_ids, simple lot allocations, and integer-minute schedule | Add exact candidate versions/hashes, BOM material identity, supply ID/kind, quantity unit, resource IDs, exact intervals, deadlines, and the canonical digest. P2 must approve any time scaling; current P2 checks exact microsecond intervals. |
| `JointVerificationResult` is a synthetic fixture receipt | Current #62 `_verify()` checks fixture-only status/provenance; tenant; snapshot ID/version; constraint-spec version; assessment watermark; portfolio run ID; selected order IDs and exact request/terms/source/evidence bindings; allocation, schedule and projected-portfolio digests; evaluation and validity fields. The DTO has no `assessment_id` or spec ID, and the verifier/receipt is not authenticated P2 authority. Keep the fixture checks, add P2-owned assessment/spec identity and authenticated receipt semantics before LIVE use, and preserve `P2_JOINT_VERIFIER_UNAVAILABLE`. |
| H validation can use an accepted-reservations-protected assertion and fixture-labelled verifier | Keep H in advisory/synthetic mode until P2 returns the complete bound receipt. Preserve fail-closed P2_CONSTRAINT_SPEC_UNAVAILABLE / P2_JOINT_VERIFIER_UNAVAILABLE; never promote FIXTURE_VALIDATED to P2 validation. |

PR #53’s pending readiness status must remain PENDING_TARGET_UNSUPPORTED until P2 approves and implements the separate projection contract. Keep calculate_atp(), check_capacity(), Core ownership and the authoritative reservation boundary intact. H must not create a second ATP/BOM/capacity calculator; P2 must implement the additive candidate overlay and joint verifier after owner review.

## 7. Required regression matrix

| Case | Expected exact behavior |
|---|---|
| A needs 70 units; B needs 60; only 100 eligible units exist | A alone → P2_VALIDATED; B alone → P2_VALIDATED; A+B on one projection → REJECTED/JOINT_MATERIAL_SHORTAGE, with no validated candidate set. No lot may be double allocated. |
| Protected accepted reservation consumes the lot | Candidate allocation cannot use the reserved quantity. If no remaining eligible supply exists → REJECTED/INSUFFICIENT_ELIGIBLE_SUPPLY; protected owner/version and reservation remain unchanged. |
| Same SKU, incompatible lot quality or required warehouse | The lot is ineligible. If the candidate relies on it and no eligible alternative exists → REJECTED/LOT_INELIGIBLE; if quality evidence is missing/unmodeled → UNKNOWN/LOT_QUALITY_UNVERIFIED. |
| Lot expires before actual material-use time | Allocation of that lot → REJECTED/LOT_EXPIRED_AT_USE; a valid alternate lot may still validate. Expiry is tested at material use, not order receipt or solver start rounding. |
| Candidate relies on unconfirmed supplier ETA | Unconfirmed delivery is absent from allocatable supply. Reliance on it → REJECTED/UNCONFIRMED_SUPPLY; if P2 cannot establish delivery status/evidence → UNKNOWN/SUPPLY_STATUS_UNKNOWN. |
| Two candidate tasks overlap on one exclusive resource | REJECTED/RESOURCE_CALENDAR_CONFLICT or REJECTED/RESOURCE_OVERLAP; no validated portfolio. |
| Candidate task overlaps a fixed accepted production job | REJECTED/FIXED_JOB_CONFLICT; fixed job is never moved to make the portfolio pass. |
| Snapshot ID or version is stale/wrong | REJECTED/STALE_SNAPSHOT even if order terms and numeric version happen to match a different snapshot. |
| Matching terms, stale snapshot, or wrong assessment | REJECTED/STALE_SNAPSHOT or REJECTED/ASSESSMENT_BINDING_MISMATCH; exact snapshot ID/version and assessment ID/watermark are mandatory. |
| Candidate tenant differs from authenticated portfolio tenant | REJECTED/CANDIDATE_TENANT_MISMATCH; do not disclose the other tenant’s data. |
| Valid request_version differs from valid terms_revision | Both versions match their own trusted fields; accept the identity binding and continue feasibility checks. Never require equality. |
| request_version differs from trusted current OrderRequest | REJECTED/REQUEST_VERSION_MISMATCH; no fallback to terms revision. |
| terms_revision differs, even if request_version is valid | REJECTED/TERMS_REVISION_MISMATCH. |
| terms_hash differs, even if versions otherwise match | REJECTED/TERMS_HASH_MISMATCH. |
| Same order IDs, changed lot allocation | Receipt digest differs; reject as REJECTED/PROJECTION_DIGEST_MISMATCH. |
| Same allocation, changed schedule/resource/interval | Receipt digest differs; reject as REJECTED/PROJECTION_DIGEST_MISMATCH. |
| Solver reports feasible; P2 joint verifier rejects | REJECTED/SOLVER_P2_DISAGREEMENT; suppress feasible/recommended portfolio and do not authorize acceptance. |
| Unknown or expired source evidence | UNKNOWN/SOURCE_EVIDENCE_UNKNOWN or UNKNOWN/SOURCE_STALE; never P2_VALIDATED. |
| Missing P2 provider/verifier | UNKNOWN/P2_CONSTRAINT_SPEC_UNAVAILABLE or UNKNOWN/P2_JOINT_VERIFIER_UNAVAILABLE; no portfolio certification. |
| Replayed receipt for another portfolio run or changed candidate version | Reject because run/candidate identity vector does not match. |
| Existing accepted demand already consumes all eligible supply | Pending candidates cannot displace it; reject for known shortage or return UNKNOWN if baseline source coverage is incomplete. |

No result in this matrix grants operational permission. A subsequent SME acceptance must re-read exact current terms and snapshot, repeat P2 validation, and use P5’s authoritative reservation/Core flow.
## 8. Ownership, approvals, and open decisions

| Owner | Required decision before implementation |
|---|---|
| P1 | Confirm authoritative OrderRequest/source identity reader and exact source_identity_ref/context evidence; confirm candidate-ready status and verified received_at policy; confirm which source versions/evidence bind each line; confirm request_version, terms_revision, and terms_hash semantics remain separate. |
| P2 | Ratify DTO names/versions and assessment watermark; define normalized units/precision/BOM waste policy; approve lot quality and warehouse eligibility sources; define exact protected allocation semantics, including avoiding reservation double subtraction; approve confirmed incoming supply evidence/freshness; approve schedule interval precision, resource/calendar semantics and unsupported diagnostics; own verifier result/reason codes and no-write behavior. |
| P5 | Confirm the authoritative tenant-scoped immutable snapshot reader and currentness check bind both snapshot ID and version; define trusted Core versions/protected demand; approve how a P2 validation receipt is authenticated, retained/retrieved and consumed; preserve exclusive reservation/Core transition ownership and audit/outbox semantics. |
| Backend A / merged PR #48 | Corrected head `568e5deff97a29244944ae31b5d138fa910a4042` is merged into `main`; P1, P5 and Backend B approved this exact head and exact-head CI passed. The receipt carries `snapshot_version`; mapping it to P2 `operational_snapshot_version` remains proposed. Those scoped approvals do not explicitly approve the alias, so P1/P5 must ratify it before an adapter treats the fields as equivalent. |
| Backend B / PR #53 | Keep readiness read-only and pending targets unsupported until P1/P2/P5 ratify the projection and status semantics; then reconcile request/version mappings without introducing a second evaluator. |
| Backend H / PR #62 | Keep the existing P2 ports unavailable for LIVE use; after approval, map H’s solver DTOs to the ratified P2 spec/projection/receipt, add exact digest comparison, and preserve synthetic fixture labels as test-only. |

Unresolved cross-owner points are deliberate: quality data authority; P2 assessment ID lifecycle; watermark encoding; source freshness expiry behavior; exact solver time scaling; receipt authentication mechanism; and whether P5 stores immutable validation receipts or validates a P2-signed envelope. None is silently settled by this RFC.

## 9. Acceptance criteria for a future implementation

A future implementation may be considered for review only after all of the following are evidenced:

1. P1, P2 and P5 approve contract fields, ownership and status/reason semantics above; P1/P5 explicitly ratify or reject the proposed #48 `snapshot_version` → P2 `operational_snapshot_version` mapping, and any changed interface is reflected in the adapter mapping.
2. One P2 builder returns an immutable spec for exactly one tenant, snapshot ID/version, assessment ID/watermark and exact candidate identity set.
3. Candidate orders remain pending; the original snapshot and Core registry are not mutated by building or verifying a projection.
4. A solver’s complete allocation and schedule are verified jointly and individually on one projection using P2’s shared semantic kernel; all accepted demand, reservations and fixed jobs remain protected.
5. Any unsupported, missing, stale, cross-tenant, digest-mismatched, or solver-disagreeing input fails closed to REJECTED or UNKNOWN, never P2_VALIDATED.
6. The receipt binds tenant, portfolio run, exact candidate IDs/versions/terms, snapshot ID/version, spec version, assessment ID/watermark, evidence/freshness and canonical projection digest.
7. The 70/60/100 contention case and every negative case in §7 pass before any live consumer wiring is requested.
8. No result is interpreted as customer acceptance, stock/capacity reservation, Core transition, purchase, or Recovery execution.

## 10. Safe implementation sequence after approval

1. P1 and P5 publish reviewed read-only candidate and frozen-snapshot adapters; no solver input is treated as an authenticated source.
2. P2 freezes DTO/version semantics and source/freshness policy; unknown quality or unsupported time/unit conversions remain fail-closed.
3. P2 adds a pending-demand overlay to the existing shared calculation kernel. Keep current calculate_atp(), check_capacity() and evaluate() behavior covered; do not duplicate their rules or write pending candidates into confirmed_commitments.
4. P2 implements the pure ConstraintSpec builder and joint verifier, then adds the §7 regression suite, including allocation- and schedule-digest tampering.
5. Backend H adapts provisional models and solver output to the approved P2 DTOs; P2 validates before H displays a feasible portfolio. P5 reviews receipt trust and any persistence/audit contract separately.
6. Only a later, separately reviewed P5 acceptance path may revalidate current exact terms and reserve resources. A portfolio validation receipt is not a reservation receipt or action token.

## 11. Explicit review state

**This RFC is PROPOSED / NOT RATIFIED.** It is a concrete review package, not a P2 certification, owner signoff, implementation approval, or operational enablement. Required P1/P2/P5 decisions are listed in section 8. PR #48's corrected head `568e5deff97a29244944ae31b5d138fa910a4042` is merged into `main` and has scoped P1, P5 and Backend B approval. The proposed snapshot-version alias remains unratified; the #62 verifier remains synthetic-only and LIVE remains fail-closed. Downstream mapping depends on the final owner-reviewed names and semantics.

## 2026-10-24 live review refresh

The actual #62 source inspected was PR head `26bff7b94a2f8939a7c0a7f79501e771699e01e5`, not the earlier `332546e` checkpoint. Its synthetic fixture verifier compares tenant, snapshot ID/version, constraint-spec version, assessment watermark, run ID, selected candidate IDs and source/version/evidence bindings, allocation/schedule/projected-portfolio digests, and evaluation/validity fields. `JointVerificationResult` has no `assessment_id` or spec ID; the fixture verifier is not an authenticated P2 receipt, and `_verify()` rejects LIVE with `P2_JOINT_VERIFIER_UNAVAILABLE`. Synthetic fixture validation does not establish live feasibility or reservation authority.

PR #48 is merged into `main` at `de3483499accd11cfed718147911cdbaab214837`; corrected head `568e5deff97a29244944ae31b5d138fa910a4042` has scoped P1/P5/Backend B approvals and exact-head CI success. The `snapshot_version` alias mapping is still pending explicit ratification. The RFC's current `main` base is `eaa5097452f17f5c4f1c9ccc6c0a5b9f5678c86a`; its old `TEAM_LOG.md` merge conflict is being refreshed while preserving both histories.
