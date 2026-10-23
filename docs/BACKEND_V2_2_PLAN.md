# MouManTAI v2.2 safe backend implementation plan

Goal: prepare a tested backend spine without activating unsigned business policy or replacing existing authority.
Architecture: existing FastAPI modular monolith; immutable typed contracts and pure deterministic validation; reuse Core/P1/P2/P4 persistence through reviewed adapters later. Python/Pydantic, existing pytest, no new dependency.
Execution: inline, per current user authorization; no routine approval gate. Review checkpoint after each code slice.

- [x] Phase 0: source read, fetched-main worktree, concrete schema/route/reuse mapping and baseline tests.
- [x] A1 `app/orders/terms.py`, `tests/v2_2/test_terms.py`: immutable OrderTerms, explicit decimal precision, full material field identity, versioned deterministic hash, field diff. Tests first: numeric/time normalization, changed prices/fees/SKU/date/address/conditions, absent disclosure, tampering and tenant scope. No Core schema change.
- [x] A2 `app/integrations/business_ports.py`, `tests/v2_2/test_business_ports.py`: typed data/command/approval protocols, reservation PENDING/CONFIRMED/UNKNOWN result guards; actual P2 EvaluationSnapshot type reused. Receipts never imply accepted order. No guessed live adapter.
- [ ] B1 `app/conversations/replies.py`, `tests/v2_2/test_replies.py`: server policy public allowlist + tenant/freshness/evidence filtering, TemplateGenerator/ReplyGenerator, unverified Replit fallback, safe fixed FAQ preview only. No provider send or duplicate P4 store.
- [ ] B2 `app/conversations/clarification.py`, `tests/v2_2/test_clarification.py`: pure per-issue reducer, deterministic candidate/quantity/date validation, successfully sent linked-answer requirement, two no-progress escalation, independent timer decision and global budget. Persisted question/answer IDs must be supplied by future P1 adapter; do not expose client-controlled transition endpoint.
- [ ] C `app/orders/router.py`, API tests: isolated-key gated terms preview, read-only persisted Core status with explicit SYNTHETIC evidence; no customer portal/status without verified link. Default disabled, 403 invalid key, 409 terms mismatch, 422 safe validation. No accept/send endpoints until reviews.
- [ ] Review cumulative diff, targeted/backend/PG regression, compile/lint, handoff and TEAM_LOG; logical commits, push dedicated branch, reviewable draft PR, attach PR, record current CI. No merge.

Remaining dependent slices: reviewed durable OrderRequest/P1 context extension and reservation saga (S1/S5); shared P2 ConstraintSpec and joint validator before CP-SAT; supplier evidence/category approval; exact single-use CTA review using existing P3/Core; permitted milestone/feedback policy; evidence-gated Forecast/Memory/RFQ and measured human task study. Preserve these as target; do not invent implementation or business metrics.
