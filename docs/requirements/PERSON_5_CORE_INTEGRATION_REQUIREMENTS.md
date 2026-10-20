# Person 5 — Shared Commitment Core, Frontend Shell & Integration

> **Owner**: P5 · **Type**: Full-Stack Core / Architecture / Integration Coordinator + tests
> **Do not become a bottleneck**: establish contracts/mocks on day one, merge/integrate continuously, assign E2E bugs to owning Feature member. P5 does **not** own everyone's UI, all deployments, or all testing.

## 1. Business Mission

Build the **Commitment Registry & Lifecycle Engine** as the one authoritative business core. Every F1–F4 module uses the same `tenant_id`, `commitment_id`, versioned terms, and evidence-based state rules. Provide common database/API/events, app shell, audit, role enforcement and integration tests so all four independent Full-Stack features form **one working automation product**.

**P0 result**: Customer request through F1 creates a relevant Context/Request; F2 produces a versioned assessment; F3 can propose/approve/execute via roles; F4 can confirm an explicit proposal; the Core preserves independent agreement/risk/recovery/fulfilment state and complete auditable history. An operational completion event can mark fulfilment only when evidence policy passes.

## 2. Frontend Ownership

**Routes**: `/overview`, `/activity`, shared app shell. Each P1–P4 retains full responsibility for feature pages.

### FE-01 App Shell / Navigation
- [ ] React Router navigation and route guard; deep links to `/inbox`, `/orders/:id`, `/commitments/:id`, `/impact/:id`, `/recovery/:id`, `/communications`, `/confirmations/:id`, `/activity`.
- [ ] Unified app layout, sidebar/topbar/breadcrumb, active tenant and demo role indicator, responsive behavior.
- [ ] Shared UI building blocks: status badge (strict enum mapping), evidence list, activity timeline, confirm dialog, toast, data-loading and error boundary, typed API client.
- [ ] Standardized UI language for `UNKNOWN`, `REVIEW_REQUIRED`, `PENDING_APPROVAL`, `INVALIDATED`, `FAILED`, `FULFILLED`; no false success color in pending state.
- [ ] React Query client + typed request/response utility + global permission context / current test-role simulator.

### FE-02 Overview
- [ ] Counts and links by authoritative shared state: Requested, Confirmed, At Risk, Pending Approval, Execution in Progress, Awaiting Confirmation, Fulfilled.
- [ ] Attention queue: stale plans, unknown feasibility, manual review, failed executions, unresolved confirmations.
- [ ] Summary cards sourced from **real backend aggregate API** (synthetic dataset allowed), not parallel hand-maintained frontend arrays.
- [ ] Last updated, integration mode badge (`SYNTHETIC`), tenant and business-context transparency.
- [ ] Filter/detail navigation; loading/error/empty/no-permission behavior.

### FE-03 Activity/Audit
- [ ] Full history scoped to commitment/tenant: actor, source event, feature, previous/new state, time, evidence pointer.
- [ ] Human approval reasons and version changes; direct links to F1 source, F2 assessment, F3 plan, F4 confirmation.
- [ ] Event correlation timeline showing why supplier delay triggered risk/plan/action/confirmation.
- [ ] Display redacted summaries only; prevent leakage of private contents to wrong roles.

## 3. Backend Core Ownership

**Suggested files**: `backend/app/core/` (`models.py`, `schemas.py`, `commitments.py`, `policy.py`, `audit.py`, `events.py`, `outbox.py`, `permissions.py`, `router.py`), `backend/app/db/`, `contracts/`, `backend/tests/integration/`. Module/service ownership is strict.

### BE-01 Shared Data / Domain Contracts
- [ ] Create canonical contract definitions from `REQUIREMENTS_SYSTEM.md`: `BusinessContext`, `Commitment`, `FeasibilityAssessment`, `RecoveryPlan`, `CommunicationRequest`, `DomainEvent`.
- [ ] Expose Pydantic/OpenAPI specs and **generate or maintain synchronized TypeScript types** for frontend.
- [ ] Maintain fixed enums, version semantics, ISO timestamps and decimal amounts; break changes require PR and owners' review.
- [ ] Provide fixture bundles P1–P4 can consume independently from minute one; avoid waiting for real DB before coding.
- [ ] Publish API error shape: `code`, `message`, `correlation_id`, `details?`; normalize 400/401/403/404/409/422/500 as appropriate.

### BE-02 Commitment Registry & Lifecycle
- [ ] Distinguish Request, OrderContext, Proposal, Confirmed Commitment and Fulfilment Evidence.
- [ ] Model one Order → many Commitments; independent Agreement / Feasibility / Risk / Recovery / Fulfilment dimensions.
- [ ] Enforce **state-transition invariants server-side**; do not let feature APIs directly overwrite core states via unrestricted PATCH.
- [ ] `request_created`, `proposal_offered`, `proposal_accepted`, `risk_detected`, `recovery_started`, `action_verified`, `fulfilment_verified` with validated guards.
- [ ] Version key terms and proposal amendments; old terms/evidence not overwritten. A signed confirmation for V2 cannot update a newer V3.
- [ ] Guarantee optimistic concurrency: require `expected_commitment_version` for updates, mismatch yields 409 + current version.
- [ ] `FEASIBLE` is snapshot-specific; confirmed commitment is not automatically safe forever; risk change does not erase agreement.
- [ ] `FULFILLED` requires trusted operational evidence and required terms satisfied; manual completion requires authorized evidence and audit, not silent override.

### BE-03 Database & Migrations
- [ ] PostgreSQL + SQLAlchemy + Alembic, reproducible Docker Compose startup and seed fixtures.
- [ ] Shared tables: `tenants`, `users`, `roles`, `customers` (lightweight mock), `orders`, `commitments`, `commitment_versions`, `commitment_proposals`, `commitment_evidence`, `audit_events`, `outbox_events`, `processed_events`.
- [ ] P1–P4 domain models extend via migration **coordinated** with P5; no direct schema change without PR review.
- [ ] All rows have tenant scope where appropriate; indexes/unique constraints on provider event, idempotency and state refs.
- [ ] Avoid cross-tenant joins/embedding retrieval; backups/restore rehearsal for Production roadmap.
- [ ] Synthetic seed supports normal, shortage, supplier delay, alternate recovery plans, ambiguous confirmation, operational completion.

### BE-04 Domain Event Bus & Reliability
- [ ] Define producer/consumer event structure (`event_id`, `event_type`, `schema_version`, `tenant_id`, `commitment_id`, `commitment_version`, `correlation_id`, `causation_id`, timestamp, payload).
- [ ] Commit DB state change and outbox event in same transaction; independent event publisher worker.
- [ ] Consumer idempotency on `event_id`; allow at-least-once reprocessing; no destructive duplicate mutation.
- [ ] Handle out-of-order messages with version checks; old event must not revert newer state.
- [ ] Failed delivery/retry trackable; dead-letter/reconciliation process for P1 roadmaps.
- [ ] Event correlation trace from Trigger→Decision→Approval→Action→Confirmation.

### BE-05 Auth & Risk-Based Approval Framework
- [ ] Simulate Owner/Manager/Staff roles **in a clearly labelled synthetic mode**, not by trusting body `role` value; backend uses server session/test actor mapping.
- [ ] API-side tenant/role checks on every protected action and scope; frontend guard is not security control.
- [ ] Implement shared policy interface `authorize(actor, action_type, business_context, plan_version)`.
- [ ] Consequential procurement, resource reallocation and promise change require authorized approval; pre-approved low-risk internal actions may auto-run.
- [ ] Approval records must include approving principal, scope, action/plan version, costs/expiry and audit.
- [ ] Existing approval invalid if plan/important terms changed or expires.
- [ ] P0 simple deterministic policy rules, OPA can be Production roadmap after E2E stable.

### BE-06 E2E Integration
- [ ] Integrate P1 context events into request/proposal and F2 evaluation trigger.
- [ ] Integrate P2 result into canonical commitment risk state and P3 recovery trigger.
- [ ] Integrate P3 approval/action verification with Core record and F4 proposal communication request.
- [ ] Integrate P4 verified confirmation into proposal acceptance/rejection; return to F3 on rejection; **separate** operational evidence for fulfilment.
- [ ] Ensure a consumer receives **link/reference**, not full PII payload when unnecessary.
- [ ] No direct P1/P2/P3/P4 update of authoritative commitment state; use typed domain methods/events.

## 4. API Contract and Shared Interfaces

```text
GET  /health
GET  /v1/overview
GET  /v1/commitments/{commitment_id}
GET  /v1/commitments/{commitment_id}/timeline
POST /v1/commitments/{commitment_id}/proposals
POST /v1/commitments/{commitment_id}/confirm-proposal
POST /v1/commitments/{commitment_id}/record-fulfilment
GET  /v1/audit?commitment_id=...
GET  /v1/events/{event_id}
```

**Do NOT** expose `PATCH /v1/commitments/{id} {"fulfilment_state":"FULFILLED"}` without evidence/state guard.

**Internal service APIs**: `CommitmentService.request`, `.offer`, `.confirm`, `.assess`, `.mark_risk`, `.start_recovery`, `.record_action_outcome`, `.verify_fulfilment`; all validate tenant/version/actor/evidence and emit outbox.

**Core events**: `commitment.created`, `commitment.proposal_offered`, `commitment.confirmed`, `commitment.at_risk`, `commitment.risk_resolved`, `commitment.fulfilment_verified`, `audit.recorded`.

**Authority map**: P1 owns message evidence; P2 owns feasibility assessment; P3 owns recovery/exec logs; P4 owns communication/confirmation evidence; P5 owns Commitment aggregate transitions and common audit/outbox.

## 5. Database Transaction & Business Safety

- [ ] Version-safe updates (`WHERE id=... AND commitment_version=...`) to avoid lost updates.
- [ ] Outbox event written atomically with state change; consumer idempotent.
- [ ] Use `Decimal` / numeric SQL for cost and quantities; timezone-aware timestamps.
- [ ] A mock resource reservation must enforce no over-allocation under concurrent requests; P3 action adapter obtains lock/transaction, P2 query evaluator stays read-only.
- [ ] Keep original evidence immutable; corrections appended; role/actor recorded server-side.
- [ ] No confirmed financial transfer or real PII required in repo.

## 6. Tests & Integration Gates

### Unit / DB
- [ ] Request cannot jump directly to confirmed without evidence/valid transition.
- [ ] `CONFIRMED + AT_RISK` coexist correctly.
- [ ] Agreement state and fulfilment state stay independent.
- [ ] Version conflict returns 409; old event cannot revert latest state.
- [ ] Wrong tenant cannot view/approve/change another tenant's commitment.
- [ ] Duplicate event results in one logical mutation and audit event.
- [ ] Outbox stores event even when publisher fails; retries not losing work.
- [ ] Expired manager approval rejected.
- [ ] Unverified receipt doesn't set paid/confirmed status.
- [ ] Customer accepted does not set fulfilment; verified operational completion can.

### UI / E2E
- [ ] Overview counts match actual DB state and refresh after F1–F4 changes.
- [ ] Activity shows linked events end to end; no fake success from mocked optimistic updates.
- [ ] Role UI hides inappropriate actions and backend denies them anyway.
- [ ] `F1 request → F2 assessment → F3 risk plan → manager approval → synthetic execution → F4 confirmation → operational fulfilment evidence` uses ONE `commitment_id` with versioned source records.
- [ ] Error-case suite: duplicate message, resource shortage, supplier change, stale approval, ambiguous OK, expired confirmation, execution failure, permission violation.
- [ ] `pytest` and frontend `vitest` both pass; no uncontrolled side effects across demo runs.

## 7. Deployment and Developer Experience

- [ ] `docker compose up` or README-equivalent brings backend, PostgreSQL and worker online; seed data command.
- [ ] `npm install && npm run dev` for frontend, with documented `VITE_API_BASE_URL`.
- [ ] `.env.example` contains variable **names and placeholders only**, not passwords/tokens.
- [ ] Backend `/health`, OpenAPI docs, CORS restricted as appropriate.
- [ ] GitHub Actions: Python unit/integration, frontend typecheck/test/build, lint/diff hygiene; failing core tests block PR.
- [ ] Give each owner stable mock server/contracts on Day 1; centralize shared migrations but don't hold up feature coding.
- [ ] Repo reference `AGENTS.md`, `TEAM_LOG.md`, `REQUIREMENTS_SYSTEM.md` at root or update relative links when copying this package.

## 8. Timeline / Team Coordination

| Date | P5 deliverable / collaboration |
|---|---|
| 20 Oct | **2–3 hour contract lock**; shared Pydantic/TypeScript interfaces, seed fixture and React/Backend skeleton, branch ownership |
| 21 Oct | Commitment states + DB migrations + overview skeleton + audit event prototype; unblock P1–P4 |
| 22 Oct | First integrated DB-backed vertical path, merged feature routes, version/permission checks |
| 23 Oct | E2E journey in deployed local app; cross-feature failure cases; assign bugs to owners |
| 24 Oct | Freeze, regression, audit proof/metrics, QA, backup/export release artifacts |
| 25 Oct | Repo/site/submission validation, targeted hotfix only |

**Critical**: P5 schedules 10–15 min daily integration sync and enforces PR acceptance checks; each Feature Owner fixes its own frontend/backend issues. Deployment owner can be assigned to one person by actual availability; it need not always be P5.

## 9. Scope Locks

**P0**: shared contract, usable DB, commitment lifecycle/version, request/approval guards, audit/outbox, application shell/overview/activity, integrated E2E tests.
**Optional**: full event queue transport, charts/visual polish, advanced role administration.
**Production roadmap**: OIDC, strong multi-tenancy with RLS + full isolation tests, Temporal/OPA, cloud ECS/SQS/KMS, backup and disaster recovery, advanced monitoring and real Orbyte connector after official APIs available.
**Forbidden**: inventing Orbyte production access, backend accepting spoofed role IDs, coding fifth feature, rewriting other owners' modules to force integration without review, classifying action approval as fulfilment.

## 10. Integration Handoff Checklist

- [ ] Exact contracts/types usable on frontend and backend.
- [ ] All modules share tenant/commitment ID and state semantics.
- [ ] Domain events persisted and traceable, no dropped audit.
- [ ] Role gates validated server-side and in demo role UX.
- [ ] Main journey, negative-case tests and deployment docs reproducible.
- [ ] `TEAM_LOG.md` reflects actual PR status, blocked tasks and decisions (no fake checkmarks).
