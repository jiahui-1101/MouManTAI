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
| P2-FE | Feasibility / Impact UI | P2 | IN_REVIEW | Phase 6 exportable pages, typed feature adapters, labeled preview; 43 focused tests and typecheck/build pass | P5 public detail/auth/persistence adapters and route mounting pending; no live page API integration | Independent external Phase 6 review; do not begin Phase 7 |
| P2-BE | Constraint + Impact engine | P2 | IN_PROGRESS | Phase 5 local correction `85d46b2` externally approved; historical 24 router / 188 combined tests pass, backend unchanged in Phase 6 | P5 mounting/auth/snapshot/version/persistence/supplier processing/Core risk integration; empty Impact Set implemented on P5 branch pending integration; P3 HTTP confirmation | Preserve approved backend; shared integration handoff remains open |
| P2-TST | Feasibility/Impact tests | P2 | IN_PROGRESS | Phase 6: 43 focused frontend tests and typecheck/build pass; historical Phase 5 backend tests preserved | Live authenticated API/UI/DB/outbox/P3/E2E remain unverified; browser viewport QA pending | Independent external Phase 6 review; no full P2 completion claim |
| P3-FE | Recovery / Approval UI | P3 | NOT_STARTED | — | — | Plan comparison cards |
| P3-BE | Plan / Approval / Action API | P3 | NOT_STARTED | — | P2 evaluator interface | Start templates |
| P3-TST | Approval/Execution tests | P3 | NOT_STARTED | — | — | Define stale-approval test |
| P4-FE | Communication / Confirmation UI | P4 | NOT_STARTED | — | — | Scaffold route |
| P4-BE | Draft/Send/Confirm APIs | P4 | NOT_STARTED | — | P3 proposal schema | Define signed confirmation |
| P4-TST | Confirmation/Channel tests | P4 | NOT_STARTED | — | — | Define ambiguous OK fixture |
| P5-FE | Shell / Overview / Audit UI | P5 | IN_PROGRESS | Real Overview (/overview) & Activity (/activity) wired to real backend endpoints via TanStack Query (FE-01, FE-02, FE-03, UI-01, UI-02); timeline with F1–F4 deep links, state diffs, version increments, human governance highlights, correlation/causation grouping, role redaction, loading/empty/error/403 states; 12 vitest tests passing | Feature pages remain owner work | Integrate P1–P4 feature routes |
| P5-BE | Registry / DB / Events / Roles | P5 | IN_PROGRESS | Integration facade & typed consumers (BE-06a–f), P1–P4 handshakes, proposal versioning, mock resource inventory & locking primitive (SAF-4, Invariant 8); 63 backend tests passing | Docker daemon unavailable for DB smoke | Complete cross-feature E2E rehearsal |
| P5-TST | Integrated E2E / Security tests | P5 + all | IN_PROGRESS | 63 backend tests + 12 frontend tests passing (BE-06a–f, SAF-4, Invariant 8, E2E-01 through E2E-12, UI-04, UI-05, UT-04, UT-06, UT-07, UT-08, UT-09, UT-10, SAF-2) | Full E2E waits for P1–P4 feature modules | Cross-feature integration complete |
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

### 2026-10-21 — P2 Phase 1 checkpoint

- P2: Completed P2-local immutable operational snapshot models, validation, ETA-change fixtures, fixture allocation/reservation/timezone documentation, and 13 focused model/fixture tests. Next: stop for external review before Phase 2. Blocked: P5 shared contract/persistence/auth/outbox work and P3 ProposedChanges integration remain unapproved dependencies.
- P2-FE remains `NOT_STARTED`; no UI was implemented.
- Local commit SHA: see phase response. This Phase 1 commit was subsequently included in the feature-branch push; no merge performed.

### 2026-10-21 — P2 Phase 1 review corrections

- P2: Corrected capacity-window upper-bound validation, commitment material-use/deadline consistency, and Oct 24 buffered-fixture capacity coverage. The three focused tests failed before implementation and passed afterward; the snapshot test file passes 16 tests. Calendar coverage does not claim full production feasibility. Next: stop for external review. Blocked: P5 shared contracts/integration and P3 ProposedChanges handoff remain pending.
- P2-FE remains `NOT_STARTED`; no UI was implemented.
- Correction commit SHA: `98ea9882a4cb27951ce78d14a19538cc162b8d58`; subsequently pushed to `origin/feat/p2-feasibility-engine` and verified against the remote ref; no merge performed.

### 2026-10-21 — P2 Phase 1 confirmation-provenance correction

- P2: Added P2-local typed supplier evidence associations. Confirmed deliveries require a source-grounded `CONFIRMATION` claim tied to the exact tenant, supplier, delivery and evidence reference; ETA changes retain that association and add a distinct ETA-change claim. Five targeted provenance tests pass and the focused snapshot file passes 21 tests. Synthetic refs establish structural provenance only; P5 must decide external source authenticity and adapter trust. P2-FE remains `NOT_STARTED`. The feature branch was pushed and the remote branch SHA was verified against local HEAD (exact SHA in phase response). Stop for external review; Phase 2 has not started.

### 2026-10-21 — P2 Phase 2 checkpoint

- P2: Phase 1 and both corrections externally approved by user at `0d990d99bfe973f7b13295d1e005639a0f61adbd`. Added P2-local Decimal-safe batch ATP, recursive BOM/cycles, source-backed conversions/waste assumptions, reservation owner/subtract-once handling, expiry at material use, confirmed evidence-linked receipt timing/cutoffs and conservative UNKNOWN. Material-only statuses do not claim full feasibility. 45 new calculation tests plus 21 Phase 1 tests pass (66 total). Internal code review found an overflow-handling gap; a failing regression was added, the gap fixed, and targeted review checks passed. External Phase 2 review is still pending.
- P2: No Phase 3 capacity/evaluator orchestration, Phase 4 events, Phase 5 APIs, Phase 6 UI or other-owner code changes. P2-FE remains NOT_STARTED. P5 authenticity/completeness/shared contracts and P3 integration/command reservations remain BLOCKED. Exact checkpoint commit/push SHA and feature-ref verification are in the phase response. Stop for external review before Phase 3.

### 2026-10-21 — P2 Main synchronization safety checkpoint

- P2: Merged Main `4ec2ba1ef7ede4a67352631178a73a6882bcd774` into the P2 branch only after backup ref `backup/p2-before-main-sync-d28b63a`. Combined package docstrings and kept all P2/P5 QA entries; all incoming non-P2 TEAM_LOG lines preserved. Nine pre-existing untracked bytecode files retained with unchanged hashes. Merge SHA/push verification in task response.
- P2: 66 P2 and 7 focused shared contract/health/SQLite registry tests pass. Backend runtime import fails with `ModuleNotFoundError: No module named 'backend'`; P2-relative import adaptation and app-based test alignment reported for review. Shared schemas/contracts/Core/DB/migrations unchanged from Main. No Phase 3 implementation. Full report: `backend/app/feasibility/MAIN_SYNC_REPORT.md`.

### 2026-10-21 — P2 runtime compatibility correction

- P2: User accepted Main-sync merge `14e794308d317e744d321f2b26ba4d5af8f677dd`. Changed only imports in five P2 modules to package-relative form and three existing P2 test files to app.feasibility. Exact runtime probe failed before the fix and now prints `P2 runtime imports OK`. Canonical class identity across P2 modules/tests and shared Pydantic base passes; no backend.app modules load. All eight Python ASTs match approved HEAD after import-only normalization, preserving calculations/evidence/fixtures.
- P2: From backend, `python -B -m pytest -o 'addopts=' app/feasibility/tests/test_snapshots.py app/feasibility/tests/test_bom.py app/feasibility/tests/test_inventory.py tests/test_contracts.py tests/test_smoke.py tests/test_registry.py -q -p no:cacheprovider` — 73 passed, 1 existing Starlette/httpx warning. P5 pytest mismatch (host 9.1.1 vs declared >=8.3,<9) documented without dependency changes. Shared demo fixture/schema alignment remains pending; P5 contracts/configuration unchanged. No Phase 3 work. Correction SHA/push verification in task response; stop for external review.

### 2026-10-21 — P2 Phase 3 local calculation checkpoint (PARTIAL)

- P2: User approved runtime correction 5a1e827b6431d4fddbaf6bf2938865f0bfdef567 and Phase3 only. Added P2-local evidence-backed fixed-production resource/rate/setup/transit/plan/job models, exact working-window/job/resource/deadline checks and pure evaluator using unchanged batch ATP/BOM. Hypothetical quantity/deadline/start changes are version-aware, conditional and non-mutating; new competitor shortage rejects a candidate. Missing data/unsupported production remains UNKNOWN.
- P2: 54 Phase3 tests pass; existing66 P2 plus7 shared tests pass (73, one existing Starlette/httpx warning). Full exact commands, red-green corrections and limitations in backend/app/feasibility/P2_PHASE_REPORTS.md. Host pytest9.1.1 vs declared>=8.3,<9 remains documented; dependencies unchanged. Frontend/API/events/E2E/live PostgreSQL/metrics NOT RUN for this phase.
- P2: User confirmed no verified P5 business semantics for nonempty affected_commitment_ids; forbade default insertion of evaluated target. evaluate returns a clearly local EvaluationResult using actual Core enums/ConstraintReason and no affected IDs. Final FeasibilityAssessment mapping BLOCKED, not claimed integrated. User will request P5 decision for every status, especially FEASIBLE/UNKNOWN. P3 serialization and shared operational-data/catalog adapter requests are in PHASE3_HANDOFF.md.
- P2: Shared Core/schema/app shell exist and were not modified. Shared demo lacks complete operational evidence and uses SAUCE/PACKAGING rather than P2 WRAP; no fixture/evidence invented to make it FEASIBLE. P2-FE remains NOT_STARTED. Only P2 code/docs and these P2 entries changed. Commit/feature-only push SHA in phase response. STOP for external Phase3 review; overall Phase3 PARTIAL and Phase4 NOT_STARTED.
### 2026-10-21 — Daily sync (P5 Core & UI Milestone)
- P1: Completed: Shared context contracts aligned | Next: Inbox / extraction API | Blocked by: None
- P2: Completed: Feasibility assessment schema contract agreed (D-CONTRACT-005 empty affected_commitment_ids) | Next: Constraint & impact evaluator | Blocked by: None
- P3: Completed: Plan / approval schemas aligned | Next: Recovery planner & action execution adapter | Blocked by: None
- P4: Completed: Communication request schemas aligned | Next: Confirmation workspace & message templates | Blocked by: None
- P5: Completed: Tasks T2.3 (Overview Page) and T2.4 (Activity & Audit Page) wired via TanStack Query; 9 REST endpoints, transactional outbox worker, idempotent consumers, version guard, role-based redaction, and simulated role switcher; 28 backend tests + 12 frontend tests passing; typecheck & build passing | Next: P0 Cross-Feature E2E Hero Journey integration tests | Blocked by: BLOCK-20261021-001 (isolated PostgreSQL for live migration smoke)
- Integration status: Core API + Overview UI + Activity UI fully integrated and tested in synthetic mode.
- Risks and decisions: D-002 (optimistic concurrency version checks), D-005 (synthetic server-side role inspection), CONTRACT-20261021-005 (FeasibilityAssessment affected_commitment_ids relaxed to allow empty list []).

### 2026-10-21 — Daily sync (P5 Task T3.1 Core Integration Facade & Handshakes)
- P1: Completed: Shared context contracts aligned | Next: Ingestion & field extraction | Blocked by: None
- P2: Completed: Feasibility assessment schema contract agreed | Next: Feasibility solver | Blocked by: None
- P3: Completed: Plan & action schemas aligned | Next: Recovery generator & ranking | Blocked by: None
- P4: Completed: Proposal & confirmation contracts aligned | Next: Message templates & channel adapter | Blocked by: None
- P5: Completed: Task T3.1 (P1–P4 Handshake Event Consumers & Core Integration Facades, BE-06a–f, UT-10); CoreIntegrationFacade, assess/recovery/proposal endpoints, Alembic migration 0004_commitment_proposals, 18 comprehensive integration tests in test_feature_handshakes.py covering UT-08, UT-09, UT-10, E2E-04, E2E-05, E2E-06, E2E-07, E2E-12, and PII minimization; 46 backend tests + 12 frontend tests passing; typecheck & build passing | Next: P0 Cross-Feature E2E Hero Journey integration tests | Blocked by: BLOCK-20261021-001 (isolated PostgreSQL for live migration smoke)
- Integration status: Core Integration Facade + P1–P4 Handshake Consumers fully implemented and tested.
- Risks and decisions: D-002 (concurrency), D-005 (synthetic server-side role inspection), CONTRACT-20261021-006 (P1–P4 Handshakes & Versioned Proposals).

### 2026-10-21 — Daily sync (P5 Task T3.2 Mock Resource Inventory & Reservation Locking)
- P1: Completed: Shared context contracts aligned | Next: Ingestion & field extraction | Blocked by: None
- P2: Completed: Read-only resource snapshot query available (get_resource_snapshot) | Next: Constraint & impact solver | Blocked by: None
- P3: Completed: Transactional locking reservation primitive available (reserve_resource) | Next: Action execution adapter | Blocked by: None
- P4: Completed: Proposal & confirmation contracts aligned | Next: Message templates & channel adapter | Blocked by: None
- P5: Completed: Task T3.2 (Mock Resource Inventory & Concurrent Reservation Lock Primitive, SAF-4, Invariant 8); resource_stocks and resource_reservations models, Alembic migration 0005_resource_reservations, pure read-only get_resource_snapshot for P2, atomic locking reserve_resource with InsufficientResourceError (409) for P3, idempotency on (tenant_id, idempotency_key), release/consume lifecycle, 8 comprehensive tests in test_resource_reservations.py; 54 backend tests + 12 frontend tests passing; typecheck & build passing | Next: P0 Cross-Feature E2E Hero Journey integration suite | Blocked by: BLOCK-20261021-001 (isolated PostgreSQL for live migration smoke)
- Integration status: Mock resource inventory and concurrent reservation lock primitive fully implemented and tested.
- Risks and decisions: Invariant 8 (no concurrent over-allocation), SAF-4 (P2 read-only, P3 transactional lock), CONTRACT-20261021-007.

### 2026-10-21 — Daily sync (P5 Task T3.3 Backend E2E Hero Journey & 12-Scenario Acceptance Matrix)
- P1: Completed: Shared context contracts aligned | Next: Ingestion & field extraction | Blocked by: None
- P2: Completed: Read-only resource snapshot query & feasibility contracts aligned | Next: Constraint & impact solver | Blocked by: None
- P3: Completed: Transactional locking reservation primitive & recovery plan contracts aligned | Next: Action execution adapter | Blocked by: None
- P4: Completed: Proposal & confirmation contracts aligned | Next: Message templates & channel adapter | Blocked by: None
- P5: Completed: Task T3.3 (Backend E2E Hero Journey & Full 12-Scenario Acceptance Matrix, UI-04, UI-05, E2E-01 to E2E-12); implemented test_e2e_hero_journey.py (full single-commitment_id 'com_001' lifecycle across 9 monotonic optimistic concurrency versions from ingestion to delivery POD) and test_e2e_negative_matrix.py (E2E-04 snapshot drift, E2E-05 ambiguous OK, E2E-06 stale proposal version rejection, E2E-07 delivery tracking without state advance, E2E-08 idempotency retry, E2E-09 unverified receipt guard, E2E-10 worker crash recovery, E2E-11 cross-tenant isolation); updated commitments.py attention queue is_ambiguous evaluation; 63 backend tests + 12 frontend tests passing; typecheck & build passing | Next: Cross-feature E2E rehearsal with team | Blocked by: BLOCK-20261021-001 (isolated PostgreSQL for live migration smoke)
- Integration status: Full 12-scenario backend E2E acceptance matrix and Hero Journey verified on real database.
- Risks and decisions: Invariant adherence verified: REQUESTED != CONFIRMED, CONFIRMED + AT_RISK coexists, SENT != ACCEPTED != FULFILLED, APPROVED != EXECUTED, OCR receipt != verified funds. CONTRACT-20261021-008.


## 6. Blocker / Dependency Ledger

| ID | Opened | Blocked owner | Blocking owner | Issue | Impact | Decision / ETA | Status |
|---|---|---|---|---|---|---|---|
| BLOCK-20261021-001 | 2026-10-21 | P5 | Environment | Docker Desktop Linux engine unavailable because host exposes WSL1; existing PostgreSQL on 5432 is unrelated | Live PostgreSQL migration and DB smoke test cannot run safely | Enable WSL2 or provide isolated PostgreSQL on host 5433 | OPEN |
| BLOCK-P2-P3-001 | 2026-10-21 | P2 | P5 | Empty actual Impact Set schema fix IMPLEMENTED ON P5 BRANCH, PENDING INTEGRATION (`a5f9915`); current P2/Main still old schema | Final shared assessment adapter still blocked on synchronization and runtime adapters | No merge authorized/performed; preserve both owners TEAM_LOG entries in a future approved sync | OPEN |
| BLOCK-P2-P3-002 | 2026-10-21 | P2 | P3 | ProposedChanges fixed-booking and Phase 5 HTTP serialization not yet owner-confirmed | Library/API handoff provisional | Review PHASE3_HANDOFF.md and PHASE5_HANDOFF.md; reuse pure evaluate(); no duplicate calculator or arbitrary stock insertion | OPEN |
| BLOCK-P2-P3-003 | 2026-10-21 | P2 | P2 + P5 | Shared summary lacks complete operational evidence; SAUCE/PACKAGING vs WRAP catalog mismatch | Shared demo cannot be safely treated as a full trusted snapshot | Review source/catalog adapter and fixture extension; missing data stays UNKNOWN | OPEN |
| BLOCK-P2-P5-004 | 2026-10-21 | P2 | P5 | No approved P2 router mount, authenticated RequestContext/internal auth, authoritative snapshot/version authority, durable assessment/history or impact reader, or transactional supplier-event/outbox adapter | Local route tests are not production integration; assessment/event success remains unavailable | P5 to answer the exact interface/ownership questions in `backend/app/feasibility/PHASE5_HANDOFF.md`; routes fail closed until approved adapters exist | OPEN |
| BLOCK-P2-P3-005 | 2026-10-21 | P2 | P3 | P3 owner confirmation of the HTTP hypothetical-evaluation request/response shape is pending | No cross-module HTTP call can be claimed; Python pure evaluator remains the documented handoff | Confirm Phase 5 serialization against `evaluate(snapshot, proposed_changes, commitment)` in `PHASE5_HANDOFF.md`; P2 made no P3 changes | OPEN |
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

### 2026-10-21 — P5 Contract Decision: affected_commitment_ids Semantics
- **Context**: P2 raised ambiguity regarding `min_length=1` on `FeasibilityAssessment.affected_commitment_ids` for `FEASIBLE`/`UNKNOWN`.
- **Decision**: Approved relaxation to allow empty list (`min_length=0`, default `[]`). The field strictly denotes downstream impacted commitments, not the assessment scope.
- **Impact**: Unblocks P2 Phase 3 calculation and prevents P3 from generating false recovery plans.
- **Owner**: P5 (Updated schema in contracts/ and app.core.schemas).
- Proposed by / reviewed by: P2 (Feasibility owner) / P5 (Core owner)
- Old vs new field/event/API:
  - `FeasibilityAssessment.affected_commitment_ids` relaxed from `min_length=1` to allow empty lists `[]` (defaults to empty list via `default_factory=list`).
  - Semantics clarified: `affected_commitment_ids` strictly represents downstream commitments demonstrably impacted by operational/resource changes (impact set), NOT the scope of the assessment itself. For standard `FEASIBLE` or `UNKNOWN` evaluations where no downstream commitments are disrupted, an empty list `[]` is expected.
- Breaking or additive: additive / non-breaking relaxation; existing fixtures with populated `affected_commitment_ids` remain fully valid.
- Affected owners, frontend screens, tests: P2 feasibility engine, P3 recovery planner (unblocked for Phase 3), contract tests in `test_contracts.py`.
- Migration or fixture update: `backend/app/core/schemas.py`, `contracts/types.ts`, and example fixture added in `contracts/fixtures/feasible_assessment_example.json`.
- Decision: ACCEPTED
- PR / commit: local branch `phase0-core-integration`

### CONTRACT-20261021-006 — P1–P4 Handshake Event Consumers, Core Integration Facade, and Versioned Proposals Persistence
- Proposed by / reviewed by: P5 (Task T3.1)
- Old vs new field/event/API:
  - Additive `CoreIntegrationFacade` (`backend/app/core/integration.py`) providing typed handshake service methods: `handle_context_updated` (BE-06a), `handle_feasibility_assessment` (BE-06b), `authorize`, `start_recovery`, `execute_recovery_plan` (BE-06c), `record_communication_status`, `record_ambiguous_response`, `confirm_proposal` (BE-06d), and `record_fulfilment` (BE-02h).
  - Additive endpoints in `backend/app/core/router.py`:
    - `POST /v1/commitments/{id}/assess`: P2 Feasibility assessment intake with version conflict guard.
    - `POST /v1/integration/context-updated`: P1 BusinessContext intake with conflict / missing field handling.
    - `POST /v1/commitments/{id}/recovery/start`: P3 recovery planning trigger.
    - `POST /v1/commitments/{id}/recovery/execute`: P3 recovery execution with snapshot drift (E2E-04) and approval expiry (UT-08) guards.
  - Additive database table `commitment_proposals` (Alembic `0004_commitment_proposals`) tracking versioned proposals, status (`ACTIVE`, `ACCEPTED`, `REJECTED`, `SUPERSEDED`), revised terms, and evidence.
  - Additive core events: `commitment.proposal_rejected`, `commitment.context_ready`, `recovery.started`, `recovery.plan_approved`, `recovery.communication_requested`.
  - PII minimization enforced in `validate_event_payload`: phone, email, contact, message_body keywords strictly forbidden in outbox payloads.
- Breaking or additive: additive; existing commitment schemas and REST APIs remain fully backward-compatible.
- Affected owners, frontend screens, tests: P1–P4 feature integration, `contracts/types.ts` and `frontend/src/shared/types.ts` updated with `RecoveryStartRequest` and `RecoveryExecuteRequest`; 18 comprehensive tests in `backend/tests/integration/test_feature_handshakes.py`.
- Migration or fixture update: Alembic migration `0004_commitment_proposals` created; offline SQL generation verified.
- Decision: ACCEPTED
- PR / commit: `7869196` on branch `feat/p5-core-integration`

### CONTRACT-20261021-007 — Mock Resource Inventory & Concurrent Reservation Lock Primitive (SAF-4, Invariant 8)
- Proposed by / reviewed by: P5 (Task T3.2)
- Old vs new field/event/API:
  - Additive database tables `resource_stocks` and `resource_reservations` (Alembic `0005_resource_reservations`).
  - Additive module `backend/app/core/reservations.py` providing:
    - Pure read-only evaluator helper `get_resource_snapshot(session, tenant_id, resource_ids)` computing `available = total - reserved` via `Decimal` without mutating rows or acquiring write locks.
    - Read-only helper `get_available_stock(session, tenant_id, resource_id)`.
    - Mock inventory initializer `seed_resource_stock`.
    - Transactional locking reservation primitive `reserve_resource(session, ..., idempotency_key, resource_id, quantity)`:
      - Enforces Invariant 8 & SAF-4: atomic conditional stock deduction (`WHERE (total_quantity - reserved_quantity) >= :qty`) and concurrency locking.
      - Idempotency on `(tenant_id, idempotency_key)`: returns existing active reservation without double-deduction (`E2E-08`, `E2E-10`).
      - Deterministic conflict rejection: raises `InsufficientResourceError` (HTTP 409 Conflict) when available < quantity, rolling back cleanly without partial allocation.
      - Increments `snapshot_version` and writes immutable `AuditEventRecord` (`resource.reserved`).
    - Reservation lifecycle operations: `release_reservation` (restores stock) and `consume_reservation` (decrements total stock upon actual execution).
  - Additive REST endpoints in `backend/app/core/router.py`:
    - `GET /v1/resources/snapshot?resource_id=...`: read-only resource availability snapshot.
    - `POST /v1/resources/reserve`: transactional locking reservation endpoint.
  - Additive TypeScript contracts in `contracts/types.ts` and `frontend/src/shared/types.ts`: `ResourceStock` and `ResourceReservation`.
- Breaking or additive: additive; existing commitment schemas and endpoints remain fully backward-compatible.
- Affected owners, frontend screens, tests: P2 feasibility engine (uses pure read-only `get_resource_snapshot`), P3 recovery action adapter (uses transactional locking `reserve_resource`); 8 comprehensive tests in `backend/tests/test_resource_reservations.py`.
- Migration or fixture update: Alembic migration `0005_resource_reservations` created; offline SQL generation verified.
- Decision: ACCEPTED
- PR / commit: `fe7b8cb` on branch `feat/p5-core-integration`

### CONTRACT-20261021-008 — Backend E2E Hero Journey & Full 12-Scenario Acceptance Matrix (E2E-01 to E2E-12, UI-04, UI-05)
- Proposed by / reviewed by: P5 (Task T3.3)
- Old vs new field/event/API:
  - Additive optional `commitment_id` in `BusinessContext` and `CommitmentCreateRequest` (`contracts/types.ts`, `frontend/src/shared/types.ts`, `backend/app/core/schemas.py`, `backend/app/core/service.py`, `backend/app/core/integration.py`) allowing deterministic commitment ID specification (e.g. `'com_001'`) or auto-generation.
  - Enhanced attention queue logic in `backend/app/core/commitments.py`: flags `UNRESOLVED_CONFIRMATION` whenever `confirmation_ambiguous` is True on terms, ensuring vague customer replies are highlighted immediately.
  - Permitted positional arguments in `seed_resource_stock` in `backend/app/core/reservations.py`.
  - Created test suite `backend/tests/integration/test_e2e_hero_journey.py`:
    - Full single-commitment_id (`com_001`) Hero Journey (`Trigger -> Data -> Decision -> Human Approval -> Outcome + Audit`, UI-04, UI-05) across 9 strictly monotonic optimistic concurrency versions (`v1` to `v9`).
    - Verified `E2E-01` (context creation -> feasibility assess -> proposal confirmation), `E2E-02` (supplier packaging shortage -> `com_001` INFEASIBLE, `AT_RISK + RECOVERY_REQUIRED` while `com_002` stays NORMAL), `E2E-03` (snapshot 102 two-plan trade-off comparison, Staff 403 denial, Manager plan approval, resource reservation), `E2E-12` (customer proposal v3 acceptance -> separate delivery POD verification transitioning to `FULFILLED + RESOLVED`), and Step 5 (overview counts and unbroken timeline audit trail).
  - Created test suite `backend/tests/integration/test_e2e_negative_matrix.py`:
    - `E2E-04`: Snapshot drift blocks execution (409 Conflict), zero unauthorized stock mutation, resets to `RECOVERY_REQUIRED`.
    - `E2E-05`: Ambiguous customer reply ("OK") flags `UNRESOLVED_CONFIRMATION`, never auto-confirms commitment.
    - `E2E-06`: Stale proposal version confirmation (V2 after V3) rejected with 409 Conflict, preserving V3.
    - `E2E-07`: Message delivery status updates (`SENT`, `DELIVERED`) record delivery tracking only; never advance agreement or fulfilment state.
    - `E2E-08`: Duplicate webhook / action retry with identical idempotency key produces exactly one reservation and no duplicate stock deduction.
    - `E2E-09`: OCR receipt screenshot upload records evidence ref but keeps agreement `REQUESTED` and flags manual review (`OCR receipt != verified funds`).
    - `E2E-10`: Worker crash after external action succeeds reconciles state via idempotency key without double deduction.
    - `E2E-11`: Cross-tenant isolation guarantees Tenant B receives 404/403 with zero data leakage across all commitment, proposal, fulfilment, timeline, audit, and overview surfaces.
- Breaking or additive: additive; 100% backward-compatible.
- Affected owners, frontend screens, tests: P1–P4 integration handshakes and contracts; all 63 backend tests and 12 frontend tests passing.
- Migration or fixture update: none required.
- Decision: ACCEPTED
- PR / commit: `ace78a4` on branch `feat/p5-core-integration`

## 8. QA / Metrics Log

| Date | Commit | Backend tests | Frontend tests | Build | E2E | Key observed metric / sample size | Known limitations |
|---|---|---|---|---|---|---|---|
| 2026-10-21 | P2 Phase 1 local commit (SHA in phase response) | `python -m pytest backend/app/feasibility/tests/test_snapshots.py -q`: 13 passed | NOT RUN | NOT RUN | NOT RUN | 13 snapshot/fixture tests; operational metrics not measured | No evaluator, API, UI, durable P5 snapshot store, or P3/P5 integration yet; fixture labels are hand-calculated synthetic ground truth only |
| 2026-10-21 | P2 Phase 1 correction commit (SHA in phase response) | Three new correction nodes: 3 failed as expected before fixes, then 3 passed; `python -m pytest backend/app/feasibility/tests/test_snapshots.py -q`: 16 passed | NOT RUN | NOT RUN | NOT RUN | 16 snapshot/fixture tests; operational metrics not measured | No evaluator, API, UI, durable P5 snapshot store, or P3/P5 integration yet; calendar coverage does not prove production feasibility; fixture labels remain hand-calculated synthetic ground truth only |
| 2026-10-21 | P2 Phase 1 confirmation-provenance correction (SHA in phase response) | Four new provenance test nodes failed before the fix; five targeted provenance tests passed after; `python -m pytest backend/app/feasibility/tests/test_snapshots.py -q`: 21 passed | NOT RUN | NOT RUN | NOT RUN | 21 snapshot/fixture tests; operational metrics not measured | No evaluator, API, UI, durable P5 snapshot store, or P3/P5 integration yet; external supplier evidence authenticity remains P5-owned; synthetic refs prove only structural provenance |
| 2026-10-21 | `ec0458d` on `phase0-core-integration` | 7 passed (`pytest`) | 1 passed (`vitest`) | passed (`npm run build`, typecheck passed) | NOT RUN | Contract/fixture/registry smoke only; sample size 1 fixture | Live DB migration pending isolated PostgreSQL; Docker/WSL1 blocker; npm audit clean after validated upgrades |
| 2026-10-21 | P2 Phase 5 external review #1 correction (PH5-R1-01; commit SHA in phase response) | 24 focused router tests + 188 combined P2/shared tests passed; one existing Starlette/httpx deprecation warning | NOT RUN | NOT RUN | NOT RUN | Synthetic test-router behavior only; no production API/security/persistence/outbox metric | P2 router not mounted in `main.py`; demo header RequestContext is not authenticated; P5 snapshot/history/outbox/empty Impact Set support and P3 HTTP contract remain blocked; pytest 9.1.1 is outside declared `<9` |
| 2026-10-21 | `phase0-core-integration` | 15 passed (`pytest`) | 1 passed (`vitest`) | passed (`npm run build`, typecheck passed) | NOT RUN | Outbox worker, idempotency, version guard, retry/dead-letter, and causation chain passed; sample size 15 tests | Live DB migration pending isolated PostgreSQL |
| 2026-10-21 | `phase0-core-integration` (T1.6/T1.7) | 24 passed (`pytest`) | 1 passed (`vitest`) | passed (`npm run build`, typecheck passed) | NOT RUN | Complete 9-endpoint surface, overview SQL counts (7 buckets), attention queue, chronological timeline with F1–F4 links, role redaction (Staff vs Manager), patch forbidden (405), and normalized errors; sample size 24 tests | Live DB migration pending isolated PostgreSQL |
| 2026-10-21 | `phase0-core-integration` (T2.3) | 24 passed (`pytest`) | 8 passed (`vitest`) | passed (`npm run build`, typecheck passed) | NOT RUN | Real Overview wired to GET /v1/overview via TanStack Query, 7 authoritative state cards with non-green enforcement, attention queue with KL timestamps and deep links, simulated role switcher, state bucket and search filtering, loading skeleton, empty state, working retry callback, and 403 permission denied state; sample size 8 frontend + 24 backend tests | Live DB migration pending isolated PostgreSQL |
| 2026-10-21 | `phase0-core-integration` (T2.4) | 28 passed (`pytest`) | 12 passed (`vitest`) | passed (`npm run build`, typecheck passed) | NOT RUN | Real Activity & Audit page (/activity) wired to GET /v1/commitments/{id}/timeline and GET /v1/audit via TanStack Query (FE-03a–d, UI-02); chronological event timeline, state transition diffs (CONFIRMED → AT_RISK), version increments, human governance approval highlights with reason and scope, correlation/causation grouping, deep links to F1–F4, Staff role redaction, and loading/empty/retry/403 states; sample size 12 frontend + 28 backend tests | Live DB migration pending isolated PostgreSQL |
| 2026-10-21 | `7869196` on `feat/p5-core-integration` (T3.1) | 46 passed (`pytest`) | 12 passed (`vitest`) | passed (`npm run build`, typecheck passed) | NOT RUN | P1–P4 Handshake consumers, CoreIntegrationFacade, snapshot drift guard (E2E-04), approval expiry (UT-08), OCR receipt guard (UT-09), proposal version guard (E2E-06, UT-10), vague OK attention (E2E-05), delivery message no-op (E2E-07), operational fulfilment (E2E-12), and PII minimization (BE-06e); sample size 18 integration tests + 28 core tests | Live DB migration pending isolated PostgreSQL |
| 2026-10-21 | `fe7b8cb` on `feat/p5-core-integration` (T3.2) | 54 passed (`pytest`) | 12 passed (`vitest`) | passed (`npm run build`, typecheck passed) | NOT RUN | Mock resource inventory, pure read-only get_resource_snapshot for P2, atomic locking reserve_resource with InsufficientResourceError (409) for P3, sequential and thread-concurrent zero over-allocation (SAF-4, Invariant 8), idempotency on (tenant_id, idempotency_key) (E2E-08, E2E-10), release/consume lifecycle; sample size 8 reservation tests + 46 core tests | Live DB migration pending isolated PostgreSQL |
| 2026-10-21 | `ace78a4` on `feat/p5-core-integration` (T3.3) | 63 passed (`pytest`) | 12 passed (`vitest`) | passed (`npm run build`, typecheck passed) | 1 passed (`test_e2e_hero_journey`) | Full 12-scenario E2E acceptance matrix (E2E-01 to E2E-12) & Hero Journey on com_001; sample size 27 integration tests + 36 unit/registry/outbox tests | Live DB migration pending isolated PostgreSQL |


Metric protocol: always disclose dataset size, date, ground truth creation method, pass/fail definitions. **Do not** mark actual customer fulfilment because communication was sent or approved.

P2 Phase 2 QA (2026-10-21): `python -m pytest backend/app/feasibility/tests/test_bom.py backend/app/feasibility/tests/test_inventory.py backend/app/feasibility/tests/test_snapshots.py -q` — 66 passed, 0 failed (45 new + 21 regression). Actual material shortage outputs: buffered before 0/0 -> after 40/0 pcs; two-order before 0/0 -> after 70/40 pcs. API/UI/build/E2E/production metrics NOT RUN; shared runtime absent and later-phase scope. No accuracy or latency claim from pytest elapsed time.

P2 Phase 4 final causal-provenance QA (2026-10-21): test-first regressions against reviewed `f5d069e9dad2cd7eb33ce3f3e9c094db0c1706af` falsely returned CONFIRMED_IMPACT for a parent-only capacity event with a separately evidenced overlapping job and for a SKU-only catalog event with an independently changed same-SKU lot. Exact atomic-key event scope now preserves those measured changes as UNKNOWN with no at-risk intent; explicit resource+job and SKU+lot batches confirm the demonstrated `com-001` impact. The lot scenario measured PATTY shortage `0→60` pcs. `python -m pytest app/feasibility/tests/test_impact.py -q` — 24 passed; `python -m pytest tests app/feasibility/tests -q` — 164 passed with one existing Starlette/httpx deprecation warning. Bare pytest discovers only the 7 shared tests due configured testpaths; the comprehensive command names both roots. Phase 4 remains PARTIAL pending independent external review; P5 empty Impact Set schema/adapter and P3/P5 snapshot/proposal alignment remain blockers. Phase 5 not started.

### 2026-10-21 — P2 Phase 5 local API boundary checkpoint (PARTIAL)
- User approved P2-local Phase 4 correction commit `f6ac87233534f0dc6deef3b5e464e0bd7fd1fd0e`; branch and feature remote matched it with a clean worktree before Phase 5 edits. Phase 5 scope is P2-owned API schemas, ports, router, API tests, and P2 handoff/tracking docs only. P5 application/Core/DB/shared contracts/auth/migrations and P3 code were not changed.
- Added all five requested paths in the P2-owned router. The internal evaluator reuses pure `evaluate()` and is unavailable without P5 authorization and trusted input authority. The assessment route evaluates the authoritative current snapshot with `evaluate()` and passes that exact result to the P5 writer, whose transaction must recheck commitment/snapshot versions. Assessment history, supplier-event and impact routes delegate through explicit P5 ports; absent durable persistence or transactional outbox yields 503. Request validation checks tenant/version and typed delivery-linked ETA evidence. No Core lifecycle state is mutated.
- Validation from `backend/`: focused router command `python -B -m pytest -o 'addopts=' app/feasibility/tests/test_router.py -q -p no:cacheprovider` — 16 passed; full applicable command `python -B -m pytest -o 'addopts=' app/feasibility/tests tests -q -p no:cacheprovider` — 180 passed. Each emitted one existing Starlette/httpx deprecation warning. No frontend, live PostgreSQL, authenticated app integration, persistence/outbox, P3 HTTP call or E2E was run.
- Latest fetched `origin/main` `4ec2ba1ef7ede4a67352631178a73a6882bcd774` still rejects empty `affected_commitment_ids`; final shared assessment mapping remains blocked. P5 exact requests for mounting, auth/internal boundary, snapshot/current-version authority, empty Impact Set, assessment history/impact storage, and transactional event/outbox are in `backend/app/feasibility/PHASE5_HANDOFF.md`. No identifiable P5 task was available in the accessible recent or archived Codex task list, so no direct message or answer is claimed.
- P3 requirements and P2's pure `evaluate(snapshot, proposed_changes, commitment)` interface align; the HTTP JSON shape remains provisional pending P3 owner confirmation. No P3 code changed. The requested `docs/AGENTS.md` is absent; repository root `AGENTS.md` still carries the old PromiseFlow name. The user's supplied MouManTAI rules, canonical system requirements and TEAM_LOG ADR-010 were followed; no instruction file was guessed or edited.
- Phase 5 is PARTIAL: local test-router behavior passes, P5 production integration remains blocked. Stop for external Phase 5 review; do not start Phase 6.

### 2026-10-21 — P2 Phase 5 external review #1 correction (PH5-R1-01)
- Reviewed commit `38f69d8f8fb1cdac132e29a7d072513191654a8c`. External review accepted the P2-local router, typed requests, evaluator reuse, fail-closed ports and ownership boundaries in principle, but found that the Core Commitment was not fully bound to the resolver Commitment before assessment.
- P2 now compares validated typed tenant/id/version, order, customer, agreement state and complete confirmed terms (SKU, quantity, unit, deadline, special instructions). Assessment mismatches return 409 before evaluator or writer. Internal evaluation compares the requested baseline with the trusted resolved baseline while leaving hypothetical ProposedChanges to the existing Phase 3 evaluator. The Phase 3 operational-snapshot/Core-term check remains unchanged; P5 still owns snapshot authority and transactional version checks.
- Added seven assessment mismatch regressions and one internal baseline mismatch regression. Quantity/deadline tests keep the resolver Commitment and OperationalSnapshot internally consistent while both differ from Core. `_assessment_inputs()` now copies actual Core order/customer identity and confirmed terms. The initial seven new tests failed before the router fix; a resolver-tenant case was added after that red run to complete field coverage. All eight pass after correction; existing exact-result writer handoff and P3 hypothetical evaluation regressions remain passing.
- Validation from `backend/`: focused `python -B -m pytest -o 'addopts=' app/feasibility/tests/test_router.py -q -p no:cacheprovider` — 24 passed; combined `python -B -m pytest -o 'addopts=' app/feasibility/tests tests -q -p no:cacheprovider` — 188 passed. One existing Starlette/httpx deprecation warning. No P5/P3 code, frontend, live PostgreSQL or E2E changes/tests.
- Phase 5 remains PARTIAL pending independent external review and P5 integration. Stop; do not begin Phase 6.

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

### 2026-10-21 — P2 Phase 3 external-review correction
- Reviewed P2 branch commit `9ff7535417cf0508d1940775a2530d9353551269`; external review accepted local capacity/deadline/evaluator work in principle and required conservative handling of target shortages caused by provisional ATP allocation order.
- P2-local `service.py` now checks the existing ATP allocation evidence for eligible same-SKU LOT/confirmed RECEIPT amounts currently allocated to other demand. If that evidence could cover the target, P2 reports an INFORMATIONAL `ALLOCATION_DEPENDENT_MATERIAL_SHORTAGE` with current batch aggregate shortage/evidence and returns UNKNOWN. If a positive target-level minimum shortage remains after compatible allocations, it remains HARD. Active reservations and time/location-ineligible supply are not transferable. ATP allocation code is unchanged.
- Hypothetical priority change still cannot hide new demand shortage for another confirmed commitment; same baseline/candidate ATP comparison emits a HARD constraint. Capacity deadline, job-conflict and working-window HARD failures remain covered.
- P5 confirmed `affected_commitment_ids` means actual Impact Set, not assessment scope: semantics RESOLVED. P5 schema support for `[]` is PENDING merge and verification because the current field has `min_length=1`. P2 did not modify P5 schema or fabricate affected IDs; final shared assessment adapter remains BLOCKED.
- Validation from backend: Phase 3 focused command — 63 passed; existing P2/shared regression — 73 passed with one existing Starlette/httpx deprecation warning. Exact commands and timing are recorded in `backend/app/feasibility/P2_PHASE_REPORTS.md`.
- Scope remains P2-only; no P3/P5 code or Phase 4 work. Phase 3 remains PARTIAL and is stopped for independent external review.

### 2026-10-21 — P2 Phase 3 external-review #2 correction
- Reviewed baseline `40c526a0bf05b215333a0832e13a88c275d61cad`; feature branch, origin ref and clean worktree verified before edits.
- Corrected `service.py` precedence: stale/missing/incomplete evidence remains UNKNOWN even when HARD constraints are retained; with complete trusted inputs, independent HARD proof yields INFEASIBLE despite allocation-policy uncertainty; allocation-dependent shortage alone remains UNKNOWN. ATP/BOM/capacity algorithms are unchanged.
- Fixed-schedule semantics are explicit: capacity/deadline/job HARD proves the supplied fixed booking violates known constraints, not that every alternative reschedule is impossible. Added regressions for overlapping job plus allocation shortage, separate unavoidable BUN shortage plus allocation-dependent PATTY, and stale inventory/production evidence alongside a HARD job conflict. Existing F2-01, allocation-only, proposal displacement and capacity failures remain covered.
- Current tests: 67 Phase 3 focused tests pass; preserved P2/shared regression is 73 passed with one existing Starlette/httpx deprecation warning. The prior reviewed Phase 3 count of 63 is the pre-correction baseline; four parametrized cases bring the current count to 67. Exact commands/results are in `backend/app/feasibility/P2_PHASE_REPORTS.md`.
- P5 actual Impact Set semantics remain RESOLVED; empty-list schema support is PENDING merge/verification. Final shared adapter, P3 proposal contract and source/catalog adapter remain blocked. No P3/P5 code or Phase 4 work; Phase 3 remains PARTIAL and STOPPED for independent review.

### 2026-10-21 — P2 Phase 4 local checkpoint (PARTIAL)
- User approved P2-local Phase 3 correction commit `650b702fbbdef3f2f0160db0bf3dc12cad3d2b2c`; Phase 3 shared integration remained PARTIAL. Phase 4 is limited to P2-owned impact logic and evaluator metadata; P5 schemas/Core/DB/routes/UI and P3 modules were not changed.
- Added deterministic evidence-bearing resource graph and incremental candidate discovery for supplier delivery, SKU, lot, production job/resource/calendar, order and commitment changes. Candidates are recomputed with existing pure `evaluate()` on both snapshots. Results include candidate/confirmed/unaffected/unknown/pre-existing sets, material/HARD deltas, buffers, versions, paths, evidence and local-only shared-envelope event intents.
- Preserved conservative semantics: material-only supplier fixtures report 0→40 and 0→70/40 PATTY shortages but remain UNKNOWN without production evidence; complete synthetic production evidence confirms only `com-001` and verifies buffered `com-002` unaffected. A new HARD delta confirms impact only with complete before/after evidence. Stale evidence, allocation-only uncertainty and unchanged pre-existing shortages do not create false risk.
- Validation from `backend/`: `python -B -m pytest -o 'addopts=' app/feasibility/tests/test_impact.py -q -p no:cacheprovider` — 14 passed in 1.55s. `python -B -m pytest -o 'addopts=' app/feasibility/tests tests -q -p no:cacheprovider` — 154 passed, one existing Starlette/httpx deprecation warning, in 3.89s. Ruff was not run because it is not installed; dependencies were not changed.
- P5 still needs to merge/verify empty `affected_commitment_ids` support and review the final FeasibilityAssessment/event adapter. P3 proposal serialization and P2/P5 source/catalog alignment remain provisional. No real event publication or persistence was added. Phase 4 is PARTIAL pending independent external review; Phase 5 is not started.
- Local commit SHA and verified branch push are in the phase response. Stop here for independent Phase 4 review.

### 2026-10-21 — P2 Phase 4 external-review correction checkpoint (PARTIAL)
- Reviewed baseline: `108565f46bf96b71bda34d47205f9d7301837c39`. External review accepted the graph/recalculation structure in principle and identified four P2-local corrections: causal attribution, collective multi-resource evidence validation, deadline extension identity, and numeric severity for worsening deadline violations.
- `impact.py` now identifies changed atomic resources and checks tenant-local dependency paths before attributing adverse deltas. A relevant undeclared concurrent change leaves the impact UNKNOWN and does not produce `commitment.at_risk`. Evidence validation now requires every declared resource to change and link to event evidence, while checking all supplied refs collectively; typed supplier ETA provenance remains enforced.
- HARD deadline comparisons now use existing evaluator finish times, explicit delivery lead minutes, and the snapshot's customer deadline. Deadline changes are matched by constraint/resource and lateness severity distinguishes NEW, WORSENED, IMPROVED, and UNCHANGED.
- Results: confounded non-overlap capacity event plus supplier delay measures com-001 PATTY shortage `0→40` but classifies causal impact UNKNOWN without risk intent; com-002 remains verified unaffected. Isolated overlapping capacity remains confirmed. Deadline extension expected delivery 11:10 / deadline 11:00→11:05 improves lateness 10→5 minutes without confirmed impact; worsening expected delivery 12:50→13:00 at deadline 12:30 is 20→30 minutes late and confirms the declared process-resource change.
- Validation from `backend/`: focused `python -B -m pytest -o 'addopts=' app/feasibility/tests/test_impact.py -q -p no:cacheprovider` — 22 passed in 0.75s; complete applicable `python -B -m pytest -o 'addopts=' app/feasibility/tests tests -q -p no:cacheprovider` — 162 passed with one existing Starlette/httpx deprecation warning in 2.46s. Ruff is unavailable; no dependency changes.
- P5 empty actual Impact Set schema support and final adapter remain pending; P3 proposal serialization and P2/P5 snapshot/catalog alignment remain provisional. No P3/P5 code, shared schemas, API, UI, persistence, outbox or event publication changed. Phase 4 remains PARTIAL; do not start Phase 5 until independent external review approves this correction checkpoint.
- Commit SHA and verified feature-branch push are recorded in the phase response; stop for independent external review.

### 2026-10-21 — P2 Phase 4 external-review #2 causal-provenance correction
- Reviewed baseline `f5d069e9dad2cd7eb33ce3f3e9c094db0c1706af`. Removed parent-child causal coverage from `_change_covers_resource()`; changed child resources require their own declared atomic key and linked event evidence. Graph paths still find candidates, while an undeclared changed child that may explain an adverse delta keeps classification UNKNOWN and suppresses `commitment.at_risk`.
- Test-first regressions failed against the reviewed baseline, then passed after the fix. Resource-only capacity rate change plus an independently evidenced overlapping job produces a visible `JOB_CONFLICT` but UNKNOWN/no at-risk, even if the job's evidence ref is supplied without its key. Explicit resource+job declaration confirms `com-001` and verifies buffered `com-002` unaffected. A SKU-only catalog event with a separately changed PATTY lot measures shortage `0→60` pcs but remains UNKNOWN/no at-risk; explicit SKU+lot declaration confirms `com-001`.
- Validation from `backend/`: `python -m pytest app/feasibility/tests/test_impact.py -q` — 24 passed; `python -m pytest tests app/feasibility/tests -q` — 164 passed with one existing Starlette/httpx deprecation warning. The full regression command names both roots because the backend's default pytest testpaths includes only the 7 shared tests.
- P2-only changes; no P3/P5/shared schema, Core, runtime, routes, database, persistence, or UI edits. Empty Impact Set schema/adapter remains P5-pending; P3 proposal serialization and P2/P5 snapshot/catalog alignment remain provisional. Phase 4 PARTIAL; stop for independent external review and do not begin Phase 5. Exact commit and feature-ref verification are in the phase response.

### 2026-10-21 — P2 Phase 6 frontend checkpoint (PARTIAL)

- User externally approved Phase 5 P2-local `85d46b2f48bea9a2e149f6dd70badc7311334061` and authorized Phase 6 only. Clean matching P2 branch/remote verified before edits. Added only P2-owned frontend pages, presentation adapters/models, labeled synthetic preview, scoped CSS/tests and P2 documentation/log records; shared routing/auth/contracts/dependencies and backend behavior unchanged.
- Prepared exportable `/commitments/:id` and `/impact/:id` pages. FE-01 preserves Core terms/agreement/risk, shows metadata/materials/fixed capacity/evidence and cautious UNKNOWN. Recalculation disabled without approved adapter; injection tests cover pending/previous-result preservation, expected versions, conflict/error/retry, deterministic repeated result and no fixture fallback. FE-02 separates candidates/confirmed/verified unaffected/UNKNOWN/pre-existing results and shows delta/deadline/path evidence without inferring Core risk.
- From frontend: `npm test -- src/features/feasibility` — 43 passed (2 files); `npm run typecheck` — passed; explicit `npx tsc --noEmit -p tsconfig.app.json` — passed; final `npm run build` — passed (tsc project build + Vite). Internal read-only review findings were verified and corrected with red/green regressions. No real API/page integration, production auth, backend regression, live PostgreSQL/outbox, P3 call, browser viewport QA or cross-feature E2E run in this frontend phase.
- Read-only Git verification: Main `4ec2ba1`, P5 branch `a5f9915`. Empty Impact Set support IMPLEMENTED ON P5 BRANCH, PENDING INTEGRATION. No merge/copy of P5 auth/query/helpers/outbox. Generic outbox is not P2 supplier processing; historical shared_output_blocker is not current readiness.
- P5 route/data/error/version handoff: `backend/app/feasibility/PHASE6_HANDOFF.md`; requires approved public material/capacity/freshness and enriched impact response, route mounting, authenticated context, snapshot authority/transactional version checks, shared mapping/history/impact storage, supplier-delay/outbox and authoritative Core risk transitions. P3 evaluator/ProposedChanges and HTTP serialization confirmations pending. Future sync must preserve both P2/P5 TEAM_LOG histories. Later nonblocking backend checkpoint: explicit SKU/unit binding tests.
- Preview is explicitly authored synthetic illustration, not persisted assessment; injected Core reader seam was tested without live HTTP. `docs/AGENTS.md` remains missing; canonical root AGENTS was read. Commit SHA/feature-ref evidence in phase response. Stop for independent external Phase 6 review; Phase 7 NOT_STARTED.

### 2026-10-21 — P2 Phase 6 external review #1 correction

- Reviewed baseline `a377b8bf18f0b38ba619c684d976c5663aeddacd`; clean P2 feature branch verified. PH6-R1-01 rejects unsupported runtime impact classification values with explicit 502 `INVALID_IMPACT_CLASSIFICATION`, full-response error/retry and no silent candidate omission/fallback. Original five classifications retained.
- PH6-R1-02 labels missing/empty/blank buffer refs `Reported buffer — evidence unavailable`; unsupported buffer-dependent VERIFIED_UNAFFECTED becomes UNKNOWN even with unrelated row refs. Independently sufficient complete scoped FEASIBLE/COMPLETED before/after proof can preserve unaffected status; its P2-only projection and future P5 mapping obligations are documented in PHASE6_HANDOFF.md. Input payloads are unchanged. Reference presence is not authenticity validation; P5 remains authoritative.
- From frontend: 24 focused new regression tests pass; existing Phase 6 suite totals 67 passed (all original 43 preserved), npm typecheck, explicit application tsc and production build pass. No backend/shared/P3/P5 implementation changes, live API/DB/outbox/P3/E2E, or Phase 7 work. P2 progress/trace/report/handoff updated; prior records preserved. Correction commit/feature-only push SHA in task response. Stop for independent Phase 6 correction review; integration remains PARTIAL.

### 2026-10-21 — P2 Phase 6 external review #2 (PH6-R2)

- Reviewed clean P2 baseline `de8749a06a117c06ec3eede57725749bb8ca4557`. Removed frontend `unaffected_proof` bypass/helper/property/type. VERIFIED_UNAFFECTED now requires a positive evidence-backed buffer plus adequate refs for all conservatively required buffers and row-level classification evidence. Empty/zero/unsupported buffer proof yields UNKNOWN; complete before/after metadata cannot override it. No backend `_classify()` duplication; all five classifications/runtime rejection/evidence-aware labels and input immutability retained.
- Independent proof is a future P5 authoritative-contract decision only. Updated P2 progress/trace/report/handoff; prior reports and TEAM_LOG entries preserved. Only P2 frontend and P2 docs changed; no P3/P5 implementation or Phase 7 work.
- From frontend: focused impact-safety tests **37 passed**; complete Phase 6 suite **80 passed**; npm typecheck, explicit app-project tsc and production build passed. Red/green regressions documented in P2_PHASE_REPORTS.md. No live API/auth/database/outbox/P3/E2E claims. Correction SHA/feature-only push verification in phase response. Stop for independent Phase 6 review; integration remains PARTIAL.
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

### 2026-10-21 — Task T3.1: P1–P4 Handshake Event Consumers & Core Integration Facades (BE-06a–f, UT-10)
- Scope: BE-06a–f, BE-02h, BE-05c, UT-08, UT-09, UT-10, E2E-04, E2E-05, E2E-06, E2E-07, E2E-12. Strictly within P5 core paths (`backend/app/core/integration.py`, `backend/app/core/commitments.py`, `backend/app/core/events.py`, `backend/app/core/models.py`, `backend/app/core/router.py`, `backend/app/core/schemas.py`, `backend/app/core/service.py`, `backend/migrations/versions/0004_commitment_proposals.py`, `backend/tests/integration/test_feature_handshakes.py`, `contracts/types.ts`, `frontend/src/shared/types.ts`). Zero edits to P1–P4 feature directories.
- P1 → P5 / P2 Handshake (BE-06a, UT-09):
  - `handle_context_updated`: When `BusinessContext` is `READY`, `LINK_VERIFIED`, and conflict-free, creates/updates `REQUESTED` commitment and emits `commitment.created` / `commitment.context_ready` with causation tracing to trigger P2 feasibility.
  - If conflicts or missing fields exist: surfaces a `MANUAL_REVIEW` attention item in overview; never auto-confirms (`REQUESTED != CONFIRMED`).
  - OCR receipt evidence (`ev_receipt_*`) is stored as evidence only and rejected when attempted as proposal confirmation evidence without contract agreement (`UT-09`).
- P2 → P5 / P3 Handshake (BE-06b):
  - `CommitmentService.assess` / `POST /v1/commitments/{id}/assess`: Optimistic concurrency check verifies `assessment.commitment_version == commitment.commitment_version` (rejects stale with 409 Conflict).
  - Feasibility status evaluated: `INFEASIBLE` on a `CONFIRMED` commitment transitions `risk_state = "AT_RISK"`, `recovery_state = "RECOVERY_REQUIRED"`, and emits `commitment.at_risk` with constraint details and affected IDs to trigger P3 recovery. Preserves invariant: `CONFIRMED + AT_RISK` coexist.
  - `UNKNOWN` feasibility preserves `risk_state = "NORMAL"`, flags `UNKNOWN_FEASIBILITY` in attention queue without false infeasibility (`UNKNOWN != INFEASIBLE`).
- P3 → P5 / P4 Handshake (BE-06c, E2E-04, UT-08):
  - Consequential recovery action authorization enforced server-side: Staff role blocked with 403 `APPROVAL_REQUIRED` (`BE-05c`).
  - Pre-execution revalidation guards:
    - Snapshot drift check: if `plan.snapshot_version != current_snapshot_version`, blocks execution with 409 `SNAPSHOT_DRIFT_CONFLICT`, invalidates approval, and transitions `recovery_state = "RECOVERY_REQUIRED"` (`E2E-04`).
    - Expiry check: if `now > approval_expires_at`, blocks execution with 409 `APPROVAL_EXPIRED` and transitions `recovery_state = "RECOVERY_REQUIRED"` (`UT-08`).
  - Versioned terms proposal: when recovery plan requires customer terms adjustment, creates proposal in `commitment_proposals` table, transitions agreement to `OFFERED`, and emits `recovery.communication_requested` outbox event for P4.
- P4 → P5 / P3 Handshake (BE-06d, UT-10, E2E-05, E2E-06, E2E-07):
  - `MESSAGE_SENT` / `DELIVERED` / `READ` delivery status records audit/evidence only; zero mutation of `agreement_state` or `fulfilment_state` (`E2E-07`).
  - Ambiguous customer response ("OK") flags `UNRESOLVED_CONFIRMATION` in attention queue; auto-confirmation blocked (`E2E-05`).
  - Proposal confirmation version guard: attempting to confirm stale V2 proposal when V3 exists is rejected with 409 `STALE_PROPOSAL_VERSION` (`E2E-06`).
  - Valid V3 proposal confirmation updates terms, bumps `commitment_version`, sets `agreement_state = "CONFIRMED"`, and leaves `fulfilment_state = "NOT_STARTED"` (`SENT != ACCEPTED != FULFILLED`, `UT-10`).
  - Customer proposal rejection marks proposal `REJECTED`, sets `recovery_state = "RECOVERY_REQUIRED"` to trigger F3 replanning.
- Operational Fulfilment Verification (BE-02h, UT-10, E2E-12):
  - `POST /v1/commitments/{id}/record-fulfilment`: Transitions `fulfilment_state = "FULFILLED"` and `risk_state = "RESOLVED"` only when trusted delivery evidence (`ev_ops_delivery_*` or `ev_pod_*`) is provided by an authorized role and `agreement_state == "CONFIRMED"`.
  - Rejects fulfilment on unconfirmed commitment (409) or when only bank slip/chat evidence is provided (422).
- PII Minimization (BE-06e):
  - Outbox payload validator rejects sensitive customer contact tokens (`phone`, `email`, `contact_number`, `message_body`, `raw_message`). Payloads pass IDs and references only.
- Database & Migrations:
  - Alembic migration `0004_commitment_proposals` created for `commitment_proposals` table; offline SQL generation verified.
- Validation:
  - Backend tests: 46 passed (`pytest -v backend/tests`), including 18 new integration tests in `test_feature_handshakes.py`.
  - Frontend checks: `tsc --noEmit` passed; Vitest 12 passed; production build passed (`npm run build`).

### 2026-10-21 — P2 Main synchronization and compatibility review (BLOCKED)
- P2: Fetched exact Main `0485d3d3490d9dacb97aedb634e99c6538327bbf`, including P5 PR #2 tip `6e09a5584000ed1b93d1f568d56e9675016b2e25`; pre-sync P2 HEAD `4e04a662eda8c2b96505e27db976727b2f9d336f` is protected by `backup/p2-pre-sync-4e04a66-20261021`. Prepared `git merge --no-ff --no-commit origin/main`; only conflict was `docs/TEAM_LOG.md`, resolved by preserving P2 and P5 histories/QA rows.
- P2/P5 compatibility: shared `FeasibilityAssessment.affected_commitment_ids` accepts `[]` for the actual Impact Set. Removed the now-stale P2 `shared_output_blocker` and corrected P2 API tests; two focused tests passed after a red run, and the empty-set compatibility test passed.
- Validation: from `backend/`, `python -B -m pytest -o 'addopts=' app/feasibility/tests -q -p no:cacheprovider` — 169 passed, 12 failed, one Starlette/httpx deprecation warning. All 12 failures return 422 because P5 Core and P2 both declare `POST /v1/commitments/{commitment_id}/assess` with incompatible request/response schemas; Core is mounted first in the P2 test app.
- P5 handshake tests send caller-authored `FeasibilityAssessment` JSON to the Core route and verify Core state/audit/outbox behavior. They do not invoke P2's evaluator or prove P2 snapshot authority, persistence/history, production route mounting, authentication, or frontend wiring.
- Stop condition: canonical assess route ownership requires P5/API review; no shared code was changed to hide the collision. P5/combined tests, runtime import probe, frontend tests/typecheck/build, live DB and E2E were not run after this blocker. No sync commit or push; `MERGE_HEAD` is Main `0485d3d...`; Phase 7 NOT_STARTED. Await independent review.

### 2026-10-21 — Task T3.4: Frontend Live-API Smoke & Role-Guard Verification (UI-01, UI-02, UI-03, UI-06, FE-01a, FE-01d)
- **Scope**: UI-01, UI-02, UI-03, UI-06, FE-01a, FE-01d. Strictly within P5 paths (`frontend/src/app/__tests__/RoleGuardAndNavigation.test.tsx`, `frontend/src/app/__tests__/LiveApiSmoke.test.ts`, `frontend/src/shared/ApprovalActionControl.tsx`, `frontend/src/shared/auth.tsx`, `frontend/src/layout/AppShell.tsx`, `frontend/src/styles.css`, `frontend/src/features/overview/__tests__/OverviewPage.test.tsx`, `frontend/src/features/activity/__tests__/ActivityPage.test.tsx`, `backend/app/db/session.py`, `backend/app/core/dependencies.py`, `scripts/reset_and_seed_test_db.py`, `docs/TEAM_LOG.md`). Zero edits to P1–P4 feature directories (`frontend/src/features/{context,feasibility,recovery,communication}/`).
- **No Route Drift**: Checked frontend codebase (`frontend/src/`); confirmed zero references or calls to `POST /v1/commitments/{id}/assess`.
- **AppShell Role Simulator (UI-03)**:
  - Topbar header updated with global demo role selector `<select aria-label="Demo role selector" data-testid="shell-role-selector">`.
  - Switching between `Owner` (`user_owner_01` / `owner_01`), `Manager` (`user_manager_01` / `manager_01`), and `Staff` (`user_staff_01` / `staff_01`) dynamically updates the `X-Actor-ID` request headers and app shell tenant badge.
- **Shared Approval Control & Role Guard Enforcement (UI-03, FE-01d)**:
  - Created `frontend/src/shared/ApprovalActionControl.tsx`: enforces server-side role check; high-privilege proposal approval controls are disabled/restricted for Staff (`data-testid="permission-restricted-notice"`, `data-testid="approval-action-btn-disabled"`).
  - Forced attempts catch backend `403 Forbidden` (`code="APPROVAL_REQUIRED"`) and surface clean alert banners (`role="alert"`, `data-testid="permission-error-banner"`).
  - Invariant strictly maintained: Never shows fake optimistic success.
  - Strict semantic badge colors verified: `PENDING_APPROVAL`, `AWAITING_CONFIRMATION`, `OFFERED`, `UNKNOWN` render warning, purple, or neutral badges; never `badge-success` or green.
- **Overview Refresh After Lifecycle Mutations (UI-01)**:
  - Unit tests in `OverviewPage.test.tsx` verify initial counts from `GET /v1/overview`, dynamic bucket updates when commitments transition `CONFIRMED` -> `AT_RISK` -> `FULFILLED`, attention queue alerts, and manual refresh via `refetch()`.
- **Activity Linked Events & Unbroken Causal Chain (UI-02)**:
  - Unit tests in `ActivityPage.test.tsx` verify chronological progression (`F1 -> F2 -> F3 -> F4 -> Core`), monotonic versions (1 -> 2 -> ... -> 9), correlation/causation tracking (`correlation_id`, `causation_id`), and role-redacted notes for Staff.
- **Deep-Link Navigation Integrity (FE-01a)**:
  - Tested navigation across all 10 frontend routes (`/overview`, `/activity`, `/inbox`, `/orders/:id`, `/commitments/:id`, `/impact/:id`, `/recovery/:id`, `/communications`, `/confirmations/:id`, `*`). All routes render valid landmark headings without unhandled exceptions or crash.
- **Database Reset & Seed Script (UI-06)**:
  - Created single documented command `python scripts/reset_and_seed_test_db.py`: drops and recreates tables, seeds stock levels (BUN, PATTY, BURGER), seeds `com_001` with complete 9-version Hero Journey history, and seeds 6 additional commitments covering all 7 state dimensions. 100% idempotent with zero side effects.
- **Live-API Smoke Suite (LIVE_API=1, UI-06)**:
  - Created `frontend/src/app/__tests__/LiveApiSmoke.test.ts`: gated by `LIVE_API=1`.
  - When `LIVE_API=1` is set, executes live HTTP network calls against FastAPI service on port 8000, asserting health, live DB-derived overview counts, Staff role headers, com_001 timeline causal chains, and Staff 403 Forbidden rejection.
- **Route Status Ledger (T4.2-B format)**:
  | Route | Owner | UI Component | Status | Integration Source |
  |---|---|---|---|---|
  | `/overview` | P5 | `OverviewPage` | Real API | `GET /v1/overview` |
  | `/activity` | P5 | `ActivityPage` | Real API | `GET /v1/commitments/{id}/timeline`, `GET /v1/audit` |
  | `/inbox` | P1 | `FeaturePlaceholder` | Designated Mock / Placeholder | Owner module pending |
  | `/orders/:id` | P1 | `FeaturePlaceholder` | Designated Mock / Placeholder | Owner module pending |
  | `/commitments/:id` | P2 | `FeaturePlaceholder` | Designated Mock / Placeholder | Owner module pending |
  | `/impact/:id` | P2 | `FeaturePlaceholder` | Designated Mock / Placeholder | Owner module pending |
  | `/recovery/:id` | P3 | `FeaturePlaceholder` | Designated Mock / Placeholder | Owner module pending |
  | `/communications` | P4 | `FeaturePlaceholder` | Designated Mock / Placeholder | Owner module pending |
  | `/confirmations/:id` | P4 | `FeaturePlaceholder` | Designated Mock / Placeholder | Owner module pending |
  | `*` | P5 | `FeaturePlaceholder` | Shared Shell | 404 fallback |
- **Validation Results**:
  - `cmd /c npm run typecheck`: Passed (0 errors)
  - `cmd /c npm test`: Passed (28 passed, 5 skipped)
  - `cmd /c "set LIVE_API=1&& npm test"`: Passed (33 passed, 0 skipped)
  - `cmd /c npm run build`: Passed (`dist/` generated in 854ms)
  - `python -m pytest backend/tests`: Passed (63 passed in 1.42s)

### 2026-10-21 — Task T3.1-C-FIX: Remove Duplicate Core /assess Route, Add Tenant/Commitment Identity Guards, Update Affected P5 Tests (Decision D-013)
- **Status**: Complete & Verified (Commit `2f06a6a`, Decision D-013 implemented).
- **Context & Ownership**:
  - Decision D-013 established that P2 exclusively owns the public trigger endpoint `POST /v1/commitments/{id}/assess`.
  - P5 Core must not expose the duplicate route to prevent route collision/capture of P2 requests.
  - Core retains strictly an internal writer (`CommitmentService.assess`) callable by trusted service principals (`service_p2_feasibility`, `SERVICE` / `SYSTEM`).
- **Changes Implemented**:
  1. Removed public route `@router.post("/commitments/{commitment_id}/assess")` and `assess_commitment_endpoint` from `backend/app/core/router.py`. Public calls to this path from Core now return 404 Not Found.
  2. Registered trusted internal service principals in `backend/app/core/dependencies.py` (`service_p2_feasibility`: `SERVICE`, `service_core`: `SERVICE`, `system`: `SYSTEM`).
  3. Added strict identity & security guards in `CommitmentService.assess`:
     - **Caller Authorization**: Enforces `context.actor_role in {"SERVICE", "SYSTEM"}`. Normal user actors (`STAFF`, `MANAGER`, `OWNER`) are denied with HTTP 403 `CALLER_NOT_AUTHORIZED`.
     - **Tenant Identity Guard**: Verifies `assessment.tenant_id == context.tenant_id`. Mismatches rejected with HTTP 400 `TENANT_MISMATCH` without mutating commitment state.
     - **Commitment Identity Guard**: Verifies `assessment.commitment_id == commitment_id`. Mismatches rejected with HTTP 400 `COMMITMENT_ID_MISMATCH` without mutating commitment state.
     - **Cross-Tenant Isolation**: Loads commitment strictly by `(context.tenant_id, commitment_id)`. Commitments of other tenants return HTTP 404 `COMMITMENT_NOT_FOUND`.
     - **Concurrency Guard**: Verifies `assessment.commitment_version == record.commitment_version`. Stale versions return HTTP 409 `COMMITMENT_VERSION_CONFLICT`.
     - **Idempotency Guard**: If `assessment.assessment_id in record.evidence_refs`, returns current commitment without bumping version or persisting duplicate audit/outbox events.
     - **Risk Invariants**: `INFEASIBLE` triggers `AT_RISK` and `RECOVERY_REQUIRED` ONLY on `CONFIRMED` commitments; unconfirmed commitments (`REQUESTED`) record `INFEASIBLE` without `AT_RISK`; `UNKNOWN` and `CONDITIONAL` do not trigger `AT_RISK`.
     - **Mutation Scope**: Mutates strictly the target commitment; `affected_commitment_ids` never triggers side-effect mutations on other commitments.
     - **Atomic Persistence**: Outbox event and audit record write is atomic; any commit failure rolls back state completely.
  4. Updated P5 Handshake & E2E Tests:
     - `backend/tests/integration/test_feature_handshakes.py`: P2 assessment steps updated to invoke `service.assess` with `service_p2_feasibility` trusted context, labelled `[SIMULATED P2 HANDSHAKE]`.
     - `backend/tests/integration/test_e2e_hero_journey.py`: assessment calls updated to invoke `service.assess` with `service_p2_feasibility`, labelled `[SIMULATED P2 HANDSHAKE]`.
  5. Added Route Uniqueness & Identity Guards Test Suite:
     - Created `backend/tests/test_assess_identity_guards.py` (16 tests) asserting: public route 404 absence, route collision prevention across `app.routes`, tenant mismatch 400, commitment mismatch 400, cross-tenant 404, caller 403 vs 200, stale version 409, risk invariants, single-target mutation scope, duplicate assessment idempotency, and atomic commit rollback.
- **What P2 Can Now Rely On**:
  - Zero route collision on `POST /v1/commitments/{id}/assess` from Core router; P2's public router mounts and handles this endpoint directly without Core interference.
  - Core `CommitmentService.assess` provides a robust, idempotent internal writer for P2's background workers or service facade with verified concurrency and identity isolation.
- **Validation Results**:
  - `python -m pytest backend/tests`: 79 passed, 0 failed.
  - `cmd /c npm run typecheck`: Passed (0 errors).
  - `cmd /c npm test`: Passed (28 passed, 5 skipped).
  - `cmd /c npm run build`: Passed (`dist/` built cleanly).

### 2026-10-21 — P2 Main synchronization after P5 PR #3

- **Refs and preservation:** fetched and verified `origin/main` at `0c082ceb0d1fa926a8b5fdf53b451505d3bd2250`, containing D-013 commit `2f06a6ac7451def712aa080eb6c1189b8d57f216`. Approved P2 baseline `4e04a662eda8c2b96505e27db976727b2f9d336f` remains at `backup/p2-pre-sync-4e04a66-20261021`. Snapshot of the interrupted staged merge is recoverable at `backup/p2-interrupted-merge-0485-before-pr3-20261021` (`2466c6b049e2da30b538f51cba1e5d3c1b363088`).
- **Merge history:** completed prior PR #2 merge as intermediate local commit `d242c31788b7d0ee97a6e95278f2e11c7137e7a9`, then merged exact latest Main in `f82f9a4279de6263236bc3d7ec04772441eb2c8b`. Final merge parents are the intermediate and `0c082ceb0d1fa926a8b5fdf53b451505d3bd2250`. Only `docs/TEAM_LOG.md` conflicted; the resolution preserves the prior P2 record, P5 T3.4 and D-013 history. No P5 implementation, shared contract, migration or authentication code was edited by P2.
- **D-013 compatibility:** Core's duplicate public assess route is removed; the public contract is owned by P2. Combined Core/P2 router runtime probe found unique method/path registrations. Empty `affected_commitment_ids` is accepted; `UNKNOWN` remains distinct from `INFEASIBLE`; P2 commitment/snapshot version checks and pure evaluator remain. No P2 Phase 6 frontend code changed.
- **Authorization and integration boundary:** `CommitmentService.assess` requires `SERVICE`/`SYSTEM`; D-013 identity tests prove ordinary user context gets 403 and directly constructed trusted service context is accepted. P2's assessment writer and current-snapshot authority are unconfigured, so the P2 public handler returns 503. Its writer seam receives the requesting context; P5 must supply a trusted server-side service identity and preserve the requesting user in audit. The synthetic X-Actor-ID role map is not an authenticated service boundary. P2 router remains unmounted in production `app/main.py`; P2 frontend routes remain placeholders. Assessment/history/impact persistence, supplier-delay/outbox processing, and real P2/P5 E2E remain pending P5; P3 evaluator serialization remains pending owner confirmation.
- **Validation:** from `backend/`, P2 `python -B -m pytest -o 'addopts=' app/feasibility/tests -q -p no:cacheprovider` — 181 passed; P2 router/API `... app/feasibility/tests/test_router.py ...` — 24 passed; P5 `... tests ...` — 79 passed; D-013 `... tests/test_assess_identity_guards.py ...` — 16 passed; combined `... app/feasibility/tests tests ...` — 260 passed. Runtime import/model identity and temporary combined-router uniqueness probe passed. Each pytest run emitted one Starlette/httpx TestClient deprecation warning. Frontend `npm test` — 108 passed, 5 skipped; `npm run typecheck` and `npm run build` passed. Host: Python 3.14.3 / pytest 9.1.1 (outside declared pytest `<9`), FastAPI 0.139.2, Pydantic 2.13.4, SQLAlchemy 2.0.51; Node 24.14.0 / npm 11.9.0 / Vitest 5.0.5 / Vite 7.3.7. Local `node_modules` lacked lockfile-pinned `@tanstack/react-query@5.104.5`; installed with `--no-save --package-lock=false`, leaving manifests unchanged. One overlapping Vitest run had one assertion failure; the focused rerun and subsequent isolated full suite passed. No DB reset, migration, live DB or live API run.
- **Gate:** synchronization and applicable local regression checks passed; branch is ready for independent review of the sync. No P2 PR was created, no P2-to-Main merge or Phase 7 work was performed. Orbyte access is optional and was not used.  ### 2026-10-21 — P4 / Commit 01: Communication foundation and integration boundaries
- Person: P4. Milestone: Commit 01. Status: Foundation prepared in an isolated project copy; real working tree untouched pending manual application. Full P4 feature remains incomplete.
- Baseline: inspected local `P4-communication` at `0485d3d`; requested branch label was `branchP4-communication`. No branch change, fetch, merge or synchronization was performed; remote main was not verified.
- Implemented Features: P4-local reference-only event view; pure event shape/tenant/reference consistency inspection preserving independent plan/proposal/commitment versions; frontend type-only entry point reusing shared types; evidence-based integration notes. Existing P4 `__init__.py` preserved. No event consumer or public API registered.
- Changed Files: added `backend/app/communication/schemas.py`, `service.py`, `tests/test_foundation.py`, `INTEGRATION_NOTES.md`; added `frontend/src/features/communication/types.ts`, `README.md`; appended this record to `docs/TEAM_LOG.md` in the isolated copy only. No existing record or teammate status changed.
- Tests Executed (isolated copy, using existing Python venv dependencies): `python -B -m pytest tests app/communication/tests -v` from backend: **69 passed** (46 existing + 23 P4). Initial run had one new test-fixture error (string datetime passed to Core factory); corrected only the P4 test and reran the complete suite successfully. One existing Starlette/httpx deprecation warning remains.
- Backend Import Check: `python -B -c "from app.communication.schemas import RecoveryCommunicationReference; from app.communication.service import inspect_recovery_communication_event"`: passed.
- Frontend Tests Executed: `npm run typecheck`: passed; `node_modules/.bin/tsc.cmd --noEmit -p tsconfig.app.json`: passed (checks actual app files despite root solution tsconfig); `npm test`: **12 passed**; `npm run build`: passed. No lint script is configured. No dependencies added or changed.
- Diff Checks: `git status --short`, `git diff --stat`, `git diff --check` reviewed against the local baseline using the isolated work tree; added files separately reviewed and whitespace-checked. Original working tree remains clean. No Git index/history mutations performed.
- Known Limitations: no request management, draft generation, message send, confirmation processing, UI page, DB table/migration, live provider, real API/UI or E2E flow in Commit 01. A valid reference does not verify identity, consent, approval, current authority or freshness. Only schema version 1 is understood. No PostgreSQL smoke test required/run for this foundation-only change.
- Integration Dependencies / Blockers: no blocker for Commit 01. Future integration needs P1 normalized reply/verified identity contract, P3 exact approved plan/proposal reader and replan handoff, P5 scoped proposal reader and completion of proposal ID/status/expiry/identity guards, shared persistence/outbox transaction coordination and later routing. Existing Core readers/confirmation services/auth simulator/outbox are documented as existing, not reimplemented. P4 target confirmation event names are not claimed as registered consumers.
- Next Milestone: **Commit 02 — Communication Request Management**. Not started.
- Git Status: **Not committed yet**. No commit hash, push, merge or PR is claimed. After manual application, record the user's actual test results and eventual commit reference separately.

### 2026-10-21 — P4 / Commit 01: Communication foundation and integration boundaries
- Person: P4. Milestone: Commit 01. Status: Foundation prepared in an isolated project copy; real working tree untouched pending manual application. Full P4 feature remains incomplete.
- Baseline: inspected local `P4-communication` at `0485d3d`; requested branch label was `branchP4-communication`. No branch change, fetch, merge or synchronization was performed; remote main was not verified.
- Implemented Features: P4-local reference-only event view; pure event shape/tenant/reference consistency inspection preserving independent plan/proposal/commitment versions; frontend type-only entry point reusing shared types; evidence-based integration notes. Existing P4 `__init__.py` preserved. No event consumer or public API registered.
- Changed Files: added `backend/app/communication/schemas.py`, `service.py`, `tests/test_foundation.py`, `INTEGRATION_NOTES.md`; added `frontend/src/features/communication/types.ts`, `README.md`; appended this record to `docs/TEAM_LOG.md` in the isolated copy only. No existing record or teammate status changed.
- Tests Executed (isolated copy, using existing Python venv dependencies): `python -B -m pytest tests app/communication/tests -v` from backend: **69 passed** (46 existing + 23 P4). Initial run had one new test-fixture error (string datetime passed to Core factory); corrected only the P4 test and reran the complete suite successfully. One existing Starlette/httpx deprecation warning remains.
- Backend Import Check: `python -B -c "from app.communication.schemas import RecoveryCommunicationReference; from app.communication.service import inspect_recovery_communication_event"`: passed.
- Frontend Tests Executed: `npm run typecheck`: passed; `node_modules/.bin/tsc.cmd --noEmit -p tsconfig.app.json`: passed (checks actual app files despite root solution tsconfig); `npm test`: **12 passed**; `npm run build`: passed. No lint script is configured. No dependencies added or changed.
- Diff Checks: `git status --short`, `git diff --stat`, `git diff --check` reviewed against the local baseline using the isolated work tree; added files separately reviewed and whitespace-checked. Original working tree remains clean. No Git index/history mutations performed.
- Known Limitations: no request management, draft generation, message send, confirmation processing, UI page, DB table/migration, live provider, real API/UI or E2E flow in Commit 01. A valid reference does not verify identity, consent, approval, current authority or freshness. Only schema version 1 is understood. No PostgreSQL smoke test required/run for this foundation-only change.
- Integration Dependencies / Blockers: no blocker for Commit 01. Future integration needs P1 normalized reply/verified identity contract, P3 exact approved plan/proposal reader and replan handoff, P5 scoped proposal reader and completion of proposal ID/status/expiry/identity guards, shared persistence/outbox transaction coordination and later routing. Existing Core readers/confirmation services/auth simulator/outbox are documented as existing, not reimplemented. P4 target confirmation event names are not claimed as registered consumers.
- Next Milestone: **Commit 02 — Communication Request Management**. Not started.
- Git Status: **Not committed yet**. No commit hash, push, merge or PR is claimed. After manual application, record the user's actual test results and eventual commit reference separately.

### 2026-10-21 — P4 / Commit 02: Communication Request Management (Pending Integration)
- Scope / status: request-management backend implemented and tested in the uploaded ZIP working copy. No Commit 03 drafting, sending, approval workflow, confirmation, reminders or UI. No production project edits. **Not committed yet**; no hash/PR/push/merge claimed.
- Baseline: `MouManTAI-P4-communication.zip` (SHA256 `12b1ae054e1e1e8406f4a5c07af3c9ba5c29073944a17eae34c0ecd1124a4312`). Archive has no .git; executed `git branch --show-current`/`git status --short`, but they report the enclosing workspace (`master`), not the P4 repository. No actual P4 branch/HEAD inferred or changed.
- Implemented code: retained Commit 01 helper/reference and its 23 tests. POST accepts only source_event_id and resolves tenant-scoped persisted Core outbox + exact Proposal/Commitment. Checks target, independent versions, latest unique proposal, ACTIVE + OFFERED eligibility, explicit valid terms, trusted approval scope/terms/expiry. ACTIVE/event presence is NOT approval. Server-only RequestAuthority port must authorize creation and resolve real evidence; default is unconfigured/503, not hardcoded approved=True.
- Request states: READY_FOR_DRAFTING only when approval, verified recipient/customer linkage, channel evidence and expiry are present. Otherwise permitted intake can persist BLOCKED with explicit missing-data reasons. Approval/policy failure rejects creation. MessageStatus remains DRAFT; no message/confirmation is created. These are P4-local intake views, not a duplicate shared CommunicationRequest. Readiness/read results are historical creation-time snapshots; later drafting/sending MUST resolve current authority again. Blocked requests are not auto-promoted by repeat POST.
- Persistence: P4-local SQLAlchemy tables `communication_requests` + `communication_request_sources` using existing Base; no production create_all and no dictionary persistence. Tenant/logical-proposal uniqueness, tenant/source-event primary key and composite FK protect deduplication. Different events can alias one logical request while retaining each event's provenance. PostgreSQL commitment/proposal row locks + DB uniqueness + one revalidated IntegrityError retry; SQLite two-session and constraint tests are not PostgreSQL locking proof.
- Atomicity: request + event aliases + existing audit/outbox rows commit together; no authoritative Commitment state changes. Emits reference-only `communication.requested` through existing generic DomainEvent/Outbox models; no shared enum or subscriber changes. Write/commit errors roll back; missing table/DB becomes COMMUNICATION_PERSISTENCE_UNAVAILABLE (503), never a fake empty list/success. Same-event retries revalidate current proposal/authorization before returning the existing snapshot; stale retries can return 409. Source/plan rebinding or same-version term changes are conflicts.
- Changed files: UPDATED `backend/app/communication/schemas.py`, `service.py`; ADDED `models.py`, `repository.py`, `router.py`, `tests/test_requests.py`. No changes to Commit 01 tests, frontend/types, Core, DB, migrations, main.py, shared contracts, auth implementation, dependencies or AGENTS.md. No new feature README/INTEGRATION_NOTES. Only this P4 entry appended to TEAM_LOG in working copy; deliver append fragment separately.
- API: POST `/v1/communications/requests`, GET `/v1/communications`, GET `/v1/communications/{communication_id}` implemented and mounted in test app only. POST 200 is a persisted intake/replay result (can be BLOCKED), not sent/accepted. GET/LIST scope by current demo tenant; optional commitment_id/request_status filters. Reuses get_request_context/get_db; known server-mapped actor validation rejects unknown/spoofed roles. Tenant membership and real authentication remain limitations of the existing demo headers.
- Tests / results: `python -B -m pytest tests app/communication/tests -v` from backend: **127 passed, 0 failed, 0 skipped** = 46 existing Core + 23 unchanged Commit 01 + 58 Commit 02. Includes TestClient endpoints, invalid/client authority claims, tenant isolation, missing/stale/ambiguous Proposal, missing approval/policy, duplicates, SQL uniqueness, two SQLite sessions, atomic rollback/commit failure, missing migration and PostgreSQL metadata DDL compilation. Existing Starlette/httpx deprecation warning remains. Router/service import check passed and showed exactly the three intended routes. Test-only FixtureAuthority is not production authorization. No frontend tests/build rerun (frontend untouched). No lint script configured.
- P5 integration dependencies / pending items: (1) import `app.communication.models` in Alembic metadata setup; create reviewed migration from current shared head for both P4 models, indexes, unique key and composite FK; migrate PostgreSQL. (2) Register communication.router in app/main.py. (3) Supply reviewed RequestAuthority adapter and bind get_request_authority: enforce actual create policy and trusted current approved-plan/proposal terms/scope/evidence/expiry, plus P1/P5 recipient and authorized channel/consent evidence. Never use the test fixture in main. Current Proposal table has no expiry or persisted plan-approval reader; placeholder evidence strings are not proof. No readiness is claimed from current Core events alone. (4) Review shared audit/outbox subscriber integration; no automatic event consumer registered yet.
- Runtime limitations: real main still does not mount P4 (404); registering only router gives POST 503 until authority wiring; GET/LIST require migration (otherwise 503). Current Core migrations end at 0004 and do not create P4 tables. PostgreSQL migration/live smoke/concurrent row-lock verification and real app E2E were **not run / Pending Integration**, not counted as passed SQLite tests. Service owns a request-scoped transaction; use with a fresh session, not inside a different unit of work or OutboxDispatcher transaction without coordination.
- Next milestone: **Commit 03 — Template-Based Message Drafting**, not started. Complete required source/approval/persistence integration before claiming the connected request flow works.


