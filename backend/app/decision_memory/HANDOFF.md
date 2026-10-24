# Backend G decision memory handoff

## Scope and authority

This package is a pure, read-only projection. It has no route, ORM table, migration, write port, provider call, worker, policy mutation, or model training. Core `CommitmentRecord`, `AuditEventRecord`, and `OutboxEventRecord` remain authoritative for lifecycle and audit. P3 `RecoveryCase`, `RecoveryPlanVersion`, `ApprovalDecision`, and `ExecutionRecord` remain authoritative for recovery stages. An audit event name or provider receipt alone does not verify the business outcome.

`CaseInput` is the narrow owner adapter contract. It requires event identity, tenant, commitment and recovery case association, exact plan/version, snapshot, timestamps, alternatives, human decision, independent approval and execution, outcome, and evidence references. The source manifest declares complete pagination, population, provenance and watermark. `validate_source` deduplicates exact replays and rejects conflicting replays. `assemble_case` makes an immutable `DecisionMemoryCase`. The output references owner records rather than copying customer data.

`DecisionMemoryService` requires an injected server identity resolver, source reader, and source authenticity verifier. The verifier must authenticate the current situation against actor access, as well as the manifest and every historical evidence binding. A live policy must come from an injected owner policy reader. No approved owner adapters or OPEN-12 minimum history policy are in this branch, so live retrieval fails closed. `authenticated=True` in a supplied evidence structure is only a reader assertion; the owner verifier must authenticate the underlying record and evidence binding. The synthetic fixture and policy are test only and never provide live authority.

## Interfaces needed from owners

- **P5/Core:** Tenant authenticated identity and read-only audit, commitment version, exact approval provenance, source snapshot and event linkage. Core audit does not supply a complete business outcome.
- **P3:** Read-only Recovery Case, plan/version, approval, execution attempt and actual business resolution evidence. Do not reuse historical approval or feasibility as current authority.
- **P1:** Authenticated provenance and verified identity linkage. Raw names, messages, and customer contact details are excluded from comparison attributes.
- **P4:** Delivery versus agreement evidence. A sent message is not customer acceptance.
- **P2:** Fresh evaluation remains the only current feasibility authority. Historical capacity decisions are advisory references.
- **Backend E:** Supplier sourcing decision and verified receipt links; no duplicate supplier reliability metric or current quote inference.
- **Backend F:** Optional read-only outcome references for forecast evaluation; no automatic model update.
- **Backend D:** Optional case and outcome references for reporting; no KPI recalculation here.
- **Orbyte:** Official authenticated read contract is not yet available.

An optional durable derived index would need tenant/case/version uniqueness, source snapshot/version and watermark, owner event/evidence references, correction lineage, retention/access policy, and owner approval. This package adds no competing historical outcome database.

## Requirements

| Requirement | Status | Remaining dependency |
|---|---|---|
| SYS-MEM-01 / BE-MEM Section 12 | IMPLEMENTED_PURE_BOUNDARY_ONLY | Trusted owner readers |
| SYS-MEM-02 / BE-FORE/MEM | IMPLEMENTED_PURE_BOUNDARY_ONLY | OPEN-12 approved live minimum and genuine verified history |
| SYS-MEM-03 | IMPLEMENTED_PURE_BOUNDARY_ONLY | Real outcome evidence and governed policy changes |
| SYS-MEM-04 | IMPLEMENTED_AND_TESTED | No automatic mutation interface exists |
| SYS-CTA-06 | IMPLEMENTED_PURE_BOUNDARY_ONLY | P3/P5 authoritative outcome linkage |
| BE-ORB-01 | BLOCKED_BY_OWNER_CONTRACT | Official read API and authentication |

The three synthetic recovery cases exercise alternative supply with an approved action, confirmed execution and synthetic business resolution; approved rescheduling with unknown outcome; and a sent revised-deadline message without exact agreement. Only the first is a verified synthetic outcome. The test policy can show one transparent historical match; the configured two-case gate returns `INSUFFICIENT_CASE_HISTORY`. No real learning or business success rate is claimed.
