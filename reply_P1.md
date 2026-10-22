Hi P1!

# Reply to P1 (Handoff #P1-1 — Context Publisher, Confirmed Terms Protection & Migration Sequencing)

**To**: Person 1 (F1 Omni-Channel Context Intelligence)  
**From**: Person 5 (Shared Core, Contracts, Integration Coordinator)  
**Date**: 2026-10-22  
**Subject**: Confirmation of Context Publishing Facade, Amendment Workflow, Route Mounting, and Migration Sequencing

---

### 1. Confirmed Commitment Terms Protection [H1-1-Q1]
- **Decision: ACCEPTED**:
  - Reason: Invariant 1 (`REQUESTED != CONFIRMED`) and Invariant 6 prohibit silently mutating agreed contractual commitments from inbound operational messages.
  - In `backend/app/core/integration.py` (`CoreIntegrationFacade.handle_context_updated`), when extracted context changes target a commitment in `AgreementState.CONFIRMED`, Core preserves the original agreed terms.
  - The modification automatically transitions to an amendment proposal workflow (`CommitmentProposalRecord` in `AgreementState.OFFERED`) and emits `commitment.proposal_offered` for customer confirmation and P2 feasibility re-evaluation.

---

### 2. Zero-Guesswork Eligibility Guard [H1-1-GUARD1]
- **Decision: ACCEPTED**:
  - Reason: `IneligibleContextError` correctly enforces that messages with `INFORMATION_PARTIAL`, `CONFLICT`, `UNRESOLVED`, or unverified/ambiguous customer identity (`UNVERIFIED`, `AMBIGUOUS`) are blocked from creating commitments.
  - P5 strictly verifies that OCR receipts or unverified payment slips never auto-advance agreement or fulfilment states.

---

### 3. Route Mounting in App Shell [H1-1-Q3]
- **Decision: ACCEPTED**:
  - Backend: `context_router` mounted under `/v1/context` in `backend/app/main.py`.
  - Frontend: `<DurableInbox />` mounted at `/inbox` and `<OrderContextDetail />` mounted at `/orders/:id` in `frontend/src/App.tsx`.
  - Accessible via application shell navigation with dynamic state badges.

---

### 4. Alembic Migration Sequencing [H1-1-Q2]
- **Decision: ACCEPT WITH CHANGES (Sequential Head after 0007)**:
  - Reason: Single linear migration chain must be preserved on `main`.
  - Current single head is `0007_recovery_case_constraints_alignment`.
  - P1's persistent context tables (`order_contexts`, `raw_messages`, `attachments`) should be submitted as migration `0008_order_contexts.py` branching directly from `0007`.

---

### 5. Next Actions for P1
1. **Rebase on `origin/main`**: Fetch and rebase `feat/p1-context-intelligence` onto latest `main` (`74470cf`, Alembic head `0007`).
2. **Resolve Shared Config Collisions**: Ensure no modifications to root `pyproject.toml`, `package.json`, or shared Alembic files other than your clean migration `0008`.
3. **What P1 Must NOT Do**:
   - Do NOT bypass `check_eligibility` to publish unverified contexts to Core.
   - Do NOT auto-promote fuzzy customer identity matches without human review.
   - Do NOT mark payment verified from raw OCR text without verified banking confirmation.

Thank you!
