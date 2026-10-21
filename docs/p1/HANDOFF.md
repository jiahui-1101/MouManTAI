# P1 BATCH 5 Handoff — 2026-10-21 (Actual P1 → Core → P2 Integration)

Active branch: `feat/p1-context-intelligence`; commits for this batch:
- Adapter & Eligibility Gate: `a5cb3ac` (`feat(p1): implement CoreIntegrationFacade adapter and context publication eligibility`)
- Confirmed Terms Protection: `f3c3b7c` (`feat(p5): preserve confirmed commitment terms through proposed amendments`)
- P2 Evaluator & Outbox Consumer: `52f90dd` (`feat(p1): connect outbox event dispatching and P2 feasibility evaluator`)
- Shell Mount & Boundary Alignment: `d5af49c`, `da82110`, `03f4076` (`feat(p1): export context_router, DurableInbox, and OrderContextDetail from module boundaries`)
- Real PostgreSQL End-to-End Suite: `c626326` (`test(p1): add end-to-end P1 Core P2 integration test suite`)

### 1. Core Deliverables and Invariants Enforced
- **Zero-Guessing CoreContextPublisher (`backend/app/context/core_publisher.py`)**:
  - Publication eligibility check (`check_eligibility`): Only contexts in `INFORMATION_READY` status, with established non-unverified customer identity (`LINK_VERIFIED` or `SUGGESTED`), valid `requested_items`, and complete delivery specifications may be published to Core.
  - Strict blocking of unready/conflicting data: Contexts in `INFORMATION_PARTIAL`, `CONFLICT`, `UNRESOLVED`, or `AMBIGUOUS`/`UNVERIFIED` identity status fail fast with `IneligibleContextError`. Unready or ambiguous contexts are never silently submitted to Core.
  - Idempotent publishing & bidirectional pointers: On successful publishing, `core_commitment_id` and `published_to_core_at` are persisted in P1's `OrderContextRecord`, preventing duplicate commitment generation.
- **Confirmed Terms Preservation via Proposals (Invariants 1 & 6, ADR-003)**:
  - In `CoreIntegrationFacade.handle_context_updated`: When context amendments arrive for an already `CONFIRMED` commitment with substantive term differences, the confirmed terms are never overwritten in place.
  - Automatic proposal flow: An active `CommitmentProposalRecord` in `AgreementState.OFFERED` status is created, recording full `ProposedChanges` and emitting `commitment.proposal_offered` to trigger re-evaluation.
- **P2 Feasibility Evaluator Integration (`backend/app/context/p2_consumer.py`)**:
  - Subscribes to `commitment.context_ready` and `commitment.proposal_offered`.
  - Canonical snapshot resolution (`resolve_snapshot_for_commitment`): Resolves operational and line calendars without fabricating stock, mapping request/proposal terms to typed `ProposedChanges` (quantity, deadline, production start).
  - Invokes pure P2 evaluator `evaluate(snapshot, proposed_changes, commitment)` and persists `FeasibilityAssessmentRecord` into Core.
  - Idempotent consumer defense: Registers `(tenant_id, event_id, consumer_name)` in `ProcessedEventRecord` to ensure duplicate event deliveries are safely ignored.
  - Atomic transaction rollback: On processing failure, the transaction rolls back cleanly, and the outbox event is marked `FAILED` with retry capability.
  - Stale version guard: Outbox dispatcher enforces `is_stale_event` checking so older event versions cannot replace newer states.
- **App Shell Integration & Boundary Compliance (P5 Decisions H1.1-Q1 through H1.1-Q3)**:
  - Backend: P1 exports `context_router` from `backend/app/context/__init__.py`; centralized mounting in `backend/app/main.py` is coordinated by P5 in Task T5.2.
  - Frontend: P1 exports `<DurableInbox />` and `<OrderContextDetail />` from `frontend/src/features/context/index.ts`; centralized mounting in `frontend/src/App.tsx` is coordinated by P5 in Task T5.2.
  - Clean PR boundary: Feature branch touches only P1-owned files (`backend/app/context/`, `frontend/src/features/context/`, `backend/tests/integration/test_p1_core_p2_e2e.py`).
- **PostgreSQL 8-Scenario End-to-End Integration Matrix (`backend/tests/integration/test_p1_core_p2_e2e.py`)**:
  1. `test_scenario_1_new_request_through_p1_to_core_and_p2`: New message extracted into ready context, published to Core, and evaluated by P2 as `FEASIBLE`.
  2. `test_scenario_2_reviewed_correction_updates_context_and_re_evaluates`: Operator correction to 120 pcs updates context, triggers P2 re-evaluation, detecting material bottleneck (`INFEASIBLE`).
  3. `test_scenario_3_ambiguous_identity_blocks_unsafe_publication`: Ambiguous customer identity blocked from Core publication with `IneligibleContextError`.
  4. `test_scenario_4_confirmed_term_change_becomes_proposal`: Amended terms on a confirmed commitment create an active proposal in `OFFERED` status, emitting `commitment.proposal_offered`.
  5. `test_scenario_5_duplicate_event_causes_no_duplicate_transition`: Idempotent event processing prevents redundant state transitions.
  6. `test_scenario_6_old_version_cannot_replace_newer_state`: P1 optimistic concurrency rejects stale context reviews (`StaleContextVersion`); outbox rejects stale event versions.
  7. `test_scenario_7_failure_retry_preserves_consistency`: Consumer error triggers transaction rollback and marks outbox event `FAILED` for retry.
  8. `test_scenario_8_wrong_tenant_cannot_access_messages_contexts_or_evidence`: Cross-tenant access attempts return `None` / 404 across messages, contexts, and orders.

### 2. Verification Results
- **PostgreSQL E2E Suite**: 8 passed in 1.45s (100% pass on real PostgreSQL instance).
- **Backend Full Suite**: 306 passed, 4 skipped, 0 failed.
- **Frontend Full Suite**: 149 passed, 5 skipped (LiveApiSmoke), 0 failed.
- **Frontend Build**: `npm run build` succeeded with 0 errors.

---

# P1 BATCH 4 Handoff — 2026-10-21 (Attachment Evidence, PDF Text and Image OCR)

Active branch: `feat/p1-context-intelligence`; commits for this batch:
- Stage 4A (Storage, Validation & Models): `c364c07` (`feat(p1): implement tenant-scoped attachment storage and magic byte validation`)
- Stage 4B (Bounded PyMuPDF Text Extraction): `d5e25a3` (`feat(p1): implement bounded PyMuPDF text extraction with page references`)
- Stage 4C (PaddleOCR Recognition & Payment Guard): `2937d59` (`feat(p1): implement PaddleOCR image recognition and unverified payment guard`)
- Stage 4D (UI AttachmentViewer & Inbox Integration): `ef58ac3` (`feat(p1): implement AttachmentViewer, OCR evidence display, and inbox integration`)

### 1. Core Deliverables and Invariants Enforced
- **Tenant-Scoped Storage and Magic Byte Verification (`p1_dev.attachments`)**:
  - Enforces magic byte signatures for supported file types (PDF `%PDF-`, PNG `\x89PNG\r\n\x1a\n`, JPEG `\xff\xd8\xff`). Blocks disguised malicious files (e.g. text file renamed `.pdf` returns 400; non-whitelisted `.exe` returns 415).
  - Hard limit on file size: 10MB maximum (returns 413 `AttachmentLimitExceeded`).
  - Path traversal protection: Sanitizes filenames, blocking `../`, `/`, and `\` characters.
  - Strict tenant scoping: Attachments and `evidence_ref` are restricted to the tenant namespace. Never accepts client-controlled filesystem paths; never fetches arbitrary remote URLs.
- **Bounded and Traceable PDF Text Extraction (`PyMuPDF`)**:
  - Page bound: `MAX_PDF_PAGES = 10`. Documents exceeding 10 pages process the first 10 pages and set `status="PARTIAL"` with explicit diagnostic info.
  - Page-by-page text extraction with 1-indexed page numbers and exact `BoundingBox` coordinates `[x0, y0, x1, y1]`.
  - Scanned vs text PDF detection: Automatically marks PDFs with no text blocks as image/scanned documents.
  - Distinct evidence boundary: Document evidence uses `DocumentEvidence` (`evidence_ref`, `page_number`, `bounding_box`, `quote`, `method="PDF_TEXT"`), strictly separated from message code-point offsets. Never fabricates message character offsets for attachments.
- **PaddleOCR for Supported Images and Scanned Documents**:
  - Configured `PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT=False` to ensure Windows AMD64 compatibility with PaddlePaddle 3.3.1.
  - Image dimension bounds: 4096×4096 px maximum, preventing resource exhaustion.
  - Line-level text extraction with recognition confidence scores and bounding boxes.
- **Payment Screenshot Guard (Unverified Payment Defense)**:
  - Detects bank transfer slips, DuitNow receipts, and payment notices (keywords: `DuitNow`, `Transfer Successful`, `Bank Slip`, `Amount RM`, etc.).
  - On detection, flags `is_payment_notice = True` and all document evidence as `is_payment_evidence = True`.
  - Extraction status forced to `UNVERIFIED_EVIDENCE` with mandatory disclaimer: *"Bank slips, transfer receipts, and payment screenshots are strictly unverified evidence. P1 never infers verified payment, identity, or fulfillment from user-uploaded slips."*
  - Invariant: Never infers verified payment, identity, or fulfillment from user-uploaded payment slips.
- **Endpoints**:
  - `POST /v1/attachments/upload`: Multipart upload with magic byte validation.
  - `GET /v1/attachments/{evidence_ref}/content`: Authorized download and inline preview.
  - `GET /v1/attachments/{evidence_ref}/metadata`: Tenant-scoped metadata retrieval.
  - `POST /v1/attachments/{evidence_ref}/extract`: Trigger and persist PDF/OCR extraction.
  - `GET /v1/attachments/{evidence_ref}/extraction`: Retrieve persisted extraction results.
- **Frontend Operational UI (`AttachmentViewer`)**:
  - Authorized inline preview and download for PDF and image attachments.
  - Interactive `[🔍 Run Extraction / OCR]` action.
  - Prominent red/yellow `⚠️ UNVERIFIED EVIDENCE` alert banner for payment screenshots.
  - Extracted order fields table (SKU, quantity, delivery time) with bounding box quotes.
  - Text block list displaying page numbers, method, confidence score, and bounding coordinates.
  - Integrated into `DurableInbox` details panel with attachment cards and modal viewer.

### 2. Verification Results
- `backend/app/context/tests/test_attachment_storage.py` (4 passed)
- `backend/app/context/tests/test_pdf_extraction.py` (5 passed)
- `backend/app/context/tests/test_image_ocr.py` (5 passed)
- Backend full suite: 284 passed, 2 skipped, 0 failed.
- Frontend full suite: 149 passed, 5 skipped, 0 failed.
- Frontend build: `npm run build` succeeded with 0 errors.

---

# P1 BATCH 3 Handoff — 2026-10-21 (Context Lifecycle, Version History and Human Review)

Active branch: `feat/p1-context-intelligence`; commits for this batch:
- Models & Storage: `8c18730` (`feat(p1): implement OrderContext models, optimistic concurrency, and storage in p1_dev`)
- Context Service & API: `d38f6c5` (`feat(p1): implement ContextService, review endpoints, message merge, and optimistic locking`)
- Frontend Review Drawer & Detail: `5e73ff0` (`feat(p1): implement OrderContextDetail, ReviewDrawer, and context actions in DurableInbox`)

### 1. Core Deliverables and Invariants Enforced
- **OrderContext Domain Storage (`p1_dev.order_contexts`)**:
  - Schema: `context_id`, `tenant_id`, `order_id`, `customer_id`, `customer_identity_status`, `status` (`INFORMATION_READY`, `INFORMATION_PARTIAL`, `CONFLICT`, `UNRESOLVED`), `requested_items`, `requested_delivery_at`, `delivery_qualifier`, `special_instructions`, `missing_fields`, `conflicts`, `source_message_ids`, `field_evidence`, `context_version`, `last_reviewed_by`, `last_reviewed_role`, `created_at`, `updated_at`.
- **Immutable Version History (`p1_dev.order_context_versions`)**:
  - Every context evolution (creation, follow-up merge, human correction, human acceptance) records a versioned immutable snapshot with change type (`INITIAL_CREATION`, `MESSAGE_MERGE`, `HUMAN_EDIT`, `HUMAN_ACCEPT`), actor credentials (`actor_id`/`actor_role`), and notes.
- **Safe Follow-up Message Merge**:
  - Follow-up messages for an existing order evolve the context without silently overwriting confirmed terms.
  - Discrepancies (SKU change, quantity change, delivery time change) transition the context to `CONFLICT`, recording differences in the `conflicts` list while retaining baseline data for human review.
- **Human Review & Field Editing (`p1_dev.context_reviews`)**:
  - Endpoints: `POST /v1/contexts/{context_id}/review` (supports `EDIT_FIELD`, `ACCEPT_EXTRACTION`, `REQUEST_MORE_INFO`, `MARK_UNRESOLVED`) and `PATCH /v1/contexts/{context_id}`.
  - Audit trail tracks actor identity (`X-Actor-ID`), role (`X-Actor-Role`), reviewer notes, field diffs (`field_changes`), and version transitions (`context_version_before` → `context_version_after`).
- **Database & API Level Optimistic Concurrency Control**:
  - Review and update operations require `expected_context_version`.
  - Concurrent stale requests return HTTP 409 Conflict (`StaleContextVersion`), preventing dirty writes.
- **Endpoints**:
  - `GET /v1/contexts/{context_id}`
  - `GET /v1/contexts/by-order/{order_id}`
  - `POST /v1/contexts/from-message/{message_id}`
  - `POST /v1/contexts/{context_id}/review`
  - `PATCH /v1/contexts/{context_id}`
  - `GET /v1/contexts/{context_id}/versions`
  - `GET /v1/contexts/{context_id}/reviews`
- **Frontend Operational UI**:
  - `ReviewDrawer` (FE-02): Drawer interface for correcting SKU, quantity, unit, requested delivery, qualifier, special instructions, and reviewer notes with standard review decisions.
  - `OrderContextDetail` (FE-03): Displays item table, verbatim Unicode evidence quotes, dimension cards, conflict alert banners, missing field banners, and collapsible version timeline / review audit log.
  - `DurableInbox` Integration: One-click `[📋 Generate / View Order Context]` modal for `PROCESSED` messages.

### 2. Verification Results
- `backend/app/context/tests/test_order_context_storage.py` (4 passed)
- `backend/app/context/tests/test_context_api.py` (3 passed)
- Backend full suite: 280 passed, 2 skipped, 0 failed.
- Frontend full suite: 135 passed, 5 skipped, 0 failed.
- Frontend build: `npm run build` succeeded with 0 errors.

---

# P1 BATCH 2 Handoff — 2026-10-21 (Verified Identity and Order Association)

Active branch: `feat/p1-context-intelligence`; commits for this batch:
- Models & Synthetic Directory: `4457c75` (`feat(p1): implement identity association models, synthetic directory, and storage`)
- Association Service & API: `5f1bc10` (`feat(p1): add association API endpoints with actor tracking and optimistic concurrency`)
- Frontend Association Panel: `d351cbe` (`feat(p1): add identity and order association panel to DurableInbox UI`)

### 1. Core Deliverables and Invariants Enforced
- **Identity Boundary Separation**: Distinguishes `PlatformIdentity` (channel/sender ID), `CustomerAccount`, `IdentityLinkStatus` (`VERIFIED`, `LINK_CANDIDATE`, `UNLINKED`, `CONFLICT`), and `MatchType`.
- **Zero-Guessing Invariants**:
  - Never establishes customer identity from sender name similarity or model output.
  - Extracted order reference alone is never authorization. Unverified senders citing valid order IDs are flagged as `LINK_CANDIDATE` requiring manual confirmation.
  - Cross-customer order reference conflict: When a verified customer cites an order belonging to another customer, a `SECURITY CONFLICT` alert is raised immediately.
  - Multiple active orders for a customer without an explicit reference are all listed as candidates without arbitrary selection.
- **Persistence and Audit (`p1_dev.message_associations`)**:
  - Schema: `association_id`, `tenant_id`, `message_id`, `status`, `verified_customer`, `verified_order`, `candidates`, `conflicts`, `last_decision`, `version`, `updated_at`.
  - Manual confirmation endpoint: `POST /v1/messages/{id}/association`, persisting decision (`CONFIRMED`/`REJECTED`), actor ID, actor role, timestamp, evidence, and reason.
  - Optimistic concurrency: Enforces `expected_version`, rejecting stale concurrent requests with HTTP 409 Conflict.
- **Frontend Association Panel (`DurableInbox`)**:
  - Displays verified vs suggested identity badges and versions.
  - Candidate cards show match type (`TRUSTED_SENDER`, `EXTRACTED_ORDER_REF`), confidence, and rationale.
  - Interactive `✓ Confirm link` and `✗ Reject / Unlink` actions with error recovery.
  - Audit trail card displays last decision maker, role, timestamp, and notes.

### 2. Verification Results
- `backend/app/context/tests/test_association_models_and_storage.py` (7 passed)
- Backend full suite: 303 passed, 0 failed.
- Frontend full suite: 129 passed, 5 skipped, 0 failed.
- Frontend build: `npm run build` succeeded with 0 errors.

---

# P1 TASK 2C Handoff — 2026-10-21 (Persisted Extraction, Processing API, and Inbox UI)

Active branch: `feat/p1-context-intelligence`; commits for this batch:
- Backend: `2dcab66` (`feat(p1): persist deterministic extraction and implement processing API`)
- Frontend: `1527f8e` (`feat(p1): integrate extraction processing and evidence highlights in DurableInbox`)
- Evidence Validation & Retry: `9eb0c4c` (`feat(p1): validate source evidence spans before persistence and add failed attempt test`)

### 1. Core Deliverables and Invariants Enforced
- **Persisted Extraction Attempts (`p1_dev.extraction_attempts`)**:
  - Schema: `attempt_id`, `tenant_id`, `message_id`, `extractor_version`, `input_content_sha256`, `status`, `fields` (JSONB), `diagnostic`, `started_at`, `completed_at`.
  - Row-level locking & concurrency protection: `process(tenant_id, message_id, reprocess=False)` uses `with_for_update()` to prevent concurrent duplicate processing (returns HTTP 409 `ProcessingConflict`).
  - Idempotency guarantees: Identical input content hash and extractor version reuse existing attempt. Explicit `reprocess=True` preserves full historical audit trail.
  - Strict evidence span validation: Validates `evidence.start`/`evidence.end` against immutable message text slices. Mismatches safely record `PROCESSING_FAILED` with diagnostic information.
- **Processing and Retrieval Endpoints**:
  - `POST /v1/messages/{message_id}/process?reprocess={true|false}`: Trigger extraction and persist status.
  - `GET /v1/messages/{message_id}/extraction`: Retrieve latest extraction result (404 if not found).
  - `GET /v1/messages/{message_id}/attempts`: Retrieve full historical attempt list (ordered by `started_at DESC`).
  - Sanitized error handling: Database connection strings redacted on 503 `PersistenceUnavailable`.
- **Frontend Operational UI (`DurableInbox`)**:
  - Connected to operational backend endpoints (`process`, `getExtraction`, `listAttempts`).
  - Exact Unicode code-point evidence span highlighting using `Array.from(text)` and `<mark className="p1-span-highlight">`.
  - Clear attribution and version: Displays `RULE (p1-deterministic-v3)` with structured extracted fields table.
  - Audit history drawer lists all historical extraction attempts with timestamps and status.
- **Contract Safety**: Candidate extractions remain bounded in P1 storage; never prematurely promoted to Core `BusinessContext` or asserted as `CONFIRMED`.

### 2. Verification Results
- `backend/app/context/tests/test_persisted_extraction.py` (8 passed)
- Backend full suite: 296 passed, 0 failed.
- Frontend full suite: 128 passed, 5 skipped, 0 failed.
- Frontend build: `npm run build` succeeded with 0 errors.

---

# P1 TASK 2B-FIX Handoff — 2026-10-21 (Extraction Safety Fixes)

- Fixes: Lower bounds, approximations, ranges, and speculative language do not default to EXACT; independent multiple expressions and cross-sentence date/time do not select the first or concatenate; missing timezones do not fill defaults; yearless dates do not guess years; DST gap/fold does not auto-resolve offsets; relative dates evaluate relative to `message_at` (fallback `received_at`) rather than execution clock; delayed receipt and past dates require review; illegal time tokens do not truncate or fallback to DATE_ONLY; ambiguous SKU/unit aliases do not mark VALID.
- Original text, hashes, and message metadata remain unchanged; source spans use Unicode code points. DATE_ONLY remains a date string without midnight; original EXACT/DEADLINE qualifier relation preserved in metadata.
- Policy strictly covers declared narrow syntax without trusted tenant defaults. Explicit envelope timezone is declared source only. Historical records with implicit defaults require independent provenance checks; old records are not silently migrated.
- Verification: 139 focused passed; full backend 295 passed, 0 skipped. Commits: `fcee8cc`, `5d70f91`, `9e492f5`, `9c6a1ed`, `a8b78a8`, `601c04f`.
- Core contract alignment: DATE_ONLY not accepted as datetime in Core; qualifiers not accepted; PARTIAL/AMBIGUOUS cannot be directly passed; legacy READY normalizes to INFORMATION_READY; `requested_items` requires at least one item.
- Safe provisional persistence verified; does not publish unverified contexts to Core.

---

## Historical TASK 2A Handoff

- Working branch: `feat/p1-context-intelligence`; baseline commit `d5dfd62`. Local implementation commit: `42087a8`.
- `extract_explicit_fields(StoredMessage, catalog=...)` returns typed `ExtractionResult`/`ExtractedField`/`FieldEvidence`. No premature Core publication.
- Supports literal `ORD-<digits>` / `synthetic_order_<alphanumeric>` references (UNRESOLVED, never authorized order link), exact English burger aliases, and positive integer quantities with pcs/pieces.
- No implicit units. Unsupported units, fractions, negative counts are INVALID. Product lists, alternatives, negation defer quantity association. Unknown products remain unresolved.
- Evidence preserves message ID, exact original quote, method `RULE (p1-explicit-v1)`, and `[start,end)` Unicode code-point offsets.
- Validation: 67 passed in test suite. Clean worktree verified.
