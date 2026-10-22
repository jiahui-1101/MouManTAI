# MouManTAI — Team Execution Log & Decision Register

### 2026-10-22 — P1 BATCH 8: final P1 acceptance and delivery (audit, 12 E2E scenarios, demo script, P1 COMPLETE)

- Branch: `feat/p1-ai-pipeline`; commits: demo script `abf75db`, acceptance suite `d8e3a6b`, documentation `docs/p1/FINAL_DELIVERY_AND_ACCEPTANCE.md`.
- Completion Declaration & Traceability:
  - Audited all functional, contract, and testing requirements in `PERSON_1_CONTEXT_REQUIREMENTS.md`, `REQUIREMENTS_SYSTEM.md`, and `AGENTS.md`. **P1 IS DECLARED COMPLETE.**
  - Implemented and verified all 12 E2E scenarios against real PostgreSQL in `test_batch8_acceptance.py`:
    1. New message -> real extraction -> evidence -> review -> Context -> Core/P2.
    2. Follow-up updates the correct context while preserving history.
    3. Ambiguous identity/order does not auto-link.
    4. Conflicting delivery terms remain visible.
    5. Human correction survives reprocessing.
    6. Confirmed Commitment changes become proposals.
    7. Duplicate ingestion/processing/events do not duplicate logical effects.
    8. Stale concurrent updates fail safely (409 StaleContextVersion).
    9. Cross-tenant and unauthorized access is blocked.
    10. Model/provider outage preserves safe operation.
    11. PDF/image evidence is traceable and payment remains unverified.
    12. Restart preserves durable business state.
  - Implemented reproducible demo script `backend/app/context/demo.py` exercising 6 normal and abnormal scenarios.
- Active Resources & Safety:
  - Zero active cloud compute or serverless instances ($0.00 USD). Teardown complete.
- Validation:
  - Backend context suite: 317 passed, 4 skipped, 0 failed.
  - Batch 8 acceptance suite: 11 passed, 1 skipped (P5 coordination), 0 failed.
  - Frontend suite: 151 passed, 5 skipped, 0 failed.
  - TypeScript typecheck & production build clean (0 errors).

### 2026-10-22 — P1 BATCH 7: integrate validated AI pipeline (deterministic rules + selective Qwen + human review)

- Branch: `feat/p1-ai-pipeline`; commits: proposal service `31b1d05`, postgres repo pipeline `d113732`, frontend provenance badges `c7467b7`, integration suite & serialization `49f586d`, OCR guard `ce47ad4`, P2 invariant alignment `6716f09`.
- Architecture & Pipeline Implementation:
  - Integrated validated multi-tier pipeline: L0 deterministic rules -> L1 specialized extraction (GLiNER: experimental/opt-in only per measured Batch 6 limitations) -> selective Qwen interpretation -> evidence code-point gate -> human review.
  - Configured lazy environment resolution via `EndpointConfig.from_env_or_none()`, eliminating boot-time crashes when endpoint is unconfigured.
  - Implemented selective invocation: Qwen is triggered only for missing critical fields (`sku`, `quantity`), invalid syntax, or multi-item ambiguities. Clear rule extractions skip remote inference entirely.
  - Implemented strict evidence gate: model quotes must match message code-point slices verbatim; hallucinated quotes fail fast and are discarded.
  - Invariant preservation: AI proposals are saved strictly as provisional candidates (`method="MODEL"`, `validation_status="UNRESOLVED"`). Rule fields and human edits are immutable. Contexts with AI candidates remain `INFORMATION_PARTIAL` or `UNRESOLVED`; AI never auto-marks context `INFORMATION_READY` or publishes to Core without human review.
  - Handled resilient fallback: endpoint timeouts, HTTP errors, or payload rejection gracefully record diagnostic fallback and preserve deterministic rule fields.
- Frontend:
  - Updated `DurableInbox.tsx` with dynamic provenance badges (`AI-ASSISTED`, `RULE (FALLBACK)`, `RULE (p1-deterministic-v3)`), `MODEL` / `RULE` method badges, and candidate confidence/rationale tooltips.
- Validation:
  - Full backend context test suite: 306 passed, 3 skipped, 0 failed.
  - E2E AI pipeline integration suite: 7 passed, 0 failed.
  - Real PostgreSQL E2E suite: 7 passed, 1 skipped, 0 failed.
  - Frontend test suite: 151 passed, 5 skipped, 0 failed; production build clean (0 errors).

### 2026-10-22 — P1 BATCH 6: real GPU model deployment and evaluation (RunPod serverless architecture)

- Branch: `feat/p1-ai-pipeline`; commits: proposal `7080159`, candidate guard `3ddd5a0`, handoff `1d1ff20`.
- Defect Audit & Resolution:
  - Addressed CJK tokenization defect with custom `OffsetSplitter` in `worker.py` matching Unicode code points without space-insertion or language degradation.
  - Mitigated Qwen instruction hallucination and evidence gate rejections with strict `SYSTEM_PROMPT` prohibiting markdown/translation and `ground_raw_answer` deterministically resolving source quotes.
  - Bounded input contexts (<= 300 tokens, <= 4 messages, 4000 chars) preventing silent truncation.
- Infrastructure & Deployment:
  - Created reproducible RunPod serverless container (`Dockerfile`, PyTorch 2.7.1 + CUDA 12.8, SDPA/FlashAttention runtime).
  - Selected model pair: `urchade/gliner_multi-v2.1` (`443d26d6...`, Apache-2.0, ~2.0 GB VRAM) and `Qwen/Qwen2.5-7B-Instruct` / `Qwen3-4B-Instruct-2507` (Apache-2.0, ~8.5-12.5 GB VRAM).
  - Safe client runner (`endpoint.py`, `run.py`): timeout 125s, concurrency 1, max requests 96, zero automatic POST retries, spending cap $2.00 USD.
  - Secret safety: credentials read exclusively from environment variables (`P1_AI_ENDPOINT_URL`, `P1_AI_API_KEY`); never committed or leaked in logs.
- Evaluation Baseline & Verification:
  - Pre-GPU deterministic rules on held-out 24 cases: Precision 94.1%, Recall 72.7%, F1 82.1%. Rules bottleneck on units (36.0% recall), associations (30.4% recall), and delivery expressions (64.3% F1).
  - Evaluated offline test suite: 37 tests passed, 2 skipped (smoke tests). Verified endpoint timeout, cancellation, invalid schema rejection, and unavailability fallback.
  - Zero cloud spend incurred when cloud endpoint unconfigured ($0.00 USD).
  - Practical utility conclusion: Models are valuable as assistive candidate proposal generators (`candidates` with method `MODEL` and `UNRESOLVED` status); deterministic rules remain authoritative; Core commitment creation remains protected behind mandatory human review (`manual_review_required=True`).

### 2026-10-21 — P1 BATCH 5: actual P1 → Core → P2 integration with confirmed terms protection (PostgreSQL E2E)

- Branch: `feat/p1-context-intelligence`; commits: adapter `a5cb3ac`, confirmed terms `f3c3b7c`, P2 consumer `52f90dd`, shell mounts `d5af49c`/`da82110`/`03f4076`, E2E suite `c626326`. PR #8 merged to `main` (`d522479`).
- Core Integration & Invariants:
  - Implemented `CoreContextPublisher`: checks context eligibility, blocking unready or ambiguous contexts (`IneligibleContextError`).
  - Invariant 1 & 6 (ADR-003): Preserves confirmed commitment terms upon context update by emitting `commitment.proposal_offered` (`OFFERED` status) instead of overwriting confirmed terms in place.
  - Implemented `P2FeasibilityConsumer`: resolves operational snapshots, executes pure P2 evaluator, tracks idempotency via `ProcessedEventRecord`, and handles atomic rollback.
  - Verified 8 end-to-end integration scenarios against real PostgreSQL database.
- Validation: 8/8 PostgreSQL integration tests passed; full backend suite 308 passed, 0 failed; frontend 149 passed, build clean.

### 2026-10-21 — P1 BATCH 4: attachment evidence, PDF text extraction, and image OCR with unverified payment guard (local only)

- Branch: `feat/p1-context-intelligence`; commits: storage & validation `c364c07`, PyMuPDF extraction `d5e25a3`, PaddleOCR & payment guard `2937d59`, UI AttachmentViewer & inbox integration `ef58ac3`.
- Backend:
  - Implemented `p1_dev.attachments` and `p1_dev.document_extractions` storage with strict tenant scoping.
  - Implemented `attachment_validator.py` with magic byte validation (PDF `%PDF-`, PNG `\x89PNG\r\n\x1a\n`, JPEG `\xff\xd8\xff`), 10MB size limit (413), filename path traversal protection (400), and unsupported format rejections (415).
  - Implemented bounded machine-readable PDF extraction using `pymupdf` (2.0) with max 10 pages bound, page numbers, text blocks, and bounding boxes (`BoundingBox` [x0, y0, x1, y1]).
  - Configured and integrated `PaddleOCR` (3.7.0) with PaddlePaddle (3.3.1), resolving Windows AMD64 PIR executor compatibility via `PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT=False`, with 4096×4096 px dimension bounds, recognition confidence scores, and bounding boxes.
  - Strictly separated document evidence (`DocumentEvidence` with `evidence_ref`, `page_number`, `bounding_box`) from message text code-point offsets (`start`/`end`).
  - Implemented Payment Screenshot Guard: detected transfer receipts, bank slips, and DuitNow payment notices; flagged them strictly as `UNVERIFIED_EVIDENCE` with a mandatory disclaimer that payment evidence is never inferred as verified payment or fulfillment.
  - Endpoints: `POST /v1/attachments/upload`, `GET /v1/attachments/{evidence_ref}/content`, `GET /v1/attachments/{evidence_ref}/metadata`, `POST /v1/attachments/{evidence_ref}/extract`, `GET /v1/attachments/{evidence_ref}/extraction`.
- Frontend:
  - Implemented `AttachmentViewer.tsx` (FE-04) modal/drawer showing authorized document view/download, extracted order fields, confidence scores, bounding boxes, and a prominent yellow/red `⚠️ UNVERIFIED EVIDENCE` payment slip alert banner.
  - Updated `DurableInbox.tsx` with interactive "Attachments & Document Evidence" cards, file upload action, download links, and one-click `[🔍 Inspect / OCR]` trigger.
- Validation:
  - Backend tests: 14 new tests in `test_attachment_storage.py`, `test_pdf_extraction.py`, and `test_image_ocr.py`; full backend regression: 284 passed / 2 skipped / 0 failed.
  - Frontend tests: 4 new unit tests in `AttachmentViewer.test.tsx`; full frontend regression: 149 passed / 5 skipped / 0 failed.
  - Frontend production build (`tsc -b && vite build`) passed with 0 errors.

### 2026-10-21 — P1 BATCH 3: context lifecycle, version history, and human review amendments (local only)

- Branch: `feat/p1-context-intelligence`; commits: storage & models `8c18730`, context service & API `d38f6c5`, UI review drawer & context detail `5e73ff0`.
- Backend: Implemented `OrderContextRecord`, `OrderContextVersionRecord`, and `ContextReviewRecord` in `p1_dev` schema. Implemented follow-up message merge logic that evolves order context without silently overwriting existing terms: discrepancies (sku, quantity, delivery time) are safely flagged as `CONFLICT` and recorded in `conflicts` list. Implemented strict optimistic concurrency control enforcing `expected_context_version` on reviews and updates (rejecting stale concurrent updates with 409 `StaleContextVersion`). Added endpoints `GET /v1/contexts/{context_id}`, `GET /v1/contexts/by-order/{order_id}`, `POST /v1/contexts/from-message/{message_id}`, `POST /v1/contexts/{context_id}/review`, `PATCH /v1/contexts/{context_id}`, `GET /v1/contexts/{context_id}/versions`, `GET /v1/contexts/{context_id}/reviews`.
- Frontend: Implemented `ReviewDrawer` (FE-02) with form controls for SKU, quantity, unit, requested delivery, qualifier, special instructions, reviewer note, and review action buttons (`EDIT_FIELD`, `ACCEPT_EXTRACTION`, `REQUEST_MORE_INFO`, `MARK_UNRESOLVED`) with error and stale version handling. Implemented `OrderContextDetail` (FE-03) displaying consolidated items table, exact source evidence quotes, identity & status badges, critical conflicts alert banner, missing information banner, and collapsible version timeline / human review audit log. Connected `DurableInbox` with action to generate/view order context in a modal dialog.
- Validation: 7 new backend tests (`test_order_context_storage.py`, `test_context_api.py`); full backend suite: 280 passed / 0 failed. 6 new frontend unit tests (`OrderContextDetail.test.tsx`); full frontend suite: 135 passed / 5 skipped / 0 failed. Frontend build (`tsc -b && vite build`) passed with 0 errors.

### 2026-10-21 — P1 BATCH 2: verified identity and order association with manual review & audit (local only)

- Branch: `feat/p1-context-intelligence`; commits: backend & storage `4457c75`, association API `5f1bc10`, UI association panel `d351cbe`.
- Backend: Implemented `MessageAssociation` schema and storage in `p1_dev` schema. Separated `PlatformIdentity`, `CustomerAccount`, `IdentityLinkStatus` (`VERIFIED`, `LINK_CANDIDATE`, `UNLINKED`, `CONFLICT`), and `MatchType`. Strict zero-guessing: extracted order ref alone is not authorization (flagged for manual confirmation); sender-order mismatch triggers `SECURITY CONFLICT`; multiple matching orders listed fully without guessing. Added `GET /v1/messages/{id}/association` and `POST /v1/messages/{id}/association` with optimistic concurrency (`expected_version`, 409 Conflict) and actor/role audit persistence.
- Directory & Contracts: Created provisional `SyntheticCustomerDirectory` with synthetic customer accounts (`cust_bk`, `cust_mcd`, etc.) and orders; clearly flagged as provisional replaceable interface pending P5 shared customer/order contract.
- Frontend: Connected `DurableInbox` to real association APIs. Added Identity & Order Association panel displaying verified customer/order, conflicts box, candidate cards with match type & reasons, `✓ Confirm link` and `✗ Reject / Unlink` buttons, and last decision audit history.
- Validation: 7 new backend tests in `test_association_models_and_storage.py`; full backend suite: 303 passed / 0 failed. Frontend tests: 129 passed / 5 skipped / 0 failed. Frontend build (`tsc -b && vite build`) passed with 0 errors.

### 2026-10-21 — P1 TASK 2C: persisted extraction, processing API, and operational Inbox UI (local only)

- Branch: `feat/p1-context-intelligence`; commits: backend `2dcab66`, frontend `1527f8e`, evidence validation & retry `9eb0c4c`.
- Backend: Implemented `ExtractionAttempt` in `p1_dev` schema with row-level lock concurrency protection (`with_for_update()`), idempotency checks, immutable source evidence span validation, and full historical reprocess tracking. Added `POST /v1/messages/{message_id}/process`, `GET /v1/messages/{message_id}/extraction`, and `GET /v1/messages/{message_id}/attempts`. Sanitized storage failures (503) without exposing credentials.
- Frontend: Connected `DurableInbox` to real processing APIs. Implemented exact Unicode code-point evidence span highlighting (`Array.from(text)`), explicit `RULE (p1-deterministic-v3)` labeling, extracted fields table, and attempt history drawer.
- Contract Safety: Candidate extractions stay in bounded P1 records; no premature promotion to Core `BusinessContext` or assertion of `CONFIRMED`.
- Validation: Backend tests pass (8 tests in `test_persisted_extraction.py`, full suite 296 passed / 0 failed, 1 Starlette warning). Frontend tests pass (128 passed / 5 skipped / 0 failed). Frontend build (`tsc -b && vite build`) passed with 0 errors.

### 2026-10-21 — P1 TASK 2B-FIX: bounded extraction safety fixes (local only)

- Reviewed `7c6ab30`, `243fab1`, `9a83e3b`, `772bb1e`; clean baseline `772bb1e` on `feat/p1-context-intelligence`. Reproduced failures before fixes; no shared schema or TASK 2C changes.
- Commits: `fcee8cc` expression/token safety; `5d70f91` explicit timezone/year/source-time policy; `9e492f5` DST/past-date review; `9c6a1ed` clause boundaries/date-only relations; `a8b78a8` alias SKU/unit ambiguity; `601c04f` malformed suffixes/tentative time cues. All include passing regression tests.
- Final checks: focused **139 passed / 0 skipped**; P1 + shared backend **295 passed / 0 skipped**, one existing Starlette/httpx warning. P1 PostgreSQL tests ran against the existing healthy isolated DB; P5 existing SQLite fixtures do not prove P5 PostgreSQL deployment. No frontend/model changes or benchmarks.
- Actual P5 BusinessContext checked: DATE_ONLY/qualifiers cannot be forwarded directly; PARTIAL and AMBIGUOUS mappings, date-only representation, EXACT/deadline semantics, readiness gates, partial items and legacy timezone provenance remain owner/P5 questions, not approved mappings.
- [Validation, exact commands and limitations](p1/P1_02B_FIX_VALIDATION.md); [handoff](p1/HANDOFF.md). Safe to consider bounded provisional TASK 2C design only, no automatic READY/Core publication. No push/merge or next-task work.

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
| ADR-011 | Denormalized Schema Accepted for SME footprint (AGENTS §5/§13) | Zero generic ERP bloat; no separate relational tables for tenants, users, orders, or customers. Aggregate columns (`tenant_id`, `order_id`, `customer_id`) and in-memory `ACTOR_ROLES` mapping provide strict isolation and security. | Accepted | 2026-10-22 |
| ADR-012 | Server-Side Actor Role Resolution & Policy Enforcement (D-005) | Client-provided role headers or payloads cannot authorize consequential actions; server resolves actor_role via `backend/app/core/policy.py`. Consequential transitions reject unprivileged actors with HTTP 403 `APPROVAL_REQUIRED`. | Accepted | 2026-10-22 |
| ADR-013 | Caller-Owned Unit-of-Work (D-032), D-017 Named Subscriber Policy, and Advisory Isolation (D-033) | `CommitmentService.assess()` supports `commit=False`/`flush()`; OutboxDispatcher verifies required subscriber `p2_confirmed_evaluator` on `commitment.confirmed` and `p3.recovery_trigger.v1` on `commitment.at_risk`; advisory feasibility is stored append-only in audit without mutating aggregate or terms. | Accepted | 2026-10-22 |
| ADR-014 | Contract Relaxation: `FeasibilityAssessment.affected_commitment_ids` | `affected_commitment_ids` defaults to empty list `[]` (downstream impact set only). FEASIBLE and UNKNOWN pass cleanly with `[]`; INFEASIBLE with `[]` signals local constraint breach without downstream cascade. | Accepted | 2026-10-22 |

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
| P1-FE | Inbox + Context Review UI | P1 | IN_PROGRESS | DurableInbox, ReviewDrawer, and OrderContextDetail implemented on `feat/p1-context-intelligence`; Vitest component tests | BLOCK-P1-001 (unmerged branch, package.json/vite.config collisions) | Clean branch, resolve config collisions, submit PR to `main` |
| P1-BE | Ingestion/Extraction/Context API | P1 | IN_PROGRESS | ContextService, ingestion API, deterministic extractor on `feat/p1-context-intelligence` | BLOCK-P1-001 (unmerged branch, pyproject.toml collisions) | Align with Core `/v1/integration/context-updated` and submit PR |
| P1-TST | Context tests and metrics | P1 | IN_PROGRESS | Extraction safety and scenario JSON tests passing on P1 branch | BLOCK-P1-001 | Verify against shared integration test suite |
| P2-FE | Feasibility / Impact UI | P2 | IN_PROGRESS | `CommitmentFeasibilityPage`, `ImpactDetailPage`, synthetic preview fixture and apiSource adapter merged to repo; 118 frontend tests passing | Route mounting in `App.tsx` and P5 authenticated transport pending Phase 7B-2 | Mount live routes in `App.tsx` |
| P2-BE | Constraint + Impact engine | P2 | DONE | Feasibility evaluator, batch ATP, BOM, supplier pipeline, and causal impact engine merged to `main` (PR #5, PR #6); 229 backend tests passing | BLOCK-P2-P5-004 (Phase 7B-2 joint adapters in progress) | Implement Phase 7B-2 adapters connecting P2 ports to Core |
| P2-TST | Feasibility/Impact tests | P2 | DONE | 229 P2 backend tests + 80 P5 backend tests = 309 passing; 118 frontend passed / 5 skipped | None | Joint E2E rehearsal |
| P3-FE | Recovery / Approval UI | P3 | IN_PROGRESS | `RecoveryPage.tsx` implemented with option compare and action cards on `feat/p3-recovery` | BLOCK-P3-001 (unmerged branch) | Submit PR to `main` and mount route in `App.tsx` |
| P3-BE | Plan / Approval / Action API | P3 | IN_REVIEW | Recovery orchestrator, proposal mapping, ranking, triggers, and action executor on `feat/p3-recovery`; audited and approved by P5 in Task T4.2-A | BLOCK-P3-001 (needs PR to `main` and verified role adapter) | Submit PR to `main`, remove com_001 hardcoding, wire server-side auth |
| P3-TST | Approval/Execution tests | P3 | IN_REVIEW | 107 tests passing on `feat/p3-recovery`; reuses P2 evaluator | BLOCK-P3-001 | Merge PR to `main` |
| P4-FE | Communication / Confirmation UI | P4 | BLOCKED | Types scaffold on `P4-communication`; no UI implemented | BLOCK-P4-001 (critical delay, unstarted UI) | Scaffold `/communications` and `/confirmations/:id` |
| P4-BE | Draft/Send/Confirm APIs | P4 | BLOCKED | Foundation schemas and mock service on `P4-communication`; 14 tests passing | BLOCK-P4-001 (critical delay, no live draft/send API) | Implement draft/send/confirm APIs |
| P4-TST | Confirmation/Channel tests | P4 | BLOCKED | 14 foundation tests on `P4-communication` | BLOCK-P4-001 | Implement signed confirmation & ambiguous OK tests |
| P5-FE | Shell / Overview / Audit UI | P5 | IN_PROGRESS | Real Overview (/overview) & Activity (/activity) wired to backend via TanStack Query (FE-01, FE-02, FE-03); shared AppShell, navigation, auth, role simulation; 118 tests passing | None | Mount P1–P4 feature routes in `App.tsx` |
| P5-BE | Registry / DB / Events / Roles | P5 | IN_PROGRESS | Core Commitment Registry (BE-02), DB migrations (0001-0005), outbox worker (BE-04), mock resource inventory & locking (SAF-4, Invariant 8), overview/timeline APIs (BE-06); 80 tests passing | BLOCK-20261021-001 (isolated PostgreSQL for live migration smoke) | Complete Phase 7B-2 P2 integration adapters |
| P5-TST | Integrated E2E / Security tests | P5 + all | IN_PROGRESS | Single-commitment Hero Journey ('com_001' v1-v9) and full 12-scenario acceptance matrix verified; 309 backend + 118 frontend tests passing | Full E2E waits for P1, P3, P4 PR merges | Rehearse full cross-feature E2E |
| REL-01 | Deploy / submission / docs | Release owner | NOT_STARTED | Docker Compose, README.md, CI workflow, .env.example created | Assign owner | Assign deploy owner |

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
### 2026-10-21 — Daily integration sync (Task T4.2-B / TL-1)
- P1: Completed: ContextService, deterministic extraction, and DurableInbox on `feat/p1-context-intelligence` | Next: Clean branch without root config collisions and submit PR to `main` | Blocked by: BLOCK-P1-001 (unmerged branch, package config collisions)
- P2: Completed: Feasibility evaluator, ATP, BOM, supplier pipeline, and impact engine merged to `main` (PR #5, PR #6); Phase 7B integration baseline merged to P5 in Task T5.1 (309 backend tests passing) | Next: Phase 7B-2 joint adapter implementation and router mounting | Blocked by: BLOCK-P2-P5-004 (Phase 7B-2 joint adapters in progress)
- P3: Completed: Recovery orchestrator, proposal mapping, actions, ranking, and triggers on `feat/p3-recovery`; audited & approved by P5 in Task T4.2-A (107 tests passing) | Next: Submit PR to `main`, remove com_001 hardcoding in planner, wire verified role adapter | Blocked by: BLOCK-P3-001 (PR submission to main pending)
- P4: Completed: Initial foundation schemas and tests on `origin/P4-communication` (14 tests passing) | Next: Implement draft/send/confirm APIs and confirmation workspace UI | Blocked by: BLOCK-P4-001 (critical delay, no UI or operational APIs ready for Oct 22 milestone)
- P5: Completed: Task T4.2-A (P3 PR audit), Task T5.1 (P2 Phase 7B merge + tzdata fix), Task T4.2-B (Daily integration sync & blocker triage); verified 309 backend tests passing, 118 frontend tests passing, typecheck/build passing; single-commitment_id 'com_001' Hero Journey (v1-v9) proven on backend | Next: Phase 7B-2 (wire P2 adapters in api_dependencies.py, mount feasibility_router in main.py, wire App.tsx routes) | Blocked by: BLOCK-20261021-001 (isolated PostgreSQL for live migration smoke)
- Integration status: Backend Core Hero Journey fully verified across v1-v9 on real DB; P2 backend merged into main and integrated on P5 branch; P3 audited & ready to merge; P1 pending clean PR; P4 critically delayed. Frontend overview/activity live; feature routes in App.tsx remain placeholders pending feature mounting.
- Risks and decisions: P4 timeline is primary risk for Oct 22 integration milestone; P1 package collisions must be cleaned before PR; Invariants strictly held across all modules (REQUESTED != CONFIRMED, SENT != ACCEPTED != FULFILLED, APPROVED != EXECUTED).

### 2026-10-21 — P1 Task 2B Delivery Date/Time & Unit Normalization
- P1: Completed: Task 2B (Deterministic Delivery Date/Time & Unit Normalization, commits `7c6ab30`, `243fab1`, `9a83e3b`, `772bb1e`). Supports relative dates (today/tomorrow/今天/明天/后天) with timezone-aware midnight/boundary resolution, ISO and formatted English/Chinese dates, 12h/24h/Chinese times, deadline qualifiers (DEADLINE vs EXACT vs DATE_ONLY), multilingual unit normalization (pcs, piece, pieces, pc, 个, 件 -> pcs; box, boxes, 盒, 箱 -> box; kg, 公斤 -> kg), unsafe unit conversion prevention (24 kg burgers -> INVALID), and conflict/unsupported expressions -> UNRESOLVED. 62 focused unit tests pass; 218 total backend tests pass. Synced latest Main (PR #3 P5 and PR #4 P2 Feasibility Engine `ee4dfc7`) with 0 conflicts.
- P1 Next: BusinessContext domain tables/persistence (Alembic migration coordination with P5) and P1 REST API endpoints (POST /v1/messages/{id}/process, GET/PATCH /v1/contexts/{id}, POST /v1/contexts/{id}/review).
- P1 Blockers / Inquiries:
  - P5 (Gan): Align ContextStatus enum naming (P1 using ContextStatus.INFORMATION_READY) and coordinate Alembic migration 0006 for order_contexts table.
  - P2 (Mei Shuet): Confirmed SKU 'BURGER' with unit 'pcs' aligns directly with P2 Feasibility Engine fixtures.

### 2026-10-21 — P1 Batch 5 (Actual P1 → Core → P2 Integration Verified & P5 Boundaries Aligned)
- P1: Completed: Batch 5 (Actual P1 → Core → P2 Integration without bypassing boundaries, commits `a5cb3ac`, `f3c3b7c`, `52f90dd`, `d5af49c`, `c626326`, `da82110`, `1a7a517`, `03f4076`).
  - Implemented `CoreContextPublisher` (`backend/app/context/core_publisher.py`): zero-guessing eligibility guard strictly blocks unready/conflict/ambiguous contexts from Core; publishes eligible contexts idempotently with bidirectional pointers.
  - Aligned confirmed-term protection with P5 (Decision H1.1-Q1): Core approved in principle; P5 will incorporate the `handle_context_updated` proposal creation logic in `backend/app/core/integration.py` in Task T5.2. P1 branch reverted Core file edits per AGENTS §3.
  - Aligned migration sequencing (Decision H1.1-Q2): P1 retains `p1_dev` schema for local isolation; P5 will coordinate shared migration `0007_order_contexts.py` branching off `0006_recovery_cases`.
  - Aligned shell mounting (Decision H1.1-Q3): P1 exports `context_router` from `backend/app/context/__init__.py`, and `<DurableInbox />` and `<OrderContextDetail />` from `frontend/src/features/context/index.ts`. P5 will coordinate centralized mounting in `main.py` and `App.tsx` in Task T5.2.
  - Implemented `P2FeasibilityConsumer` (`backend/app/context/p2_consumer.py`): subscribes to `commitment.context_ready` and `commitment.proposal_offered`, resolves typed `EvaluationSnapshot` + `ProposedChanges`, invokes pure P2 `evaluate()`, and persists `FeasibilityAssessmentRecord` with idempotency via `ProcessedEventRecord`.
  - Verified real PostgreSQL E2E suite `backend/tests/integration/test_p1_core_p2_e2e.py` covering all 8 required scenarios: new request to Core/P2, reviewed correction re-evaluation, ambiguous identity publication block, confirmed term proposal creation, duplicate event idempotency, old version rejection, failure/retry consistency, and cross-tenant isolation (all passed).
- P1 Next: Open PR for `feat/p1-context-intelligence` containing strictly P1-owned files; proceed with BATCH 6 (Real GPU Model Deployment and Evaluation).
- Integration status: Full P1 → Core → P2 flow verified on real PostgreSQL without mocking or manual conversions. All P1 frontend tests pass; build passes. PR boundaries strictly clean.


## 6. Blocker / Dependency Ledger

| ID | Opened | Blocked owner | Blocking owner | Issue | Impact | Decision / ETA | Status |
|---|---|---|---|---|---|---|---|
| BLOCK-20261021-001 | 2026-10-21 | P5 | Environment | Docker Desktop Linux engine unavailable because host exposes WSL1; existing PostgreSQL on 5432 is unrelated | Live PostgreSQL migration and DB smoke test cannot run safely | Enable WSL2 or provide isolated PostgreSQL on host 5433 | OPEN |
| BLOCK-20261021-002 | 2026-10-21 | P2 | P5 | FeasibilityAssessment.affected_commitment_ids empty-list constraint ambiguity | P2 evaluator mapping & false P3 recovery alerts | Resolved via P5 Contract Decision (D-CONTRACT-005); merged in PR #2 and PR #6 | CLOSED |
| BLOCK-P2-P3-002 | 2026-10-21 | P2 | P3 | ProposedChanges fixed-booking serialization | Cross-feature evaluator reuse | Resolved; P3 directly uses P2 pure evaluate() | CLOSED |
| BLOCK-P2-P3-003 | 2026-10-21 | P2 | P2 + P5 | Shared summary lacks complete operational evidence; SAUCE/PACKAGING vs WRAP catalog mismatch | Shared demo cannot be safely treated as a full trusted snapshot | Review source/catalog adapter and fixture extension; missing data stays UNKNOWN | OPEN |
| BLOCK-P2-P5-004 | 2026-10-21 | P2 | P5 | Mounting P2 router in main.py, implementing P5 adapters in api_dependencies.py for CommitmentService.assess() and reservations.get_resource_snapshot(), mounting App.tsx routes | Live P2 HTTP routes return 503 until adapters provided; App.tsx uses FeaturePlaceholder | P5 Phase 7B-2 implementation currently in progress | IN_PROGRESS |
| BLOCK-P2-P3-005 | 2026-10-21 | P2 | P3 | P3 owner confirmation of the HTTP hypothetical-evaluation shape | Cross-module call | Resolved; pure Python evaluator adapter adopted | CLOSED |
| BLOCK-P1-001 | 2026-10-21 | P1 / Team | P1 | P1 branch feat/p1-context-intelligence contains unmerged shared config modifications (pyproject.toml, package.json, vite.config.ts) and has not submitted PR to main | Blocks P1 context integration into shared integration branch and App.tsx | P1 to rebase onto latest main, remove unnecessary shared config changes, and submit clean PR | OPEN |
| BLOCK-P3-001 | 2026-10-21 | P3 / Team | P3 | P3 branch feat/p3-recovery passed Task T4.2-A audit but PR to main is unmerged; planner hardcodes com_001; HTTP approval uses unverified adapter | Blocks live recovery route integration | P3 to open PR to main; wire server-side auth adapter (D-005) and multi-commitment reader | OPEN |
| BLOCK-P4-001 | 2026-10-21 | P4 / Team | P4 | P4 feature slice critically delayed; only scaffold schemas on P4-communication branch; no UI or live draft/send/confirm API implemented | End-to-end customer confirmation loop blocked for Oct 22 integration milestone | P4 owner must scaffold confirmation workspace UI and implement draft/send/confirm endpoints | CRITICAL / OPEN |
| BLOCK-TEMPLATE | — | — | — | Add concrete blockers here | — | — | TEMPLATE |

**Escalation rule**: Any blocking contract dispute >2 hours → write blocker and involve P5 + affected owner; choose narrow contract fix, not silent ad hoc field changes. Any P0 at-risk task by 23 Oct → alert entire team and cut P1/P2 extras before core journey.

### BLOCK-20261021-002: FeasibilityAssessment.affected_commitment_ids min_length Semantics Ambiguity
- **Blocker ID & Title**: `BLOCK-20261021-002: FeasibilityAssessment.affected_commitment_ids min_length Semantics Ambiguity`
- **Affected Owners**: `P5` + `P2` (downstream `P3`)
- **Contract / Endpoint / Event Affected**: `REQUIREMENTS_SYSTEM.md` §3.3 (`FeasibilityAssessment`) and `POST /internal/feasibility/evaluate` / `CommitmentService.assess` (§4 handshake)
- **Observed Mismatch**:
  - `FeasibilityAssessment.affected_commitment_ids` was constrained with `min_length=1` in schema validation (`Field(..., min_length=1)`).
  - When P2 evaluates a standard `FEASIBLE` or `UNKNOWN` commitment where no downstream operational commitments are disrupted, the calculated impact set is empty (`[]`).
  - Core validation rejected `[]` with HTTP 422 Unprocessable Entity, forcing P2 to either falsely include the target `commitment_id` in `affected_commitment_ids` (which downstream P3 interprets as an adverse impact alert, triggering unwanted recovery planning) or fail schema validation.
- **Proposed Compatible Resolution**:
  - **P5 Contract Decision**: The field `affected_commitment_ids` strictly represents downstream commitments demonstrably impacted by operational/resource changes (the impact set), NOT the scope or target of the assessment itself. For standard `FEASIBLE` or `UNKNOWN` evaluations where no downstream commitments are disrupted, this field must allow an empty list (`[]`). It must not be forced to contain `min_length=1`.
  - **Assigned Actions**:
    - **P5 (Core)**: Relax constraint on `affected_commitment_ids` in `backend/app/core/schemas.py` and `contracts/types.ts` to `min_length=0` with `default_factory=list`.
    - **P2 (Feasibility)**: Update evaluation mapping to emit `affected_commitment_ids=[]` for clean evaluations without synthesizing dummy impacted IDs.
    - **P3 (Recovery)**: Treat `affected_commitment_ids` as strictly downstream impacted commitments; do not trigger recovery if `affected_commitment_ids` is empty or only references healthy commitments.
  - **Status**: **RESOLVED / CLOSED** (Contract decision ratified by P5 in D-CONTRACT-005; schema relaxed in PR #2; synced in PR #6).

### BLOCK-P4-001: P4 Communication Slice Delivery Delay
- **Blocker ID & Title**: `BLOCK-P4-001: P4 Communication Slice Delivery Delay`
- **Affected Owners**: `P5` + `P4` (downstream full-team integration)
- **Contract / Endpoint / Event Affected**: `REQUIREMENTS_SYSTEM.md` §3.5 (`CommunicationRequest`, `Confirmation`), §4 handshake (`confirmation.accepted|rejected|counteroffer_received`), and UI routes `/communications`, `/confirmations/:id` (§5)
- **Observed Mismatch**: Only scaffold schemas and 14 foundation tests exist on `origin/P4-communication`; no live draft/send/confirm API routes or confirmation workspace UI have been authored, blocking the customer closed-loop confirmation and proposal acceptance flow required for the Oct 22 integration milestone.
- **Proposed Compatible Resolution**: P4 owner must immediately scaffold the confirmation workspace UI and implement the core communication endpoints (`POST /v1/communications/draft`, `POST /v1/confirmations/{id}/respond`) adhering to `REQUIREMENTS_SYSTEM.md` §3.5.

### BLOCK-P1-001: P1 Context Intelligence Unmerged Branch & Config Drift
- **Blocker ID & Title**: `BLOCK-P1-001: P1 Context Intelligence Unmerged Branch & Config Drift`
- **Affected Owners**: `P5` + `P1`
- **Contract / Endpoint / Event Affected**: `REQUIREMENTS_SYSTEM.md` §3.1 (`BusinessContext`), §4 handshake (`business.context_updated`), root `pyproject.toml`, `frontend/package.json`, and `/inbox` route
- **Observed Mismatch**: P1 has functional ingestion and extraction code on `feat/p1-context-intelligence`, but the branch contains uncoordinated edits to root configuration files and has not submitted a clean PR to `main`, leaving `/inbox` as a placeholder on `main`.
- **Proposed Compatible Resolution**: P1 to rebase onto latest `origin/main`, revert uncoordinated modifications to shared config files (`pyproject.toml`, `package.json`, `vite.config.ts`), and open a clean PR to `main`.

### BLOCK-P3-001: P3 Recovery Slice PR Merge & Auth Adapter Wiring
- **Blocker ID & Title**: `BLOCK-P3-001: P3 Recovery Slice PR Merge & Auth Adapter Wiring`
- **Affected Owners**: `P5` + `P3`
- **Contract / Endpoint / Event Affected**: `REQUIREMENTS_SYSTEM.md` §3.4 (`RecoveryPlan`), §4 handshake (`recovery.communication_requested`), and router mounting under `/v1/recovery`
- **Observed Mismatch**: P3 slice on `feat/p3-recovery` passed Task T4.2-A audit, but PR to `main` is unmerged; planner `RecoveryPlanner._get_commitment` hardcodes `com_001` lookup; HTTP approval endpoints use unverified context adapter returning 403 on live calls.
- **Proposed Compatible Resolution**: P3 to open clean PR to `main`; wire verified role adapter mapping server-side headers (`X-Tenant-ID`, `X-Actor-ID`) to `context.actor_role in {"OWNER", "MANAGER"}`; fall back to `P5CommitmentReader` for arbitrary commitment IDs.

### BLOCK-P2-P5-004: P2/P5 Phase 7B-2 Joint Adapter Integration & Route Mounting
- **Blocker ID & Title**: `BLOCK-P2-P5-004: P2/P5 Phase 7B-2 Joint Adapter Integration & Route Mounting`
- **Affected Owners**: `P5` + `P2`
- **Contract / Endpoint / Event Affected**: `backend/app/feasibility/api_dependencies.py`, `backend/app/main.py`, and `frontend/src/App.tsx` routes `/commitments/:id`, `/impact/:id`
- **Observed Mismatch**: Feasibility engine is merged (PR #6), but P2 router is unmounted in `main.py` and returns 503 until P5 provides integration adapters for `CommitmentService.assess()` and `reservations.get_resource_snapshot()`; `App.tsx` uses `FeaturePlaceholder`.
- **Proposed Compatible Resolution**: P5 (in Task Phase 7B-2) implements adapters in `backend/app/feasibility/api_dependencies.py`, mounts `feasibility_router` in `backend/app/main.py`, and wires `CommitmentFeasibilityPage` and `ImpactDetailPage` into `frontend/src/App.tsx`.


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
- **Gate:** synchronization and applicable local regression checks passed; branch is ready for independent review of the sync. No P2 PR was created, no P2-to-Main merge or Phase 7 work was performed. Orbyte access is optional and was not used.

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

### 2026-10-21 — Task T4.1: GitHub Actions CI Workflow, Docker Compose Seed & Windows DevEx Documentation (DEV-1 to DEV-5, UI-06, BE-03f)
- **Status**: Complete & Verified (Commit `1497f1e`).
- **Scope & Changes**:
  1. **GitHub Actions CI (`.github/workflows/ci.yml`, `DEV-5`)**:
     - Job 1 (`backend-tests`): Python 3.12, installs backend in editable mode (`pip install -e "./backend[dev]"`), executes `compileall` syntax validation across `backend/app`, and runs full `pytest -v backend/tests` (80 tests: unit, concurrency, outbox, E2E journey, and identity guards).
     - Job 2 (`frontend-checks`): Node.js 20, runs `npm ci`, `npm run typecheck`, `npm test -- --run` (Vitest), and `npm run build` (`vite build`).
     - Job 3 (`hygiene-check`): Enforces `.env.example` existence and placeholder-only compliance (scans for unmasked tokens/keys), and asserts zero leftover legacy branding (`PromiseFlow`) across all frontend, backend, and contracts source files.
  2. **Docker Compose & Synthetic Seed Reproducibility (`DEV-1`, `BE-03f`)**:
     - `docker-compose.yml`: Automated start sequence running PostgreSQL on 5433, Backend API on 8000 (with active `/health` check), and Outbox worker.
     - Automated startup command runs `alembic upgrade head` and executes `python scripts/seed_demo.py` before serving traffic.
     - `backend/Dockerfile`: Added `COPY scripts ./scripts` so seed scripts are packaged into the runtime container.
     - Created `scripts/seed_demo.py`: Fully idempotent seed script populating stock levels (`BUN`, `PATTY`, `BURGER`, `GREENS`) and the 5 canonical demo commitments:
        1. `com_normal_01`: Standard confirmed feasible order (`CONFIRMED`, `FEASIBLE`, `NORMAL`).
        2. `com_001`: Material shortage of 40 beef patties triggering recovery (`CONFIRMED`, `INFEASIBLE`, `AT_RISK`, `RECOVERY_REQUIRED`).
        3. `com_delay_01`: Supplier delay with 2 alternate recovery proposals (`CONFIRMED`, `INFEASIBLE`, `AT_RISK`, `PENDING_APPROVAL`).
        4. `com_ambiguous_01`: Ambiguous customer reply requiring manual review (`OFFERED`, `requires_manual_review=True`).
        5. `com_fulfilled_01`: Verified operational completion (`CONFIRMED`, `FULFILLED`, `RESOLVED`, signed POD proof).
     - Added automated verification in `backend/tests/test_seed_demo.py`.
  3. **Environment Template (`DEV-3`)**:
     - Created `.env.example` containing variable names and placeholders only for DB, API, CORS, Vite, and Outbox. Zero secrets or real keys committed.
  4. **Documentation & Windows PowerShell DevEx (`DEV-2`, `DEV-4`)**:
     - Rewrote `README.md` with product identity (**MouManTAI**), architecture overview, single-command Docker Compose startup, manual local setup steps, testing guides, synthetic scenario breakdown, and CI badges.
     - Documented explicit Windows PowerShell execution policy troubleshooting (`PSSecurityException` on `npm.ps1`), instructing developers to use `cmd /c npm ...` or `npm.cmd ...`.
- **Validation Results**:
  - `python -m pytest backend/tests`: Passed (80 passed, 0 failed in 1.51s).
  - `cmd /c npm run typecheck`: Passed (0 errors).
  - `cmd /c npm test`: Passed (28 passed, 5 skipped).
  - `cmd /c npm run build`: Passed (`dist/` generated cleanly in 841ms).
  - Hygiene check: Passed (zero secret patterns, zero `PromiseFlow` occurrences).
### 2026-10-21 — P2 Phase 7A independent gap closure and integration readiness

- **Branch/scope:** clean starting repository; fetched Main `ee4dfc73deb998a5af902422220cb1a34e0182cc` contains PR #4; created `feat/p2-phase7-integration` directly from it. Only P2 feature source/tests/docs and these P2 log entries changed. No shared contract, migration, auth, app/router mount, P3 module, Main or old P2 branch changes. Feature-only commit/push authorized; final SHAs in task response.
- **Implementation:** `supplier_pipeline.py` validates snapshot IDs/versions, previous/updated ETA, exact supplier-delivery/resource binding and linked typed claim, then delegates to existing impact/evaluator. Complete synthetic cases demonstrate one impacted/one buffered-unaffected and two impacted; incomplete/stale/confounded remain UNKNOWN; preexisting shortage causes no new alert. `python -B -m app.feasibility.demo` (backend) prints eight scenarios with snapshots/calculations/evidence/replay; all repeat calls return zero new intents in synthetic reference history.
- **P2 domain/readiness:** canonical assessment mapping preserves empty actual Impact Set; serialized append-only reference history binds complete snapshot/Core/proposal contents, tenant lookup and event payload conflicts; actual P5 stock helper read preserves Decimal/reserved/available/unit/resource versions and reports INCOMPLETE or UNAVAILABLE. No fabricated complete snapshot, global version, source provenance, reservation owners or durable replay/outbox claim.
- **Validation:** backend `python -B -m pytest -o 'addopts=' app/feasibility/tests tests -q -p no:cacheprovider` — **291 passed, 0 failed/skipped**, one existing Starlette/httpx warning (212 P2 + 79 P5). Frontend `cmd /c npm test` — **108 passed, 5 skipped**, zero failed; `cmd /c npm run typecheck` and `cmd /c npm run build` exit 0. Combined-router/runtime class identity probe passes; official P3 fixture is **FEASIBLE / COMPLETED**. Python 3.14.3 / pytest 9.1.1 remains outside declared pytest <9. No new dependencies, destructive DB seed/reset, live PostgreSQL, authenticated API or real browser E2E run.
- **Measured synthetic metrics:** `python -B -m app.feasibility.benchmark --iterations 10`; false-feasible **0/2**, impact recall **3/3**, false-alert **0/3**, stale current-safe acceptance **0/2** through actual public-route guard. Six feasibility cases; eight impact scenarios/16 commitment observations, six known causal labels, ten null labels excluded; nine UNKNOWN outputs retained. Median/p95 in `PHASE7A_METRICS.json`; repetitions measure latency, not independent sample size. Small synthetic benchmark does not prove production accuracy. Mutation test disabling current guard detects unsafe acceptance.
- **Handoffs/blockers:** `PHASE7A_HANDOFF.md` specifies exact P3 imports/typed inputs and P5 source/version/identity/history/schema/transaction/outbox/public transport/mounting tasks with joint tests. P3 branch `ca7517c` inspected read-only, not merged; newer adapter accepts module function but needs full authoritative snapshot and typed proposals. P5 SERVICE identity must be server-resolved, separate from requesting user; no client header privilege promotion. Public P2 dependency defaults still fail closed. Direct P1 requested-context mapping remains a joint contract task.
- **Review:** internal reviewer found history content-binding and tautological stale-metric gaps; red regressions reproduced both plus unresolved-Core result mismatch, then fixes passed. Existing evaluation identities/math and impact/event IDs preserved; additive local input digest binds complete impact input. Internal review is not external Phase 7B approval. Stop after validated feature push for independent review; no PR automatically created.

- **P2 implementation commits:** `653936a` supplier pipeline; `6de2e7b` bound history/resource readiness; `d16aa45` independent metrics/current guard. Documentation checkpoint and feature-only remote verification follow in task response.


### 2026-10-21 — P2 Phase 7A approved follow-up: first-insert result integrity

- **Finding:** approved baseline `0f82ced0cdbac248d49efaaa10b0b223f27152af` bound recorded inputs but allowed first-insert result tampering with original IDs/digests. Red history run: 13 failed / 15 passed; each tampered output was accepted instead of rejected.
- **Correction:** only SyntheticHistoryRepository reruns existing `evaluate` / `recalculate_supplier_delay` from complete recorded inputs and compares the entire expected result before acceptance. No ignored fields, duplicated business rules, producer semantic changes or user-forgeable token. Rejections leave the empty repository unchanged; genuine UNKNOWN, typed proposals and replay preserved.
- **Validation:** backend focused history/impact command `python -B -m pytest -o 'addopts=' app/feasibility/tests/test_history.py app/feasibility/tests/test_impact.py -q -p no:cacheprovider` — 52 passed; full `python -B -m pytest -o 'addopts=' app/feasibility/tests tests -q -p no:cacheprovider` — 307 passed (228 P2 + 79 P5), zero failures/skips, one existing Starlette/httpx warning. Frontend `cmd /c npm test` — 108 passed / 5 skipped; typecheck/build exit 0. No dependency changes or live production E2E claim.
- **Production boundary:** P2 AssessmentWriter contract and handoff explicitly require exact P2 output through trusted server-side execution plus transactional version checks. Never authenticate results with input hashes or caller-supplied assessment objects. P5 writer must not recalculate/change the result; stale inputs reject back to P2 flow. Synthetic comparison proves consistency with recorded inputs only; P5 trusted writer/source/auth/transaction integration remains pending. No P5/P3-owned code changed.
- **Scope/Git:** history.py, ports.py, test_history.py and P2 handoff/progress/trace/report plus this P2 log entry only. Commit/push only feat/p2-phase7-integration; final remote SHA in task response. No PR/Main integration or Phase 7B; stop for review.


### 2026-10-21 — P2 Phase 7B-1 integration readiness

- **Baseline/branch:** verified `origin/main` at `03d5928e060271585a617afb3733b83732e6d4cd` (PR #5 merge with approved Phase 7A/history integrity); created new `feat/p2-phase7b-integration` from that exact SHA. Existing Phase 7A branch was clean and left unchanged. Read-only P3 `ca7517c7c09390f0926d01825e689dbf1a8c8ca6` and P5 `5823db8c89d509243f904d988f865a6777ea6c4` were not treated as Main implementation or confirmed owner replies.
- **P2-only implementation:** added injected public GET mapping for Core commitment, P2 assessment history and P2 impact results; the mapping leaves current snapshot/details, trigger source values and Core risk transitions unavailable when the API does not supply them. Added a SERVICE/SYSTEM role gate before internal evaluation authority resolution. No engines, shared contracts, Core/auth/DB/migrations, app routes or P3/P5 modules changed.
- **Validation:** P2 backend **229 passed**, P5/shared backend **79 passed**, combined **308 passed**; one existing Starlette/httpx deprecation warning per pytest invocation. `python -B -m app.feasibility.demo` exit 0 and explicitly reports synthetic process-local data. Frontend **118 passed / 5 skipped**, typecheck/build exit 0; five skips include gated live API, plus Vitest jsdom worker advisory. Focused P2 router 25 passed; focused adapter/currentness Vitest 18 passed.
- **Integration blockers:** P5 still needs trusted requester/SERVICE identities, complete authoritative snapshots/current version, durable exact-result AssessmentWriter/history and ImpactReader, atomic supplier processor/Core risk/audit/outbox, production router mount, authenticated frontend transport/detail contracts and P2 route mounting. P3 must confirm the authoritative typed call through the latest evaluator adapter. Exact dependency matrix and requested interfaces are in `PHASE7B1_INTEGRATION_READINESS.md`.
- **Evidence boundary:** test doubles use local SQLite and injected dependencies. No live PostgreSQL/migration, authenticated API, durable P2 writer, mounted P2 page, browser flow, or joint P2/P5/P3 E2E was run. Open `BLOCK-20261021-001` still blocks live DB migration/smoke validation because Docker exposes WSL1.
- **Checkpoint:** validated implementation commit `1507b5918b8ea9200aba4edca9b618929386e1fd` was pushed only to `origin/feat/p2-phase7b-integration`; remote ref matched at push time. Follow-up documentation records the checkpoint; final branch head is in the task result.
- **Gate:** P2-local readiness is validated for independent review. Do not begin 7B-2 or joint production wiring before separate approval. No PR or Main merge was created.

### 2026-10-21 — Task T5.1: P2 Phase 7B Integration Merge & Combined Baseline Validation (P2/P5)
- **Status**: Complete & Verified (Merge commit `71ee80f` + validation).
- **Scope & Changes**:
  1. **Branch Integration**: Merged `origin/feat/p2-phase7b-integration` into `feat/p5-core-integration`. Resolved single conflict in `docs/TEAM_LOG.md` cleanly, preserving both P5 Task T4.1 and all P2 Phase 7A/7B logs.
  2. **Environment & Dependency Compatibility**: Added `tzdata>=2024.1` to `backend/pyproject.toml` dependencies ensuring robust cross-platform validation for IANA timezone keys (including `Asia/Kuala_Lumpur`) on Windows hosts lacking system tzdata.
  3. **Combined Baseline Verification**:
     - Backend tests: `309 passed, 0 failed` across `backend/tests` (80 tests) and `backend/app/feasibility/tests` (229 tests).
     - Frontend tests: `118 passed, 5 skipped` (gated live API) in Vitest across all Core and Feasibility test files.
     - Frontend typecheck: Passed (`tsc --noEmit`, 0 errors).
     - Frontend production build: Passed (`vite build`, generated in 895ms).
- **Next Steps for Phase 7B-2**:
  - Implement P5 integration adapters in `backend/app/feasibility/api_dependencies.py` connecting P2 ports to `CommitmentService.assess()` and `reservations.get_resource_snapshot()`.
  - Mount `feasibility_router` in `backend/app/main.py` and feature pages in `frontend/src/App.tsx`.
  - Execute joint E2E supplier delay -> P2 recalculation -> Core risk transition -> dashboard flow.

### 2026-10-21 — Task T4.2-B: Daily Integration Sync Status & Blocker Triage (TL-1)
- **Status**: Complete & Verified (Audit, test runs, and triage recorded).
- **Scope & Findings**:
  1. **Single-Commitment Hero Journey (`F1 -> Core -> F2 -> Core -> F3 -> Core -> F4 -> Core -> Fulfilment`)**:
     - Authoritative backend lifecycle verified on single `commitment_id` (`com_001`) through 9 monotonic versions (`REQUESTED` v1 -> `FEASIBLE` v2 -> `OFFERED` v3 -> `CONFIRMED` v4 -> `INFEASIBLE`/`AT_RISK` v5 -> `PLANNING` v6 -> revised `OFFERED` v7 -> customer `CONFIRMED` v8 -> operational POD `FULFILLED` v9).
     - Cross-module handshakes: P2 calculation verified and merged to `main` (PR #6); P3 recovery slice audited and approved in Task T4.2-A (PR pending); P1 ingestion/extraction slice functional on branch `feat/p1-context-intelligence` (PR pending); P4 communication critically delayed (scaffold only).
  2. **Feature Route Wiring Matrix**:
     - `/overview` (P5): **LIVE BACKEND API** (`GET /v1/overview`).
     - `/activity` (P5): **LIVE BACKEND API** (`GET /v1/commitments/{id}/timeline` / audit).
     - `/inbox` (P1): **FIXTURE / PLACEHOLDER** in `App.tsx` (P1 `DurableInbox` unmerged on `feat/p1-context-intelligence`).
     - `/orders/:id` (P1): **FIXTURE / PLACEHOLDER** in `App.tsx` (P1 `OrderContextDetail` unmerged).
     - `/commitments/:id` (P2): **FIXTURE / PLACEHOLDER** in `App.tsx` (`CommitmentFeasibilityPage` in repo with synthetic preview + `apiSource.ts`, awaiting Phase 7B-2 mount).
     - `/impact/:id` (P2): **FIXTURE / PLACEHOLDER** in `App.tsx` (`ImpactDetailPage` in repo with synthetic preview + `apiSource.ts`, awaiting Phase 7B-2 mount).
     - `/recovery/:id` (P3): **FIXTURE / PLACEHOLDER** in `App.tsx` (`RecoveryPage` unmerged on `feat/p3-recovery`).
     - `/communications` (P4): **FIXTURE / PLACEHOLDER** in `App.tsx` (P4 UI not implemented).
     - `/confirmations/:id` (P4): **FIXTURE / PLACEHOLDER** in `App.tsx` (P4 UI not implemented).
  3. **Blockers & Bug Assignments**:
     - `BLOCK-P1-001` (Assigned: P1): Rebase `feat/p1-context-intelligence` on latest `main`, clean shared config collisions (`pyproject.toml`, `package.json`, `vite.config.ts`), and open clean PR.
     - `BLOCK-P3-001` (Assigned: P3): Submit clean PR for `feat/p3-recovery` to `main`; wire server-side auth adapter (D-005) and multi-commitment reader.
     - `BLOCK-P4-001` (Assigned: P4): CRITICAL. Implement draft/send/confirm API endpoints and confirmation workspace UI to unblock Oct 22 customer confirmation loop.
     - `BLOCK-P2-P5-004` (Assigned: P5): In progress. Phase 7B-2 joint adapter implementation and router mounting.
- **Validation**:
  - Backend tests: `309 passed, 0 failed` (`pytest tests app/feasibility/tests`).
  - Frontend tests: `118 passed, 5 skipped` (`cmd /c npm test -- --run`).
  - Frontend typecheck: Passed (`tsc --noEmit`, 0 errors).
  - Frontend build: Passed (`vite build`, generated in 821ms).

### 2026-10-21 — Task T5.1: Feature Freeze Regression & Quantitative Metrics Report (REQUIREMENTS §7, PERSON_5 §8)
- **Status**: Complete & Verified (Reproducible evaluator and honest measured metrics report generated).
- **Scope & Implementation**:
  1. **Reproducible Metrics Evaluator (`scripts/evaluate_metrics.py`)**:
     - Authored standalone CLI benchmark harness running against isolated in-memory test database and FastAPI `TestClient(app)`.
     - Integrated 12 E2E acceptance scenarios (`E2E-01` through `E2E-12`) via real integration test suite calls.
     - Implemented atomic audit and outbox completeness evaluator verifying pairing of `AuditEventRecord` and `OutboxEventRecord` across all lifecycle mutations.
     - Implemented 7 security probes testing: Staff recovery execution (403), Staff fulfilment recording (403), Cross-tenant read (404), Cross-tenant mutation (404), Stale snapshot drift (409), Concurrency version conflict (409), and direct lifecycle PATCH prohibition (405).
     - Implemented 4 false-fulfilment & confirmation guardrail checks verifying `SENT != ACCEPTED != FULFILLED` (message delivery does not auto-advance state, vague "OK" flags `CLARIFICATION_REQUIRED`, unverified payment slip rejected with 422, OCR context keeps `REQUESTED`).
     - Implemented wall-clock latency benchmarking (N=15 iterations) across 9 Core lifecycle operations (`context_ingest`, `feasibility_assess`, `proposal_offer`, `proposal_confirm`, `recovery_start`, `recovery_execute`, `fulfilment_record`, `overview_query`, `timeline_query`).
  2. **Quantitative Metrics Report (`docs/metrics_report.md`)**:
     - Generated markdown report containing measured metrics tables, hardware/platform disclosures (Windows 11 AMD64, Python 3.14.7), sample sizes, and explicit hackathon synthetic limitations per `REQUIREMENTS_SYSTEM.md` §7 and `AGENTS.md` §8/§10.
- **Measured Metrics Summary**:
  - **E2E Acceptance Scenarios**: **100.0% (12/12 passed)** across `E2E-01` to `E2E-12`.
  - **Audit & Outbox Atomic Completeness**: **100.0% (13/13 paired lifecycle transitions)**; zero unpaired mutations.
  - **Unauthorized & Stale Action Block Rate**: **100.0% (7/7 blocked)**; **0 unauthorized mutations permitted**.
  - **False Fulfilment / False Confirmation Rate**: **0.0% (0/4)**; strict invariant adherence verified.
  - **Core Command Latencies (p50 / p95 in ms)**:
    - Context Ingest: `p50=5.35 ms`, `p95=15.32 ms`
    - Feasibility Assess: `p50=1.15 ms`, `p95=1.72 ms`
    - Proposal Offer: `p50=6.02 ms`, `p95=8.04 ms`
    - Proposal Confirm: `p50=6.09 ms`, `p95=16.44 ms`
    - Recovery Start: `p50=5.71 ms`, `p95=6.53 ms`
    - Recovery Execute: `p50=6.62 ms`, `p95=7.59 ms`
    - Fulfilment Record: `p50=5.61 ms`, `p95=6.45 ms`
    - Overview Query: `p50=5.70 ms`, `p95=7.77 ms`
    - Timeline Query: `p50=5.09 ms`, `p95=7.53 ms`
- **Validation**:
  - Metrics script: `python scripts/evaluate_metrics.py` (exited with code 0; generated `docs/metrics_report.md`).
  - Backend tests: `309 passed, 0 failed` (`pytest tests app/feasibility/tests -q`).
  - Frontend tests: `118 passed, 5 skipped` (`cmd /c npm test -- --run`).
  - Frontend typecheck: Passed (`tsc --noEmit`, 0 errors).
  - Frontend build: Passed (`cmd /c npm run build`, 0 errors).

### 2026-10-21 — Task T5.2: Clean-Room Deployment Verification & Security/Scope Guardrail Audit (SAF-6, SC-1)
- **Status**: Complete & Verified (Zero secret leaks, zero scope-lock violations, zero leftover PromiseFlow UI branding, clean deployment rehearsal).
- **Scope & Audit Execution**:
  1. **Product Identity Check**:
     - Verified `backend/app/main.py` OpenAPI metadata: `title="MouManTAI API"`.
     - Verified `frontend/index.html`: `<title>MouManTAI</title>`.
     - Verified `frontend/package.json`: `"name": "moumantai-frontend"`.
     - Verified zero user-facing `PromiseFlow` strings across all code and UI components (`frontend/src/`, `contracts/`, `backend/app/`). CI workflow updated with `--exclude="*.md"` to prevent legacy log trips while strictly guarding code surfaces.
  2. **Secrets & PII Hygiene (`SAF-6`, `DEV-3`, `AGENTS.md` §9)**:
     - Verified `.gitignore` ignores `.env` and `.env.*` while keeping `.env.example`.
     - Scanned `.env.example`: verified placeholder values only (`replace_with_local_postgres_password`, `INTEGRATION_MODE=SYNTHETIC`); zero leaked API tokens (`sk-`, `ghp_`, `AKIA`) or private keys.
     - Verified `git ls-files` tracks `.env.example` only; no live secrets in git history or seed fixtures.
  3. **Scope Lock Audit (`SC-1`, `REQUIREMENTS_SYSTEM.md` §9)**:
     - Verified zero claims of live Orbyte API connectivity exist (all docs and adapters explicitly declare synthetic/hypothetical Orbyte-compatible interface).
     - Verified direct lifecycle override `PATCH /v1/commitments/{id}` is strictly rejected with HTTP 405 `UNRESTRICTED_PATCH_FORBIDDEN` and zero state mutation.
     - Verified server-side auth (`X-Tenant-ID`, `X-Actor-ID` mapped to `ACTOR_ROLES`) rejects body-spoofed roles (`"role": "OWNER"`) with HTTP 422 (`extra="forbid"`) and strictly blocks unauthorized staff mutations with HTTP 403 `APPROVAL_REQUIRED`.
  4. **End-to-End Rehearsal Verification**:
     - Executed Alembic database migrations from base to head (`0001_foundation` through `0005_resource_reservations`) with 0 errors.
     - Executed `scripts/seed_demo.py` and validated idempotent double-run populating the 5 canonical demo commitments (`com_normal_01`, `com_001`, `com_delay_01`, `com_ambiguous_01`, `com_fulfilled_01`) and inventory stocks.
     - Automated all audit verifications into permanent test suite: `backend/tests/test_clean_room_audit.py`.
- **Validation**:
  - Clean room audit tests: `6 passed` (`pytest tests/test_clean_room_audit.py -v`).
  - Full backend test suite: `315 passed, 0 failed` (`pytest tests app/feasibility/tests -q`).
  - Metrics benchmark: `python scripts/evaluate_metrics.py` (exited 0, all 5 metric categories 100% passing).
  - Frontend test suite: `118 passed, 5 skipped` (`cmd /c npm test -- --run`).
  - Frontend typecheck: `tsc --noEmit` passed (0 errors).
  - Frontend build: `cmd /c npm run build` passed (production bundle built in 881ms).

### 2026-10-22 — Task T5.3: Final P5 Integration Handoff Sign-Off & Checklist Audit (PERSON_5 §10, HO-1)
- **Status**: Complete, Verified & Signed Off by Person 5 (Core Architecture, Registry, Outbox/Audit, Shell & Contracts).
- **Handoff Checklist Verification (`PERSON_5` §10)**:
  1. [x] **Exact contracts/types usable on frontend and backend**:
     - Backend Pydantic v2 domain schemas (`backend/app/core/schemas.py`) and TypeScript interfaces (`contracts/types.ts`, `frontend/src/shared/types/`) are 100% synchronized, type-safe, and frozen.
     - Verified by `backend/tests/test_contracts.py` and `frontend/src/app/__tests__/RoleGuardAndNavigation.test.tsx`.
  2. [x] **All modules share `tenant_id`, `commitment_id`, and 5-dimension state semantics**:
     - Unified authoritative `CommitmentRecord` aggregate with composite primary key `(tenant_id, commitment_id)` and independent lifecycle dimensions (`agreement_state`, `feasibility_state`, `risk_state`, `recovery_state`, `fulfilment_state`).
     - Invariants enforced server-side: `REQUESTED != CONFIRMED`, `FEASIBLE` snapshot-specific, `CONFIRMED + AT_RISK` valid, `SENT != ACCEPTED != FULFILLED`, `APPROVED != EXECUTED`, and direct `PATCH` prohibited (`HTTP 405`).
  3. [x] **Domain events persisted and traceable, no dropped audit**:
     - Atomic dual-write writes `AuditEventRecord` (with full JSON state snapshots, evidence refs, causation/correlation) and `OutboxEventRecord` in the exact same database transaction.
     - 100.0% completeness verified across all 13 evaluated lifecycle transitions (`scripts/evaluate_metrics.py`).
     - Chronological timeline API (`GET /v1/commitments/{id}/timeline`) operational.
  4. [x] **Role gates validated server-side and in demo role UX**:
     - Server-side header inspection (`X-Tenant-ID`, `X-Actor-ID` mapped to `ACTOR_ROLES`) enforces RBAC (`OWNER`, `MANAGER`, `STAFF`).
     - Request body role/tenant spoofing strictly rejected with HTTP 422 (`extra="forbid"` on `ContractModel`).
     - Manager write actions (confirm proposal, execute recovery, record fulfilment) reject staff with HTTP 403 `APPROVAL_REQUIRED`.
     - Frontend `RoleSwitcher` and dynamic navigation badges active in app shell.
  5. [x] **Main journey, negative-case tests, and deployment docs reproducible**:
     - Single-commitment Hero Journey (`com_001` through v1 to v9) verified in `backend/tests/integration/test_e2e_hero_journey.py`.
     - 12-scenario negative test matrix (`E2E-01` through `E2E-12`) verified in `backend/tests/integration/test_e2e_negative_matrix.py`.
     - Seed script (`scripts/seed_demo.py`) and quantitative evaluation script (`scripts/evaluate_metrics.py`) verified and reproducible.
     - `README.md` documents environment setup, Windows PowerShell DevEx (`cmd /c npm ...`), database migrations, and testing commands.
  6. [x] **`TEAM_LOG.md` reflects actual PR status, blocked tasks, and architectural decisions (no fake checkmarks)**:
     - Architectural baseline decisions (`D-001` through `D-012`, `D-013`, `D-CONTRACT-005`, `ADR-001` through `ADR-010`) documented with zero silent reversals.
     - Cross-module handoff status honestly reflected:
       - **P5**: All Core components, audit/outbox, application shell, overview/activity, integration facade, metrics, and security audits complete.
       - **P2**: Feasibility, impact, supplier pipeline merged to `main` (PR #5, PR #6); Phase 7B merged to P5; Phase 7B-2 adapter integration ready.
       - **P3**: Recovery planner audited & approved (Task T4.2-A); PR to `main` pending (`BLOCK-P3-001`).
       - **P1**: Context extraction functional on branch; PR to `main` pending (`BLOCK-P1-001`).
       - **P4**: Communication slice scaffolded; UI and live endpoints critically delayed (`BLOCK-P4-001`).
- **Final Validation Test Evidence**:
  - Backend tests: `315 passed, 0 failed` (`pytest tests app/feasibility/tests -q`).
  - Frontend typecheck: `tsc --noEmit` passed (0 errors).
  - Frontend unit/component tests: `118 passed, 5 skipped (live smoke), 0 failed` (`cmd /c npm test -- --run`).
  - Frontend production build: `tsc -b && vite build` built in 841ms (0 errors).
  - Quantitative metrics report: Generated with measured numbers only (`docs/metrics_report.md`).

## 2026-10-22 — P4 Commit 03: Template-Based Message Drafting

- Baseline: local `P4-communication`, HEAD `443ff6cab6178ad3109669a46262701073e81ad2`. Implementation and verification performed in an isolated copy; real repository unchanged.
- Implemented: deterministic English (`en`), Bahasa Melayu (`ms`) and Simplified Chinese (`zh`) delivery-change drafts; exact approved SKU/quantity/unit/deadline and complete special instructions; email-only subject; provider-independent plain text. Unknown material terms or missing required terms block generation.
- Safety: prepare AND retrieval re-read scoped current Core proposal/commitment and invoke a trusted action-specific `DraftAuthority`. Current version, expiry, revocation, approved terms, recipient and channel evidence must pass. No stale snapshot fallback; default production authority is absent and fails closed. Hashes track content; fresh rendering plus full metadata comparison establishes consistency. Status is DRAFT with `send_authorized=false`.
- Persistence: SQLAlchemy `communication_drafts` model/repository, composite tenant/request FK, unique draft variant, atomic draft/audit/outbox transaction, scoped retrieval and idempotent reuse after fresh validation. Reference-only `communication.draft_prepared` audit/outbox association; no body/contact details in those payloads. No Core state changes or sends.
- Changed files: communication/{schemas,service,models,repository,router}.py and frontend/src/features/communication/types.ts. New: communication/{templates,drafting}.py and communication/tests/test_drafting.py. Existing foundation/request tests retained byte-for-byte. Shared code, migrations, main, contracts and AGENTS.md untouched.
- Tests actually run: `python -B -m pytest app/communication/tests -v`: 140 passed, 0 failed, 0 skipped (81 existing + 59 new; 1 existing Starlette/httpx warning). Refactor initially exposed two obsolete local-variable references; corrected and full P4 suite rerun successfully. `python -B -m pytest tests -v -k 'not test_thread_concurrent_reservations_prevent_overallocation'`: 78 passed, 0 failed, 1 deselected, 0 skipped (1 existing warning). That single Core test was deliberately excluded because of the previously reported Windows Python 3.13 access violation; no claim of full-suite verification. Frontend `npm run typecheck`, `tsc --noEmit -p tsconfig.app.json`, and `npm run build` passed. No frontend test suite or real PostgreSQL/production API end-to-end test run. P4 uses isolated SQLite plus PostgreSQL DDL compilation checks.
- Current integration status: repository includes Core migration `0005_resource_reservations`, but P4 tables/model registration, router mount and trusted authority providers are still absent. Module APIs were exercised through TestClient; main application does not expose them yet.
- P5 dependency: register P4 models in Alembic metadata; migrate Commit 02 request/source tables plus new `communication_drafts` with its composite FK/unique/index; mount P4 router; bind real RequestAuthority and DraftAuthority. Revalidation must enforce PREPARE_DRAFT/READ_DRAFT actor policy and current trusted approval, plan, terms, evidence, expiry/revocation and identity/channel mapping using read-only queries in the passed Session, without commit/rollback or mutation. Review generic draft-prepared event integration. Do not enable test doubles or blanket approvals in production.
- P3/P5 dependency: provide authoritative approved recovery-plan/proposal references and expiry, evidence and revocation lookup. P1 is not a drafting blocker; future sends/replies require P1 verified identity/contact mapping. No incoming parser, webhook or duplicate identity store added.
- Future live Telegram/WhatsApp: no SDK, secrets, live/mock send adapter or channel-enum changes included. Shared enum currently supports only MOCK channels/UNKNOWN; P5 must add LIVE values through shared contracts before they are accepted. Future adapters/send preparation must revalidate and map provider requirements, including WhatsApp approved template ID/language/parameters where required. Ordinary preview text is not a provider-approved WhatsApp template.
- Limitations: only built-in delivery_change template v1; required SKU/quantity/unit/deadline follow current CommitmentTerms contract. No human edits, approval workflow, delivery tracking, acceptance, fulfilment, sending, AI or frontend UI. A saved draft never grants permission to send.
- Next milestone: Commit 04 — Communication Center UI (not started).
- Git status: not committed; no add/commit/push/merge/rebase or branch switch performed. Suggested future commit: `feat(p4): implement version-safe message drafting`.

## 2026-10-22 — Person 4 / Commit 04: Communication Center Frontend UI

- Baseline: real local P4-communication branch was clean and already contained Commit 01-03 (including drafting.py/templates.py and draft APIs). Implementation performed only in an isolated copy. No branch switch, git add/commit/push/merge/rebase/reset or changes to the real repository.
- Implemented: exported CommunicationCenterPage; real-API request list/detail; loaded-data reference/status/channel filtering; three metrics only (Total, Drafted, Needs Attention); request/proposal/plan references; read-only terms and evidence snapshots; blocked reasons; language selection en/ms/zh; POST prepare followed by GET persisted draft revalidation; read-only preview with optional email subject; known-session draft selection and existing draft lookup by ID; loading/empty/error/permission/conflict/integration-pending/retry states.
- Status decision: Pending/Drafted/Sent/Blocked are frontend labels only. Request intake's default message_status=DRAFT is not proof of a saved draft. Drafted requires a successful current draft read; counts describe this session's checked drafts, not a server-wide draft total. Current intake schema is DRAFT-only, so Sent/Sending cannot arise from today's API. Defensive display mapping for future typed integration keeps QUEUED/SUBMITTED as Sending, FAILED as Blocked, DELIVERY_UNKNOWN as Blocked (never confirmed delivery); no confirmation or fulfilment state is used as communication status. Future response-contract changes require explicit client updates, not silently trusting new fields.
- Safety: shared apiRequest/authHeaders/AuthProvider/TanStack Query reused. Cache keys include tenant AND actor AND request/draft. Local selection/known IDs clear on tenant/actor change; no persistent browser draft/contact store. Query cancellation, unmount abortion of prepare, duplicate-click guard, no automatic mutation retry, revalidation on reopening/focus/manual recheck, immediate preview hiding while manually rechecking, expiry hiding, and response-scope checks prevent misleading stale previews. Backend is the authority; UI never generates terms, approves, sends, accepts or fulfils. Unknown errors use safe messages rather than raw server stack traces.
- Files: updated frontend/src/features/communication/types.ts with P4-local intake response type while preserving shared exports and Commit 03 draft types. Added api.ts, presentation.tsx, CommunicationCenterPage.tsx, CommunicationDetails.tsx, DraftPreview.tsx, communication.css, CommunicationCenterPage.test.tsx. No App.tsx, AppShell, shared files, config/dependencies/contracts or Backend changes.
- Frontend validation: npm test => 179 passed, 0 failed, 5 skipped (184 total; 9 test files passed, 1 skipped). Includes 61 new P4 tests; all prior frontend tests retained. Five existing live API smoke tests skip unless LIVE_API=1; no seeded live service was run. npm run typecheck, tsc --noEmit -p tsconfig.app.json, npm run build passed. No lint script/config present. No Backend suite rerun because no Backend code changed; the Windows Core concurrency test was not run or modified.
- Test development: first P4 run exposed a cached preview remaining visible briefly after Recheck; fixed the UI to hide content synchronously and reran successfully. Tests cover real shared-client request shapes/headers, tenant/actor scope, stale/revoked/expired/503/403/network failures, rapid selection/out-of-order responses, repeat clicks, cached draft reopening, exact backend text and safe text rendering. Narrow-width test checks semantic interaction only; jsdom cannot prove CSS geometry.
- Backend integration check: TestClient on the unchanged main app GET /v1/communications returns 404. Router remains unmounted; RequestAuthority and DraftAuthority providers remain None; Alembic metadata imports Core only; migrations run through 0005_resource_reservations and do not create P4 tables. No production persistence or live happy-path UI/API E2E claim.
- Route integration: UI component implemented, awaiting P5 route integration. P5 must replace only the /communications placeholder with <CommunicationCenterPage /> and import it from ./features/communication/CommunicationCenterPage. Reuse existing QueryClientProvider, AuthProvider and Router; no second app/router or production preview entry was added. Current production build still builds the unmodified shell with its placeholder; the exported feature is typechecked and tested independently.
- P5 dependencies: route wiring; Backend P4 router registration; Commit 02 request/source and Commit 03 draft migrations/model metadata; real trusted RequestAuthority/DraftAuthority and action policies. Do not bypass authorization to make the demo populate. Supplied D-020–D-023 design approvals are not evidence that these runtime integrations exist.
- P1/P3/P5: future customer/contact names require trusted lookup; current UI uses actual returned IDs and recorded evidence only. P1 verified identity/contact mapping and P3/P5 current approval/version/revocation checks remain authoritative. No incoming parser or identity mapping duplicated. Live channel enums/provider adapters/WhatsApp official template mapping remain later work; no credentials or provider calls in UI.
- Known limitations: no draft-list/latest endpoint exists. Only IDs opened/prepared in the current mounted session are remembered; a known ID can be loaded via the existing retrieval API, but history cannot be discovered after reload/navigation. Backend list is a plain array without pagination; filtering covers the returned loaded set. Request readiness/terms/evidence are creation-time snapshots. This is a frontend implementation with API wiring, not full integrated deployment. Responsive CSS follows existing design; real-browser visual/narrow-screen and full App route E2E verification pending P5 mount.
- Next milestone: Commit 05 — Message Preview & Approval Workflow (not started). No fake approve/send button, confirmation workspace, delivery tracking or fulfilment UI included.
- Git status: not committed by this task. Suggested commit: feat(p4): build communication center frontend.

### 2026-10-22 — Task T5.4: P2/P3 Handoff Integration, Caller-Owned Transactions, Shell Hardening & Core Architecture Delivery (P5)
- **Status**: Complete, Verified & Delivered by Person 5 (Core Architecture, Registry, Outbox/Audit, Shell & Contracts).
- **Scope & Objectives**:
  - Implement agreed decisions D-002, D-005, D-017, D-030, D-032, D-033, and CONTRACT-20261021-005 from P2/P3 handoffs (`reply_P2.md`, `reply_P3.md`).
  - Strict preservation of lightweight SME footprint under AGENTS §5 & §13 (no generic ERP tables; Gap 1 closed as designed).
- **Key Changes Implemented**:
  1. **Caller-Owned Transactions (D-032, R26/R36/R55)**:
     - `CommitmentService.assess()` and `create_request()` support `commit: bool = True` with `db.flush()` semantics.
     - Outbox consumer dispatcher and `AuthoritativeAssessmentWriter` own transaction commits and rollbacks atomically with `ProcessedEventRecord`.
     - Verified: downstream consumer failure rolls back aggregate, outbox, audit, and processed events atomically (`backend/tests/test_outbox_events.py`).
  2. **D-017 Named Subscriber Policy Extended**:
     - `OutboxDispatcher` enforces named subscribers without wildcards: `p2_confirmed_evaluator` on `commitment.confirmed` and `p3.recovery_trigger.v1` on `commitment.at_risk`.
     - Unregistered or failing subscribers keep events in `PENDING`/`FAILED`; never prematurely published. Stale events reconciled via audit.
  3. **Advisory Feasibility Isolation (D-033)**:
     - Advisory feasibility assessments write exclusively to `AuditEventRecord` (`advisory=True`, `event_type="commitment.advisory_feasibility_assessed"`).
     - Advisory assessments never mutate aggregate state, never touch `revised_terms`, and never satisfy authoritative idempotency checks.
  4. **Contract Relaxation for `FeasibilityAssessment.affected_commitment_ids`**:
     - Field defaults to empty list `[]` representing downstream impact set. `contracts/types.ts` and JSON fixtures updated.
  5. **Snapshot Drift Detection & Intent Suppression**:
     - `AuthoritativeAssessmentWriter` detects resource/supplier snapshot drift against active reservations and returns HTTP 409 `SNAPSHOT_DRIFT_CONFLICT`.
     - Suppresses local P2 `commitment.at_risk` events; exactly one authoritative outbox event is emitted on verified aggregate transition.
  6. **Migration `0006_recovery_cases` (Task T5.3)**:
     - Added tables `recovery_cases` and `recovery_case_triggers` for P3 ORM persistence.
     - Enforces `tenant_id` on every table, composite unique constraints, partial index `uq_recovery_cases_one_active_per_commitment`, and `ON DELETE RESTRICT`. Tested upgrade and downgrade cleanly on Docker PostgreSQL.
  7. **Frontend Shell Building Blocks & Live P2 Route Mounting (FE-01a, FE-01b, FE-01c)**:
     - Mounted live `CommitmentFeasibilityPage` (`/commitments/:id`) and `ImpactDetailPage` (`/impact/:id`) in `App.tsx` with authenticated transport.
     - Added `Breadcrumbs` (`Overview > Commitments > com_001`) in `AppShell.tsx`.
     - Added `ErrorBoundary` with sanitized errors and retry affordance in `frontend/src/shared/ErrorBoundary.tsx`.
     - Added `ToastProvider` and `useToast()` in `frontend/src/shared/Toast.tsx` with invariant prohibiting success toasts on pending/awaiting states. Wired to proposal confirmation.
  8. **Section 4 Alias Methods & Policy Extraction (R43, R55)**:
     - Extracted server-side `authorize()` into `backend/app/core/policy.py`.
     - Added Section 4 facade aliases on `CommitmentService` (`request`, `offer`, `confirm`, `verify_fulfilment`, `mark_risk`, `start_recovery`, `record_action_outcome`).
- **Validation Test Evidence**:
  - Backend pytest: `322 passed, 0 failed, 1 warning` (`pytest tests app/feasibility/tests`).
  - Frontend Vitest: `126 passed, 5 skipped (live smoke), 0 failed` (`npm test -- --run`).
  - Frontend typecheck: `tsc --noEmit` passed with 0 errors.
  - Alembic migrations: `0001_foundation` through `0006_recovery_cases` upgrade & downgrade verified on PostgreSQL.

### 2026-10-22 — Task T-P3H1: Migration 0007 (Recovery Case Constraints Alignment), Fail-Closed Assessment History Reader, and Transaction A/B Isolation (P5 / ADR-017 / D-034)
- **Status**: Complete, Verified & Delivered by Person 5 (Core Architecture, Registry, Outbox/Audit, Shell & Contracts).
- **Decision / Impact / Owner**:
  - **Decision ID**: `ADR-017` (Decision `D-034`)
  - **Owner**: P5 (Shared Core, DB & Integration)
  - **Impact**:
    1. **Alembic Migration 0007 (`0007_recovery_case_constraints_alignment`)**:
       - Branches cleanly from `0006_recovery_cases` as the single head on `main`.
       - `recovery_cases` primary key remains composite `(tenant_id, case_id)`.
       - Renames unique constraint to plural form `uq_recovery_cases_tenant_case_commitment` on `recovery_cases(tenant_id, case_id, commitment_id)`.
       - Updates foreign key `fk_recovery_case_triggers_case_tenant_commitment` deletion policy to `ON DELETE RESTRICT` (append-only trigger history; prevents silent cascade deletion of audit evidence).
       - Retains partial unique index `uq_recovery_cases_one_active_per_commitment` covering exactly the 5 active statuses (`OPEN`, `AWAITING_EVALUATION_INPUTS`, `OPTIONS_READY`, `NO_SAFE_PLAN`, `NEEDS_REPLAN`).
       - Retains direct trigger-to-commitment foreign key on `(tenant_id, commitment_id)` referencing `commitments(tenant_id, commitment_id)` with `ON DELETE RESTRICT`.
       - Zero data loss: existing case and trigger rows preserved during upgrade. Symmetrical `downgrade()` cleanly restores 0006 constraints and `CASCADE` policy.
    2. **Fail-Closed Assessment Provenance Reader (`AuthoritativeAssessmentHistoryReader`)**:
       - Located in `backend/app/core/feasibility_adapters.py`.
       - Raises typed `DomainError("ASSESSMENT_PROVENANCE_MISSING", ...)` (HTTP 422) if candidate record lacks `assessment_id`, evaluated `commitment_version`, `snapshot_version`, or has `advisory=True`.
       - Zero synthetic fallback to audit IDs or version 1. Timezone-aware ISO-8601 timestamps enforced.
    3. **Transaction A/B Dual-Boundary Isolation**:
       - Transaction A (Core `assess()` + risk state transition `AT_RISK` + `AuditEventRecord` + `OutboxEventRecord` `PENDING`) commits independently and atomically.
       - Transaction B (Outbox Dispatcher -> Consumer handler -> `ProcessedEventRecord`) runs in its own session.
       - Injected consumer failure rolls back Transaction B writes (case and trigger rows) and `ProcessedEventRecord`. Transaction A state remains committed.
       - Outbox event attempts increment to 1, status becomes `FAILED`, and exponential backoff `next_retry_at` is scheduled. Subsequent retry succeeds and marks outbox `PUBLISHED`.
- **Validation Test Evidence**:
  - Migration 0007 tests (`backend/tests/test_migration_0007.py`): 2 passed (upgrade 0006->0007, zero data loss on seeded data, negative RESTRICT tests on case and commitment deletion, partial active index enforcement, clean downgrade 0007->0006, re-upgrade, and single head assertion).
  - Reader fail-closed tests (`backend/tests/test_assessment_reader_fail_closed.py`): 5 passed (provenance missing errors, advisory rejection, fully provenanced success, audit event parser).
  - Transaction A/B isolation test (`backend/tests/test_transaction_ab_isolation.py`): 1 passed (A commits independently, B rolls back on failure, attempts increment, retry succeeds, idempotency holds).
  - Full backend pytest suite: `331 passed, 8 skipped, 6 warnings` (`pytest backend/tests backend/app/feasibility/tests`).
  - Single Alembic head confirmed: `0007_recovery_case_constraints_alignment (head)`.
  - Frontend typecheck: Passed (`tsc --noEmit`, 0 errors).
  - Frontend Vitest: `218 passed, 5 skipped (live smoke), 0 failed` (`npm test -- --run`).
  - Frontend production build: Passed (`cmd /c npm run build`, 0 errors).
- **Pending Acknowledgements**: P3 (for rebase of PR #10 onto `0007_recovery_case_constraints_alignment`).
## 2026-10-22 — Person 4 / Commit 04.1: Dashboard Statistics & Simple Integration

- Baseline: uploaded MouManTAI-P4-communication (1).zip, extracted into an independent work copy (285 baseline source files). Actual local Git branch checked as P4-communication with clean status before work. The uploaded ZIP has no Git history; no commit hash is asserted. Real project was not edited; no branch switch/add/commit/push/reset/merge/rebase performed.
- Decision/scope: current user request supersedes the earlier three-card limit: exactly Total | Drafted | Sent | Needs Attention. Counts now come exclusively from GET /v1/communications/summary, never frontend-session draft counts. Request/draft status labels and all existing backend enums remain unchanged. No Commit 05 approval or Commit 06 sending implementation.
- Backend: added CommunicationSummary P4-local contract, tenant-scoped SQL request total/BLOCKED aggregate and persisted-draft lookup; MessageDraftService.summary reuses current proposal/approval/identity/channel/template checks and READ_DRAFT policy plus full saved-content comparison. Multiple languages/variants count each request once. Known expired/stale/revoked/invalid drafts do not count. Summary only reads and rolls back to release locks; no draft/audit/outbox/Core writes.
- Contract: tenant_id:string, total:nonnegative integer, drafted:nonnegative integer|null, sent:nonnegative integer|null, needs_attention:nonnegative integer, checked_at:offset-aware timestamp, unavailable_reasons:map keyed drafted/sent. Null means unavailable, never zero. Summary static route is registered before /{communication_id} in the P4 router, retaining plural /v1/communications prefix.
- Availability: absent DraftAuthority => drafted=null/DRAFT_REVALIDATION_UNAVAILABLE, including empty DB. Configured authority with no persisted drafts => drafted=0. Adapter failure, READ_DRAFT denial or unsupported/corrupt saved schema => drafted=null/DRAFT_VALIDITY_UNAVAILABLE, never a partial count. Missing draft table => drafted=null/DRAFT_STORAGE_UNAVAILABLE while known request counts remain available. Missing request storage => COMMUNICATION_SUMMARY_UNAVAILABLE/503.
- Sent: no actual outbound/send-attempt persistence exists in the uploaded repository, so sent=null/SENDING_RECORDS_UNAVAILABLE. Request snapshot DRAFT/QUEUED/SUBMITTED/SENT/DELIVERED/FAILED/DELIVERY_UNKNOWN fields and generic audit/outbox statuses are not provider proof and are not counted as sent. No dummy sending module/source added. Current module has no send path, so verified saved drafts remain draft-only; future sending integration must add trusted send counts and exclude actually sent requests from Drafted.
- Needs Attention: distinct persisted request_status=BLOCKED requests only. No draft is not an exception. No real failed-delivery model exists to add further counts yet. This metric reflects stored intake state, not a newly invented live exception engine. The four metrics are not mutually exclusive buckets.
- Frontend: four server-backed cards, desktop four columns/mobile 2x2; independent summary loading/error/retry/unavailable states, scoped tenant+actor query key, response count/scope guards and no cached values shown during loading/error. Summary refreshes after prepare/read/revalidation failures and on focus/manual refresh; no optimistic increment. Summary errors never disable list/details/preview. Existing local verified-preview data remains only for conservative row display, not dashboard totals. Known-ID draft history limitation from Commit 04 remains.
- Modified files: backend/app/communication/{schemas,repository,drafting,router}.py; frontend/src/features/communication/{types.ts,api.ts,CommunicationCenterPage.tsx,CommunicationDetails.tsx,presentation.tsx,communication.css,CommunicationCenterPage.test.tsx}. New: backend/app/communication/tests/test_summary.py. Existing foundation/request/drafting tests, models, service.py, templates, DraftPreview, shared files and other members' modules preserved.
- Actual validation: python -B -m pytest app/communication/tests -v => 172 passed, 0 failed, 0 skipped (140 preserved + 32 new, 1 existing Starlette/httpx warning). An initial new tenant fixture incorrectly used a raw string in model_copy for RequestStatus; corrected it to the existing enum and reran the complete P4 suite. No production rule was relaxed.
- Frontend: npm ci --ignore-scripts --no-audit --no-fund succeeded in the work copy using the uploaded lockfile, after the sandbox install failed; package.json/lockfile unchanged and no new dependencies introduced. npm test -- src/features/communication/CommunicationCenterPage.test.tsx => 81 passed, 0 failed, 0 skipped (61 preserved/updated + 20 new). npm test => 230 passed, 0 failed, 5 skipped (14 files passed, 1 skipped); skips are the pre-existing LIVE_API=1 smoke suite. npm run typecheck; tsc --noEmit -p tsconfig.app.json; npm run build all passed. No lint script configured.
- Integration evidence: TestClient on unchanged main app GET /v1/communications/summary returns 404; the P4 router itself exposes the correct static route and is covered through test app requests, including trusted test-only authority, default fail-closed authority and tenant isolation. Main still mounts Core only, App.tsx /communications remains Placeholder, Alembic metadata imports Core only, migrations end at 0005_resource_reservations, authority providers return None. No production PostgreSQL or live browser/API happy-path E2E verification claimed. The existing unmounted-shell build passes; new feature is typechecked/tested independently.
- P5 dependencies: retain approved plural prefix; mount existing P4 backend router and exported frontend page, register P4 metadata/migrate existing request/source/draft tables, bind trusted RequestAuthority/DraftAuthority with action-specific READ_DRAFT policy and authoritative approval/version/expiry/revocation/identity/channel data. Summary adds no model or migration. P1 identity/contact and P3/P5 approval sources remain authoritative; no duplication or bypass added.
- Known limits: per-draft revalidation is a read-time DB scan suited to current demo volume, not a benchmarked large-scale aggregate. Counts are read-time observations and may change on refresh; Needs Attention is persisted BLOCKED only. Drafted cannot be proven without trusted authority. Sent remains unavailable until real sending persistence exists. Responsive CSS exists but jsdom cannot verify geometry; main route and actual browser integration remain pending P5. Full Backend/Core suite and its previously problematic Windows reservation concurrency test were not run or modified.
- Next milestone: Commit 05 — Message Approval Workflow, not started; wait for user confirmation.
- Git status: not committed by this task. Suggested message: feat(p4): add communication dashboard summary.
## 2026-10-22 — Person 4 / Commit 04.2: Simple Route Integration

- Scope: only register the existing Communication backend router and replace the existing /communications frontend placeholder. Current user explicitly authorizes these two minimal P5-owned shared-file changes for P5 review. No new business features, endpoints, migrations, authority adapters or enums.
- Baseline: actual local P4-communication branch, clean git status before work; Commit 04.1 already present. Independent copy of 291 source files used. Real project unchanged, no switch/reset/add/commit/push/merge/rebase. Main initially registered only Core; no existing P1/P2/P3 router registrations were removed or altered. Remote/unprovided unmerged branches were not inspected or merged.
- Shared changes for P5 Review: backend/app/main.py adds communication_router import and app.include_router(communication_router), with no additional prefix. frontend/src/App.tsx adds CommunicationCenterPage import and replaces only the /communications Placeholder element. Original AppShell, AuthProvider, QueryClientProvider, BrowserRouter, role logic, other routes, CORS/config, Core registration and exception handlers retained.
- API registration: GET /v1/communications; GET /v1/communications/summary; GET /v1/communications/{communication_id}; POST /v1/communications/requests; POST /v1/communications/{communication_id}/prepare; GET /v1/communications/{communication_id}/drafts/{draft_id}. No duplicated prefixes/registrations; /summary precedes dynamic detail and real main TestClient dispatches to the summary endpoint.
- Tests added only in P4 paths: backend/app/communication/tests/test_route_integration.py (10 tests) and frontend/src/features/communication/RouteIntegration.test.tsx (14 tests). Backend tests import the real main App, inspect effective registered routes/OpenAPI, retain Core endpoints, exercise startup/health/auth/error handlers, use isolated test databases for dispatch and missing-table cases, and verify production providers remain None/503. Test arrangement may use existing persisted-request fixtures; real main authority providers are never replaced by fake approval.
- Frontend integration tests render the actual App and its existing BrowserRouter/Providers/Shell, using test-only HTTP responses (no duplicate test route tree). Cover direct /communications load, navigation via existing shell link, shared tenant/actor headers and role switching, safe 503 UI, and preservation of ten other actual App paths. No production fixtures, alternate app or router added.
- Validation: python -B -m pytest app/communication/tests -v => 182 passed, 0 failed, 0 skipped (172 existing + 10 new), one existing Starlette/httpx deprecation warning. App import/startup/health are covered in this run. Initial new route-table tests assumed older FastAPI flat app.routes; corrected test inspection to support this installed FastAPI's lazy included routers/effective paths. Production registration did not need a workaround.
- Frontend: npm test => final clean run 244 passed, 0 failed, 5 skipped (15 files passed, 1 skipped); 5 skips are the existing LIVE_API=1 smoke suite. A first concurrent default-worker run had one existing P2 pages.test.tsx alert timeout (243 passed); no P2 change. npm test -- --maxWorkers=2 passed 244/5, then a standalone normal npm test also passed 244/5. New tests initially used an unsupported RTL exact option; corrected test options. npm run typecheck, tsc --noEmit -p tsconfig.app.json and npm run build passed. Production build now bundles the actual communication page/CSS (100 modules), rather than the prior placeholder-only shell.
- Patch handoff: P4-route-integration.patch is the exact unified Before/After diff for just main.py/App.tsx. No full shared-file replacements included. Validated git apply --check, actual apply in a disposable directory, reverse --check for already-applied detection, and equivalence to tested source. Shared-file baseline hashes and all protected copy/real source hashes checked. Preserve latest owner changes; if patch context conflicts or integration is already present, review/apply only missing lines manually, never force or overwrite full files.
- Status distinction: Router Registered = verified in tested copy; API Functional = route dispatch/health/error/fail-closed behavior verified with isolated DB; production database/approval happy path still pending; Full E2E Integrated = not claimed. Actual browser/live PostgreSQL/provider workflow not run.
- Remaining dependencies: P5 review of shared diff, existing P4 request/source/draft migrations/model registration, trusted RequestAuthority/DraftAuthority and P1/P3/P5 source integration. Providers remain None; no fake authorization. Missing P4 tables produces existing storage 503, not a missing route; unavailable approval remains blocked/503 and Summary may show unavailable metrics. No Core/DB/Migration/Contract modifications and no reservation concurrency test run.
- Next milestone: Commit 05 remains unstarted; stop after Commit 04.2.
- Git status: not committed by this task. Suggested message: chore(p4): wire communication routes.

## 2026-10-22 — Person 4 / Commit 05: Communication Draft Approval Workflow

- Baseline: current local P4-communication, with 04.2 routes already mounted. Initial git status had existing modifications to backend/app/main.py and docs/TEAM_LOG.md, plus untracked backend/app/communication/tests/test_route_integration.py; all real files preserved. A separate copy of 293 baseline source files was used. No shared-file edits, branch switches, Git add/commit/push/merge/rebase/reset or real-project changes by this task.
- Scope: persistent message draft review only. Reuses Core ApprovalState (PENDING, APPROVED, REJECTED, INVALIDATED); no shared enum/contract modification. Core recovery proposal approval is still independently required and cannot be created by P4 review. No sending/dispatcher/provider/webhook/confirmation/replanning or Core lifecycle mutations.
- APIs: GET /v1/communications/{communication_id}/drafts/{draft_id}/review; POST same base /approve and /reject. POST requires request_key and expected_content_hash; reject also requires a nonblank reason <=1000 characters. Extra actor/approved/body/terms claims rejected. Existing plural router reused, old APIs unchanged and /summary matching retained. Already-mounted main/App files unchanged.
- Security: new ReviewAuthority server-only port defaults None/503. It must verify actual identity, tenant membership and explicit action policy for READ_REVIEW / APPROVE_DRAFT / REJECT_DRAFT; demo OWNER/MANAGER text alone grants nothing. Scope/actor/role/action/evidence/expiry bound and checked. For existing APPROVED reviews, adapter must return current original-reviewer authorization status VALID/REVOKED/UNKNOWN with trusted evidence; UNKNOWN is unavailable/503, not approval. Review also invokes existing trusted DraftAuthority READ_DRAFT checks in the same transaction, re-reading current Core proposal/terms/approval/revocation/identity/channel data. No fake production approval.
- Content/currentness: review requires READY_FOR_DRAFTING in both stored request state and snapshot. Locked saved draft is revalidated and compared against freshly generated expected content/metadata; hash alone is insufficient. expected_content_hash is an optimistic preview guard, not a source of approved terms. Decision binds tenant/request/draft/full proposal-plan references/content_hash/validation_hash/language/recipient/channel/current Core approval evidence and trusted reviewer evidence/role/time/expiry. Approval time cannot extend beyond draft or action-policy expiry.
- Persistence: communication_draft_reviews stores immutable original decision snapshot and nullable permanent invalidation latch; composite PK tenant/review_id, exact tenant/request/draft FK, unique terminal decision per draft, tenant/request_key uniqueness, tenant/request index. Existing draft model gains uq_draft_request_identity for the referenced triple. P5 must migrate both changes; no migration chain touched. No dict/global state substitutes for DB persistence.
- Transaction/audit: database locks plus unique constraints serialize competing decisions. Integrity conflict retries once with full current validation; conflicting reviewer/action/key returns 409, not overwrite. Exact retries return the same persisted decision without duplicate audit. Decision and existing AuditEventRecord commit atomically; immutable review fingerprint is checked against original audit on reads. No outbound outbox event is created. Semantic invalidation appends a separate audit and latches INVALIDATED while retaining original decision/reason/evidence; retry cannot revive it. A review GET may persist an observed invalidation. Infrastructure/policy uncertainty returns unavailable and never exposes an effective approval. No Core record changes.
- Minimal lifecycle limit: one terminal decision per exact draft. Rejected/invalidated drafts cannot be reapproved under a different key. Existing Prepare remains idempotent, so preparing an identical variant does not create a replacement reviewable draft; a legitimate different language/template/source/current-version variant needs its own new draft ID. No editing/reset/revision endpoint or automatic recovery replan added.
- Frontend: ManagerReview appears only below an actually loaded, valid DraftPreview. Preview includes recipient and approved proposal terms. Controls come exclusively from backend allowed_actions; read-only/unavailable/403 handling, approve confirmation, reason validation, loading/duplicate guard, stable per-operation idempotency key on retry, query cancellation/unmount protection and scoped review keys are implemented. POST is followed by authoritative review GET; stale cached or unreadable approval is not shown as success. Switching request/draft/actor resets controls. Review history/evidence/invalidation is read-only. Approved never becomes Sent; Summary is refreshed, never incremented optimistically. send_authorized remains false.
- Files changed: communication/{schemas,models,repository,drafting,router}.py and tests/test_route_integration.py; frontend communication/{types.ts,api.ts,presentation.tsx,CommunicationDetails.tsx,DraftPreview.tsx,communication.css,CommunicationCenterPage.test.tsx}. New: review.py, tests/test_review.py, ManagerReview.tsx, ManagerReview.test.tsx. Public validate_current extracts existing GET checks without committing inside review's transaction; original foundation/request helper/service/templates and all other source files preserved. Existing route test extended for the three new endpoints; old frontend fixture now returns a test-only read-only review response.
- Actual tests: python -B -m pytest app/communication/tests -v => 226 passed, 0 failed, 0 skipped (182 preserved + 44 new), one existing Starlette/httpx warning. Covers explicit manager policy, Owner/Staff denial, scope/expiry/revocation/tamper, exact hash, rejection, DB persistence, atomic rollback, permanent invalidation, audit integrity, duplicate keys, and concurrent approve/reject with two isolated file-SQLite sessions (one terminal success, other conflict). No P5 reservation concurrency test/full Core suite run.
- Frontend: npm test -- src/features/communication --maxWorkers=2 => 114 passed, 0 failed, 0 skipped; npm test -- --maxWorkers=2 => 263 passed, 0 failed, 5 skipped (16 files passed, 1 skipped). 19 new review UI tests. Five skips are existing LIVE_API=1 smoke tests. npm run typecheck, tsc --noEmit -p tsconfig.app.json, npm run build all passed. Backend imports and PostgreSQL review DDL compilation passed. Ruff module/executable is not installed, so Ruff was not run and no new dependency installed.
- Test development: two initial expiry tests accidentally expired the test reader's own authorization before reaching the intended proposal/original-review expiry gate; fixture grants corrected and unchanged production checks passed. One UI cache assertion initially used an unobserved gcTime=0 query, corrected test cache lifetime; a test-only unused variable was corrected. Final complete suites pass, no security rule removed.
- P5 migration handoff: register P4 models, migrate previously pending request/source/draft tables, add parent UNIQUE(tenant_id,communication_id,draft_id), create review table and named FK/uniques/index exactly as models.py. Current migration head remains 0005_resource_reservations and Alembic metadata imports Core only. PostgreSQL DDL contract is embedded in COPY_AND_TEST.md for P5 review, not an alternate migration or executable production bootstrap.
- P5 authority handoff: bind get_request_authority/get_draft_authority as previously pending, and get_review_authority with real ReviewAuthority. Its authorize_review receives existing_review, must enforce tenant/action policy and recheck original reviewer revocation/evidence; VALID/REVOKED require evidence, UNKNOWN is blocked. Use read-only queries in supplied Session without committing/rolling back or mutating Core. Existing Core recovery authorize(action_type) is not a manager-review policy and must not be called with an unknown action as a bypass. P1/P5 contact/consent and P3/P5 current recovery approval remain authoritative sources.
- Integration status: P4 module workflow and real registered routes are test-verified with isolated DB and explicit test doubles. Production authority providers are None, migrations absent, so live approve/reject is Pending Integration and returns safe errors rather than fake success. No production PostgreSQL, trusted production manager happy-path, actual browser geometry or full E2E claim. Expired/stale draft bodies stay hidden by existing preview rules; historical review remains available via authorized review API, but stale previews are not made actionable in UI.
- Next: Commit 06 Sending is not started. Future send preparation must independently revalidate current review/Core approval/contact/channel/consent and may not trust a stored snapshot or effective_approval from an old response; this milestone never grants send authorization.
- Git status: not committed by this task. Suggested message: feat(p4): add communication draft approval workflow.

### 2026-10-22 — P4 Commit 05.1: Database Migration & Persistence Integration

- Scope: implement P4 persistence migration and metadata registration; validate real database behavior. No Sending/Confirmation/authority implementation or Core business changes. Database work is completed by P4 here, no longer automatically deferred to P5.
- Baseline: real branch P4-communication, latest commit bef5045. Correct explicit-work-tree status returned clean and MERGE_HEAD absent at inspection. Initial plain git status failed work-tree resolution; no state-changing workaround used. Isolated copy of 309 source files, no real-project edits or Git writes by this task.
- Migration before: single head 0007_recovery_case_constraints_alignment. After: unique head 0008_p4_communication, down_revision=0007_recovery_case_constraints_alignment; revision length 21. New filename 0008_p4_communication_persistence.py. No existing revision overwritten, parallel head, stamp or duplicate table migration.
- Tables: communication_requests, communication_request_sources, communication_drafts, communication_draft_reviews. Frozen explicit DDL matches current ORM JSON/timezone/nullable/scalar columns, composite PKs, all indexes and named uniques/FKs. Includes parent uq_draft_request_identity for triple FK fk_review_exact_draft, terminal review uniqueness and tenant-scoped request-key uniqueness. Source/Draft/Review cannot reference another tenant's parent.
- Shared diff: only one Import added to migrations/env.py, registering app.communication.models into existing Base.metadata. All Core imports and environment/online/offline config retained. Delivered as patches/alembic-p4-model-registration.patch rather than an old shared env.py. Shared-file review required before team merge.
- Files delivered: new backend/migrations/versions/0008_p4_communication_persistence.py; new backend/app/communication/tests/test_migration_persistence.py; shared env.py patch; COPY_AND_TEST.md and this append. No Models/Repository/Service/API/Frontend/shared-contract functional changes required. Existing stale model docstring is not changed merely to force an extra Models overwrite.
- PostgreSQL: actually used fresh postgres:16-alpine container at 127.0.0.1:15441, DB p4_migration_test; every test creates its own UUID schema and upgrades from empty through full existing chain. 22 PostgreSQL database cases passed, including two real concurrent review cases. No create_all/stamp substitution. Disposed only own test schemas and own container/temporary volume, verified zero leftover test schemas. No user database deleted, reset, downgraded or migrated.
- Migration/persistence tests: 44 passed (22 PostgreSQL, 20 SQLite, 2 topology/offline/fresh-metadata cases), included in full P4 result below. Introspection/autogenerate comparison found no P4 schema diffs. Actual PostgreSQL accepted exact-draft triple FK and all constraints. Downgrade removes only new P4 tables/indexes while retaining Core and P3 Recovery tables/data, followed by successful re-upgrade and correct revision.
- Repository/API: actual Service intake/draft replay and persisted approve/reject survive fresh Sessions; no duplicate approval audit; authority revocation persists invalidation without overwriting original decision. Review+Audit rollback atomic. Concurrent same-key approval produces one record/audit; competing Approve/Reject yields one decision and one 409. TestClient mounts actual App and only overrides DB for empty/populated List/Summary; production authority dependencies stay None and writes fail closed. drafted/sent remain null when unverifiable.
- Actual full P4 Backend: python -B -m pytest app/communication/tests -v --tb=short with P4_TEST_DATABASE_URL and DISABLE_SQLALCHEMY_CEXT=1 => 270 passed, 0 failed, 0 skipped, 49 warnings (existing Starlette/httpx warning plus 48 Alembic path_separator deprecations). App import and heads/history passed. No P4 persistence defect required a production code fix.
- Frontend actual: npm test -- src/features/communication --maxWorkers=2 => 114 passed, 0 failed, 0 skipped. npm run typecheck, tsc --noEmit -p tsconfig.app.json, npm run build passed (110 modules). No frontend changes; complete frontend suite not rerun in this milestone.
- Relevant shared Backend regression actual: tests/test_contracts.py, test_smoke.py, test_core_api.py, test_registry.py, test_outbox_events.py, test_migration_0007.py => 28 passed, 1 failed, 6 warnings. Failure is test_migration_0007.py::test_alembic_has_exactly_one_head line 54, hardcoded old head ==0007. New valid 0008 is sole head; 0007 upgrade/downgrade/RESTRICT behavior passes. Per scope restriction, no non-P4 test edits, skips or interception. Shared Regression Readiness PENDING: owner should review replacing historical head equality with single-head/0007-ancestor assertion. Do not claim all Backend/CI green. Full Core suite and known hazardous Windows reservation-concurrency test not run.
- Remaining authority dependencies: production RequestAuthority/DraftAuthority/ReviewAuthority providers still None; real actor/tenant/action authorization, current recovery/Core plan/proposal approval/revocation evidence, P1 verified identity/contact/channel/consent required. Database migration does not grant any approval. No Fake Approval/Manager/Identity in production. Full authoritative workflow E2E remains pending, separate from verified database integration.
- Next milestone: integrate authority adapters against agreed real authoritative sources; no Commit 06 Sending started. No Commit SHA invented and no automatic add/commit/push/merge/rebase/reset/checkout/stash.
- Suggested commit message: feat(p4): add communication database migration.

### 2026-10-22 — P4 Commit 05.2: Trusted Authority & Runtime Integration (PARTIAL)

- Baseline: P4-communication at 080503b, with existing uncommitted docs/TEAM_LOG.md. Isolated copy of 311 source files used; preserve all real files and Git state. No Git writes or real-project edits by this task.
- Status: Core current-state reader and explicit fail-closed runtime boundaries implemented. Affirmative RequestAuthority, DraftAuthority and ReviewAuthority integration remains unavailable because real upstream authority is absent; this is not production-ready approval or full E2E. No automatic Demo fallback or fabricated evidence.
- Actual sources reviewed: Core CommitmentRecord/CommitmentProposalRecord, audit/outbox, dependencies/policy/service/integration/router; P1 Directory/Association/Hosting; P3 module; P4 services/schemas/router/models/migrations. Core current facts usable, but Proposal ACTIVE/evidence_refs are not approval. No persistent approval/proposal expiry/revocation reader, authenticated actor/membership or P4 review policy exists. Core policy ignores unknown P4 actions, so it is not used as a grant. P3 app/recovery contains only __init__.py; generic Recovery Case JSON does not supply a trustworthy plan approval reader.
- P1 gap: PlatformIdentity contains channel/sender ID/alias, CustomerAccount has verified_channels:list[str], DEFAULT_DIRECTORY is SyntheticCustomerDirectory. No authoritative typed outbound customer/identity/channel/address binding with verification evidence/currentness/revocation and purpose-specific consent. Never infer Telegram/WhatsApp identity from those strings or invent an address/consent.
- Minimal upstream requirements: Core authenticates a principal, current tenant membership and explicit P4 action policy with evidence/expiry/revocation; Core/P3 reads exact plan/proposal/commitment versions and approved terms/current approval/proposal expiry/revocation plus trusted source-event provenance; P1 supplies verified typed outbound identity/customer/channel/consent evidence and validity. Original reviewer status also requires current Core authorization/revocation evidence. These are concrete authority gaps, not a blanket Pending P5 assignment.
- Implemented: new communication/authority_adapters.py with RuntimeRequestAuthority, RuntimeDraftAuthority, RuntimeReviewAuthority. Current implementations only reject with existing 503 codes and details.integration_status=UNAVAILABLE/missing_capabilities. Router supplies them instead of None. No positive grants, Test Fixtures, actor-role policy copy, extra Auth system, engine, env-mode bypass or Core mutations in production wiring.
- Core integration: service.py extracts existing source/current commitment/proposal/version/state/terms checks to reusable read_current_basis() and CurrentCommunicationBasis. This DTO is facts only, not permission/expiry/source-authentication proof. Existing resolve_current uses it, retaining all grant/terms/expiry checks. All Core source/current SELECTs use populate_existing so a long-lived Session cannot reuse stale ORM identities after another transaction modifies source/state/version/terms. Regression verified on real PostgreSQL and SQLite. Reader uses caller Session, owns no commit/rollback and writes no Core data.
- Runtime safety: availability preflight before privileged object lookup avoids 404/storage errors masking authority absence. Summary explicitly checks availability even for an empty database, keeps drafted=null and sent=null. Existing actor/header validation, request idempotency, draft hashes/currentness, immutable review audit/invalidation and tenant scope preserved. Read List/Details retain existing Core Demo Header contract and are not newly authenticated production APIs.
- Changed files: authority_adapters.py (new); service.py, drafting.py, review.py, router.py; tests/test_authority_adapters.py (new, 43 tests); tests/test_requests.py and tests/test_route_integration.py update obsolete None-provider assertions while retaining HTTP refusal; tests/test_migration_persistence.py updates one obsolete comment. No Model/Repository/Frontend/shared config/Core/P1/P3/migration edits, no shared Patch, no added dependencies.
- Actual P4 Backend: python -B -m pytest app/communication/tests -v --tb=short with P4_TEST_DATABASE_URL and DISABLE_SQLALCHEMY_CEXT=1 => 313 passed, 0 failed, 0 skipped, 59 warnings (existing Starlette/httpx warning plus 58 Alembic path_separator warnings). New tests=43, including 6 PostgreSQL cases and 4 SQLite-migration cache-refresh cases. Total PostgreSQL cases=28 including 22 preserved migration cases. All database cases execute actual Alembic in isolated UUID schemas.
- HTTP DB integration: empty/populated PostgreSQL scenarios pass using actual App/default runtime authority providers and overriding DB only. Create/Prepare/Retrieve/Review/Approve/Reject refuse missing trusted evidence with 503, unauthenticated/unknown actor and client approved/role claims remain rejected. List/Details/Summary/Health remain usable under existing read contract. Compare entire tracked Core/Audit/Outbox/P4 rows before/after: no mutation or send. Test-positive records are created only by clearly test-only fixtures, not production DI.
- Existing Protocol regression: missing/expired/revoked approval, terms mismatch, unverified identity/channel, original reviewer revocation still rejected with test-only fixtures. Saved approval does not authorize a production actor; unknown original-reviewer validity is unavailable rather than falsely VALID or falsely revoked. No authenticated production manager happy path or trusted production contact success claimed; these remain NOT RUN pending genuine sources.
- Frontend actual: full npm test -- --maxWorkers=2 => 271 passed, 0 failed, 5 existing LIVE_API=1-gated skips (17 files passed, 1 skipped). npm run typecheck, tsc --noEmit -p tsconfig.app.json, npm run build passed (110 modules). No UI changes. App import/provider imports passed; production wiring does not import P1 synthetic directory. Alembic remains single head 0008_p4_communication.
- Relevant shared regression actual: same contract/smoke/Core API/registry/outbox/0007 suite => 28 passed, 1 failed, 6 warnings. Failure remains non-P4 test_migration_0007.py:54 hardcoding old Head=0007; actual valid sole Head=0008. No non-P4 edit/skip/interception, so shared Backend/CI not claimed all green. Full Core suite and hazardous Windows resource-reservation concurrency test not run.
- Test environment limitation: initial full app.context import failed due missing numpy in the OCR Router import chain. Directory/Schema behavior is finally tested by loading the actual P1 files in a private test namespace, without P1 router side effects. No fake authority and no P1 edits/install. Whole P1/OCR runtime not verified. New production P4 avoids that synthetic import entirely, preserving startup.
- Test database: separate postgres:16-alpine container p4-commit05-2-authority-test on 127.0.0.1:15441, DB p4_migration_test; no user database touched. Temporary schemas cleaned and own container/temporary volume removed after tests. No real database downgrade or cleanup.
- Next: obtain the concrete authoritative interfaces described above, replace unavailable Runtime boundaries with genuinely verified adapters, then test affirmative workflow. No Commit 06 Sending/dispatcher/provider/confirmation/replanning/Core approval/fulfilment started. Suggested commit: feat(p4): integrate trusted communication authorities. No Commit SHA invented.
### 2026-10-22 — P4 Commit 06: Mock Outbound Messaging, Delivery Tracking & Sent Dashboard

- Baseline: P4-communication at 009e3c0, clean status, Commit 05.2 present. Real Alembic head 0008_p4_communication, no existing outbound implementation. Isolated copy of 313 source files used; real project/Git state preserved. No automatic commit/push/merge/rebase/reset/checkout/stash.
- Scope: local mock outbound, durable submission/attempts/history/audit/outbox, send eligibility and SEND_MESSAGE policy boundary, dashboard statistics and existing frontend integration. No network connectors/credentials/costs, dispatcher, callback/webhook, confirmation/customer acceptance/replanning/Core approval/fulfilment.
- Channel contract: official CommunicationChannel includes MOCK_EMAIL, MOCK_WHATSAPP, MOCK_TELEGRAM, UNKNOWN. First three implemented/tested. MOCK_SMS absent from official contract and not added to shared enum; precise coordination gap only, not a blocker for declared channels.
- APIs: GET /v1/communications/{communication_id}/drafts/{draft_id}/send-eligibility; POST same base /send; GET /v1/communications/{communication_id}/outbound. Existing plural Router reused once. POST body only request_key and expected_content_hash. Client tenant/approval/role/provider/content/recipient/channel/accepted/fulfilled claims forbidden. Eligibility may return 200 can_send=false; POST always revalidates.
- Authorization: original DraftAuthority and ReviewAuthority checks reused in validate_for_send without commit/rollback; exact approved review/audit/hash/versions/terms/expiry/revocation/original reviewer/current verified recipient/channel evidence required. Separate SendAuthority binds explicit SEND_MESSAGE, actor/role/tenant/request/draft/review/content_hash/validation_hash/evidence/expiry. RuntimeSendAuthority always refuses current upstream authority gaps; no Demo Role/Mock Provider bypass. Positive fixtures live only in tests.
- Persistence: new communication_outbound_messages and communication_send_attempts; tenant composite PK/FKs, exact four-column Review FK backed by new uq_review_exact_identity, one send intent per tenant/draft, tenant/request_key unique, channel/provider_reference unique, explicit state/SENT-proof checks, one Attempt submission, tenant/request/status indexes and timestamps/evidence. Provider/body/address/credential data not exposed by History.
- Migration: new frozen 0009_p4_outbound_messaging.py, revision=0009_p4_outbound_messaging (26 chars), down_revision=0008_p4_communication. Old 0008 unchanged; existing env.py registration sees new P4 Models without shared edits. Single head verified. Real PostgreSQL migration/ORM comparison and constraints passed. Delta downgrade 0009->0008 preserves old Request/Draft/Review and Core/P3 tables/data, re-upgrade passed; combined P4 suite also verifies down to 0007 in disposable schemas only.
- Transaction/concurrency: lock current exact Draft/Review/Core, commit QUEUED intent+Attempt+Audit+Outbox before any provider effect; revalidate, commit conservative DELIVERY_UNKNOWN/PROVIDER_RESULT_PENDING, then revalidate/reacquire currentness locks through submission and outcome persistence. Same key replays same record, different key cannot bypass one-Draft unique; key cannot rebind another draft. At-most-once submission, no lease reclaim/automatic replay. Crash may leave QUEUED/UNKNOWN requiring manual reconciliation; no liveness/eventual-delivery guarantee claimed.
- Outcomes: LocalMockProvider deterministic success/failure/timeout, no randomness or external I/O/tokens. SENT only on provider success+reference and durable confirmed state; FAILED explicit provider failure; timeout/exception/invalid success -> DELIVERY_UNKNOWN. Final result write failure rolls back to committed UNKNOWN and does not leave a false SENT Audit/Outbox. Queued/Failed/Unknown never trigger automatic resubmission; retry_allowed=false, reconciliation_required for Queued/Unknown. No state-reset/reconcile command in this milestone; historical evidence boundary is explicit, no fake recovery.
- Events: existing canonical factory constructs P4-local queue/submission/result events with tenant, commitment/version, correlation/causation, evidence refs and LOCAL_MOCK marker. Saved atomically with Audit and business state. No dispatcher or customer agreement/fulfilment consumer implemented. Duplicate send replay creates no extra provider/audit/outbox event.
- Dashboard: Sent counts distinct tenant Request IDs with durable provider-confirmed SENT+reference+sent_at; empty query=0, unavailable=null; other states and approvals not counted. Needs Attention counts union of blocked and actual FAILED requests once. Drafted excludes sent exact drafts and blocked requests while checking current authority. Totals unchanged; multiple variants may make metrics overlap. If send storage unavailable, attention is explicitly unavailable and frontend hides partial known count rather than presenting it as complete.
- Frontend: new OutboundPanel, real backend eligibility gating, two-step confirmation, same-key retry on ambiguous HTTP failure, double-click guard, abort/scope resets, late response isolation, server history/summary refresh, confirmed SENT success only, Failed/Unknown/Queued explanations and no resend affordance. History remains readable without a valid preview under existing tenant-scoped Demo Header read contract. Original Request List/Filters/Preview/Manager Review/four cards/providers/routes retained. P4 Request view adds optional outbound_status projection, source snapshot unchanged; display uses actual status rather than assuming Draft or Sent. Narrow CSS and semantic viewport test added; actual browser geometry not claimed.
- Files: communication backend models/schemas/repository/service/drafting/review/router; new outbound.py/providers.py/tests/test_outbound.py; necessary P4 authority/migration/route/summary regression expectations; frontend communication types/api/page/details/review/presentation/css and tests, new OutboundPanel and tests; new migration; two handoff docs. No Core/P1/P3/shared enums/auth/app shell/main/App/env/old migrations changed. No added dependency or shared Patch.
- Actual P4 Backend: python -B -m pytest app/communication/tests -v --tb=short => 370 passed, 0 failed, 0 skipped, 74 warnings (existing Starlette/httpx + 73 Alembic path_separator deprecations). New outbound tests=57 including 13 PostgreSQL; total PostgreSQL cases=41 including prior 28. Real DB coverage includes concurrency same/different keys, exact tenant/review FK, uniques, SENT-proof checks, attempt constraint, result commit failure, delta downgrade/reupgrade and affirmative TestClient workflow with explicit test-only authorities. Provider socket guard, client-claim rejection, current approval/contact/hash/revocation, Core agreement/fulfilment immutability, safe queued/unknown recovery boundary all pass.
- Actual Frontend: P4 npm test -- src/features/communication --maxWorkers=2 =>132 passed. Full npm test -- --maxWorkers=2 =>289 passed, 0 failed, 5 existing LIVE_API-gated skips (18 files passed, 1 skipped). npm run typecheck, actual tsc --noEmit -p tsconfig.app.json, npm run build passed (111 modules). App import and final head passed. No production network smoke/browser geometry/full real-authority E2E claim.
- Shared regression actual: contract/smoke/Core API/registry/outbox/0007 tests =>28 passed, 1 failed, 6 warnings. Existing test_migration_0007.py:54 still asserts old head==0007; actual legitimate sole head==0009. Not deleted/modified/skipped/intercepted; global Backend/CI readiness not green. Full Core and known hazardous Windows reservation-concurrency test not run.
- Test development: initial pre-outbound Sent=null expectations updated to the required new empty-storage=0 semantics; table-unavailable null case explicitly covered. Existing frontend transport fixture extended for new read-only APIs without removing draft failure assertions. New row-label test corrected to wait for asynchronous list loading. Final suites above passed; no security validation relaxed.
- Integration limits: production Runtime Request/Draft/Review/Send authorities still lack trusted authenticated principal/membership/action grants, current Core/P3 approval/expiry/revocation and P1 typed verified identity/channel/consent. Production Send denies 503. Read-only routes retain Core's existing Demo Header contract and are not production authentication. Positive Mock HTTP E2E is PostgreSQL + actual registered App + LocalMockProvider with test-only authority fixtures, not production identity success. No SMS contract, actual delivery proof or callback/reconciliation command.
- Test DB cleanup: own postgres:16-alpine container p4-commit06-outbound-test on 127.0.0.1:15441, DB p4_migration_test; per-case UUID schemas, no development DB touches. Verified zero leftover schemas, removed own container and temporary volume.
- Next milestone: obtain authoritative contracts for positive runtime operation; no automatic advancement to Commit 07. Suggested commit message: feat(p4): add mock outbound messaging and delivery tracking. No fabricated Commit SHA.

### 2026-10-22 — Task H-IMPLEMENT: Teammate Handoff Triage, Core Invariant Implementations & PostgreSQL Evidence (P5 / ADR-018 / D-035)
- **Status**: Complete, Verified & Delivered by Person 5 (Shared Core, Contracts, Shell, Outbox & Integration Coordinator).
- **Decision / Impact / Owner**:
  - **Decision ID**: `ADR-018` (Decisions `D-032`, `D-017` ext, `D-033`, `D-035`)
  - **Owner**: P5 (Shared Core, DB & Integration)
  - **Impact**:
    1. **Caller-Owned Transaction Semantics (D-032)**:
       - `CommitmentService.assess()` and consumer callpaths support `commit: bool = False` (flush only; caller commits).
       - Outbox dispatcher owns transaction commits and rollbacks atomically with `ProcessedEventRecord`.
       - Downstream consumer failure rolls back aggregate, outbox, audit, and processed events atomically.
    2. **D-017 Required-Subscriber Policy Extended**:
       - `OutboxDispatcher` enforces named subscriber `p2_confirmed_evaluator` on `commitment.confirmed` and `p3.recovery_trigger.v1` on `commitment.at_risk` without wildcards.
       - Unregistered or failing subscribers retain events in `PENDING`/`FAILED`; never prematurely published.
    3. **Advisory Feasibility Append-Only Isolation (D-033)**:
       - Advisory assessments write exclusively to `AuditEventRecord` (`advisory=True`, `event_type="commitment.advisory_feasibility_assessed"`).
       - Never mutates aggregate or `revised_terms`; readers and idempotency guards exclude advisory records.
    4. **Contract Relaxation for `affected_commitment_ids`**:
       - `FeasibilityAssessment.affected_commitment_ids` defaults to empty list `[]` (`min_length=0`), representing downstream impact set only.
    5. **Adapter Placement & Boundary Discipline (D-013, D-035)**:
       - Concrete feasibility adapters live in P5-owned `backend/app/core/feasibility_adapters.py`.
       - Public Core router preserves D-013 invariant: `POST /v1/commitments/{id}/assess` returns HTTP 404 (`test_public_core_assess_route_is_absent`).
       - Internal evaluation requires server-validated `SERVICE`/`SYSTEM` role; spoofing via `X-Actor-ID` fails closed.
    6. **Alembic Migration Ownership & Alignment**:
       - Migration 0006/0007 scope verified: strictly `recovery_cases` and `recovery_case_triggers` constraint alignments (`ON DELETE RESTRICT`).
       - P4 owns implementation of migration `0008_communication_tables.py` branching directly from `0007`. P5 will not build duplicate P4 tables.
    7. **ADR-018: Lightweight SME Schema Acceptance**:
       - Denormalized schema for tenants/users/roles/customers/orders/commitment_versions/commitment_evidence is formally accepted under AGENTS §5 & §13.
       - Generic ERP bloat rejected to maintain lean, responsive SME footprint.
    8. **PostgreSQL Dual-Boundary Handshake Verification (W8)**:
       - Executed against PostgreSQL on port 5433 (`TEST_DATABASE_URL="postgresql://[credentials redacted]@localhost:5433/moumantai_test"`).
       - 19 passed in 2.79s. Engine dialect verified as `postgresql` (`test_feature_handshakes.py:L1181-L1183`).
       - Full test output logged to `docs/evidence/postgres_handshake_20261022.log`.
    9. **Teammate Handoff Replies Delivered**:
       - Generated and verified `reply_P1.md`, `reply_P2.md`, `reply_P3.md`, `reply_P4.md` addressing all items by ID with required greetings and sign-offs.
- **Validation Test Evidence**:
  - Full backend pytest suite: `331 passed, 8 skipped, 6 warnings` (`pytest backend/tests backend/app/feasibility/tests -q`).
  - PostgreSQL handshake suite: `19 passed, 0 failed` (`pytest backend/tests/integration/test_feature_handshakes.py -v`).
  - Single Alembic head: `0007_recovery_case_constraints_alignment (head)`.
  - Frontend Vitest suite: `218 passed, 5 skipped (live smoke), 0 failed` (`cmd /c npm test -- --run`).
  - Frontend typecheck: Passed (`tsc --noEmit`, 0 errors).
  - Frontend production build: Passed (`tsc -b && vite build` in 926ms, 0 errors).
- **Pending Acknowledgements**:
  - P1: Rebase `feat/p1-context-intelligence` on latest `main` (`5cf5cae5`, Alembic head `0007`).
  - P2: Acknowledge Core adapter placement and D-013 public assess route guard.
  - P3: Restart PR #10 merge against updated `main` (`5cf5cae5`) and rerun affected regressions.
  - P4: Implement migration `0008_communication_tables.py` branching from `0007`.
### 2026-10-22 — P4 PR CI Hotfix: migration ancestry and route/recalculation regression tests

- Scope: confirmed PR CI failures only; isolated current P4-communication 6f5102a working tree with user's latest MouManTAI-main (4).zip as PR integration input. Formal repo untouched, starting file hashes verified. No Git commit/push/merge/rebase/reset/checkout/stash.
- Baseline difference: local branch/local origin/main still mount P1 placeholders; latest supplied main mounts real DurableInbox and OrderContextDetail. Reconstructed validation input retains existing P4 slice and registrations while using latest main source. This baseline composition is not part of the delivered changes. Applying route tests to an unsynchronized old Placeholder branch is expected to fail; do not weaken real-route assertions to support that branch.
- Backend root cause: test_migration_0007.py hardcoded 0007 as current Head despite legitimate later migrations. Fix checks exactly one Head, required 0007 existence and ancestry, resolvable full revision graph, unique revision IDs, base and parent completeness. No hardcoded 0010, no migration edits, no contract/approval changes.
- P1 route root causes: stale Smart inbox / Order context placeholder headings after main mounted real pages, plus transport fixture lacking a base for relative P1 URLs. Fix uses real Message Inbox / Order Context Unavailable, real API 404/error cards, P1-specific structures, Retry buttons, expected API paths/retry counts, retained URL and shared shell/navigation. P1 components are not mocked and both route cases retained.
- P2 diagnosis: production already retains old data and renders FeatureDataError through role=alert. Reported 409 was not consistently reproduced locally; an adjacent receipt-time recalculation test intermittently lost its result with the same immediate-Promise/initial-effects pattern. Tests were interacting before initial lifecycle effects were explicitly settled. Fix awaits async mount effects/actions and explicitly rejects controlled first/retry promises for 403/409/503. Alert assertions strengthened to exact status/code/message; pending disabled button, retained prior assessment, no success claim, second alert and unchanged expected versions asserted. Related recalculation tests await the same initial effect boundary. No P2 Production Code/calculation/feasibility status/Core state edits.
- Changed files only: backend/tests/test_migration_0007.py; frontend/src/features/communication/RouteIntegration.test.tsx; frontend/src/features/feasibility/pages.test.tsx. Backend shared test and P2 test changes require corresponding owner review; explicitly authorized by current user task. No App.tsx/main.py/Production/shared contract/migration hotfix delivered.
- Backend validation: python -m pytest tests/test_migration_0007.py -q -> 2 passed (Windows and Linux); python -m pytest tests -q -> 103 passed + 1 existing module-level P1_DATABASE_URL skip, final Linux Python 3.12 container exit 0. All resource-reservation concurrency tests ran in Linux to avoid the known Windows SQLite native crash; no deselection. Disposable SQLite only, no dev/prod DB or PostgreSQL operations. Initial incomplete container inputs failed setup; final complete source inputs passed without bypassing assertions.
- Frontend validation: requested target Vitest files -> 49 passed; three additional independent final runs -> 49 passed each; full npm test -- --maxWorkers=2 -> 308 passed / 5 existing LIVE_API skips; npm run typecheck, actual app tsc and npm run build -> passed, 121 modules. No --retry or timeout inflation. Latest main reproduction before fixes -> 47 passed / 2 stale-heading failures.
- Delivery: P4-PR-CI-hotfix.zip with three tests, minimal HOTFIX.patch and COPY_AND_TEST.md / TEST_RESULTS.md / TEAM_LOG_APPEND.md. Append this entry manually; do not replace team history.
- Remaining limitation: local branch must receive real P1 routes through normal team integration for the new route tests to pass; no Git merge performed here. No remote GitHub CI rerun or production E2E claimed.
- Suggested commit: fix(ci): align migration and integration regression tests. Stop after hotfix; no feature work.

### 2026-10-22 — Task T-P2H2: Feasibility Read Router Mount, Session-Aware Resolver & No-Commit Writer (P5 / ADR-019 / D-036)
- **Status**: Complete, Verified & Delivered by Person 5 (Core Architecture, Registry, Shell & Contracts).
- **Decision / Impact / Owner**:
  - **Decision ID**: `ADR-019` (Decision `D-036`)
  - **Owner**: P5 (Shared Core, DB & Integration)
  - **Impact**:
    1. **Production Feasibility Read Router Mount**:
       - Mounted `feasibility_read_router` in `backend/app/main.py`, exposing `GET /v1/commitments/{commitment_id}/assessments` and `GET /v1/impacts/{impact_id}`.
       - Configured dependency overrides for `get_assessment_history` -> `AuthoritativeAssessmentHistoryReader` and `get_impact_reader` -> `AuthoritativeImpactReader`.
       - Preserved D-013 route absence invariant: `POST /v1/commitments/{id}/assess` remains unmounted on Core (returns HTTP 404).
    2. **Transaction-Safe AssessmentWriter Operation**:
       - `AuthoritativeAssessmentWriter.assess(..., commit=True)` now supports `commit: bool = False` to stage assessments via `CommitmentService.assess(commit=False)` without committing or rolling back the dispatcher's database session.
       - Preserved original P2 evaluation `result.assessed_at` and records pre-transition `commitment_version` in `AuditEventRecord.new_state`.
    3. **Session-Aware Evaluation Authority**:
       - `AuthoritativeEvaluationAuthority.resolve_current()` supports `db: Session | None = None` to query genuine persisted `CommitmentRecord` state from the active transaction.
- **Validation Test Evidence**:
  - Full backend pytest suite: `342 passed, 6 warnings` (`pytest backend/tests backend/app/feasibility/tests -q`).
  - Route absence and duplicate guards: `2 passed in 0.07s` (`test_public_core_assess_route_is_absent` and `test_no_duplicate_http_routes_across_routers`).
  - Feasibility router tests: `35 passed in 2.92s` (`pytest backend/app/feasibility/tests/test_router.py`).
  - PostgreSQL handshake suite: `19 passed in 2.68s` (`pytest backend/tests/integration/test_feature_handshakes.py -v`).
  - Frontend Vitest suite: `228 passed, 5 skipped (live smoke), 0 failed` (`npm test -- --run`).
  - Frontend typecheck: Passed (`tsc --noEmit`, 0 errors).
- **Pending Acknowledgements**: P2 (for implementing `app/feasibility/consumer.py` using `writer.assess(commit=False)` and session-aware resolver).

### 2026-10-22 — Incremental P5 loopback CORS review unit

- **Status:** APPROVED & MERGED into `main` via PR [#18](https://github.com/jiahui-1101/MouManTAI/pull/18).
- **Cause/fix:** Vite serves `127.0.0.1:5173` while the shared API's default CORS setting allowed only `localhost:5173`, causing browser preflights to fail. The default permits both loopback spellings; an explicitly configured `CORS_ORIGINS` still takes precedence. The new test checks both origins' communication API preflight response and allowed-origin header. No migration, subscriber, identity, or consequential route change.
- **Evidence:** `python -m pytest tests/test_local_frontend_cors.py tests/test_smoke.py -q -p no:cacheprovider --basetemp=.pytest-basetemp-cors-only --tb=short` → 2 passed. Scoped Ruff F/E4/E7/E9, compileall and `git diff --check` passed.

### 2026-10-22 — P5 stale mandatory outbox guard (IN_REVIEW)

- Contributor: P3 integration assistance. Owner/reviewer: P5 (`Gan0117`); approval pending. Source branch `fix/p5-stale-mandatory-outbox`, based on Main `c7a0f7d42a014cee94c1963e22e493207adcd121`. Extracted narrowly from draft integration PR #16; no migration, subscriber registration, P2 evaluator, P3 consumer or external action is enabled.
- Root cause: Main's outbox reconciled a stale event to `PUBLISHED` solely because a newer Commitment Version existed, even if the named mandatory subscriber had never completed. This could silently discard a required prior P2 evaluation or P3 recovery transition.
- Changed files: `backend/app/core/outbox.py`, `backend/tests/test_outbox_events.py`, `backend/tests/integration/test_feature_handshakes.py`, `docs/TEAM_LOG.md`. The dispatcher now checks the exact tenant/event/mandatory consumer `ProcessedEventRecord` before supersession; missing completion leaves the event `FAILED` with explicit reason and retry, or `DEAD_LETTER` at the configured attempt limit. Existing completed events retain supersession audit behavior. The handshake test verifies the newly visible stale P2 failure separately from a downstream P3 rollback. No test-only callback is wired into production.
- Validation: `python -m pytest tests/test_outbox_events.py tests/test_transaction_ab_isolation.py tests/integration/test_feature_handshakes.py -q -p no:cacheprovider --basetemp=.pytest-basetemp-stale-check --tb=short` passed, 31 tests. `python -m pytest tests -q -p no:cacheprovider --basetemp=.pytest-basetemp-stale-all --tb=short` passed (exit 0). Scoped Ruff `F,E4,E7,E9`, compileall and `git diff --check` passed. These commands used portable SQLite fixtures; no PostgreSQL/migrated schema validation is claimed for this unit.
- Review and integration: code commit `ae20793a94911b7b7f7ec6e6dc56885ad5b9d5a9` on draft PR #20; P5 reviewer `Gan0117` requested, approval pending; no merge to Main. Required production `p2_confirmed_evaluator` and P3 subscriber are still not registered; stale mandatory events require an authoritative reconciliation path. PR #16 remains draft and unmerged.

### 2026-10-22 — P4 post-merge test alignment (IN_REVIEW)

- Contributor: P3 integration assistance. Owner/reviewer: P4 (`Sheng554`); approval pending. Source: `fix/p4-postmerge-regression-tests` from Main `c7a0f7d42a014cee94c1963e22e493207adcd121` (PR #17 merge). This unit changes tests only; no production code or migration.
- Root cause: Main added P4 recipient preference migration `0010_p4_recipient_preferences` and three routes, while P4 tests still expected migration `0009_p4_outbound_messaging`, six P4 tables and the older route set. Main baseline `python -m pytest app/communication/tests -q -p no:cacheprovider --basetemp=.pytest-basetemp-p4-main --tb=short` failed four tests.
- Changed files: `backend/app/communication/tests/test_migration_persistence.py`, `backend/app/communication/tests/test_route_integration.py`, `docs/TEAM_LOG.md`. The migration test now includes both recipient preference tables, verifies the `0008 -> 0009 -> 0010` parent chain and full P4 downgrade scope; the route test covers all three new endpoints. Existing assertions and migrated schema checks remain active.
- Validation: `python -m pytest app/communication/tests -q -p no:cacheprovider --basetemp=.pytest-basetemp-p4-fix --tb=short` passed (exit 0; PostgreSQL cases skipped without URL). PowerShell `$env:P4_TEST_DATABASE_URL='postgresql+psycopg://postgres@127.0.0.1:15444/p4_test_final_reconcile'; python -m pytest app/communication/tests/test_migration_persistence.py app/communication/tests/test_route_integration.py -q -p no:cacheprovider --basetemp=.pytest-basetemp-p4-pg --tb=short -rA` passed (exit 0; fresh UUID schemas on authorized disposable PostgreSQL 16). Final route test rerun passed; scoped Ruff `F,E4,E7,E9`, compileall and `git diff --check` passed. No general backend/front-end suite claimed.
- Review and integration: code commit `5dfa32cd4718ac6b4ec6714f7563ab1ad18ce544` on draft PR #19; P4 reviewer `Sheng554` requested, approval pending; no merge to Main. Outstanding integration work includes PR #16 migration/Core/P2/P3 dependencies, P2 required changes, P1 route, trusted authority and positive customer acceptance.
# 追加到 docs/TEAM_LOG.md 的 P4 记录（不要覆盖原文件）

## 2026-10-22 — P4 Commit 07: Durable Customer Confirmation & Response Handling

- Status: P4 backend evidence workflow implemented and regression-tested in isolated copy; positive customer acceptance cross-module E2E remains BLOCKED, not production integrated.
- Scope: durable session/attempt/decision, secure hashed challenge, exact tenant/customer/channel/outbound/proposal/version/terms binding, EN/MS/ZH conservative response rules, verified P1 ports, replay/concurrency controls, atomic P4 evidence + Audit/Outbox. No frontend, live sending, Core agreement/fulfilment writes or P3 Plan mutation.
- Changed files:
- `backend/app/communication/confirmation_authority.py`
- `backend/app/communication/confirmation_router.py`
- `backend/app/communication/confirmation_schemas.py`
- `backend/app/communication/confirmations.py`
- `backend/app/communication/models.py`
- `backend/app/communication/response_rules.py`
- `backend/app/communication/router.py`
- `backend/app/communication/tests/test_confirmation_integration.py`
- `backend/app/communication/tests/test_confirmations.py`
- `backend/app/communication/tests/test_migration_persistence.py`
- `backend/app/communication/tests/test_route_integration.py`
- `backend/migrations/versions/0011_p4_confirmations.py`
- Migration: new 0011_p4_confirmations -> actual 0010_p4_recipient_preferences; unique standalone Head. Historical migrations untouched. P5 Review required for new shared migration and events. Future P3 0013 coexistence requires a new merge revision after checking actual Heads, not rewriting existing files.
- Tests: final P4 460 passed / 0 skipped; requested shared Backend + P4 563 passed / 1 existing P1 module skip; new rule/service tests 62, integration file 28; migrated=postgresql subset 49 passed (overlap; excludes offline/metadata/fake-bind tests). Compileall + heads pass. Frontend P4 141 passed; full FE 308 passed / 5 existing LIVE_API skips; typecheck, explicit App tsc and build pass.
- Runtime: all new evidence explicitly SYNTHETIC_ONLY/P4_EVIDENCE_ONLY, Core transition false. Default new create/read/revoke restricted to explicit synthetic scope and actual disposable PostgreSQL bind. Respond default denies header-user impersonation; P1 source adapter never wired by default. No test trust fixtures installed in app.
- BLOCK-P4-07-IDENTITY: P1/P5 authenticated processor principal and trusted normalized-message/identity composition pending. Typed P1 contracts/directory confirmed available; tests use source fixtures, not live ingress.
- BLOCK-P4-07-CORE: trusted P5 confirmation.accepted consumer and idempotent version-safe Core transaction protocol pending. Existing Core confirm_proposal is not equivalent to a connected consumer. No automatic proposal confirmation.
- P3 durable approval producer plus rejection/counteroffer handoff consumer absent in this baseline. Existing P4 authority still fails closed when necessary source is unavailable.
- Evidence limitation: token minted once for issuer, not delivered to customer by this task; no token recovery/rotation/reissue; synthetic fixtures do not establish production acceptance. Counteroffer leaves approved proposal unchanged.
- P5 Review: migration DDL/graph, router composition, identity/processor authorization contract, redacted events and Core consumer. P1/P3 review their integration boundaries.
- Live safety: 353 baseline file hashes unchanged; P4-communication remains clean; no Git mutations.
- Cleanup: dedicated test PostgreSQL UUID schemas verified absent after final suite; only this task's test containers/network removed after validation. No development database used.
- Next milestone: P1/P5 trusted composition + P3 producer + Core consumer; then verify actual positive Customer Acceptance E2E before claiming full integration. Confirmation Workspace frontend remains deferred.
- Suggested commit: feat(p4): add durable customer confirmation and response handling

## 2026-10-22 — P4 Commit 08: Customer Confirmation Workspace (Frontend Only)

- Status: Frontend workspace implemented against actual Commit 07 GET contracts; positive views covered by transport-fixture tests, live API fail-closed smoke verified. No actual positive Customer Acceptance E2E claimed.
- Source: user-provided MouManTAI-P4-communication (4).zip contains Commit 07 backend/router/schema and 0011 migration. No remote Git history verification or branch mutation.
- Features: Confirmation overview; exact Proposal ID/version and digest; backend-only expiry/revocation/supersession/currentness rendering; synthetic P4-only evidence labeling; separate Delivery/Confirmation/Core Fulfilment; persisted response timeline/evidence/counteroffer; loading/empty/error/403/404/409/503/retry; tenant/actor/id-scoped query cache; safe Communication-to-Confirmation navigation using real IDs.
- APIs: GET /v1/confirmations?communication_id=..., GET /v1/confirmations/{id}, GET /v1/confirmations/{id}/attempts. No mutation requests, token display, client approval or accept-on-behalf action.
- D-037: exact returned proposal/version only; earlier acceptance never transfers to revised proposal. Active/currentness not returned -> Unavailable; no client authoritative version inference or Core state writes.
- Contracts: reuse contracts/types.ts through shared/types; local read projection needed because Core Confirmation differs from P4 nested ConfirmationView/Attempt. Shared Contracts unchanged.
- P5 update: Core Confirmation Consumers reported implemented with identity/version/transaction checks. Current P4 GET contract still does not return current Core transition/fulfilment or consumer outcome. Do not label consumers as unimplemented; follow up on authorized read/display contract and actual runtime composition.
- P1/authority: read DTO does not expose live identity verdict; default current snapshot inbound processing remains fail-closed. Errors accurately shown, including exact processor-unavailable wording. No Fixture authority installed in app.
- Tests: new workspace 49 passed; full FE 357 passed / 5 existing LIVE_API skips / 0 failures. Typecheck, explicit App tsc and production build passed (126 modules). Shared routes preserved. Real browser to unchanged backend returned expected PRODUCTION_AUTH_UNAVAILABLE 503 and Retry remained blocked.
- Changed files:
- `frontend/src/App.tsx`
- `frontend/src/features/communication/CommunicationCenterPage.test.tsx`
- `frontend/src/features/communication/CommunicationDetails.tsx`
- `frontend/src/features/communication/ConfirmationWorkspace.test.tsx`
- `frontend/src/features/communication/ConfirmationWorkspacePage.tsx`
- `frontend/src/features/communication/LinkedConfirmations.tsx`
- `frontend/src/features/communication/RouteIntegration.test.tsx`
- `frontend/src/features/communication/confirmation.css`
- `frontend/src/features/communication/confirmationApi.ts`
- `frontend/src/features/communication/confirmationPresentation.tsx`
- `frontend/src/features/communication/confirmationTypes.ts`
- P5 Review Required: App.tsx one Import + existing confirmation element replacement, exact APP_ROUTE.patch supplied. Keep current AppShell/Providers/other Routes, never overwrite latest App.tsx wholesale.
- Scope proof: all 247 Backend baseline files and file set unchanged; Contracts unchanged. No database operations, migration, production config or Git writes. Formal project untouched. Shared Team Log delivered as append-only text, not overwritten.
- Data limitations: complete terms, latest active proposal/current approval verdict, current identity, recipient contact, Core agreement/fulfilment/consumer result, updated_at, full audit and rejected/duplicate delivery details are not in these APIs. UI marks unavailable rather than synthesizing records.
- Next milestone: P1/P5 deployment/read-contract verification and positive runtime E2E, then later confirmation actions/follow-up only under approved trusted contracts. P3 migration reconciliation remains independent.
- Suggested commit: feat(p4): add customer confirmation workspace

**No Backend Changes. No Database Changes. No New Alembic Migrations.**
