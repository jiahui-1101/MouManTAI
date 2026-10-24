# v2.2 Mock forecast advisory follow-up

Stacked on PR #83. The registered `/v1/backend-v2/mock-forecasts` routes persist tenant-bound Mock Orbyte demand history and call the existing Backend F validation, moving-average baseline, same-holdout backtest and four-family risk engines. The adapter replaces any caller-supplied reader attestation with a server-bound synthetic attestation; source and observation evidence must be `synthetic://`, `MOCK`, `DEMO-ONLY`, and match tenant, SKU, unit, version and watermark. Migration 0020 stores immutable history with audit and outbox evidence.

Baselines and backtests expose diagnostics when sources are incomplete or stale. No P2 forward scenario or supplier-history attestation is fabricated; corresponding risk statuses remain `UNKNOWN`. Backtest numbers describe only the deterministic fixture and explicitly do not establish real-world predictive skill. Forecast output cannot reserve resources, accept orders or change policy.

PostgreSQL HTTP tests cover source seed/read/replay, real forecast points, three model backtests, risk limitations, incomplete/stale suppression, evidence validation, tenant/role denial, production disablement and OpenAPI registration. The whole v2.2 A–H target remains partially integrated pending optimization and decision memory APIs and accepted-order event links into P3/P4.
