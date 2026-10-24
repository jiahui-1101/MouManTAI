# Developer A — v2.2 Backend Integration & Dual-Mode Readiness Report

**Author:** Developer A (Customer & Communications)  
**Date:** 2026-10-24  
**Git Branch:** `feat/frontend-orbyte-sidebar`  
**Target Backend Baseline:** MouManTAI v2.2 (P1 Inbound Context & P4 Communications)  
**Collaborators:** P1 Backend Owner, P4 Backend Owner, Developer C (P5 Shared Frontend Lead), Developer B (Orders Lead)

---

## 1. Executive Status & Contract Summary

This report documents Developer A's frontend implementation readiness for the upcoming P1/P4 v2.2 backend endpoints. The backend developers are actively implementing Human Review task queue routes and Clarification dispatch routes; Developer A has implemented feature-local, typed adapters with capability detection, optimistic version guards, and graceful fallbacks to verified P1/P4 operational APIs.

### Status Scorecard

| Capability Area | Target Contract Endpoint(s) | Current Backend Status | Frontend Readiness | Fallback Mode |
|---|---|---|---|---|
| **Human Review Task Queue** | `GET /v1/reviews`<br>`POST /v1/reviews/{id}/resolve` | **MISSING** | **READY (Dual-Mode)** | Projects review items from verified P1 messages and resolves via `POST /v1/contexts/{id}/review`. |
| **Context Review Correction E2E** | `POST /v1/contexts/{id}/review` | **PASS (Verified Live)** | **PRODUCTION READY** | Audited multi-item correction, approved catalog SKUs, strict ISO deadlines, optimistic locking (HTTP 409 conflict detection). |
| **Clarification Issue Timeline** | `GET /v1/conversations/{id}/issues` | **MISSING** | **READY (Dual-Mode)** | Projects issues from context `missing_fields`, `conflicts`, and candidate proposals; enforces 2-turn max rule. |
| **Clarification Outbound Dispatch** | `POST /v1/conversations/{id}/clarify` | **PARTIAL / MISSING** | **READY (Non-Simulated)** | Returns `PREVIEW ONLY · NOT SENT` safely without fabricating external delivery or mutating state. Note adoption supported. |

---

## 2. Capability Detection & Dual-Mode Architecture

To prevent breaking during the backend development transition, Developer A implemented automatic capability detection with safe fallback logic:

### 2.1. Review Task Queue Adapter (`reviewTaskApi.ts`)
- **Probe:** `detectReviewTaskCapability()` checks `GET /v1/reviews?limit=1`.
- **Authoritative Mode (`AUTHORITATIVE_BACKEND_QUEUE`):** When the backend endpoint is mounted, queries and resolves tasks directly using `/v1/reviews` and `/v1/reviews/{id}/resolve`.
- **Provisional Mode (`PROVISIONAL_INQUIRY_PROJECTION`):** When the endpoint returns 404/501, transparently projects tasks from `operationalApi.list(...)`.
- **Optimistic Locking:** Always transmits `expected_task_version` (or `expected_context_version`) to guarantee atomic concurrency protection.

### 2.2. Clarification Adapter (`clarificationApi.ts`)
- **Probe:** `detectClarificationCapability()` checks `GET /v1/conversations/{id}/issues`.
- **Authoritative Mode (`AUTHORITATIVE_BACKEND`):** Consumes backend issues, turn counters, and validator progress outcomes.
- **Provisional Mode (`PROVISIONAL_CONTEXT_PROJECTION`):** Derives issues dynamically from `OrderContextRecord.missing_fields` and `conflicts`. Flags `has_escalated_issues: true` if consecutive no-progress attempts reach 2.
- **Strict Non-Simulation:** When `POST /v1/conversations/{id}/clarify` is missing, returns `delivery_status: 'PREVIEW_NOT_SENT'` with an informative notice:
  > *"Preview Retained: Outbound endpoint is pending backend release. Clarification remains PREVIEW ONLY · NOT SENT."*

---

## 3. Real Backend & PostgreSQL Verification (Evidence)

The existing P1 context review workflow was verified live against the running FastAPI daemon (`http://127.0.0.1:8000`) and real PostgreSQL container (`127.0.0.1:55432`):

1. **Context Creation:**  
   `POST /v1/contexts/from-message/9c1e0b02-5353-43d8-a579-ff377e68dbf4`  
   Created context `447e8493-dbf4-4aad-bd38-a12b16658f11` at version `1`.

2. **Audited Correction Submission:**  
   `POST /v1/contexts/447e8493-dbf4-4aad-bd38-a12b16658f11/review`  
   - Actor: `user_staff_01` (Role: `STAFF`)  
   - Action: `EDIT_FIELD`  
   - Items: `BURGER` x `15` `pcs`  
   - Deadline: `2026-10-25T15:00:00+08:00` (`DEADLINE`)  
   - Expected Version: `1`  
   - Result: Successfully advanced context to version `2` with audited review row persisted in `p1_dev.context_reviews`.

3. **Optimistic Locking Guard (409 Conflict Replay):**  
   Replaying review with stale `expected_context_version: 1` against the version `2` context immediately raised HTTP 409:  
   `StaleContextVersion: Context version mismatch: expected 1, got 2`  
   Verified that frontend correctly catches this and presents the dedicated conflict banner with "Reload Latest Context" button.

---

## 4. UI Enhancements in Human Review Workspace

`HumanReviewPage.tsx` was enhanced with:
1. **Operational Capability Badge:** Displays `Backend Queue (v2.2)` or `Direct Review (v2.1)` in the workspace header.
2. **Clarification Issues Timeline:**
   - Displays issue breakdown for missing fields and conflicts.
   - Shows authoritative turn budget (`Turns: 0 / 2 max`).
   - Surfaces escalation alerts when 2 consecutive no-progress attempts occur.
3. **Clarification Dispatch Control:**
   - Staff can review draft text and trigger dispatch.
   - Safely retains preview with clear diagnostic notice when outbound route is not deployed.
   - Staff note adoption allows one-click copying of suggested clarification into audited context notes.

---

## 5. Remaining Backend-Owner Deliverables

To transition the frontend from Provisional to Authoritative mode, backend developers must provide the following:

### 5.1. P1 Backend Owner Deliverables (`v2.2 Reviews`)
1. `GET /v1/reviews`  
   - Query params: `status`, `priority`, `task_type`, `assigned_to`, `search`, `limit`, `offset`.  
   - Response: `{ items: ReviewTask[], total: number }`.
2. `POST /v1/reviews/{id}/resolve`  
   - Request: `{ expected_task_version: number, resolution: ReviewResolutionAction, field_edits?: object, note?: string }`.  
   - Enforce optimistic lock on `task.version` and update linked `order_context.context_version`.

### 5.2. P4 Backend Owner Deliverables (`v2.2 Clarifications`)
1. `GET /v1/conversations/{id}/issues`  
   - Response: `{ conversation_id: string, issues: ClarificationIssue[], total_turns_used: number, max_turns_allowed: number, has_escalated_issues: boolean }`.
2. `POST /v1/conversations/{id}/clarify`  
   - Request: `{ conversation_id: string, issue_ids: string[], draft_text: string, channel: string, recipient_identity_id: string, approval_note?: string }`.  
   - Connect to customer communication channels and persist in audit timeline.

---

## 6. Verification Summary

- **TypeScript Typecheck:** `npm run typecheck` passed with 0 errors.
- **Production Build:** `npm run build` (`tsc -b && vite build`) passed in 2.62s.
- **Unit Test Suite:** All feature-local context tests pass cleanly (`HumanReviewPage.test.tsx`, `reviewTaskApi.test.ts`, `clarificationApi.test.ts`, `ReviewDrawer.test.tsx`, `ReviewDrawerSafety.test.tsx`).
- **File Ownership Integrity:** Zero modifications made to Developer C shared files (`App.tsx`, `layout/**`, `shared/**`) and Developer B files (`orders/**`, `feasibility/**`).


---

## 7. Backend Integration Assessment Alignment & Confirmed Team Agreement

*In response to "# MouManTAI v2.2 — Backend Integration Assessment & API Gap Confirmation" from the Backend Lead.*

### 7.1. Reconciled Status on the 5 Integration Items

| Original Item | Reconciled Architecture Decision | Implementation Status | Frontend State | Action Required |
|---|---|---|---|---|
| **1. Delivery Timezone Validation** | Backend enforces offset-aware ISO 8601 (`2026-10-28T10:00:00+08:00`) and rejects naive timestamps (`2026-10-28T10:00:00`). | **SOLVED (Both Ends)** | `validateDeliveryTimestamp` verifies explicit offsets (`+08:00` or `Z`) with zero false positives. | None. Both ends completely aligned. |
| **2. Review Task Resolution** | **REUSE EXISTING**: Do NOT implement redundant `POST /v1/reviews/{id}/resolve`. Reuse authoritative `POST /v1/contexts/{context_id}/review`. | **SOLVED VIA REUSE** | Frontend already invokes `POST /v1/contexts/{id}/review` directly with `expected_context_version` and audited `field_edits`. Catch 409 conflict. | Backend: Add P2 Feasibility Invalidation trigger on review save. |
| **3. Human Review Task Queue** | `GET /v1/reviews` requires canonical `task_type`, priority, assignment, tenant isolation, and audit. If backend model is pending, dual-mode fallback is accepted for demo. | **GENUINELY MISSING (Backend)** | Frontend operates in Dual-Mode: probes `/v1/reviews`; falls back to projecting from durable P1 `GET /v1/messages`. Labeled honestly. | P1 + P5: Provide adapter or lightweight Task model when ready. Not a demo blocker. |
| **4. Issue-Level Clarification Progress** | Contract logic exists; durable query `GET /v1/conversations/{id}/issues` not yet exposed. Clarification rule: **two-consecutive-no-progress applies per issue**, not as a blanket conversation question limit. | **GENUINELY MISSING (Backend)** | Tracks `consecutive_no_progress_count` per issue. Unanswered questions do not increment. Derives from `missing_fields` and `conflicts`. | P3 + P1/P4: Provide durable issues endpoint when ready. |
| **5. Clarification Sending** | `POST /v1/conversations/{id}/clarify`. Sending cannot bypass authorization or accept raw email as identity. Outbound states: `DRAFT`, `PENDING_APPROVAL`, `QUEUED`, `SENT`, `FAILED`. | **GENUINELY MISSING (Backend)** | Strict non-simulation: blocks send when recipient identity is unverified; displays draft preview; deep-links to Communication Center for authorized send. | P3 + P4 + P5: Wire durable clarify endpoint coordinating Communication service. |

---

### 7.2. P2 Feasibility Invalidation Contract

As highlighted by the backend team, consequential order commitments must never rely on stale feasibility evaluations:
1. When a human reviewer amends `requested_items` (SKU, quantity, unit) or `requested_delivery_time` via `POST /v1/contexts/{id}/review`, the context version increments ($v \to v+1$).
2. Any prior P2 feasibility assessment linked to `context_version: v` must be treated as `SUPERSEDED` / `STALE_TERMS`.
3. In the UI, candidate orders linked to this context reflect updated terms and mandate a fresh feasibility assessment prior to commercial acceptance.

---

### 7.3. Answers to Backend Team Confirmation Questions (Section 8)

1. **Which endpoints have equivalent, reusable functionality?**
   - `POST /v1/contexts/{context_id}/review` completely covers task resolution with optimistic locking (`expected_context_version`) and audited field edits. `POST /v1/reviews/{id}/resolve` is NOT needed.
   - Delivery timezone validation is already solved on both ends using offset-aware ISO 8601 (`+08:00`).

2. **Which data models/repositories are already durable and authoritative?**
   - P1 PostgreSQL tables (`messages`, `order_contexts`, `order_context_versions`, `extraction_attempts`, `message_associations`, `context_reviews`).
   - P1 Source Reader & Context Mapping modules (`app/orders/p1_source_reader.py`, `app/orders/context_mapping.py`).

3. **Which endpoints are genuinely missing from the current API?**
   - `GET /v1/reviews` (Aggregated Task Queue).
   - `POST /v1/conversations/{conversation_id}/clarify` (Durable Clarification Outbound Dispatch).
   - `GET /v1/conversations/{conversation_id}/issues` (Durable Clarification Issue Timeline).

4. **Which request/response fields need adjustment to match current backend contracts?**
   - Review amendments use `ContextReviewRequest`: `{ action: "EDIT_FIELD" | "ACCEPT_EXTRACTION", expected_context_version: number, field_edits: object, note: string }`.
   - Datetimes must always include explicit UTC offset (e.g. `2026-10-28T10:00:00+08:00`).
   - Recipient references must use validated `recipient_identity_id` rather than arbitrary email strings.
   - Outbound status follows `DRAFT` | `PENDING_APPROVAL` | `QUEUED` | `SENT` | `FAILED`.

5. **Who will own each required integration?**
   - **P1 + P5**: Review Task semantics, Context Association, and shared persistence/auth.
   - **P3**: Clarification decision logic, issue-level progress evaluation, and turn accounting.
   - **P4**: Outbound sending, communication channel policies, and delivery status tracking.
   - **P2**: Feasibility assessment invalidation when order context terms are amended.

6. **Which integrations are essential for the demo, and which remain documented limitations?**
   - **Essential for End-to-End Demo Journey:**
     - Ingestion (synthetic/Gmail) $\to$ Message Inbox $\to$ Human Review Queue $\to$ Review & Amend full-page workspace $\to$ Audited Save (advances context $v1 \to v2$) $\to$ Link Candidate Order $\to$ P2 Feasibility Re-evaluation.
   - **Documented Limitations for Demo:**
     - Clarification Outbound Sending is demonstrated as Draft Preview with validation guards (no synthetic `SENT` spoofing).
     - Review Task Queue operates via the transparent Dual-Mode Adapter over durable P1 messages until a dedicated queue model is deployed.

7. **How will Context Review updates invalidate or supersede stale P2 assessments?**
   - On `POST /v1/contexts/{id}/review`, backend records the new version ($v+1$) and emits a domain event (`context.amended` or similar) that marks any active feasibility assessment referencing version $\le v$ as `SUPERSEDED`.
   - Order terms comparison reports `TERMS_AMENDED_REVALUATION_REQUIRED`, blocking acceptance until re-assessed.
