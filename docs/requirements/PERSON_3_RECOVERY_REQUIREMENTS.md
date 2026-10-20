# Person 3 — Intelligent Recovery & Change-to-Action

> **Owner**: P3 · **Type**: Full-Stack + Optimization + Governed Execution + tests
> **Dependencies**: P2 `evaluate()` and constraint snapshots, P5 Commitment/Approval policies, P4 communication/confirmation contracts.
> **Business mission**: Turn *verified commitment risk* into **feasible, compared, approved, executed, and verified** recovery actions. Never market "LLM chose the best" or let a model bypass an approval gate.

## 1. Core Journey / Definition of Done

A supplier delay makes a confirmed commitment `AT_RISK`. The system creates a Recovery Case, proposes at least two logically distinct options (e.g. alternative supply at extra cost vs approved delay/partial delivery), checks all candidates using **P2's common feasibility engine**, compares cost, delay and affected commitments, and lets an authorized manager approve/reject. On approval the action preconditions/version are checked again, then a **synthetic authorized Action Adapter** changes a business record or creates a tracked task; the UI displays actual outcome and audit. If customer agreement is needed, send a communication request to P4 rather than falsely considering the commitment changed.

## 2. Frontend Ownership

**Route**: `/recovery/:id` (optional child tabs: `options`, `approvals`, `execution`, `evidence`). Use P5 app shell/shared styles.

### FE-01 Recovery Case Overview
- [ ] Commitment and incident: original deadline, trigger event, current risk, affected resources and orders, assessment ID/snapshot version.
- [ ] Clear "what changed" and source evidence; show business facts vs predicted/conditional information separately.
- [ ] Loading/Empty/Error/Stale/No Feasible Plan states.

### FE-02 Plan Comparison
- [ ] Side-by-side cards/table: plan option, extra `MYR` cost, expected delay, customer impact, dependencies, plan feasibility status, known risks.
- [ ] Show constraints/proof links returned by P2, and **options** rather than absolute "BEST". Recommended label explicitly tied to visible business preference settings.
- [ ] Selection + explanation; reject invalid plan; preserve available alternatives.
- [ ] Selection preview enumerates actions and which require approval/third-party confirmation.

### FE-03 Approval + Execution
- [ ] Manager `Approve`, `Reject`, `Request Revision`; prevent unauthorized action client-side **and server-side**.
- [ ] Consequential action requires confirm dialog showing plan version, cost estimate, target systems, affected commitments.
- [ ] After approval: display revalidation progress, workflow steps, action attempts and actual state (PENDING/RUNNING/SUCCEEDED/FAILED/NEEDS_REPLAN).
- [ ] Distinguish manager approval, API request submitted, external operation verified, customer confirmation pending, fulfilment completed.
- [ ] Render stale plan warning and disable execution when snapshot/version has changed.
- [ ] Audit timeline: who, when, what, outcome, source refs; no optimistic fake “success”.

## 3. Backend Ownership

**Suggested module**: `backend/app/recovery/`: `plan_templates.py`, `candidate_generator.py`, `ranking.py`, `plan_validator.py`, `approval.py`, `executor.py`, `action_adapters.py`, `service.py`, `router.py`, `tests/`.

### BE-01 Recovery Case & Trigger
- [ ] Consume `commitment.at_risk` idempotently using `event_id`, `tenant_id`, `commitment_id`, `assessment_id`.
- [ ] Create one active Recovery Case per relevant triggering state/change version or policy-defined grouping; no alert storms.
- [ ] Preserve triggering assessment, source evidence, current plan version, affected commitments.
- [ ] A new, materially changed operational event can invalidate plan; don't silently mutate approved plan in place.

### BE-02 Candidate Plan Generation
- [ ] Deterministic templates: `ALTERNATIVE_SUPPLY`, `RESCHEDULE_PRODUCTION`, `PARTIAL_FULFILMENT`, `NEGOTIATE_DELIVERY`, `REPLAN_TASK`; generate only if required inputs available.
- [ ] Plan preconditions: confirmed available supply vs pending supplier quotation, total cost components, impact on other commitments, target lead time.
- [ ] Explicit `CONDITIONAL` if supplier quote/availability or customer acceptance remains unresolved. A draft supplier message is **not** a committed supplier agreement.
- [ ] Avoid options that violate product safety, reservation locks or known hard constraints.
- [ ] For P0 implement 2–3 realistic plan templates against canonical synthetic data; more strategies Roadmap.

### BE-03 Shared Constraint Validation (mandatory)
- [ ] **Call P2 `POST /internal/feasibility/evaluate` / same pure library** for every plan under hypothetical proposed changes.
- [ ] Pass current snapshot/version and affected commitments, not just the target order.
- [ ] Persist `validation_status`, `constraint_reasons`, `solver_status`, cost/deadline assumptions, source evidence refs.
- [ ] `UNKNOWN` and `CONDITIONAL` are not safe for unconditional action execution.
- [ ] Revalidate approved plan just before doing any side effect; if version changed mark `INVALIDATED` and request new approval.

### BE-04 Multi-Criteria Comparison
- [ ] First eliminate hard-infeasible plans; preserve conditional plans with explicit caveats.
- [ ] Score/compare: extra cost, customer delay, number of impacted commitments, operational disruption; weights configured by SME owner/policy (synthetic fixture P0).
- [ ] Label recommendation `RECOMMENDED_UNDER_POLICY`, never universal best; return trade-off explanation.
- [ ] `Decimal` for cost and currency, exact duration units; assumptions visible.
- [ ] Optional Qwen3 explanation only from deterministic results; no LLM authority to edit quantities/costs or approve.

### BE-05 Governance & Approval
- [ ] Risk-based policy actions: non-consequential internal tasks can be automated; major procurement, changing promises, real resource reallocation require proper approval.
- [ ] Data structure: actor ID, role, tenant, plan_version, snapshot_version, max approved cost, action scope, timestamp, expiration, decision reason.
- [ ] Validate server-side role; staff cannot spoof manager in request body.
- [ ] Every approval/rejection is audited; modifying approved plan requires new approval.
- [ ] P5 owns shared policy conventions; P3 implements the action-specific enforcement.

### BE-06 Structured Action Execution
- [ ] Actions have stable `action_id`, dependency list, parameters, preconditions, idempotency key, execution status, provider operation ref and evidence refs.
- [ ] Implement a fully functional **synthetic side-effect adapter**: e.g., create purchase request, update mock capacity scheduling task, reserve allowed synthetic stock through safe transaction, create follow-up task.
- [ ] Do **not** create real purchase order at an external provider without authorized connection and appropriate approval.
- [ ] Execute `PENDING → VALIDATED → APPROVED → EXECUTING → VERIFYING → SUCCEEDED` with failure/stale/manual-intervention paths.
- [ ] Verify provider/mock record after write; DB write only after a robust transaction. `HTTP 202/200` ≠ business fulfilled.
- [ ] Retry only safe/idempotent operations; external timeout ambiguous → reconcile status before replay.
- [ ] Outbox event when actual action result is verified; maintain action history. P0 can use DB-based workflow state machine; Temporal Production Roadmap.

### BE-07 Communications & Feedback
- [ ] If change needs customer acceptance, emit `recovery.communication_requested` containing proposal ID/version, approved terms and recipient ref for P4.
- [ ] On P4 `confirmation.rejected/counteroffer_received`, invalidate dependent plan steps and replan; do not keep executing obsolete assumptions.
- [ ] On `confirmation.accepted`, Core validates and updates Agreement proposal version; P3 resumes appropriate conditional workflow only after checks.
- [ ] Emit verified action results to P5; F2 re-evaluates as actual resource conditions change.

## 4. Contracts & Endpoints

**Consumes**: `FeasibilityAssessment`, `commitment.at_risk`, operational snapshot refs, P5 policy/auth/Commitment. **Produces**: `RecoveryPlan`, `recovery.plan_generated`, `recovery.approval_required`, `recovery.action_completed`, `recovery.action_failed`, `recovery.communication_requested`, `recovery.replan_required`.

```text
POST /v1/recovery/cases/{id}/generate
GET  /v1/recovery/cases/{id}
GET  /v1/recovery/cases/{id}/plans
POST /v1/recovery/plans/{id}/validate
POST /v1/recovery/plans/{id}/approve
POST /v1/recovery/plans/{id}/reject
POST /v1/recovery/plans/{id}/execute
GET  /v1/recovery/plans/{id}/actions
```

**P2 handshake**: stable `evaluate(snapshot, proposed_changes, commitment)` returns same status/reasons as standalone F2. **P4 handshake**: proposal versioned outbound request, no direct message send from F3. **P5 handshake**: identity/role, versioned approval, audit/outbox, transactional business-state updates.

## 5. Data Entities

`recovery_cases`, `recovery_plan_versions`, `recovery_options`, `plan_evaluations`, `planned_actions`, `action_dependencies`, `approval_requests`, `approval_decisions`, `action_executions`, `action_attempts`, `external_operation_receipts`, `compensation_records`, `recovery_outcomes`.

No arbitrary JSON exec or dynamic Python from LLM. Use typed/allowlisted action handlers. Plan-version mutability controlled; auditable immutable approval decisions.

## 6. Required Tests

| Test | Expected |
|---|---|
| F3-01 No feasible options | Return explicit no-safe-plan state and escalation; no invented action |
| F3-02 Multiple options | Cost/delay/risks computed from same snapshot, ranking under configured policy |
| F3-03 Plan claims alternative supply without confirmation | `CONDITIONAL`, not unconditional safe |
| F3-04 Non-manager tries purchase/major change | Backend denies and auditable security event |
| F3-05 Plan approved after stock/supplier change | Revalidation blocks stale approval/old plan |
| F3-06 Duplicate execute request | Single logical action, no duplicate reservation/request |
| F3-07 Executor timeout after external action | Reconcile and do not blindly duplicate |
| F3-08 Simulated action failure | State `FAILED` or compensation/manual required, no fake completion |
| F3-09 Customer rejects new deadline | Plan stays unresolved; replan event emitted |
| F3-10 Approved action completed | Outbox/audit proof, updated mock operation, Core risk re-evaluated |
| F3-11 Unauthorized tenant tries to approve | No access to plan or approval |
| F3-12 F3 feasibility vs P2 result | Identical when same input snapshot, no duplicate solver logic |

**Frontend tests**: options comparability; policy reason; review confirmation; loading/failed/stale; execution timeline; no unauthorized button effect. **System metric**: valid plan rate, unauthorized action attempts blocked, false completed action count, additional cost estimation error and E2E time to recovery.

## 7. Timeline

| Date | P3 deliverable |
|---|---|
| 20 Oct | Candidate schema, fixtures, UI skeleton; confirm P2 evaluator and P4 communication request |
| 21 Oct | Two recovery plan generators + comparison view and unit tests |
| 22 Oct | Approval APIs/UX, side-effect mock adapter, Core integration |
| 23 Oct | Full trigger→choice→approve→execute path incl. reject/stale/failure |
| 24 Oct | Regression, audit, metrics, freeze |
| 25 Oct | Submission support |

## 8. Scope

**P0**: at least two options, shared P2 validation, explicit conditional facts, business preference ranking, consequential approval, synthetic action that truly changes data, audit and frontend.
**Optional**: OR-Tools complex option optimization, natural language Qwen3 explanation, multi-step rollback.
**Production**: Temporal long-running workflow, OPA, provider integrations, distributed idempotency & Saga compensation.
**Never**: autonomous external purchasing without approval, "best solution" with no stated business preference, LLM-executed arbitrary code, direct update to `FULFILLED` on plan completion.

## 9. Handoff Checklist

- [ ] P2 validated every action plan under exact snapshot/version.
- [ ] P4 has clear proposal ID/version + terms to seek approval or confirmation.
- [ ] P5 Core records approval, action, audit and risk changes consistently.
- [ ] Frontend routes demonstrate real approvals and execution statuses, not only cards.
- [ ] README/tests/fixtures and accurate status in `TEAM_LOG.md`.
