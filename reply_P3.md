Hi P3!

# Reply to P3 (Handoff #P3-1 & #P3-2 — Migration 0007 Acceptance, APPROVE_PLAN Policy & Test Reconciliation)

**To**: Person 3 (F3 Recovery Full-Stack)  
**From**: Person 5 (Shared Core, Contracts, Integration Coordinator)  
**Date**: 2026-10-22  
**Subject**: Confirmation of Migration 0007, APPROVE_PLAN Consequential Policy, Test Fixture Alignment, and Staged Merge Unblock

---

### 1. Delivery & Commit SHA Notification [HP3-1-INFO1, HP3-1-SHA1]
- **Target Schema Merged**: Migration `0007_recovery_case_constraints_alignment.py` is committed and merged to `main`:
  - **Feature Branch Commit SHA**: `7175066` on `feat/p5-core-integration`.
  - **Main Merge HEAD SHA**: `74470cf` on `main`.
  - **Alembic Single Head**: `0007_recovery_case_constraints_alignment`.
- **Target Schema Invariants Enforced**:
  1. `recovery_cases` PK remains composite `(tenant_id, case_id)`.
  2. `fk_recovery_case_triggers_case_tenant_commitment` enforces `ON DELETE RESTRICT` (append-only trigger history; no silent cascade of audit evidence).
  3. Unique constraint uses plural form `uq_recovery_cases_tenant_case_commitment` on `(tenant_id, case_id, commitment_id)`.
  4. Partial unique index `uq_recovery_cases_one_active_per_commitment` covers the 5 active statuses (`OPEN`, `AWAITING_EVALUATION_INPUTS`, `OPTIONS_READY`, `NO_SAFE_PLAN`, `NEEDS_REPLAN`).
  5. Direct Trigger-to-Commitment FK retained with `ON DELETE RESTRICT`.

---

### 2. Resolution of P0 Security Blocker: `APPROVE_PLAN` [HP3-2-AUTH1]
- **Decision: ACCEPTED & DELIVERED**:
  - Reason: Plan approval is an irreversible, consequential recovery transition committing SME resources.
  - Added `"APPROVE_PLAN"` to `CONSEQUENTIAL_ACTIONS` in `backend/app/core/policy.py`.
  - Server-side role check strictly enforces: `actor_role` must be `"OWNER"` or `"MANAGER"`. Callers with `"STAFF"` are rejected with HTTP 403 `APPROVAL_REQUIRED`.
  - Server-resolved identity (D-005) is mandatory; request-body role claims or client headers are never trusted as production authentication.

---

### 3. Reconciliation of Backend Test Failures [HP3-2-TEST1, HP3-2-TEST2]
1. **Trigger Table Shape Alignment**:
   - P5 has updated all Core test fixtures ([`test_transaction_ab_isolation.py`](file:///c:/Users/ganru/Documents/MouManTAI/backend/tests/test_transaction_ab_isolation.py), [`test_feature_handshakes.py`](file:///c:/Users/ganru/Documents/MouManTAI/backend/tests/integration/test_feature_handshakes.py)) to match the current approved P3 ORM columns (`snapshot_id`, `snapshot_version`, `constraints`, `affected_commitment_ids`, `evidence_refs`, `correlation_id`, `occurred_at`, `event_digest`).
   - Line 1390 of [`test_feature_handshakes.py`](file:///c:/Users/ganru/Documents/MouManTAI/backend/tests/integration/test_feature_handshakes.py) now asserts `ON DELETE RESTRICT` via `pytest.raises(IntegrityError)` when deleting a case with triggers, matching Migration 0007.
2. **Stale Event Guard Preservation**:
   - The stale-event guard (`event.commitment_version < current_version`) is preserved as a non-negotiable invariant. Tests generating at-risk events must align the event's version with the current commitment version.

---

### 4. Shared-File Conflict Approvals [HP3-2-MERGE1]
- **`frontend/src/App.tsx`**: Approved. Preserves P2 `/commitments/:id`, `/impact/:id`, P3 `/recovery/:id`, P4 `/communications`, and P5 shell.
- **`docs/TEAM_LOG.md`**: Approved. Both branches' entries are preserved without overwriting historical records.
- **`backend/app/main.py`**: P3 recovery router inclusion is approved; live subscriber registration and consequential execution remain guarded.

---

### 5. Next Actions for P3
1. **Pull Latest Main**: Sync your branch against `origin/main` (including the `APPROVE_PLAN` policy update and trigger shape alignment).
2. **Finalize Merge Commit**: Complete your staged history-preserving merge of PR #10.
3. **What P3 Must NOT Do**:
   - Do NOT weaken the stale-event guard.
   - Do NOT change `ON DELETE RESTRICT` back to CASCADE.
   - Do NOT enable live subscriber `p3.recovery_trigger.v1` or unverified execution until joint E2E confirmation passes.

Thank you!
