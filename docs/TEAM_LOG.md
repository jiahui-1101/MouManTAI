# MouManTAI — Team Execution Log & Decision Register

> **Log start**: 2026-10-20 · **Submission**: 2026-10-25
> **Document state**: **INITIAL PLANNING TEMPLATE**. No implementation tasks are pre-marked complete. Update this file from real code, PRs, tests and evidence only.
> **Working rule**: Update at least once per day; every PR should reference a log item. Do not claim integrations deployed from architecture plans alone.

## 1. Members / Responsibilities

| Member | Role | Main UI | Main Backend | Assigned person/contact | Branch prefix |
|---|---|---|---|---|---|
| P1 | F1 Context Full-Stack | Inbox / Order Context | Ingestion, Extraction, Identity, Context | TBD | `feat/p1-context-` |
| P2 | F2 Feasibility Full-Stack | Commitment / Impact | ATP, BOM, Solver, Impact | TBD | `feat/p2-feasibility-` |
| P3 | F3 Recovery Full-Stack | Recovery / Approval | Plans, Ranking, Approved Execution | TBD | `feat/p3-recovery-` |
| P4 | F4 Communication Full-Stack | Communications / Confirmations | Drafts, Channel Adapter, Confirmations | TBD | `feat/p4-communication-` |
| P5 | Shared Core Full-Stack | App Shell / Overview / Activity | Registry, DB, API Contracts, Audit, Integration | TBD | `feat/p5-core-` |

**Project lead**: TBD · **Release owner**: TBD · **Demo/pitch owner**: TBD · **Main repo URL**: TBD · **Prototype URL**: TBD.

## 2. Non-Negotiable Project Decisions

| ID | Decision | Rationale | Status | Date |
|---|---|---|---|---|
| ADR-001 | Product positioning: **Intelligent Commitment Assurance & Recovery** | Single Domain 2 SME problem | Proposed baseline | 2026-10-20 |
| ADR-002 | 4 Feature Owners + 1 Shared Core Owner, each full-stack | Parallel work, clear ownership | Proposed baseline | 2026-10-20 |
| ADR-003 | Single shared Commitment Registry with independent lifecycle dimensions | Prevent inconsistent states | Proposed baseline | 2026-10-20 |
| ADR-004 | Deterministic feasibility; predictive ML optional | Traceable accuracy | Proposed baseline | 2026-10-20 |
| ADR-005 | F3 reuses F2 constraint validator; important actions require authorized approval | No duplicate solver or unsafe execution | Proposed baseline | 2026-10-20 |
| ADR-006 | `SENT ≠ ACCEPTED ≠ FULFILLED` | Evidence-grounded closed loop | Proposed baseline | 2026-10-20 |
| ADR-007 | Synthetic data; no real payments or assumed Orbyte live API | Domain 2 boundary | Proposed baseline | 2026-10-20 |
| ADR-008 | No continuous LLM self-learning before 25 Oct | Reduce risk and preserve core demo | Proposed baseline | 2026-10-20 |
| ADR-009 | 24 Oct feature freeze; 25 Oct submission only | Deadline protection | Proposed baseline | 2026-10-20 |
| ADR-010 | Product name finalized as **MouManTAI** | Align repository and implementation naming | Accepted by current task request | 2026-10-21 |

Change a decision using: `ADR-ID`, alternatives, pros/cons, affected contract/files, agreed-by, time; never silently reverse a lock.

## 3. Day-by-Day Team Plan

### 20 Oct — Contract Freeze & Parallel Start
- [ ] Assign actual names to P1–P5 and designate release/pitch owner.
- [ ] Confirm 4 shared API data contracts and DomainEvent envelope.
- [ ] Agree synthetic SME example, SKU/BOM/inventory/supplier calendar fixture.
- [ ] Decide workflow proof that must be shown live (one core end-to-end case).
- [ ] Scaffold frontend/backend, test commands, Docker/environment.
- [ ] Each owner opens branch/PR with UI/API skeleton, fixtures and first test.

### 21 Oct — Independent Vertical Slices
- [ ] P1: message extraction & context update from synthetic inbound event.
- [ ] P2: ATP/BOM/feasibility & impact basics.
- [ ] P3: 2+ candidate plans, ranking/approval model.
- [ ] P4: message draft/send states + confirmation model.
- [ ] P5: Commitment Registry, migrations, app shell, audit/event API.
- [ ] Agree each Feature API + expected status/errors in PR review.

### 22 Oct — First Integration
- [ ] F1 → Core → F2 uses same Commitment ID and real backend API.
- [ ] F2 → F3 passes versioned feasibility/impact; F3 calls **same** F2 evaluator.
- [ ] F3 → F4 proposal/communication event and F4 → Core confirmation result.
- [ ] React pages fetch real backend state; resolve cross-feature schema mismatches.
- [ ] Re-run permission/version/duplicate-event negative tests.

### 23 Oct — Full Working Journey
- [ ] Customer request → feasibility → valid commitment → supplier change → risk.
- [ ] Recovery choices → manager approve → actual synthetic action + evidence.
- [ ] Customer confirmation accept/reject and separate fulfilment handling.
- [ ] End-to-end audit timeline proves every consequential transition.
- [ ] Negative case: stale approval, ambiguous “OK”, duplicate action.

### 24 Oct — Freeze, Metrics, QA
- [ ] All P0 acceptance tests pass; list known unresolved limitations honestly.
- [ ] Measure e.g. false-feasible, false-acceptance, wrong-link, valid plan and processing time with denominators.
- [ ] Run typecheck, pytest, Vitest, build, docker smoke tests.
- [ ] Rehearse user journey and contingency demo.
- [ ] Prepare README, GitHub visibility and submission artifacts.
- [ ] Freeze new features: only critical fixes.

### 25 Oct — Submission
- [ ] Confirm final branch/commit hash and working deploy URL (if applicable).
- [ ] Repeat smoke test + permissions + audit screenshot/recording.
- [ ] Verify submission format, GitHub access, links, presentation material.
- [ ] Submit before deadline; record submission confirmation and time.

## 4. Feature Status Board (update daily)

**Allowed status**: `NOT_STARTED` / `IN_PROGRESS` / `BLOCKED` / `IN_REVIEW` / `DONE` / `DEFERRED`.

| ID | Deliverable | Owner | Status | Evidence / PR / Test | Blocker | Next action |
|---|---|---|---|---|---|---|
| P1-FE | Inbox + Context Review UI | P1 | NOT_STARTED | — | — | Scaffold route |
| P1-BE | Ingestion/Extraction/Context API | P1 | NOT_STARTED | — | Shared contracts | Define fixtures |
| P1-TST | Context tests and metrics | P1 | NOT_STARTED | — | — | Define expected labels |
| P2-FE | Feasibility / Impact UI | P2 | NOT_STARTED | — | — | Scaffold route |
| P2-BE | Constraint + Impact engine | P2 | NOT_STARTED | — | SKU/BOM fixtures | Pure evaluate API |
| P2-TST | Feasibility/Impact tests | P2 | NOT_STARTED | — | — | Set known examples |
| P3-FE | Recovery / Approval UI | P3 | NOT_STARTED | — | — | Plan comparison cards |
| P3-BE | Plan / Approval / Action API | P3 | NOT_STARTED | — | P2 evaluator interface | Start templates |
| P3-TST | Approval/Execution tests | P3 | NOT_STARTED | — | — | Define stale-approval test |
| P4-FE | Communication / Confirmation UI | P4 | NOT_STARTED | — | — | Scaffold route |
| P4-BE | Draft/Send/Confirm APIs | P4 | NOT_STARTED | — | P3 proposal schema | Define signed confirmation |
| P4-TST | Confirmation/Channel tests | P4 | NOT_STARTED | — | — | Define ambiguous OK fixture |
| P5-FE | Shell / Overview / Audit UI | P5 | IN_PROGRESS | Real Overview (/overview) & Activity (/activity) wired to real backend endpoints via TanStack Query (FE-01, FE-02, FE-03, UI-01, UI-02); timeline with F1–F4 deep links, state diffs, version increments, human governance highlights, correlation/causation grouping, role redaction, loading/empty/error/403 states; 12 vitest tests passing | Feature pages remain owner work | Integrate P1–P4 feature routes |
| P5-BE | Registry / DB / Events / Roles | P5 | IN_PROGRESS | Canonical contracts, fixture, PostgreSQL/Alembic foundation, registry lifecycle, transactional outbox dispatcher, idempotent consumers, version guard, and retry/dead-letter framework; 15 backend tests passing | Docker daemon unavailable for DB smoke | Integrate P1–P4 domain subscribers |
| P5-TST | Integrated E2E / Security tests | P5 + all | IN_PROGRESS | 15 backend tests + 1 frontend smoke test passing (UT-04, UT-06, UT-07, SAF-2, BE-04) | Full E2E waits for P1–P4 modules | Add integrated cross-feature E2E journey suite |
| REL-01 | Deploy / submission / docs | Release owner | NOT_STARTED | — | — | Assign owner |

**DONE definition**: reviewed PR merged + live API/UI or valid designated mock + passing relevant tests + integration compatibility + log link. `95% done` is not a status. Screenshots alone do not prove backend behavior.

## 5. Daily Standup Entries (append; do not overwrite)

```markdown
### YYYY-MM-DD — Daily sync
- P1: Completed: ... (PR/link) | Next: ... | Blocked by: ...
- P2: Completed: ... (PR/link) | Next: ... | Blocked by: ...
- P3: Completed: ... (PR/link) | Next: ... | Blocked by: ...
- P4: Completed: ... (PR/link) | Next: ... | Blocked by: ...
- P5: Completed: ... (PR/link) | Next: ... | Blocked by: ...
- Integration status: ... / E2E proof: ...
- Risks and decisions: ...
```

### 2026-10-21 — Daily sync (P5 Core & UI Milestone)
- P1: Completed: Shared context contracts aligned | Next: Inbox / extraction API | Blocked by: None
- P2: Completed: Feasibility assessment schema contract agreed (D-CONTRACT-005 empty affected_commitment_ids) | Next: Constraint & impact evaluator | Blocked by: None
- P3: Completed: Plan / approval schemas aligned | Next: Recovery planner & action execution adapter | Blocked by: None
- P4: Completed: Communication request schemas aligned | Next: Confirmation workspace & message templates | Blocked by: None
- P5: Completed: Tasks T2.3 (Overview Page) and T2.4 (Activity & Audit Page) wired via TanStack Query; 9 REST endpoints, transactional outbox worker, idempotent consumers, version guard, role-based redaction, and simulated role switcher; 28 backend tests + 12 frontend tests passing; typecheck & build passing | Next: P0 Cross-Feature E2E Hero Journey integration tests | Blocked by: BLOCK-20261021-001 (isolated PostgreSQL for live migration smoke)
- Integration status: Core API + Overview UI + Activity UI fully integrated and tested in synthetic mode.
- Risks and decisions: D-002 (optimistic concurrency version checks), D-005 (synthetic server-side role inspection), CONTRACT-20261021-005 (FeasibilityAssessment affected_commitment_ids relaxed to allow empty list []).


## 6. Blocker / Dependency Ledger

| ID | Opened | Blocked owner | Blocking owner | Issue | Impact | Decision / ETA | Status |
|---|---|---|---|---|---|---|---|
| BLOCK-20261021-001 | 2026-10-21 | P5 | Environment | Docker Desktop Linux engine unavailable because host exposes WSL1; existing PostgreSQL on 5432 is unrelated | Live PostgreSQL migration and DB smoke test cannot run safely | Enable WSL2 or provide isolated PostgreSQL on host 5433 | OPEN |
| BLOCK-TEMPLATE | — | — | — | Add concrete blockers here | — | — | TEMPLATE |

**Escalation rule**: Any blocking contract dispute >2 hours → write blocker and involve P5 + affected owner; choose narrow contract fix, not silent ad hoc field changes. Any P0 at-risk task by 23 Oct → alert entire team and cut P1/P2 extras before core journey.

## 7. Integration & Contract Change Log

```markdown
### CONTRACT-YYYYMMDD-001 — <description>
- Proposed by / reviewed by:
- Old vs new field/event/API:
- Breaking or additive:
- Affected owners, frontend screens, tests:
- Migration or fixture update:
- Decision: ACCEPTED / REJECTED / DEFERRED
- PR / commit:
```

### CONTRACT-20261021-002 — Shared Commitment Registry persistence and lifecycle API
- Proposed by / reviewed by: Phase 1 readiness task / P5 review pending
- Old vs new field/event/API: no existing persistence API → additive `POST/GET /v1/commitments`, `POST /v1/commitments/{id}/transitions`, and `GET /v1/audit?commitment_id=...`; adds typed create/transition/read/audit schemas.
- Breaking or additive: additive; existing canonical lifecycle enums and evidence semantics are unchanged.
- Affected owners, frontend screens, tests: P5 core; P1–P4 consume the registry by tenant, commitment ID and version; backend registry and API tests.
- Migration or fixture update: Alembic `0002_commitment_registry`; existing demo fixture remains compatible.
- Decision: ACCEPTED for implementation by the current task; owner review remains required for future contract changes.
- PR / commit: `ec0458d` (`feat(core): establish Phase 0 foundation and commitment registry`).

### CONTRACT-20261021-003 — Outbox Status, Idempotent Consumers, and Causation Propagation
- Proposed by / reviewed by: P5 (Task T1.4)
- Old vs new field/event/API:
  - Additive `OutboxEventRecord.status` (`PENDING`, `PUBLISHED`, `FAILED`, `DEAD_LETTER`), `last_error`, `next_retry_at`.
  - Additive `ProcessedEventRecord` (`tenant_id`, `event_id`, `consumer_name`, `processed_at`) for idempotent consumers.
  - Additive `causation_id` propagated through `RequestContext`, `CommitmentCreateRequest`, `CommitmentTransitionRequest`, `AuditEvent`, `DomainEvent`, `audit_events`, `outbox_events`.
  - Additive `CoreEventType` enum covering `commitment.created`, `commitment.proposal_offered`, `commitment.confirmed`, `commitment.at_risk`, `commitment.risk_resolved`, `commitment.fulfilment_verified`, `audit.recorded`.
- Breaking or additive: additive; existing event schemas and commitment contracts remain backward-compatible.
- Affected owners, frontend screens, tests: P1–P4 domain event subscribers; P5 core outbox dispatcher; unit and DB tests.
### CONTRACT-20261021-004 — Overview Aggregate API, Correlated Commitment Timeline, Proposals & Fulfilment API, and Role Redaction
- Proposed by / reviewed by: P5 (Tasks T1.6 / T1.7)
- Old vs new field/event/API:
  - Additive `GET /v1/overview`: tenant-scoped SQL aggregate counts (7 buckets: requested, confirmed, at_risk, pending_approval, execution_in_progress, awaiting_confirmation, fulfilled), attention queue (stale plans, unknown feasibility, manual review, failed executions, unresolved confirmations), and filterable commitment summaries.
  - Additive `GET /v1/commitments/{id}/timeline`: chronological correlated timeline merging audit and outbox events, providing actor/role, source feature (`F1_CONTEXT | F2_FEASIBILITY | F3_RECOVERY | F4_COMMUNICATION | CORE`), action, state diffs, correlation/causation IDs, approval reasons, and deep-link pointers (`context_id`, `assessment_id`, `recovery_case_id`, `communication_id`, `proposal_id`).
  - Additive `POST /v1/commitments/{id}/proposals`: offers revised/new terms, advances agreement state to `OFFERED`, optimistic version checks.
  - Additive `POST /v1/commitments/{id}/confirm-proposal`: records customer accept/reject with manager approval and evidence verification.
  - Additive `POST /v1/commitments/{id}/record-fulfilment`: records verified operational completion with manager role and evidence guards; enforces `SENT != ACCEPTED != FULFILLED` invariant.
  - Forbidden unrestricted `PATCH /v1/commitments/{id}`: returns HTTP 405 Method Not Allowed (`UNRESTRICTED_PATCH_FORBIDDEN`).
  - Normalized error response shape (`code`, `message`, `correlation_id`, `details`) across 400, 401, 403, 404, 405, 409, 422, 500.
  - Role-based redaction: sensitive margin, financial, and contact fields sanitized for `STAFF` role in audit and timeline.
- Breaking or additive: additive; existing commitment schemas and transition APIs remain backward-compatible.
- Affected owners, frontend screens, tests: P5 overview and activity screens, P1–P4 feature integration; frontend `shared/types.ts` and `shared/api.ts` synchronized; unit and integration tests.
- Migration or fixture update: contracts/types.ts synchronized.
- Decision: ACCEPTED
- PR / commit: local branch `phase0-core-integration`

### CONTRACT-20261021-005 — Relaxation of FeasibilityAssessment.affected_commitment_ids constraint
- Proposed by / reviewed by: P2 (Feasibility owner) / P5 (Core owner)
- Old vs new field/event/API:
  - `FeasibilityAssessment.affected_commitment_ids` relaxed from `min_length=1` to allow empty lists `[]` (defaults to empty list via `default_factory=list`).
  - Semantics clarified: `affected_commitment_ids` strictly represents downstream commitments demonstrably impacted by operational/resource changes (impact set), NOT the scope of the assessment itself. For standard `FEASIBLE` or `UNKNOWN` evaluations where no downstream commitments are disrupted, an empty list `[]` is expected.
- Breaking or additive: additive / non-breaking relaxation; existing fixtures with populated `affected_commitment_ids` remain fully valid.
- Affected owners, frontend screens, tests: P2 feasibility engine, P3 recovery planner (unblocked for Phase 3), contract tests in `test_contracts.py`.
- Migration or fixture update: `backend/app/core/schemas.py`, `contracts/types.ts`, and example fixture added in `contracts/fixtures/feasible_assessment_example.json`.
- Decision: ACCEPTED
- PR / commit: local branch `phase0-core-integration`

## 8. QA / Metrics Log

| Date | Commit | Backend tests | Frontend tests | Build | E2E | Key observed metric / sample size | Known limitations |
|---|---|---|---|---|---|---|---|
| 2026-10-21 | `ec0458d` on `phase0-core-integration` | 7 passed (`pytest`) | 1 passed (`vitest`) | passed (`npm run build`, typecheck passed) | NOT RUN | Contract/fixture/registry smoke only; sample size 1 fixture | Live DB migration pending isolated PostgreSQL; Docker/WSL1 blocker; npm audit clean after validated upgrades |
| 2026-10-21 | `phase0-core-integration` | 15 passed (`pytest`) | 1 passed (`vitest`) | passed (`npm run build`, typecheck passed) | NOT RUN | Outbox worker, idempotency, version guard, retry/dead-letter, and causation chain passed; sample size 15 tests | Live DB migration pending isolated PostgreSQL |
| 2026-10-21 | `phase0-core-integration` (T1.6/T1.7) | 24 passed (`pytest`) | 1 passed (`vitest`) | passed (`npm run build`, typecheck passed) | NOT RUN | Complete 9-endpoint surface, overview SQL counts (7 buckets), attention queue, chronological timeline with F1–F4 links, role redaction (Staff vs Manager), patch forbidden (405), and normalized errors; sample size 24 tests | Live DB migration pending isolated PostgreSQL |
| 2026-10-21 | `phase0-core-integration` (T2.3) | 24 passed (`pytest`) | 8 passed (`vitest`) | passed (`npm run build`, typecheck passed) | NOT RUN | Real Overview wired to GET /v1/overview via TanStack Query, 7 authoritative state cards with non-green enforcement, attention queue with KL timestamps and deep links, simulated role switcher, state bucket and search filtering, loading skeleton, empty state, working retry callback, and 403 permission denied state; sample size 8 frontend + 24 backend tests | Live DB migration pending isolated PostgreSQL |
| 2026-10-21 | `phase0-core-integration` (T2.4) | 28 passed (`pytest`) | 12 passed (`vitest`) | passed (`npm run build`, typecheck passed) | NOT RUN | Real Activity & Audit page (/activity) wired to GET /v1/commitments/{id}/timeline and GET /v1/audit via TanStack Query (FE-03a–d, UI-02); chronological event timeline, state transition diffs (CONFIRMED → AT_RISK), version increments, human governance approval highlights with reason and scope, correlation/causation grouping, deep links to F1–F4, Staff role redaction, and loading/empty/retry/403 states; sample size 12 frontend + 28 backend tests | Live DB migration pending isolated PostgreSQL |


Metric protocol: always disclose dataset size, date, ground truth creation method, pass/fail definitions. **Do not** mark actual customer fulfilment because communication was sent or approved.

## 9. Submission Checklist

- [ ] Exactly one clearly explained SME operational problem and value proposition.
- [ ] One complete runnable Trigger→Connected Data→Decision→Human Approval→Visible Outcome + Audit journey.
- [ ] GitHub repo public/accessible and matches demonstrated build; tested installation steps.
- [ ] Synthetic data only; no real payment processing, secrets, real customer/company data.
- [ ] Roles/permissions and important action approval demonstrated.
- [ ] Metric evidence includes definitions and limitations; clarity maintained.
- [ ] Team member contributions and feature owners accurately recorded.
- [ ] Orbyte connector assumptions described as assumptions, not real integration.

## 10. Risks / Fallbacks

| Risk | Trigger | Fallback |
|---|---|---|
| LLM or GPU unavailable | Qwen timeout/credit limit | Rule-based/typed input & `UNKNOWN`; core journey unaffected |
| One official channel inaccessible | Provider OAuth/template denied | Fully labelled synthetic adapter and authorized API contract |
| OR-Tools complex model too slow | Solver timeout | Deterministic ATP/basic capacity + UNKNOWN; no false infeasibility |
| Temporal not integrated | Workflow server unavailable | DB-backed state machine / approval steps in P0 |
| F1 fuzzy order ambiguity | Multiple candidate matches | Manual review; no forced identity link |
| Team integration delayed | APIs differ / PRs blocked | Lock one hero scenario; cut optional endpoints and diagrams |
| Deployment failures | Production-like host down | Tested local Docker run + recorded fallback, truthfully disclose |

## 11. Release Notes (fill when real)

- Release tag: TBD
- Commit hash: TBD
- Test command/results: TBD
- Deployed URL and access: TBD
- Feature limitations: TBD
- Known defects: TBD
- Submission timestamp/reference: TBD

## 12. Phase 0 — Shared Contracts and Repository Foundation

### 2026-10-21 — Phase 0 audit and foundation
- Scope: shared contracts, repository foundation, synthetic fixture, parallel boundaries; no P1–P4 business module implementation.
- Repository audit: `main` clean and synchronized with `origin/main` before changes; repository was an empty foundation with only `docs/` and `README.md`.
- Added: canonical Pydantic schemas and enums, synchronized TypeScript types, unified synthetic fixture, FastAPI `/health`, React/Vite shell and routes, shared API client, PostgreSQL Compose service, SQLAlchemy/Alembic wiring, worker entrypoint, `.env.example`, `.gitignore`, and minimal tests.
- Contract decisions: canonical `BusinessContext.status` is `INFORMATION_READY` with legacy `READY` input normalization; `Confirmation` is version- and identity-bound; approval/execution states are frozen only to the lifecycle values already required by P3/P4.
- Validation: backend `7 passed`; frontend typecheck passed; frontend `1 passed`; frontend production build passed; Alembic offline SQL generation passed; `docker compose config` passed.
- Not run: live PostgreSQL/Alembic upgrade because Docker Desktop's Linux engine is unavailable and the existing host PostgreSQL rejects the project credentials. No existing database was modified.
- Repository documentation gap resolved: all five owner requirement files are now checked into `docs/requirements/`; root `AGENTS.md` is the single canonical agent instruction file.
- Dependency note: the initial audit reported 5 findings (3 moderate, 2 critical); validated non-breaking manual upgrades reduced the final audit to 0 findings.
- Next: enable WSL2 or provide an isolated PostgreSQL instance on host port 5433, then run the DB migration smoke; assign P1–P5 branches and implement feature slices independently.

### 2026-10-21 — Phase 1 core integration readiness
- Branch: `phase0-core-integration`; implementation baseline `ec0458d` committed and pushed to `origin/phase0-core-integration`.
- Registry: added tenant-scoped Commitment persistence, controlled lifecycle transitions, optimistic `commitment_version` checks, immutable audit rows, transactional outbox rows, and typed API errors.
- APIs: `POST/GET /v1/commitments`, `GET /v1/commitments/{id}`, `POST /v1/commitments/{id}/transitions`, `GET /v1/audit`, and `GET /v1/events/{id}`. Actor role is resolved server-side from the synthetic actor map; client role headers are ignored.
- Security audit: initial 5 findings were dev-only Vitest/Tinypool criticals plus React Router moderate findings. Manual upgrades to `vitest@5.0.5` and `react-router-dom@7.18.4` were validated with typecheck, tests and build; final `npm audit` reports 0 vulnerabilities.
- Database: migration `0002_commitment_registry` passes offline SQL generation. Live `upgrade head` is blocked by Docker/WSL1; no connection was made to or mutation performed on host port 5432.
- P1–P4 readiness: each owner now has its requirement file in `docs/requirements/`; shared schemas/types and fixture remain compatible; feature routes and backend package boundaries remain unchanged.

### 2026-10-21 — Task T1.4: Outbox Worker, Event Dispatcher & Idempotent Consumer Framework
- Scope: BE-04a–BE-04f, SAF-2, UT-04, UT-06, UT-07. Strictly within P5 core paths; no edits to P1–P4 feature directories.
- Envelope validation (BE-04a): canonical `DomainEvent` envelope enforced with `event_id`, `schema_version`, `event_type`, `tenant_id`, `commitment_id`, `commitment_version`, `correlation_id`, `causation_id`, `occurred_at`, `payload`; `CoreEventType` enum defines `commitment.created`, `commitment.proposal_offered`, `commitment.confirmed`, `commitment.at_risk`, `commitment.risk_resolved`, `commitment.fulfilment_verified`, `audit.recorded`; sensitive keywords/PII in payloads are strictly rejected.
- Atomic outbox persistence (BE-04b, SAF-2): every `CommitmentService` state transition writes `CommitmentRecord`, `AuditEventRecord`, and `OutboxEventRecord(status="PENDING", attempts=0)` in the same database transaction. If publisher is offline or fails, pending outbox records remain safely stored in DB.
- Dispatcher & subscriber registry (BE-04b, BE-04e): `OutboxDispatcher` provides in-process named subscriber registry (`register_subscriber`), batched processing (`process_outbox_batch`), exponential backoff retries, status tracking (`PENDING`, `PUBLISHED`, `FAILED`, `DEAD_LETTER`), and reconciliation (`requeue_dead_letter`). Background polling loop implemented in `run_worker`.
- Consumer idempotency & version guard (BE-04c, BE-04d, UT-04, UT-06): duplicate event delivery checks `processed_events` for `(tenant_id, event_id, consumer_name)` and cleanly skips duplicate execution without double mutations or duplicate audit entries; `is_stale_event` version guard ensures events with stale `commitment_version` cannot revert newer commitment state.
- Correlation trace (BE-04f): `correlation_id` and `causation_id` propagate from trigger events and requests through `RequestContext` and `CommitmentService` into downstream `outbox_events` and `audit_events`.
- Database & migrations: Alembic migration `0003_outbox_processing` created (adds `status`, `last_error`, `next_retry_at` to `outbox_events`, `causation_id` to `audit_events`, and creates `processed_events` table); offline PostgreSQL migration SQL generation passes; `contracts/types.ts` updated with `OutboxStatus` and `causation_id`.
- Validation: 15 backend tests passed (`pytest`); frontend typecheck passed (`tsc --noEmit`); frontend vitest passed (`1 passed`); frontend production build passed (`npm run build`).

### 2026-10-21 — Tasks T1.6 / T1.7: Core REST API, Overview Aggregate, Timeline, and Redacted Audit API
- Scope: BE-01e, FE-02a–c, FE-03a–d, API-1. All work confined to P5 core paths (`backend/app/core/`, `backend/app/main.py`, `backend/tests/`, `contracts/`, `frontend/src/shared/`). No P1–P4 feature directories modified.
- Complete 9-endpoint REST API surface verified:
  1. `GET /health` (status "ok", service "moumantai-api")
  2. `GET /v1/overview` (aggregate counts, attention queue, commitment summaries)
  3. `GET /v1/commitments/{commitment_id}` (retrieval with tenant isolation)
  4. `GET /v1/commitments/{commitment_id}/timeline` (chronological correlated audit/outbox entries with F1–F4 entity links)
  5. `POST /v1/commitments/{commitment_id}/proposals` (offer new/revised terms, advance agreement to OFFERED)
  6. `POST /v1/commitments/{commitment_id}/confirm-proposal` (manager-governed acceptance/rejection with evidence)
  7. `POST /v1/commitments/{commitment_id}/record-fulfilment` (manager-governed operational evidence recording; enforces `SENT != ACCEPTED != FULFILLED`)
  8. `GET /v1/audit?commitment_id=...` (audit log with tenant verification and role-based redaction)
  9. `GET /v1/events/{event_id}` (domain event inspection scoped to tenant)
- Unrestricted PATCH rejected (BE-02c, API-1): `PATCH /v1/commitments/{id}` explicitly caught and rejected with HTTP 405 Method Not Allowed (`code="UNRESTRICTED_PATCH_FORBIDDEN"`).
- Overview Aggregate & Attention Queue (FE-02a–c): Real SQL aggregate counts for the 7 authoritative buckets (requested, confirmed, at_risk, pending_approval, execution_in_progress, awaiting_confirmation, fulfilled); attention queue identifies actionable items across `STALE_PLAN`, `UNKNOWN_FEASIBILITY`, `MANUAL_REVIEW`, `FAILED_EXECUTION`, and `UNRESOLVED_CONFIRMATION` with deep links and severities.
- Correlated Timeline & Deep Links (FE-03a–c): Merges `audit_events` and `outbox_events` sorted chronologically; tracks `correlation_id` and `causation_id`; resolves `source_feature` (`F1_CONTEXT | F2_FEASIBILITY | F3_RECOVERY | F4_COMMUNICATION | CORE`); maps entity pointers (`context_id`, `assessment_id`, `recovery_case_id`, `communication_id`, `proposal_id`).
- Role-Based Redaction (FE-03d, UT-05): Redacts confidential/financial notes (margins, profits, markups) and customer contact strings (phone, email) for `STAFF` role in both audit and timeline, while preserving full unredacted records for `OWNER` and `MANAGER`.
- Normalized Error Responses (BE-01e): Added exception handlers for `DomainError`, `StarletteHTTPException`, and `RequestValidationError` so all 400, 401, 403, 404, 405, 409, 422, and 500 errors return `{"code": "...", "message": "...", "correlation_id": "...", "details": {...}}`. Optimistic concurrency conflict (409) includes `current_commitment_version` in details.
- Frontend Contract Synchronization: `contracts/types.ts` and `frontend/src/shared/types.ts` updated with `AttentionItem`, `OverviewCounts`, `OverviewResponse`, `TimelineEntry`, `SourceFeature`, `ProposalCreateRequest`, `ProposalConfirmRequest`, `RecordFulfilmentRequest`; typed API helper functions added to `frontend/src/shared/api.ts`.
- Validation: 24 backend tests passed (`pytest`); frontend typecheck passed (`tsc --noEmit`); frontend vitest passed (`1 passed`); frontend production build passed (`npm run build`).

### 2026-10-21 — Task T2.3: Real Overview Page Wired to GET /v1/overview (FE-02a–e, UI-01)
- Scope: FE-02a–e, FE-01d, UI-01. Confined strictly to P5 owned files (`frontend/src/features/overview/`, `frontend/src/shared/`, `frontend/src/layout/AppShell.tsx`, `frontend/src/App.tsx`, `frontend/src/pages/OverviewPage.tsx`, `frontend/src/styles.css`). Zero edits to P1–P4 feature directories.
- Real TanStack Query integration (FE-02a, FE-02c): Replaced static placeholder cards with live `useQuery` fetching `GET /v1/overview` with `X-Tenant-ID` and `X-Actor-ID` headers; zero hardcoded frontend commitment arrays.
- 7 Authoritative State Summary Cards (FE-02a, FE-02c): Displays counts and interactive filters for Requested, Confirmed, At Risk, Pending Approval, Execution in Progress, Awaiting Confirmation, and Fulfilled. Enforces FE-01d strict semantic status badge colors: warning/amber for Pending Approval, purple/violet for Awaiting Confirmation, neutral/violet for Unknown — never green/success for pending or unconfirmed states.
- Attention Queue (FE-02b): Renders live items from backend `attention_queue` covering stale plans, unknown feasibility, manual review, and failed executions with severity borders, category badges, Asia/Kuala_Lumpur (MYT) timestamps, and deep links to `/commitments/:id`, `/orders/:id`, and `/activity?commitment_id=...`.
- Transparency Header (FE-02d): Displays active `tenant_id`, current simulated actor and role selector (`Owner` / `Manager` / `Staff` mapped to `user_owner_01`, `user_manager_01`, `user_staff_01`), `SYNTHETIC` integration mode badge, last-updated timestamp formatted in KL time, and a manual Refresh button.
- Interactive Filtering & Mandatory UI States (FE-02e):
  - State bucket filter buttons and search input filtering by commitment ID, order ID, customer ID, or SKU.
  - Loading skeleton with shimmer animation (`aria-busy="true"`, `role="status"`).
  - Empty state when commitments list or search result is empty with reset filter action.
  - API Error state with error details and working "Retry Connection" callback.
  - Permission Denied (403) state handling forbidden access with role switcher.
- Testing & Branding: Zero `PromiseFlow` strings in UI; all branding displays **MouManTAI**; 7 Vitest + React Testing Library tests in `src/features/overview/__tests__/OverviewPage.test.tsx` plus shell test passing (8 tests total).
- Validation: 24 backend tests passed (`python -m pytest`); frontend typecheck passed (`npm run typecheck`); frontend vitest passed (`8 passed`); frontend production build passed (`npm run build`).

### 2026-10-21 — Contract Update: FeasibilityAssessment.affected_commitment_ids Schema Relaxation (P2/P5)
- Scope: `backend/app/core/schemas.py`, `contracts/types.ts`, `contracts/fixtures/feasible_assessment_example.json`, `backend/tests/test_contracts.py`. Strictly within P5 contract paths.
- Problem: `FeasibilityAssessment.affected_commitment_ids` was constrained to `min_length=1`. For standard `FEASIBLE` or `UNKNOWN` evaluations where no downstream commitments are disrupted, requiring ≥1 affected commitments forced false risk associations and blocked P2 solver output.
- Resolution (CONTRACT-20261021-005): Relaxed `affected_commitment_ids` to `default_factory=list` without `min_length=1`. Added field description: *"List of commitment IDs demonstrably impacted by operational changes. Empty list if none or unconfirmed."*
- Cross-language synchronization: Updated `contracts/types.ts` with JSDoc semantics; verified `frontend/src/shared/types.ts` correctly accepts `string[]` (including `[]`). Added canonical example fixture `contracts/fixtures/feasible_assessment_example.json` demonstrating `FEASIBLE` and `UNKNOWN` assessments with `affected_commitment_ids: []`.
- Tests: Added 4 unit tests in `backend/tests/test_contracts.py` verifying validation of empty affected commitments for `FEASIBLE`, `UNKNOWN`, default omitted list, and example fixture loading. Existing `demo_dataset.json` remains fully backward-compatible.
- Validation: 28 backend tests passed (`python -m pytest`); frontend typecheck passed (`npm run typecheck`); frontend vitest passed (`8 passed`); frontend production build passed (`npm run build`). Unblocks P2 Phase 3 evaluation pipeline.



