# Backend B B4 — projected-target feasibility review

**2026-10-24 SGT. Disposition: REVIEW-READY DESIGN, BLOCKED ON P2 OWNER APPROVAL.** No projected-target evaluator was implemented. The present P2 kernels consume a confirmed-demand snapshot and a confirmed Core target. Reusing them by labelling a pending OrderRequest as confirmed would violate that meaning. B4 adds one pure existing-kernel contention test and an [Backend A handoff update](BACKEND_AB_CONTRACT_HANDOFF.md#8-b4-review-note-for-meishuet--provisional-feasibility-is-still-advisory). This is not an acceptance workflow.

## 1. Git baseline and preservation

Existing worktree `C:/Users/User/OneDrive/Documents/sdc hackathon 2026/MouManTAI-backend-b-b1-readiness`, branch `feat/backend-b-b1-readiness`, HEAD `3efa7f23fc2842664f1164cc1dce363f7371bdd3`. Latest fetched `origin/main` is the same SHA; PR #48 exact head `741976d3cdd59352d66a30c5712ce9eca5d3bc16`, stacked PR #49 `62040da02b4ec3532ea02d734567e0913996ec2b`. Neither PR head advanced in this fetch. Main has no new Backend A candidate/pending-order mapper or P2 semantic change. Inspected relevant P2 remote branch names and repository docs/source for a provisional-target owner approval; **no documented approval was found in this inspected material**. This is an evidence limit, not a claim about private conversations.

B1/B2/B3 source, tests and reports remain uncommitted and untouched. The dirty original P3 checkout, Phase 0/0.1 reports, PR #48 reconciliation worktree and three untracked interrupted duplicate Phase 1A files remain preserved. No reset, clean, stash, merge, commit, push, migration or shared code edit. The v2.2 six-document pack is the target; B1–B3 and [A/B handoff](BACKEND_AB_CONTRACT_HANDOFF.md) were read rather than redone.

## 2. Actual P2 constraint dependency map

| Existing code | Exact dependency and semantics |
|---|---|
| `feasibility/service.py:101-134` | `evaluate` requires tenant-matching Core `Commitment`, matching ID/version in `OperationalSnapshot.confirmed_commitments`, `agreement_state=CONFIRMED`, one matching line and terms/deadline. `REQUESTED/OFFERED` and absent target reject before calculation. B2 tests pin this boundary. |
| `feasibility/models.py:119-169,224-235,318-~555`; `production.py:99-150` | Tenant/version/source-bound operational and production data; active reservations belong to confirmed commitment owners; production plans key by commitment/line/version. No provisional order target or customer/terms-hash field. Validators forbid invented cross-tenant/unknown references. |
| `feasibility/bom.py:~75-102` | Explodes each **confirmed** commitment line through known SKU/BOM/unit conversion to leaf material demand. Absent/unsupported mapping cannot silently yield zero demand. |
| `feasibility/inventory.py:19-~210`; `materials.py` | Batch ATP protects active reservations, applies lot/expiry/warehouse and confirmed incoming evidence, and allocates all confirmed competing demand in a deterministic order. It cannot include a pending target unless a reviewed pure projection representation feeds the same kernel. Supplier quote is not stock. |
| `feasibility/capacity.py:62-~300` | Requires explicit production sources, process, plan, job ledger and calendars; evaluates fixed exclusive intervals and delivery/dispatch bounds. Missing data remains UNKNOWN. A failed supplied plan does not disprove every alternate schedule. |
| `feasibility/persisted_sources.py:123-163`; `currentness.py:11-25` | Tenant-scoped current snapshot reader and token check. A trusted source/actor and transaction-time version recheck are future integration obligations. |
| B1/B3 `readiness.py`, `portfolio_readiness.py`; B2 `test_pending_boundary.py` | B1 assesses an existing confirmed single target; B3 checks existing confirmed portfolio baseline; pending IDs return `PENDING_TARGET_UNSUPPORTED`. Neither is an acceptance or projected-order evaluator. |

No P2 model, evaluator, ATP/BOM/capacity formula or shared schema was changed in B4. A separate FEASIBLE result for each order does not establish jointly feasible stock or machine time. Active reservations and existing confirmed demand must remain protected in any future projection.

## 3. P2 owner gate and exact proposed extension

**Review status: NO-GO for semantic code change.** The B4 task expressly requires documented existing P2 owner approval before altering evaluator, snapshot, ATP, BOM or capacity semantics. None was found in the inspected main, current #48/#49 heads or relevant local P2 docs. Backend A's ongoing mapper and persisted AcceptanceCandidate are also unavailable there. The current P2 kernels would require pending demand to be inserted into `confirmed_commitments` and production plans keyed as if it were a confirmed Core commitment. That would make a green result semantically false; B4 did not do it.

Proposal for P2/P5 review, **not implemented**:

```text
ProvisionalTarget (P2-owned, scenario_kind=PROJECTED, output=ADVISORY)
  tenant_id; order_request_id; request_version; terms_revision; terms_hash
  exactly one SKU/variant, Decimal quantity/unit and explicit material-use/warehouse
  customer delivery window/deadline, named timezone and fulfilment mapping
  snapshot ID/version/current token; evaluation instant; evidence refs
  explicit production process/plan/ledger inputs where needed
```

The type is distinct from a Core `Commitment` and from `ConfirmedCommitment` in the operational ledger. Backend A owns canonical terms, assent and price/disclosure authority; these are independently verified before this operational projection. P2 would need a **pure kernel extraction or an explicit scenario input** that combines fixed confirmed demand/reservations with one provisional target for the same BOM, ATP and capacity calculations. The projected row must remain tagged `PROJECTED`, never persisted as confirmed. The result must bind request/terms/snapshot versions and source refs, expose the target's constraints plus any displaced confirmed demand, and carry `ADVISORY` and `authorization=false`. Evaluate the whole projected scenario, not just the target in isolation. Do not reuse existing `evaluation_identity` as proof of source authenticity.

Questions for approval: where does the provisional material-use instant and warehouse come from; can purchased finished goods or multi-stage production be mapped; what does a missing plan/job horizon mean; how are variants and units resolved; may future incoming receipt count before actual receiving; how does target demand compete with protected reservations; how are capacity and lot allocations attested; what are the exact `UNKNOWN` versus `UNSUPPORTED` codes; does P2 permit one line only in this first slice? Any shared snapshot/ConstraintSpec change needs P2/P5 review. No ORM or migration is proposed for this pure step.

## 4. Result semantics and no-write evidence

Future readiness `READY_FOR_EVALUATION` means verified current inputs and supported mapping, **not** feasibility. Future feasibility uses existing `FeasibilityState.FEASIBLE/INFEASIBLE/UNKNOWN` only where the shared kernel can determine it. `UNSUPPORTED` and `MISSING_EVIDENCE` are boundary outcomes outside that enum; `STALE` requires reload. FEASIBLE remains advisory: it does not establish customer assent, SME approval, reservation, a scheduled job, accepted Core state or guaranteed fulfilment. UNKNOWN cannot be upgraded by a missing-source default. `INFEASIBLE` for a fixed production plan is scoped to that plan. The [handoff §8](BACKEND_AB_CONTRACT_HANDOFF.md#8-b4-review-note-for-meishuet--provisional-feasibility-is-still-advisory) gives Meishuet the candidate/source/version and OrderDecision separation.

B4 added only `backend/app/feasibility/tests/test_projected_review_gate.py`. It builds **synthetic confirmed-demand test snapshots** to exercise the unchanged P2 ATP kernel, not a pending-order representation. Two demands of 60 units are each `COVERED` in separate 100-unit-lot snapshots, but the joint confirmed batch reports `SHORTAGE`. It checks immutable input JSON and leaves the original fixture unchanged. This proves a concrete double-allocation hazard in isolated evaluation and the need for joint P2 validation; it does not implement or validate provisional assessment. Test calls no session, provider, reservation, Core writer or outbox. B1/B2/B3 source is unchanged. No inventory, reservation, audit or Core state was written.

## 5. Tests and environmental limits

Local Windows Python 3.14; `PYTHONDONTWRITEBYTECODE=1`, `DATABASE_URL=sqlite+pysqlite:///:memory:`, `MOUMANTAI_SYNTHETIC_MODE=1`, `REQUIRE_POSTGRES=0`. From `backend/`, pytest uses `-p no:cacheprovider -q -o addopts= --disable-warnings --tb=short` and unique task-owned `--basetemp` paths.

| Run | Result |
|---|---|
| `python -m pytest ... app/feasibility/tests/test_projected_review_gate.py` | **1 passed**, 0 failed/errors/skipped. |
| `python -m pytest ... app/feasibility/tests tests/test_resource_reservations.py tests/test_p5_integration_recovery.py tests/test_outbox_events.py` | **357 passed**, 0 failed/errors/skipped, 4 warnings. |

The new test covers joint stock contention, not the requested projected-target positive or full negative matrix, because that evaluator is owner-gated. Existing P2/B1/B3 tests cover known source, reservation, BOM, expiry, capacity and unknown semantics for confirmed inputs only. PostgreSQL integration was not run: no explicitly approved disposable database was identified. No multi-worker concurrency, real inventory/provenance, Orbyte receipt, PR #48/#49 runtime, optimizer, frontend or live acceptance path was validated.

## 6. Backend A dependencies, GO/NO-GO and B5

Backend A must publish a persisted, versioned candidate and P1 mapper with authoritative tenant/request/customer identity, exact canonical terms hash/revision, source-context version/spans, original-offer or exact proposal assent, approved price source/version and whole-offer disclosure evidence. B must re-read all current evidence; a hash/DTO alone is not authorization. PR #48 evidence-currentness, revision and timezone/DST findings remain Backend A-owned. PR #49 supplier comparison is not stock or a reservation. A/B/P2/P5 must agree the operational line/plan mapping and version locks. S1 was expressly approved earlier in this chat; S2–S5 are not inferred from the ownership split.

**Integration GO/NO-GO: NO-GO** for connecting projected feasibility to a persisted AcceptanceCandidate now. There is no reviewed provisional P2 input, no published authoritative candidate on the inspected refs and no documented P2 owner approval. **Smallest B5 step:** obtain P2/P5 review of the pure `ProvisionalTarget`/scenario contract above and Backend A review of handoff §8, then implement a single-line read-only projected scenario by extracting/reusing the existing P2 kernel with fixed confirmed demand. Add the full negative matrix, including missing/stale/wrong-tenant/version inputs, unknown SKU/unit/BOM, protected/expired lots, job/plan/capacity gaps, contention and unchanged confirmed results. Continue to stop before optimizer, reservation, SME acceptance or Core writes.
