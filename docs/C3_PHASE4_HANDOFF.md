# C3 Phase 4 handoff (25 October 2026)

## Contract and ownership

`InferenceInput.task=c3_classification` extends the existing P1 Qwen task boundary. `InferenceOutput.classification` carries a strict `SemanticAssessment` with source segment IDs and exact Unicode spans. P1's Qwen endpoint, same-length privacy masking, bounded Gemini fallback, timeout and validation remain the only provider path. Valid `UNKNOWN` output and source evidence disagreement do not trigger another model vote. C3's deterministic classifier runs first.

The existing `communication_draft_reviews` table is bound to a P4 draft and send validation. P1 context reviews are bound to order context fields. Neither is a generic message review. The new `c3_message_reviews` table is C3-owned and stores an immutable candidate/source snapshot, evidence links, model provenance, provider attempts, reason codes, source digest/version and one terminal classification decision. The service recomputes the candidate from a current tenant-scoped P1 row, then checks the current source again before a decision. Its decision grant is a read-only P5 authorization port. With no trusted authority supplied, decisions fail closed. An APPROVE decision confirms a classification only; it does not create an OrderRequest, update a supplier or P2, approve Recovery, or send through P4.

## Authorization and integration dependencies

The new `C3ReviewAuthority.authorize` port requires tenant, actor, action, expiry and trusted evidence references. The existing P4 `ReviewAuthority` cannot implement it directly because it binds communication and draft IDs. P5 must supply a verified C3 policy adapter before exposing review commands through a production API. The current header-based synthetic `RequestContext` is not production identity proof. A C3 Human Review page and queue API are pending Frontend/P5 integration; this change does not edit frontend pages. A durable worker/ingress trigger to call `C3ReviewService.enqueue` after verified C1/C2/P1 ingestion is also pending. No background dispatch is enabled by this PR.

Inquiry drafts remain gated by verified customer association and approved, current public business facts in `draft_customer_inquiry`. Supplier delay handoff remains a reported claim and requires current verified supplier association and exact P2 delivery snapshot in `validate_supplier_delay`. Neither draft nor assessment sends or mutates operational state.

## Verification

- `backend/tests/test_c3_phase4.py` against a fresh Alembic-migrated PostgreSQL 16 database: **11 passed**. Covers Qwen success, timeout, malformed output, Gemini fallback, valid ambiguous output, forged model identity, invalid evidence span, tenant and stale-source rejection, all three terminal decisions, tamper rejection and durable storage.
- C1/C2/P1 selected provider and provenance regressions against PostgreSQL: **passed** with existing skips in that selection. Initial run hit a Windows temp-directory permission error; rerun with a workspace-local pytest base directory passed.
- Frontend `npm test`: **1,232 passed, 5 skipped**; `npm run build`: **passed**. No frontend source changed.
- Alembic: exactly one head, `0026_c3_message_reviews`. Python compile and `git diff --check`: **passed**.
- Real Qwen/Gemini inference smoke: **NOT_RUN**; authorized endpoint/API credentials were not available in the environment.

## Release decision

**NO-GO for unattended real C3 semantic processing** until the P1 Qwen endpoint and optional Gemini credentials are configured and safely smoke tested, a trusted P5 C3 review policy adapter and queue API exist, and verified ingress invokes the durable enqueue path. The classification gateway and inert review service are ready for controlled integration testing. Do not treat fixture results as real inference accuracy.
