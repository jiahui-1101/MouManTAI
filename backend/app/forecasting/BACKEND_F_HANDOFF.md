# Backend F handoff

This package is a pure, read-only implementation of the proposed v2.2 forecasting boundary.
It adds no route, migration, worker, reservation, Core transition, Recovery action or message send.

Target: **accepted-order quantity by SKU and business day**. Known zero is explicit;
unknown days remain missing. A server-injected `DemandReader` must authenticate and attest
its source; a client payload or Pydantic model is never sufficient. No production reader is
wired. `ForecastService.readiness` returns a typed `SOURCE_UNAVAILABLE` diagnostic when
that reader is absent.

The pure models support moving average, seasonal naive and naive forecasts, plus expanding
origin backtests. Synthetic results are DEMO-ONLY and their metrics are fixture mechanics,
not evidence of real-world skill. The current service does not award VALIDATED or LIVE.
An approved source adapter and tenant-specific evaluation policy are required before that.

P2 must supply a versioned forward scenario attestation and current operational snapshot;
otherwise stock/expiry and capacity/deadline return UNKNOWN. Backend E must supply verified
supplier summaries; otherwise supplier risk is UNKNOWN. No ATP, lot allocation, supplier
performance statistics or capacity formula is duplicated here. Alert options are suggestions
for human review, never permission to take action.

Review boundaries: P1 historical acceptance provenance, P2 scenario semantics, P5 source
authority and currentness, Backend E supplier summary, Backend D genuine subsequent actuals,
and tenant-approved thresholds all remain owner dependencies. No Orbyte connector, statistical
intervals, calibrated probabilities or operational activation is claimed.

## Reproducible synthetic example

`tests/test_forecasting.py` creates 21 daily accepted-demand observations for demo tenant
`demo`, SKU `A`, unit `pcs`, with a repeating 1..7 quantity. The source is explicitly
`DEMO-ONLY` + `SYNTHETIC`. At 2026-10-21 cutoff, moving average (7 days) predicts 4
units for each of 2026-10-22, 23 and 24. Seasonal naive (7 days) predicts 1, 2 and 3.
The expanding-origin seven-day holdout after 2026-10-14 yields moving-average MAE
`1.714285714285714285714285714`, WAPE `0.4285714285714285714285714286`, MASE
`1.238095238095238095238095238`, signed bias `0`, with seven eligible actuals.
These values demonstrate fixture mechanics only. Without P2 or Backend E adapters, the
stock/expiry, supplier and capacity/deadline alerts are `UNKNOWN`; every alert has
`operational_action_authorized=False`.

## Requirement coverage

| ID | Scope in this package |
| --- | --- |
| BE-FORE-01 | IMPLEMENTED_AND_TESTED demand baselines; IMPLEMENTED_PURE_BOUNDARY_ONLY forward scenario |
| BE-FORE-02 | IMPLEMENTED_AND_TESTED chronological metrics and evidence gate; PROPOSED_NOT_AUTHORIZED real validation |
| SYS-FORE-01 | IMPLEMENTED_AND_TESTED demand; IMPLEMENTED_PURE_BOUNDARY_ONLY other three families |
| SYS-FORE-02 | IMPLEMENTED_AND_TESTED typed versioned forecast result and provenance |
| SYS-FORE-03 | IMPLEMENTED_AND_TESTED synthetic isolation; PROPOSED_NOT_AUTHORIZED production gate |
| SYS-FORE-04 | IMPLEMENTED_PURE_BOUNDARY_ONLY advisory alerts and options |
| SYS-FORE-05 | IMPLEMENTED_AND_TESTED no operational actions |
| SYS-FORE-06 | IMPLEMENTED_AND_TESTED fixture backtest; BLOCKED_BY_MISSING_AUTHORITATIVE_DATA genuine actuals |
