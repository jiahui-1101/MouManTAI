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

## 8. QA / Metrics Log

| Date | Commit | Backend tests | Frontend tests | Build | E2E | Key observed metric / sample size | Known limitations |
|---|---|---|---|---|---|---|---|
| 2026-10-21 | `ec0458d` on `phase0-core-integration` | 7 passed (`pytest`) | 1 passed (`vitest`) | passed (`npm run build`, typecheck passed) | NOT RUN | Contract/fixture/registry smoke only; sample size 1 fixture | Live DB migration pending isolated PostgreSQL; Docker/WSL1 blocker; npm audit clean after validated upgrades |

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
