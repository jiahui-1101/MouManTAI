# Developer A — Customer & Communications Frontend Scope & P5 Handoff

**Author:** Developer A (Customer & Communications)  
**Date:** 2026-10-24  
**Baseline:** MouManTAI v2.2 (Commit Baseline: `feat/frontend-orbyte-sidebar`)  
**Target Recipient:** Developer C (P5 Shared Frontend Foundation Lead) & Developer B (Orders & Feasibility Lead)

---

## 1. Executive Summary & Ownership Boundaries

Developer A has finalized the **Customer & Communications** frontend scope to production-oriented quality, strictly respecting repository ownership boundaries:
- **Developer A Owned & Modified:** `frontend/src/features/context/**`, `frontend/src/features/communication/**`, feature-local styles, local unit tests, and this handoff document.
- **Developer C / P5 Owned (Untouched):** `frontend/src/App.tsx`, `frontend/src/layout/**`, `frontend/src/shared/**`, shared navigation configuration.
- **Developer B Owned (Untouched):** `frontend/src/features/orders/**`, `frontend/src/features/feasibility/**`. All reusable context and review drawer components are cleanly exported with strict TypeScript prop contracts for Developer B's Order Detail integration.

---

## 2. Feature Completion Matrix (A1 – A4)

| Feature ID | Scope Description | Requirements Covered | Status | Implementation Details |
|---|---|---|---|---|
| **A1** | **Customer Inbox & Inquiry Detail** | `FE-CUS-01`<br>`FE-CUS-02` | **COMPLETE** | Live multi-channel inbox (`DurableInbox.tsx`) with search, channel filter, processing status, pagination, sender identity, OCR extraction provenance, attachment viewer with rotate/zoom, and drawer toggle. |
| **A2** | **Order Draft & Clarification** | `FE-CUS-03`<br>`FE-CUS-04` | **COMPLETE** | Multi-item order draft form (`ReviewDrawer.tsx`), candidate proposals, unverified product candidate handling, strict delivery ISO timestamp validation with explicit UTC offset, AI suggested clarification preview (P4 draft integration), and note adoption. Decoupled from message sending. |
| **A3** | **Human Review Workspace** | `FE-HR-01`<br>`FE-HR-02` | **COMPLETE** | Dedicated workspace (`HumanReviewPage.tsx`) filtering review-relevant inquiries, showing side-by-side evidence, model telemetry, context initialization, multi-item field corrections, conflict review acknowledgment, and optimistic locking (`expected_context_version`) with 409 conflict banners and reload retry. |
| **A4** | **Communications, Status & Feedback** | `FE-STAT-01`<br>`FE-STAT-02`<br>`FE-FB-01`<br>`FE-FB-02` | **COMPLETE** | Communication Center (`CommunicationCenterPage.tsx`), Confirmation Workspace (`ConfirmationWorkspacePage.tsx`), Follow-Up Queue (`FollowUpQueuePage.tsx`), and Recipient Preferences (`RecipientPreferences.tsx`). Template-based factual milestone tracking without false AI confirmation emails. |

---

## 3. Component Exports & Integration Contract for Developer C (P5)

Developer C can mount the newly provided dedicated pages and existing views using `App.routeExtensions` without modifying feature internals:

| Component / Export Name | Import Path | Intended Route | Required Route Parameters | Required API / Backend Dependencies | Permission Requirements | Loading / Error / Unavailable States |
|---|---|---|---|---|---|---|
| `HumanReviewPage` | `features/context` | `/human-review` | None | `GET /v1/messages`<br>`GET /v1/contexts/{id}`<br>`POST /v1/contexts/{id}/review`<br>`GET /v1/contexts/catalog` | Role: `STAFF`, `MANAGER`, `OWNER` | Loading skeleton, empty queue notice, inline error alert, 409 version conflict banner with reload button. |
| `DurableInbox` | `features/context` | `/inbox` | None | `GET /v1/messages`<br>`POST /v1/messages/ingest`<br>`POST /v1/messages/{id}/process`<br>`GET /v1/messages/{id}/association` | Any authenticated actor | Shimmer loading rows, empty search/filter state, API error notice with retry, auto-refresh on submission. |
| `OrderContextDetail` | `features/context` | `/orders/:id/context` or `/contexts/:id` | `:id` (order_id or context_id) | `GET /v1/contexts/{id}`<br>`GET /v1/contexts/by-order/{order_id}`<br>`POST /v1/contexts/{id}/publish` | Role: `STAFF`, `MANAGER`, `OWNER` | Loading state, 404 order context not found, audit history accordion, publish error/success banners. |
| `CommunicationCenterPage` | `features/communication` | `/communications` | None | `GET /v1/communications`<br>`GET /v1/communications/summary`<br>`GET /v1/communications/{id}` | Any authenticated actor | Skeleton loading, empty queue message, blocked preparation explanations, draft expiry ticker. |
| `ConfirmationWorkspacePage` | `features/communication` | `/confirmations/:id` | `:id` (confirmation_id) | `GET /v1/confirmations/{id}`<br>`GET /v1/confirmations/{id}/attempts` | Role: `MANAGER`, `OWNER` | Loading spinner, 404 not found, revoked/expired/superseded warnings, terms digest presentation. |
| `FollowUpQueuePage` | `features/communication` | `/communications/follow-ups` | None | `GET /v1/confirmations` | Any authenticated actor | Real-time counts bar, filter tabs, read-only exception badges (Expiring Soon, Terminal, Expired). |
| `RecipientPreferences` | `features/communication` | `/communications/preferences` | None | `GET /v1/communications/recipient-preferences`<br>`POST /v1/communications/recipient-preferences` | Write requires `MANAGER` / `OWNER` | Read-only enforcement for STAFF, optimistic save protection, revocation audit history. |

### Route Extension Registration Spec for Developer C

```tsx
// In Developer C's App.tsx / route extension hook:
import { HumanReviewPage } from "./features/context";

export const developerARoutes: AppRouteRegistration[] = [
  {
    path: "/human-review",
    element: <HumanReviewPage />,
  },
];
```

---

## 4. Developer B Integration Contract (Order Detail Integration)

Developer B can embed the following components inside the Order Detail workspace (`frontend/src/features/orders/OrderDetail.tsx`):

### 4.1. `ReviewDrawer` (Context & Multi-Item Correction Drawer)

```tsx
import { ReviewDrawer } from "../context";
import type { ReviewDrawerProps, OrderContextRecord } from "../context";

// Props interface:
export interface ReviewDrawerProps {
  context: OrderContextRecord;
  isOpen: boolean;
  onClose: () => void;
  onUpdated: (updated: OrderContextRecord) => void;
  catalogLoader?: () => Promise<{ sku: string; unit: string }[]>;
}

// Usage in Order Detail:
<ReviewDrawer
  context={orderContext}
  isOpen={isReviewOpen}
  onClose={() => setIsReviewOpen(false)}
  onUpdated={(updatedCtx) => {
    setOrderContext(updatedCtx);
    // Refresh order detail feasibility if needed
  }}
/>
```

### 4.2. `OrderContextDetail` (Embedded or Routed Context Detail)

```tsx
import { OrderContextDetail } from "../context";
import type { OrderContextDetailProps } from "../context";

export interface OrderContextDetailProps {
  orderId?: string;
  contextId?: string;
  onClose?: () => void;
  onContextUpdated?: (updated: OrderContextRecord) => void;
}

// Embedded usage inside Order Detail tabs:
<OrderContextDetail
  orderId={order.order_id}
  onContextUpdated={(updated) => console.log("Context refreshed:", updated)}
/>
```

### 4.3. `AttachmentViewer` & `ExtractionProvenance`

- `AttachmentViewer`: accepts `evidenceRef: string`, `filename?: string`, `mediaType?: string`, and `onClose?: () => void`. Displays PDF/image attachments with zoom, pan, and rotation.
- `ExtractionProvenance`: accepts `attempt: ExtractionAttemptRecord`. Displays pipeline version (`p1-deterministic-v6` or AI pipeline), runtime telemetry, model outcomes, and accepted model fields.

---

## 5. Real Backend Integration & Architecture Invariants

1. **Message-Review Workspace vs Authoritative Review-Task Queue**:
   - The backend does not provide a standalone `/v1/reviews` queue endpoint.
   - Review actions are executed directly per context via `/v1/contexts/{context_id}/review`.
   - `HumanReviewPage` is therefore explicitly architected as an **Inquiry & Context Review Workspace** that identifies review-relevant inquiries from `/v1/messages` and `/v1/contexts`. It displays an explicit architectural note clarifying that it is not a distributed task queue assignment engine.
2. **Optimistic Version Locking**:
   - Review actions (`EDIT_FIELD`, `ACCEPT_EXTRACTION`) send `expected_context_version: context.context_version`.
   - The backend enforces version matching and raises `StaleContextVersion` (HTTP 409) if concurrent edits occurred.
   - Both `ReviewDrawer` and `HumanReviewPage` catch 409 responses and present a `VersionConflictBanner` with a one-click `Reload Latest Context` retry button.
3. **Decoupled Clarification & Reviewer Notes**:
   - Adopting an AI suggested clarification note populates the staff reviewer note for audit purposes.
   - It **does not send** a message to the customer, adhering strictly to the invariant that previewing or drafting is never represented as sending.

---

## 6. Verification Evidence

- **Database & Backend Services**:
  - PostgreSQL container `monmantai-p1-dev-postgres-1` healthy on port `55432`.
  - FastAPI server running on `http://127.0.0.1:8000` with live ingestion streaming (`synthetic_tenant_a` has >1,760 verified messages).
- **TypeScript & Typecheck**:
  - `npm run typecheck` (`tsc --noEmit`): **0 errors**.
- **Automated Vitest Suite**:
  - `npx vitest run`: **31 test files passed, 493 tests passed, 5 skipped (100% pass rate)**.
- **Production Bundle Build**:
  - `npm run build` (`tsc -b && vite build`): **Built in 2.53s** (`dist/` generated cleanly).
- **Git State**:
  - All changes staged / committed locally on feature branch `feat/frontend-orbyte-sidebar`. **Zero remote push executed**.
