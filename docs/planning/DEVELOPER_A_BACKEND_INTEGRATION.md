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
