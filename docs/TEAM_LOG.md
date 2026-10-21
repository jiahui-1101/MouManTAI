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
| P2-FE | Feasibility / Impact UI | P2 | NOT_STARTED | No P2 UI; Main sync supplies shared frontend shell/types/client | P2 assessment/impact APIs and later-phase UI integration pending | Implement only after approved Phase 6 scope |
| P2-BE | Constraint + Impact engine | P2 | IN_PROGRESS | Phase 4 targeted causal/evidence/deadline corrections; 22 focused + 162 combined P2/shared backend tests pass; final shared assessment BLOCKED | P5 empty Impact Set schema, source/catalog adapter and P3 proposal agreement | Stop for independent external Phase 4 review; do not start Phase 5 |
| P2-TST | Feasibility/Impact tests | P2 | IN_PROGRESS | 22 Phase 4 impact tests; 162 P2/shared regressions pass with one existing Starlette/httpx warning; no earlier tests removed | API/UI/event publication/E2E and P3/P5 integration pending; host pytest9.1.1 vs declared<9 | External Phase 4 review; no full P2 completion claim |
| P3-FE | Recovery / Approval UI | P3 | NOT_STARTED | — | — | Plan comparison cards |
| P3-BE | Plan / Approval / Action API | P3 | NOT_STARTED | — | P2 evaluator interface | Start templates |
| P3-TST | Approval/Execution tests | P3 | NOT_STARTED | — | — | Define stale-approval test |
| P4-FE | Communication / Confirmation UI | P4 | NOT_STARTED | — | — | Scaffold route |
| P4-BE | Draft/Send/Confirm APIs | P4 | NOT_STARTED | — | P3 proposal schema | Define signed confirmation |
| P4-TST | Confirmation/Channel tests | P4 | NOT_STARTED | — | — | Define ambiguous OK fixture |
| P5-FE | Shell / Overview / Audit UI | P5 | IN_PROGRESS | Phase 0 shell, routes, health status card; committed in `ec0458d` | Feature pages remain owner work | Add shared audit/overview data API |
| P5-BE | Registry / DB / Events / Roles | P5 | IN_PROGRESS | Canonical contracts, fixture, PostgreSQL/Alembic foundation, registry lifecycle and outbox; committed in `ec0458d` | Docker daemon unavailable for DB smoke | Add tenant/version/duplicate-event integration suite |
| P5-TST | Integrated E2E / Security tests | P5 + all | IN_PROGRESS | 7 backend tests + 1 frontend smoke test passing | Full E2E waits for P1–P4 modules | Add integrated tenant/version/duplicate-event suite |
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

## 6. Blocker / Dependency Ledger

| ID | Opened | Blocked owner | Blocking owner | Issue | Impact | Decision / ETA | Status |
|---|---|---|---|---|---|---|---|
| BLOCK-20261021-001 | 2026-10-21 | P5 | Environment | Docker Desktop Linux engine unavailable because host exposes WSL1; existing PostgreSQL on 5432 is unrelated | Live PostgreSQL migration and DB smoke test cannot run safely | Enable WSL2 or provide isolated PostgreSQL on host 5433 | OPEN |
| BLOCK-P2-P3-001 | 2026-10-21 | P2 | P5 | P5 schema still requires nonempty `affected_commitment_ids` although the actual Impact Set may be empty | Final shared FeasibilityAssessment adapter blocked; no fabricated IDs | Actual Impact Set semantics RESOLVED; await P5 empty-list schema support merge and verification | OPEN |
| BLOCK-P2-P3-002 | 2026-10-21 | P2 | P3 | ProposedChanges fixed-booking serialization not yet owner-confirmed | Library handoff provisional | Review PHASE3_HANDOFF.md; no duplicate calculator or arbitrary stock insertion | OPEN |
| BLOCK-P2-P3-003 | 2026-10-21 | P2 | P2 + P5 | Shared summary lacks complete operational evidence; SAUCE/PACKAGING vs WRAP catalog mismatch | Shared demo cannot be safely treated as a full trusted snapshot | Review source/catalog adapter and fixture extension; missing data stays UNKNOWN | OPEN |
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

## 8. QA / Metrics Log

| Date | Commit | Backend tests | Frontend tests | Build | E2E | Key observed metric / sample size | Known limitations |
|---|---|---|---|---|---|---|---|
| 2026-10-21 | P2 Phase 1 local commit (SHA in phase response) | `python -m pytest backend/app/feasibility/tests/test_snapshots.py -q`: 13 passed | NOT RUN | NOT RUN | NOT RUN | 13 snapshot/fixture tests; operational metrics not measured | No evaluator, API, UI, durable P5 snapshot store, or P3/P5 integration yet; fixture labels are hand-calculated synthetic ground truth only |
| 2026-10-21 | P2 Phase 1 correction commit (SHA in phase response) | Three new correction nodes: 3 failed as expected before fixes, then 3 passed; `python -m pytest backend/app/feasibility/tests/test_snapshots.py -q`: 16 passed | NOT RUN | NOT RUN | NOT RUN | 16 snapshot/fixture tests; operational metrics not measured | No evaluator, API, UI, durable P5 snapshot store, or P3/P5 integration yet; calendar coverage does not prove production feasibility; fixture labels remain hand-calculated synthetic ground truth only |
| 2026-10-21 | P2 Phase 1 confirmation-provenance correction (SHA in phase response) | Four new provenance test nodes failed before the fix; five targeted provenance tests passed after; `python -m pytest backend/app/feasibility/tests/test_snapshots.py -q`: 21 passed | NOT RUN | NOT RUN | NOT RUN | 21 snapshot/fixture tests; operational metrics not measured | No evaluator, API, UI, durable P5 snapshot store, or P3/P5 integration yet; external supplier evidence authenticity remains P5-owned; synthetic refs prove only structural provenance |
| 2026-10-21 | `ec0458d` on `phase0-core-integration` | 7 passed (`pytest`) | 1 passed (`vitest`) | passed (`npm run build`, typecheck passed) | NOT RUN | Contract/fixture/registry smoke only; sample size 1 fixture | Live DB migration pending isolated PostgreSQL; Docker/WSL1 blocker; npm audit clean after validated upgrades |

Metric protocol: always disclose dataset size, date, ground truth creation method, pass/fail definitions. **Do not** mark actual customer fulfilment because communication was sent or approved.

P2 Phase 2 QA (2026-10-21): `python -m pytest backend/app/feasibility/tests/test_bom.py backend/app/feasibility/tests/test_inventory.py backend/app/feasibility/tests/test_snapshots.py -q` — 66 passed, 0 failed (45 new + 21 regression). Actual material shortage outputs: buffered before 0/0 -> after 40/0 pcs; two-order before 0/0 -> after 70/40 pcs. API/UI/build/E2E/production metrics NOT RUN; shared runtime absent and later-phase scope. No accuracy or latency claim from pytest elapsed time.

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
