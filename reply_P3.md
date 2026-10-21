Hi P3!

# Reply to P3 (Handoff #P3-1 — Additive Migration 0007 Alignment, Schema Invariant Delivery & Integration Plan)

**To**: Person 3 (F3 Recovery Full-Stack)  
**From**: Person 5 (Shared Core, Contracts, Integration Coordinator)  
**Date**: 2026-10-22  
**Subject**: Confirmation of Migration 0007 Scope, RESTRICT Invariant, Fail-Closed Provenance Reader, and Verification Sequencing

---

### 1. Migration 0007 Target Schema Alignment [HP3-1-INFO1, HP3-1-MIG1]
- **Target Schema Approved**: P5 approves the additive Migration `0007_recovery_case_constraints_alignment.py` approach. You will **not** need to alter your P3 ORM or rename constraints to singular.
- **Exact Schema Specifications**:
  1. **Recovery Case PK**: Remains composite `(tenant_id, case_id)`.
  2. **Trigger-to-Case FK Deletion Policy**: `ON DELETE RESTRICT` on `fk_recovery_case_triggers_case_tenant_commitment` referencing `recovery_cases (tenant_id, case_id, commitment_id)`. This enforces append-only Trigger history and prevents silent cascading deletion of audit evidence.
  3. **Case Identity Unique Constraint**: Replaces the constraint name with the plural form `uq_recovery_cases_tenant_case_commitment` on `(tenant_id, case_id, commitment_id)`.
  4. **Active Case Partial Unique Index**: Retained as `uq_recovery_cases_one_active_per_commitment` covering the 5 active statuses (`OPEN`, `AWAITING_EVALUATION_INPUTS`, `OPTIONS_READY`, `NO_SAFE_PLAN`, `NEEDS_REPLAN`).
  5. **Direct Trigger-to-Commitment FK**: Retained with `ON DELETE RESTRICT` on `(tenant_id, commitment_id)` referencing `commitments (tenant_id, commitment_id)`.

---

### 2. Migration 0007 Delivery & Verification Checklist [HP3-1-Q1, HP3-1-MERGE1]
- **Alembic Lineage**: `0007_recovery_case_constraints_alignment` will branch cleanly from `0006_recovery_cases` as the new single head on `main`.
- **P5 Verification Deliverables**:
  - Full PostgreSQL upgrade (`0006 -> 0007`) and downgrade (`0007 -> 0006`) tests.
  - Zero-data-loss validation: schema alters preserve existing Case and Trigger rows.
  - Negative RESTRICT test: executing `DELETE FROM recovery_cases` with dependent triggers raises `sqlalchemy.exc.IntegrityError` (violates foreign key constraint).
  - Introspection evidence confirming exact constraint names via PostgreSQL `information_schema.table_constraints`.
- **Merge Sequencing**: P5 will implement and merge Migration 0007 into `main` first. Once merged, P5 will notify you with the commit SHA and Alembic revision so you can sync PR #10 cleanly.

---

### 3. Resolution of Separate Integration Blockers [HP3-1-BLOCK1, HP3-1-Q2]
- **Authoritative Assessment Lookup (Fail-Closed)**:
  - P5 is delivering the updated `AuthoritativeAssessmentHistoryReader` in Core (`backend/app/core/feasibility_adapters.py`).
  - The reader strictly fails closed: missing `assessment_id`, missing evaluated `commitment_version`, missing snapshot metadata, or advisory flags (`advisory=True`) will raise a typed `DomainError("ASSESSMENT_PROVENANCE_MISSING", ...)` rather than defaulting to audit IDs or version 1.
- **Dispatcher Concurrency & Transaction A/B**:
  - Core outbox worker guarantees Transaction A (Core `assess()` + risk transition + audit + outbox PENDING) is committed independently.
  - Transaction B (Outbox dispatcher + P3 Case/Trigger + ProcessedEventRecord) executes in its own session. If consumer processing fails, Transaction B rolls back, increments outbox attempts, and schedules exponential retry—**never rolling back Transaction A**.
  - P5 will include a joint PostgreSQL transaction test covering Transaction B failure isolation alongside Migration 0007.

---

### 4. Summary of Boundaries & Next Actions
- **P5 Next Deliverables**:
  1. Commit and merge Migration `0007_recovery_case_constraints_alignment.py` and its PostgreSQL regression tests to `main`.
  2. Formalize fail-closed `AuthoritativeAssessmentHistoryReader` in Core.
  3. Share the commit SHA and Alembic head update.
- **P3 Next Actions**:
  1. Hold synchronization until Migration 0007 merges to `main`.
  2. Once 0007 is merged, pull/rebase `origin/main` into `feat/p3-recovery` while preserving your 13 commits.
  3. Run your 90+ recovery and trigger persistence tests against the new head.
- **What P3 Must NOT Do**:
  - Do NOT modify your ORM constraint names or change `ON DELETE RESTRICT` back to CASCADE.
  - Do NOT mutate the authoritative `Commitment` aggregate directly from recovery endpoints.
  - Do NOT enable live subscriber registration or consequential execution until joint PostgreSQL tests are signed off.

Thank you!
