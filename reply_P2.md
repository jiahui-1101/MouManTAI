Hi P2!

# Reply to P2 (Handoff #P2-1 — Schema Constraint Alignment, Adapter Placement & PR Verification)

**To**: Person 2 (F2 Feasibility Full-Stack)  
**From**: Person 5 (Shared Core, Contracts, Integration Coordinator)  
**Date**: 2026-10-22  
**Subject**: Alignment on Migration 0006 Constraints, Feasibility Adapters Placement, and PR Delivery

---

### 1. Migration 0006 Schema & Constraints Verification [H2-1-ITEM1, H2-1-ITEM2]

P5 has finalized and verified migration `0006_recovery_cases` on real PostgreSQL:

1. **Foreign Key Delete Policy (`ON DELETE CASCADE`)**:
   - The three-column foreign key `(tenant_id, case_id, commitment_id)` on `recovery_case_triggers` defines:
     ```sql
     FOREIGN KEY (tenant_id, case_id, commitment_id)
     REFERENCES recovery_cases (tenant_id, case_id, commitment_id)
     ON DELETE CASCADE
     ```
   - Verified on PostgreSQL: deleting a `recovery_cases` row cascades cleanly to its linked `recovery_case_triggers`.

2. **Constraint & Index Naming Alignment**:
   - Unique constraint backing the composite foreign key:
     ```sql
     CONSTRAINT uq_recovery_case_tenant_case_commitment
       UNIQUE (tenant_id, case_id, commitment_id)
     ```
   - Partial unique index: `uq_recovery_cases_one_active_per_commitment`, scoped strictly to active statuses:
     `'OPEN', 'AWAITING_EVALUATION_INPUTS', 'OPTIONS_READY', 'NO_SAFE_PLAN', 'NEEDS_REPLAN'`.

---

### 2. Feasibility Adapters Placement [H2-1-ITEM3]

- **Current Dual-Path Setup**: The authoritative adapter implementations (`AuthoritativeEvaluationAuthority`, `AuthoritativeAssessmentWriter`, `AuthoritativeAssessmentHistoryReader`, `AuthoritativeSupplierDelayProcessor`, `AuthoritativeImpactReader`) reside in `backend/app/core/feasibility_adapters.py` and are also exposed via `backend/app/feasibility/adapters.py`.
- **Proposal for P2**: We propose to **keep both paths aliased until P2 completes your integration review, or consolidate strictly into `backend/app/core/` if you confirm that P2 prefers importing directly from Core**.
- **Dependency Injections**: Concrete adapters are registered via dependency overrides in `backend/app/main.py`.

---

### 3. Implementation Verification & Checkpoint PR [H2-1-ITEM4]

- **Delivery Scope**: The Phase 7B-2 PR delivers `backend/app/core/feasibility_adapters.py`, D-017 multi-subscriber dispatcher gates (`p2_confirmed_evaluator`, `p3.recovery_trigger.v1`), single-edge risk transition in `assess()`, and migration `0006_recovery_cases`.
- **PostgreSQL Test Evidence**:
  - The handshake test suite has been executed against PostgreSQL (`19 passed, 0 failed`):
    ```bash
    TEST_DATABASE_URL="postgresql://postgres:postgres@localhost:5432/moumantai_test" pytest backend/tests/integration/test_feature_handshakes.py -q
    ```
  - Full output log is saved in `docs/postgresql_handshake_verification.log` confirming `engine.dialect.name == "postgresql"`, dual-boundary rollback (HTTP path and outbox consumer path), and atomic commit/rollback.

Thank you!
