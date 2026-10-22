Hi P2!

# Reply to P2 (Handoff #P2-1 — Feasibility Adapters, Contract Relaxation & Schema Alignment)

**To**: Person 2 (F2 Feasibility Full-Stack)  
**From**: Person 5 (Shared Core, Contracts, Integration Coordinator)  
**Date**: 2026-10-22  
**Subject**: Confirmation of Feasibility Adapters Placement, Contract Relaxation, and Route Mounting

---

### 1. Feasibility Adapters Placement [H2-1-ADAPTER1]
- **Decision: Core Placement (`backend/app/core/feasibility_adapters.py`)**:
  - Reason: P5 owns shared adapters and integration boundaries; placing them in Core prevents cross-owner edits into `backend/app/feasibility/`.
  - Concrete adapters (`AuthoritativeEvaluationAuthority`, `AuthoritativeAssessmentWriter`, `AuthoritativeAssessmentHistoryReader`, `AuthoritativeSupplierDelayProcessor`, `AuthoritativeImpactReader`) are registered via FastAPI dependency overrides in `backend/app/main.py`.
  - P2 may import from Core or continue using local facades where appropriate.

---

### 2. Contract Relaxation for `affected_commitment_ids` [H2-1-CONTRACT1]
- **Decision: ACCEPTED with default `[]`**:
  - Reason: `affected_commitment_ids` strictly denotes downstream commitments disrupted by operational/resource changes (impact set), not the scope of the assessment itself.
  - Schema in `backend/app/core/schemas.py`, TypeScript types in `contracts/types.ts`, and fixtures updated to `default_factory=list, min_length=0`.
  - For standard `FEASIBLE` or `UNKNOWN` evaluations where no downstream commitments are disrupted, an empty list `[]` is expected and valid.

---

### 3. Fail-Closed History Reader & Status Preservation [H2-1-READER1]
- **Decision: All 4 Statuses Preserved with Fail-Closed Provenance**:
  - Reason: Invariant safety requires that missing evaluation provenance cannot default to version 1 or fake audit IDs.
  - `AuthoritativeAssessmentHistoryReader` preserves all four statuses (`FEASIBLE`, `CONDITIONAL`, `INFEASIBLE`, `UNKNOWN`).
  - Advisory records (`advisory=True`) write only to `AuditEventRecord` and are strictly excluded from authoritative lookup.
  - Missing provenance raises typed `DomainError("ASSESSMENT_PROVENANCE_MISSING", ..., status_code=422)`.

---

### 4. D-017 Named Subscriber Gate & Shell Route Mounting [H2-1-DISPATCH1, H2-1-SHELL1]
- **D-017 Policy**: `OutboxDispatcher` enforces named subscriber `p2_confirmed_evaluator` on `commitment.confirmed` (no wildcards). Unregistered or failing events remain `PENDING`/`FAILED`, never prematurely published.
- **Frontend Routes**: `CommitmentFeasibilityPage` (`/commitments/:id`) and `ImpactDetailPage` (`/impact/:id`) are mounted in `frontend/src/App.tsx` with authenticated transport.
- **Alembic Single Head**: `0007_recovery_case_constraints_alignment`.

---

### 5. Next Actions for P2
1. **Pull/Rebase on `origin/main`**: Sync with `main` (`74470cf`) and Alembic head `0007`.
2. **Verify Dependencies**: Confirm P2 evaluation pipeline resolves adapters from `backend/app/core/feasibility_adapters.py`.
3. **What P2 Must NOT Do**:
   - Do NOT emit direct `commitment.at_risk` outbox events from local feasibility methods; Core `assess()` alone emits authoritative risk transitions.
   - Do NOT treat `UNKNOWN` as `INFEASIBLE`.

Thank you!
