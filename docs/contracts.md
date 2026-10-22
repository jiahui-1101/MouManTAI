# MouManTAI System Contracts & Architecture Specifications

## 1. Overview
This document specifies cross-feature system contracts, persistent schema invariants, and transactional execution guarantees for MouManTAI (SDCHackathon 2026-10-25).

---

## 2. Recovery Persistence & Invariants (Migration 0007)

### 2.1 Target Schema & Invariants
Alembic head revision: `0007_recovery_case_constraints_alignment` (branches from `0006_recovery_cases`).

1. **`recovery_cases` Primary Key**:
   - Composite PK: `(tenant_id, case_id)`.
2. **Case Identity Unique Constraint**:
   - Constraint name: `uq_recovery_cases_tenant_case_commitment` (plural) on columns `(tenant_id, case_id, commitment_id)`.
3. **Trigger-to-Case Foreign Key**:
   - Constraint name: `fk_recovery_case_triggers_case_tenant_commitment`.
   - Referenced table: `recovery_cases (tenant_id, case_id, commitment_id)`.
   - On-Delete Policy: `ON DELETE RESTRICT` (append-only trigger history; prevents silent cascade deletion of audit evidence).
4. **Trigger-to-Commitment Foreign Key**:
   - Constraint name: `fk_recovery_case_triggers_commitment_tenant`.
   - Referenced table: `commitments (tenant_id, commitment_id)`.
   - On-Delete Policy: `ON DELETE RESTRICT`.
5. **Partial Unique Active Index**:
   - Index name: `uq_recovery_cases_one_active_per_commitment`.
   - Columns: `(tenant_id, commitment_id)`.
   - Predicate:
     ```sql
     status IN ('OPEN', 'AWAITING_EVALUATION_INPUTS', 'OPTIONS_READY', 'NO_SAFE_PLAN', 'NEEDS_REPLAN')
     ```
   - Enforces that exactly one recovery case may be active per commitment at any time. A `COMPLETED` (or closed) case does not block opening a new active case for subsequent risk episodes.

---

## 3. Fail-Closed Assessment History Reader (`AuthoritativeAssessmentHistoryReader`)

### 3.1 Interface Specification
Located in `backend/app/core/feasibility_adapters.py`.

```python
class AuthoritativeAssessmentHistoryReader:
    @staticmethod
    def read_latest_authoritative_assessment(
        session: Session,
        tenant_id: str,
        commitment_id: str,
        expected_commitment_version: int | None = None,
    ) -> FeasibilityAssessment:
        ...
```

### 3.2 Provenance Invariants & Error Codes
- **Missing Required Provenance**:
  - Missing or empty `assessment_id` -> raises `DomainError("ASSESSMENT_PROVENANCE_MISSING", "Assessment provenance incomplete: missing 'assessment_id'", status_code=422)`.
  - Missing `commitment_version` or `commitment_version < 1` -> raises `DomainError("ASSESSMENT_PROVENANCE_MISSING", "Assessment provenance incomplete: missing evaluated 'commitment_version'", status_code=422)`.
  - Missing `snapshot_version` or `snapshot_version < 1` -> raises `DomainError("ASSESSMENT_PROVENANCE_MISSING", "Assessment provenance incomplete: missing 'snapshot_version'", status_code=422)`.
  - Advisory records (`advisory=True`) -> raises `DomainError("ASSESSMENT_PROVENANCE_MISSING", "Candidate assessment record ... is advisory; authoritative provenance required", status_code=422)`.
- **Zero Fallback**:
  - The reader must NEVER fall back to synthetic values, audit IDs, or default version 1.
  - If authoritative provenance cannot be verified against the audit log, the evaluation fails closed.

---

## 4. Transaction A/B Dual-Boundary Isolation Guarantee

### 4.1 Boundary Definitions
- **Transaction A (Core State & Outbox Persistence)**:
  - Invocation: `CommitmentService.assess(...)` (or state transition command).
  - Scope:
    1. Authoritative `CommitmentRecord` risk transition (e.g. `NORMAL` -> `AT_RISK`, version increment).
    2. `AuditEventRecord` recording full state snapshot, evidence references, causation, and correlation IDs.
    3. `OutboxEventRecord` written with status `PENDING`, attempts = 0.
  - Lifecycle: Commits atomically and independently. Guaranteed durable before any downstream consumer is triggered.

- **Transaction B (Outbox Dispatcher & Feature Consumers)**:
  - Invocation: `OutboxDispatcher.process_outbox_batch(...)`.
  - Scope:
    1. Lock/fetch `PENDING` or eligible `FAILED` outbox events.
    2. Idempotency check against `ProcessedEventRecord`.
    3. Consumer execution (e.g. P3 recovery case and trigger persistence).
    4. `ProcessedEventRecord` insertion.
  - Error Handling & Rollback Boundary:
    - If the consumer fails or raises an exception:
      - Transaction B rolls back completely: all consumer writes (cases/triggers) and `ProcessedEventRecord` are rolled back.
      - Outbox event attempts increment by 1.
      - Outbox status is set to `FAILED` (or `DEAD_LETTER` if max attempts exceeded).
      - `next_retry_at` is scheduled using exponential backoff.
      - **Transaction A aggregate state, audit records, and outbox event are NEVER rolled back.**
    - On retry with a successful consumer:
      - Consumer writes succeed and commit.
      - `ProcessedEventRecord` is persisted.
      - Outbox event status transitions to `PUBLISHED` with `published_at` timestamp.
      - Subsequent dispatcher runs skip the event idempotently.
