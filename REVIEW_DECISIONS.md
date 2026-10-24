# MouManTAI 2.2 — Review Decisions & Implementation Readiness

**Date:** 2026-10-23 · **Status:** Engineering proposal ready for owner review. **No live repo audit or code changes performed.**

## What changed from v2.1

| ID | Reviewer observation | Engineering decision | Where specified |
|---|---|---|---|
| REV-01 | Original-order accept shortcut permits changed commercial terms | **Fully accepted.** Backend `accept` is customer-agreed exact-terms-only (original offer or customer-assented counteroffer). Price/source/disclosure included in canonical terms; changes require counteroffer/Proposal, exact customer assent, then SME decision and reservation. | System §13.1; Backend §3.0; Frontend FE-ORD-02A; Blueprint §3 |
| REV-02 | Replit endpoint may not be available | **Accepted with qualification.** Preserve product owner's requested Replit generation as *preferred provider*, not an assumed runtime endpoint; template baseline, explicit adapter smoke test, no silent Qwen provider swap. | Backend §4.1; System §0.1; Blueprint §4 |
| REV-03 | Too many status/decision labels | **Accepted.** One matrix with independent requirement decision and evidence tier. `MUST` only normative language. | System §13.2; Blueprint §2.1 |
| REV-04 | Two backend commands should not require two ordinary clicks | **Accepted.** Primary Approve & Execute one human click triggers approve then execute; separate audit, authorization and validation; secondary Approve Only. Handle partial outcomes. | Frontend FE-CTA-01A; Backend §11.1; Blueprint §7 |
| REV-05 | Need real measured-value baseline | **Accepted.** Three controlled manual-vs-assisted tasks, correctness and complete metadata; results must actually be collected, with sample caveats. | Backend §16.1; System §15; Blueprint §12 |
| REV-06 | Supplier schema setup burdens SME | **Accepted.** Editable seeded food container, perishable ingredient and general supply templates, unknown fails closed. | Backend BE-SUP-02; Blueprint §6 |
| REV-07 | Docs make code mapping assumptions | **Accepted.** Mandatory repository schema/route/ORM/test read-only audit; output `LEGACY_REUSE_MATRIX.md` before migration. | AGENTS §3.1 and §15; Blueprint §8–9 |

## Important nuances

1. **Do not change owner decisions to satisfy reviewer preferences.** Specifically, Qwen analysis and intended Replit generation remain the selected architecture; execution capability is gated by provider verification and templates.
2. **Do not downgrade emergency approval.** Every Change-to-Action must have human review and scoped authorization. A single approved plan may enumerate multiple internal actions; the UX can eliminate a redundant click while the backend retains separate commands.
3. **Do not remove full-system Forecasting, Memory or Feedback** solely because synthetic data cannot validate generalization. Separate mechanism demo from genuine evidence, and prioritize data collection/cold-start behavior.
4. **Do not claim live integration, schema compatibility or test pass counts** without inspecting/running the actual Git repo. The files are implementation instructions, not shipped code.

## Specific owner signoffs requested

- **S1:** Accept only exact explicitly customer-agreed original terms; materially changed or newly undisclosed price/fees require exact customer Proposal assent.
- **S2:** Replit preferred provider remains; deterministic templates are baseline for status, approved public FAQ and milestone; no silent substitution of generation provider.
- **S3:** Primary `Approve & Execute` one UI click backed by two separate API commands; `Approve Only` available for deferred action.
- **S4:** Accept suggested seeded supplier category templates and `SPEC_UNKNOWN` fallback; determine industry-specific template edits later.
- **S5:** Set tenant-specific no-reply/expiry/global clarification limits, milestone opt-out/consent, and actual evidence policy when real business configuration becomes available.

## Next executable step

**Prompt to Codex (analysis only, before implementation):**

> Inspect the actual repository read-only. Report branch/commit/status; concrete backend/ORM/Alembic entities, routes, Frontend pages and tests for old P1–P5; identify existing single sources of truth for Message, Order, Commitment, Proposal, P2 Feasibility, Inventory/Reservation, P3 Recovery, P4 Outbound, Audit/Outbox. Produce `LEGACY_REUSE_MATRIX.md` classifying each as REUSE / EXTEND / ADD / DEPRECATE with exact paths, code symbols and compatibility/migration risks. Compare to v2.2 System, Backend, Frontend and Implementation Blueprint. Do not change files, create migrations, commit or push; provide report first.

After this report is reviewed, proceed to Blueprint §9 phased implementation with actual names, replacing any guessed route/table name with verified ones.
