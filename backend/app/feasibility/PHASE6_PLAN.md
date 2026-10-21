# Phase 6 — approved frontend implementation plan

Baseline: clean `feat/p2-feasibility-engine` at `85d46b2f48bea9a2e149f6dd70badc7311334061`.
Only Phase 6 is authorized. Execute inline; do not merge shared infrastructure or begin Phase 7.

## Design and scope

Export `CommitmentFeasibilityPage` and `ImpactDetailPage` from the P2 frontend feature.
Use existing React, Router, shared contract types and styles, plus scoped feature CSS.
Data comes through injected, tenant-scoped P2 feature ports. With no adapter the pages
explain the unavailable public API. An explicit preview source is separately labeled
synthetic and never presented as persisted. No competing client, auth or shell.

## Field/source map (before implementation)

| Display | Verified source | Browser availability in this branch |
|---|---|---|
| Identity, terms, agreement/risk, commitment version | Core `Commitment`, GET `/v1/commitments/{id}` | Mounted; header-based development context only, not production authentication |
| Assessment identity/status/time/version, solver, constraints, assumptions/evidence | shared `FeasibilityAssessment` | Shared type exists; P2 history/assess routes unmounted and persistence ports unavailable |
| Required/allocated usable/owned reserved/confirmed incoming/shortage/units/need time/allocation evidence | P2 `EvaluationResult.materials.materials`, filtered to target | Internal query result only; requires approved P5 public detail mapping |
| Fixed production start/finish/required and available minutes/resources | P2 `EvaluationResult.capacity.operations`, filtered to target | Internal only; available minutes are diagnostics, not universally available hours |
| Freshness observations/valid-through/source rows and evidence completeness | snapshot sources and `EvaluationResult.evidence_complete` | Requires P5 public snapshot/detail adapter; shared assessment alone insufficient |
| Trigger, changed resources/ETA values | `OperationalChange` plus before/after source rows | Not included in ImpactAssessment alone; P5 detail response extension required |
| Candidate/classification/deltas/buffers/paths/reasons | P2 `ImpactAssessment` | P2 GET impact unmounted; durable reader unavailable |
| Authoritative risk change | Core audit/transition evidence | Not inferred from impact result or local event intent |
| Preview fields | Explicit synthetic fixture generated from existing P2 calculations | Preview only, not a persisted assessment |

Empty Impact Set support is IMPLEMENTED ON P5 BRANCH, PENDING INTEGRATION:
verified `origin/feat/p5-core-integration` at `a5f99151f2bc88f1c4d2cd530b0243a869a45d9c`.
Main remains `4ec2ba1`; P2's schema still has the old restriction. Do not expose
historical `shared_output_blocker` metadata as current integration readiness.

## Tasks and verification

- [x] Add failing feature component/adapter tests for all statuses, version/freshness,
  error/retry, preserved previous assessment, invalid response, impact evidence and uncertainty.
- [x] Implement typed feature projections and injected source boundary. Retain canonical
  Commitment/FeasibilityAssessment types. Validate scope/identity/version before display.
- [x] Implement both accessible pages with scoped responsive tables, cautious status,
  evidence and unavailable-field explanations. Recalculate remains disabled without
  an approved adapter; injection tests exercise future adapter behavior.
- [x] Run focused Vitest; repair only failing tests first. Run npm typecheck, explicit
  application TypeScript project validation (root command has only references), and build.
- [x] Review changed TSX for accessibility/hooks/state issues, update progress/trace/report
  and P2 TEAM_LOG. Document exact P5 mounting and public-data handoff, plus P3/P5 blockers.
- [x] Inspect staged scope, create a local PARTIAL/WIP commit, stop for external review.

No backend behavior changes or full backend/E2E regression in this frontend phase.
Later backend checkpoint: add nonblocking explicit SKU/unit binding test cases; do not
reopen the approved Phase 5 implementation here.
