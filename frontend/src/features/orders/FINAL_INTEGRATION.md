# Phase 6 integration checkpoint

Baseline: frontend-orders-planning 9083a5ad1ebf0d58cb822bd577fba57387b3ef47.
Latest Main examined: b1255f5a428e8cd87a0ecb48576bc373b6286c50 (PR #58).

Queue, detail and decision reads hide previous sensitive results during refresh/error and use zero inactive cache retention. Source-derived queue filter choices are hidden too. Local preparation unmounts on source refresh. Legacy context tenant/order mismatches withhold the embedded workflow; Refresh re-reads it. These safeguards require the scoped P1 compatibility props retained on the B branch; latest Main needs the accompanying owner-reviewed patch.

Queue instants now use strict civil-date/offset validation, shared with calendar; date-only values remain dates. Portfolio expiry scheduling is snapshot-bound and no longer updates the clock on every render. Calendar Intl formatters are cached per IANA zone.

Orders-only CSS adopts current Orbyte --ui-* tokens with light fallbacks. Embedded P1 header/actions wrap inside order detail on mobile. No global tokens, Sidebar, navigation configuration or other feature styling changes are shipped.

Route tests support both the B flat Sidebar and the merged grouped Orbyte Sidebar while retaining exact destination assertions and role checks. FinalOrdersIntegration.test.tsx exercises the actual App, explicit test-only queue injection, P1/history/publication controls, static planning routes, reloads and wrong-order recovery. Test fixtures are not operational results.

Latest Main lacks B queue/composite-detail registration and P1 scoped compatibility. shared-integration.patch is based ONLY on latest Main, for C/A review; do not apply it to the B baseline. It preserves new Human Review, feasibility links, submenu placeholders and shared foundation. Keep /orders/portfolio and /orders/calendar via App.routeExtensions; /planning/portfolio and /calendar remain distinct existing placeholders.

See external Phase 6 handoff, capability matrix, UAT matrix, safety audit, manifest and demo guide. Operational queue/assessment/decision/portfolio/calendar APIs remain blocked. No new command is enabled.
