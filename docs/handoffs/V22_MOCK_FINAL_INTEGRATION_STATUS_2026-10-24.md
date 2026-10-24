# MouManTAI v2.2 Mock-backed Backend A–H integration status

**Verdict: PARTIALLY_INTEGRATED.** The accepted-order Mock business workflow, a separate supplier-delay Recovery workflow, Mock Communication flow, operational evidence projection, and A–H advisory APIs execute through registered Backend routes and persistent state. They are not one automatic customer-to-delivery chain. Real channel transport, verified contacts, frontend API wiring and production identity remain separate work. Every Orbyte-origin fact, external reservation/receipt and controlled history in this stack is **DEMO/SYNTHETIC**.

## Delivered stack and source of truth

| PR | Layer and primary implementation | PostgreSQL migration | Demonstrated route family |
|---|---|---|---|
| #81 | Canonical Mock OrderRequest, source/terms versions, P2 check, SME approval, persistent Mock Orbyte reservation, Core commitment, audit/outbox; `backend/app/orders`, Mock resource models/services and v2.2 HTTP tests | 0018 | `/v1/backend-v2/mock-orbyte`, `/order-requests`, `/commitments/{id}/status-preview` |
| #82 | Read-only Core/P3/P4 operational evidence join and cross-module regression tests; `backend/app/operational_reporting` | None | `/v1/backend-v2/commitments/{id}/operational-evidence` |
| #83 | Persisted synthetic supplier requirement/quotes, existing comparator, SME choice, RFQ draft, audit/outbox; `backend/app/supplier_intelligence` | 0019 | `/v1/backend-v2/mock-suppliers` |
| #84 | Persisted synthetic demand history, source attestation, existing baseline/backtest/risk engine, audit/outbox; `backend/app/forecasting` | 0020 | `/v1/backend-v2/mock-forecasts` |
| #85 | Reviewed OrderRequest-bound portfolio constraints, native OR-Tools CP-SAT FCFS/profit/expiry comparison and full-set synthetic verifier, audit/outbox; `backend/app/optimization` | 0021 | `/v1/backend-v2/mock-optimization` |
| #88 | Persisted validated DEMO decisions, existing Backend G retrieval/outcome/review engine, read-only insights, audit/outbox; `backend/app/decision_memory` | 0022 | `/v1/backend-v2/mock-memory` |

The detailed field-level route, version, error and Frontend page matrix is in `docs/contracts/V22_MOCK_BACKEND_API_2026-10-24.md`. The exact stacked PR numbers and merge status must be checked on GitHub before release.

## Operational journeys and evidence boundaries

| Journey | Verified behavior | Boundary |
|---|---|---|
| Controlled inquiry → OrderRequest → P2 → SME review/approval → Mock reservation → accepted Core commitment | Registered HTTP endpoints and migrated PostgreSQL; fresh terms/source/resource versions, human gate, row-locked stock-lot allocation, confirmed durable receipt, Core/audit/outbox in one local transaction. HTTP tests cover capacity, stale/malformed versions, duplicate/concurrent commands, rejected/unknown receipts, reconciliation, tenant and actor denial. | Inquiry and resources are synthetic fixtures, not authenticated customer/Orbyte facts. One SKU line and one isolated tenant per configured environment. No automatic P1 message-to-OrderRequest bridge. |
| Supplier delay → Recovery plan → human approval → controlled internal execution receipt | Existing registered P2/P3 routes and live Uvicorn + worker + migrated PostgreSQL test, rerun on the final branch. Verified internal task and audit feed the operational evidence projection. | This is a separate synthetic seeded commitment, not a supplier event automatically connected to a newly accepted Mock OrderRequest. No automatic emergency execution or external supplier action. |
| Communication request → review → Mock send/receipt → confirmation tests | Existing P4 route, outbound and confirmation regressions; a matching persisted Mock send attempt/audit is reported as `MOCK_PROVIDER_SENT`. | `LocalMockProvider` and Mock channel identities are fixtures, not Telegram, WhatsApp or Email provider delivery. A send or delivery receipt never proves customer assent. New accepted-order outbox has no subscriber creating a customer milestone. |
| Order timeline and operational status | Read-only OrderRequest/Core audit/status plus tenant-scoped P3/P4 evidence. Accepted state requires a matching confirmed reservation and Core record. | Physical production, delivery and customer agreement actuals remain `NOT_AVAILABLE`; no invented KPI. |
| Supplier / Forecasting / Optimization / Decision Memory advisory | Registered HTTP APIs execute existing comparison, forecast, CP-SAT and historical insight engines against PostgreSQL-persisted, bounded DEMO data. Human supplier selection is recorded; RFQ remains a draft. | Advice cannot reserve, accept, purchase, send, execute or update policy. Synthetic backtests establish no real predictive skill. Missing live attestations fail closed. |

## Verification performed

- Final stacked branch: strict v2.2 suite against disposable migrated PostgreSQL, **533 passed**; no skipped tests. The suite includes registered HTTP, OpenAPI, security, idempotency, concurrency and advisory negative cases.
- After the PR #85 UTC-offset response fix was merged forward: affected Optimization and Decision Memory PostgreSQL HTTP tests, **7 passed**.
- Migration 0022 downgraded to 0021, upgraded back to head and reported `0022_mock_memory_history` as the single head.
- Final stacked branch: live P3 Uvicorn + worker + PostgreSQL Recovery test, **1 passed**.
- Final stacked branch: P4 route, outbound and confirmation regression subset, **74 passed, 21 skipped** (skips are alternate database parametrizations). This verifies Mock fixtures, not actual provider transport.
- A broader local `app tests` sweep ran **2,431 passed, 256 skipped, 8 failed**. Six AI spike experiment failures came from missing local `psutil` or the repository-parent Python import path; all six passed on targeted rerun after correcting that setup. The migration 0007 test required a separate PostgreSQL migration database under strict mode; both tests in its file passed on a targeted SQLite rerun. The P1 image OCR acceptance test failed with `FAILED` instead of `SUCCESS` and remains an open blocker. Do not describe the broad sweep as green.
- Earlier layers: PR #81 exact-head GitHub CI succeeded; PR #81 live Mock acceptance E2E and negative/concurrency cases passed. PR #84 forecasting pure-engine tests passed; PR #85 native CP-SAT pure tests passed. Relevant Frontend build and serial Vitest run passed on PR #81 with no Frontend source changes in later layers.
- Exact-head GitHub push CI succeeded for PRs #82–#84 and for PR #85 after its UTC-offset response fix. PR #88 CI must be checked again on the final merged head.
- Local lint, compile and diff checks for the last layer passed. GitHub exact-head CI and reviewer state for later stacked PRs are separate merge gates.

## Security and release gates

The `/v1/backend-v2` Mock routes require synthetic and isolated feature gates, a server-owned key, an exact configured Manager actor and tenant, and they are disabled in production. PostgreSQL records, audits and outbox events are tenant-scoped. Source provenance, exact versions and human decisions are rechecked at mutation time. Unknown reservation outcomes cannot make an accepted commitment. Optimization and memory have no operational authority. Production identity and real Orbyte authority remain fail-closed.

Do not merge the stack solely on this report. Required exact-head checks, Meishuet's Backend reviews and Jiahui's final Backend review/branch protection still govern merge. Stacked PR bases must be maintained in order. No force-push or bypass is authorized.

## Remaining integration dependencies

1. Frontend team: connect Orders, Review, Recovery, Communication and advisory pages to the documented APIs through a trusted server proxy, preserving 202/409/unknown/evidence-tier states. Run browser → API → PostgreSQL tests. Never expose the isolated key in browser code.
2. Backend: subscribe accepted-order events into the existing P3/P4 workflows only when authenticated operational incidents, verified recipients and relevant consent exist; exercise a single cross-module case. Current projection joins evidence but does not itself dispatch work.
3. Separate real-channel phase: verify Telegram Bot API HTTPS webhook, Meta WhatsApp Cloud API test-number, bidirectional Email, attachments/OCR, Qwen-first and Gemini fallback, verified contact registry, cross-channel Order association, supplier-delay trust/review, provider receipts and originating-channel replies. The detailed handoff is `docs/handoffs/V22_REAL_CHANNEL_AND_FRONTEND_NEXT_PHASE_2026-10-24.md`. Existing P1 channel code is a starting point, not a verified real-provider claim. The known OCR blocker remains open.
4. Production use: independently verified identity and external authority adapters, contracts and credentials. This hackathon stack intentionally enables none of them.
