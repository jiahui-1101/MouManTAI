# PromiseFlow — Team Execution Log & Decision Register

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
| P2-FE | Feasibility / Impact UI | P2 | NOT_STARTED | No UI implementation; Phase 1 made no frontend changes | Shared frontend skeleton and P5 route/API contract absent | Implement views only in approved Phase 6 after shared frontend integration is available |
| P2-BE | Constraint + Impact engine | P2 | IN_PROGRESS | Phase 2 P2-local ATP/BOM/conversions/waste, reservation ownership, expiry/ETA cutoffs and UNKNOWN handling; 66 P2 tests pass; full evaluator/impact not implemented | P5 shared snapshot/assessment contracts, source authenticity/completeness, persistence and backend skeleton absent | Stop for external Phase 2 review; Phase 3 requires later explicit approval |
| P2-TST | Feasibility/Impact tests | P2 | IN_PROGRESS | `python -m pytest backend/app/feasibility/tests/test_bom.py backend/app/feasibility/tests/test_inventory.py backend/app/feasibility/tests/test_snapshots.py -q` — 66 passed | API/UI/full evaluator/event/integration suites remain later-phase work | Independent external Phase 2 review |
| P3-FE | Recovery / Approval UI | P3 | NOT_STARTED | — | — | Plan comparison cards |
| P3-BE | Plan / Approval / Action API | P3 | NOT_STARTED | — | P2 evaluator interface | Start templates |
| P3-TST | Approval/Execution tests | P3 | NOT_STARTED | — | — | Define stale-approval test |
| P4-FE | Communication / Confirmation UI | P4 | NOT_STARTED | — | — | Scaffold route |
| P4-BE | Draft/Send/Confirm APIs | P4 | NOT_STARTED | — | P3 proposal schema | Define signed confirmation |
| P4-TST | Confirmation/Channel tests | P4 | NOT_STARTED | — | — | Define ambiguous OK fixture |
| P5-FE | Shell / Overview / Audit UI | P5 | NOT_STARTED | — | — | Create shared UI kit |
| P5-BE | Registry / DB / Events / Roles | P5 | NOT_STARTED | — | Contract decisions | Create schema/migrations |
| P5-TST | Integrated E2E / Security tests | P5 + all | NOT_STARTED | — | Feature PRs | Early smoke tests |
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

## 6. Blocker / Dependency Ledger

| ID | Opened | Blocked owner | Blocking owner | Issue | Impact | Decision / ETA | Status |
|---|---|---|---|---|---|---|---|
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

## 8. QA / Metrics Log

| Date | Commit | Backend tests | Frontend tests | Build | E2E | Key observed metric / sample size | Known limitations |
|---|---|---|---|---|---|---|---|
| 2026-10-21 | P2 Phase 1 local commit (SHA in phase response) | `python -m pytest backend/app/feasibility/tests/test_snapshots.py -q`: 13 passed | NOT RUN | NOT RUN | NOT RUN | 13 snapshot/fixture tests; operational metrics not measured | No evaluator, API, UI, durable P5 snapshot store, or P3/P5 integration yet; fixture labels are hand-calculated synthetic ground truth only |
| 2026-10-21 | P2 Phase 1 correction commit (SHA in phase response) | Three new correction nodes: 3 failed as expected before fixes, then 3 passed; `python -m pytest backend/app/feasibility/tests/test_snapshots.py -q`: 16 passed | NOT RUN | NOT RUN | NOT RUN | 16 snapshot/fixture tests; operational metrics not measured | No evaluator, API, UI, durable P5 snapshot store, or P3/P5 integration yet; calendar coverage does not prove production feasibility; fixture labels remain hand-calculated synthetic ground truth only |
| 2026-10-21 | P2 Phase 1 confirmation-provenance correction (SHA in phase response) | Four new provenance test nodes failed before the fix; five targeted provenance tests passed after; `python -m pytest backend/app/feasibility/tests/test_snapshots.py -q`: 21 passed | NOT RUN | NOT RUN | NOT RUN | 21 snapshot/fixture tests; operational metrics not measured | No evaluator, API, UI, durable P5 snapshot store, or P3/P5 integration yet; external supplier evidence authenticity remains P5-owned; synthetic refs prove only structural provenance |

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
