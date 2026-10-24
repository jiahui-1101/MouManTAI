# v2.2 cross-module operational evidence follow-up

Stacked on Mock order acceptance PR #81. This branch adds a read-only `GET /v1/backend-v2/commitments/{id}/operational-evidence` route. It runs under the same server-bound synthetic Manager/tenant gate and reads existing PostgreSQL Core, Recovery and Communication records. No migration or new external command is introduced.

The projection reports `VERIFIED_INTERNAL_TASK` only when a Recovery execution has its exact durable task, receipt and matching Core audit. It reports `MOCK_PROVIDER_SENT` only when P4 has a persisted Mock send, matching send attempt and audit. If those proofs disagree, it reports `UNVERIFIED` and withholds the receipt reference. It never turns a Mock provider send into customer delivery, customer agreement, production completion or fulfilment. Those actuals remain `NOT_AVAILABLE`.

Verification: the existing live Uvicorn/worker/PostgreSQL supplier-delay Recovery test passed with a new operational-evidence read and a negative tampered-audit assertion. The P4 outbound suite passed (44 passed, 13 skipped in its portable run), including a registered API read after a Mock send, cross-tenant/actor denial and a negative tampered-receipt assertion. The relevant single P4 test passed again after the final query refinement. `ruff` and diff checks remain release gates.

The accepted-order outbox is still not subscribed into P4 messaging, and P3 supplier-delay input remains a separate synthetic fixture. This is a cross-module evidence read, not a claim that all workflow branches now share one accepted order. The whole v2.2 A–H target remains **PARTIALLY_INTEGRATED** pending those links and source-backed advisory APIs.
