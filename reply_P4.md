Hi P4!

# Reply to P4 (Handoff #P4-1 — Communication Center Integration, Router Mounting & Authority Wiring)

**To**: Person 4 (F4 Communication & Confirmation Full-Stack)  
**From**: Person 5 (Shared Core, Contracts, Integration Coordinator)  
**Date**: 2026-10-22  
**Subject**: Confirmation of Communication Center UI Mount, Router Registration, Server Authorities, and Invariant Boundaries

---

### 1. Communication Center UI Mount [H4-1-UI1]
- **Decision: ACCEPTED**:
  - Reason: `<CommunicationCenterPage />` is type-safe and independently tested in `frontend/src/features/communication/`.
  - P5 has wired `/communications` in `frontend/src/App.tsx`, replacing the placeholder with `<CommunicationCenterPage />` within `AppShell`.
  - Reuses shared `QueryClientProvider`, `AuthProvider`, and navigation badges.

---

### 2. Backend Router Registration [H4-1-ROUTER1]
- **Decision: ACCEPTED**:
  - Reason: Clean boundary separation; endpoints are tenant-isolated and reuse `get_request_context` and `get_db`.
  - P5 mounts `communication_router` in `backend/app/main.py` under `/v1/communications`.

---

### 3. Server-Side Authorities (`RequestAuthority` & `DraftAuthority`) [H4-1-AUTH1]
- **Decision: ACCEPTED**:
  - Reason: Invariant safety (D-005) prohibits client-supplied `role`, `tenant_id`, or `approved=true` from request bodies.
  - Action authorization (`PREPARE_DRAFT`, `SEND_MESSAGE`, `APPROVE_REQUEST`) must be validated server-side against current approved proposals, terms, snapshot versions, recipient identity links, and explicit expiration.
  - Absence of server authorization fails closed with HTTP 403 `APPROVAL_REQUIRED` or HTTP 503 `AUTHORITY_UNAVAILABLE`.

---

### 4. Alembic Migration & Persistence [H4-1-MIG1]
- **Decision: ACCEPT WITH CHANGES (Sequential Head after 0007)**:
  - Current Alembic head on `main` is `0007_recovery_case_constraints_alignment`.
  - P4's models (`communication_requests`, `communication_request_sources`, `communication_drafts`) will be scheduled in migration `0008` (or `0009` following P1 context tables) preserving composite `(tenant_id, ...)` foreign keys and unique constraints.

---

### 5. Channel Scope & Invariant Guardrails [H4-1-CHANNEL1]
- **Decision: Synthetic / Mock Channels Only**:
  - Reason: SDCHackathon safety rules (AGENTS §9, §13) forbid live messaging credentials or paid external provider charges.
  - Supported channels remain synthetic (`MOCK_EMAIL`, `MOCK_WHATSAPP`, `MOCK_SMS`).
  - Strict invariant: `SENT != ACCEPTED != FULFILLED`. Message delivery confirmation never auto-advances commitment agreement or fulfilment states without explicit customer confirmation and operational proof of delivery.

---

### 6. Next Actions for P4
1. **Rebase on `origin/main`**: Sync branch with latest `main` (`74470cf`, Alembic head `0007`).
2. **Submit Clean PR**: Ensure PR includes only P4-owned paths (`backend/app/communication/`, `frontend/src/features/communication/`).
3. **What P4 Must NOT Do**:
   - Do NOT advance commitment state upon sending a message.
   - Do NOT accept vague customer replies ("OK", "Noted") as binding confirmation without proposal-version verification.
   - Do NOT hardcode production API credentials or live gateway secrets.

Thank you!
