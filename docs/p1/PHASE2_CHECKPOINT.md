# P1 phase 2 checkpoint

Latest L2-only continuation: [L2_PHASE1_CHECKPOINT.md](L2_PHASE1_CHECKPOINT.md), implementation `75b5c87`, 85 targeted tests passed. L2 remains default-disabled; no real inference performed. Stop awaiting the user's GPU endpoint. The earlier six integration/accuracy items below are not silently marked complete by this L2 task.

Branch: `feat/p1-phase2-refinement`. Starting checkout `a3b2ba3` already contains Main/P5 changes; preserve them. No push/merge/PR, provider provisioning, L2 inference, historical reprocess/edit/publication, or shared migration changes performed.

## Completed in this phase

- `0e0f328`: bounded 60-second / 128-entry raw observation cache; tenant/endpoint-instance/model/revision/request isolation; current source/domain/review validation on reuse; concurrent identical requests coalesced; failed calls counted, failures never cached; reused observations do not claim fresh inference in UI. Unit checks 9 passed; provenance checks 4 passed + application TypeScript passed. This is process-local reuse, not a distributed cache or persistent global idempotency guarantee.
- `6d4f910`: guarded tentative requests, historical feedback and explicit price inquiries from being accepted as current quantity/delivery terms; original spans preserved. Absence of an intent guard remains UNCLASSIFIED, never CONFIRMED. `paket/bungkus` normalize to pack, never silently to pieces. Factory defaults to GLiNER only; L2 requires explicit stages. Guards are conservative patterns, not a trained intent classifier or exhaustive language coverage.
- `683ed73`: generated order references now tested against available P5 amendment workflow: confirmed original quantity stays 100, reviewed 150 enters one proposal, replay creates no duplicate proposal.
- `e170eb4`: reproducible PostgreSQL READ ONLY historical inventory, tenant scoped, no model calls, no processing/publication; test verifies tenant isolation and unchanged message state.
- Focused deterministic/routing/model/domain/P1-P5 publication/amendment checks: **185 passed**. Subsequent cache/factory/audit/publication checks: **21 passed**. Final aggregate result recorded below when completed.

## P5 readiness and actual blockers

- D-037 implementation is available locally: `CoreIntegrationFacade.handle_context_updated` creates proposals for CONFIRMED/OFFERED, preserves current terms, carries every item in `terms.items`, and no longer invents a delivery timestamp. Existing P1 publisher already removed its old blanket block; terminal-state/customer guards, current-context locking, first publication, replay and rollback remain intact. Targeted PostgreSQL amendment/multi-item tests passed. An old test expecting unavailable P5 behavior was updated to assert actual proposal safety, not deleted/skipped.
- Actual Alembic head is **`0011_p4_confirmations`**, after `0010_p4_recipient_preferences`. **No P1 Alembic migration exists in the current checkout**; nothing can safely have its down_revision edited. Shared revision allocation and P1 schema lifecycle require P5 review; do not create a competing migration from the obsolete head or edit P4/P5 migrations independently.
- Main now mounts P1 (`backend/app/main.py`), but P1 dependencies still use `development_context` / `local_repository` with synthetic tenant/private P1 DB. Production trusted tenant/auth/session injection and exception handling are not established by route mounting. This is a joint wiring blocker, not permission to rewrite P5 host code.
- DATE_ONLY versus EXACT/DEADLINE mapping remains unapproved in the shared BusinessContext (no qualifier field); P1 still requires evidence-backed explicit DEADLINE to publish. No midnight/current-time/default-unit repair.
- Review P1 context/Core lock order against D-041 with P5. P2 must consume authoritative terms/version, never model candidates or a proposal as confirmed terms.

## One real L1 benchmark; limitations

Existing configured endpoint health returned HTTP 200 once; reused private environment; no dependency/model download or provider change. Ran existing `run_l1_benchmark.py` with **GLiNER only**, pinned protocol model `urchade/gliner_multi-v2.1@443d26d654e0324125a96bebd8e796c14ff2efe6`. No Qwen request.

Observed 40-case runner result (before intent/package guard changes, after cache fix): product P/R/F1 100/78.4/87.9%; quantity 100/82.8/90.6%; unit 100/100/100%; delivery 96.6/96.6/96.6%. Language pass counts: EN 7/10, ZH 8/10, MS 6/10, mixed 8/10. SKU false accepts 0; runner reports 15 failures. Reproduces supplied metrics; **does not show an accuracy improvement**. Mean wall time 0.938s includes skipped-rule cases (minimum 0), so it is not pure model CPU latency. Existing runner combines L0/candidate results and scores entities; delivery span correctness does not establish normalized timestamp or final BusinessContext correctness. Per-case actual network call counts are not emitted by that runner; routing/caching counts are independently tested with spies, not substituted for real network measurements.

Raw report/log (ignored): `.local/phase2-l1-benchmark.json`, `.log`. Do not repeatedly benchmark unchanged worker code. Future measurement must record raw observations, actual requests, normalization, model versions and final review/persistence outcomes separately. This run cannot establish independent remote hardware/revision attestation or a completed L2 runtime. Old Qwen2.5/Qwen3 labelling defects are documented in the earlier audit; do not deploy L2 to resolve documentation discrepancies.

## Historical coverage and evidence

Read-only initial and post-fix inventory: **177/177** accessible current-tenant messages; **0 audit processing errors**, 0 model calls/writes. Existing 182 contexts, 109 reviews, 291 context versions were read. 160 messages have at least one unresolved/missing current-rule field (not 160 incorrect orders). 3 messages have different VALID field/value sets versus latest stored extraction:

- `942c78f4-b7d6-4f84-850c-b81998b90568`: original example A; current rules add quantity 40; missing timezone/future receipt still unresolved.
- `e90ca854-1554-4c13-89cd-866a7d7742c8` and `ad932f00-6f79-4af5-aaf7-7dfcf6c9c495`: current rules additionally find quantity 50 / delivery candidate; require source/intent review, not automatic historical correction.

Full original text, latest persisted fields, all attempt diagnostics, current L0 and associated contexts: `.local/phase2-historical-audit.json` and `.local/phase2-historical-after.json`. These are automated evidence comparisons, **not independent semantic gold review of all 177 messages**. Historical unnecessary L1 calls, missed escalations and final BusinessContext accuracy remain UNVERIFIED where configuration/call telemetry/gold is missing. No confirmed data or audit history was changed. Current source catalog remains provisional; benchmark's broader catalog is not automatically the app's approved production catalog.

## Validation and exact continuation

Current final frontend: `npm.cmd test` → **401 passed, 5 skipped** (P5 LIVE_API opt-in); `npx.cmd tsc --noEmit -p tsconfig.app.json` passed; `npm.cmd run build` passed (bundle >500KB warning). Final backend: **531 passed, 2 skipped, 1 deselected, 6 warnings in 187.45s** (`.local/phase2-final-backend.txt`). Two skips are opt-in real model smoke tests; one exclusion is the known Windows/Python 3.13 SQLite native-thread reservation crash test. No skipped P5 amendment-success test was counted as passed. Warnings are Paddle ccache and Alembic legacy path splitting. These results describe this phase's tested tree; subsequently detected unrelated ReviewDrawer changes are preserved and not covered by this claim.

```powershell
# Repository root; never print private env contents.
. .\backend\app\context\dev\load-env.ps1 -Path .local/p1.env
$env:P1_DATABASE_URL=$env:P1_TEST_DATABASE_URL
$env:P1_AI_ENABLED='false'
.venv/Scripts/python.exe -m pytest backend/app/context/tests backend/tests -o addopts='' -q -ra --tb=short -k 'not test_thread_concurrent_reservations_prevent_overallocation'
# Read existing .local/phase2-final-backend.txt first; do not repeat a passing unchanged suite.
# Historical report refuses overwrite; use a new ignored filename only if new data/code justifies rerun.
.venv/Scripts/python.exe -m app.context.experiments.audit_historical --output .local/phase2-historical-new.json
```

Remaining work, in order (task is **not fully complete**):

1. Joint P5 migration + trusted repository/tenant/auth/session wiring and delivery qualifier contract; do not independently change shared modules.
2. Semantic review of full local historical report and all 15 benchmark failures; build independently labelled normalized business-field gold before tuning. Existing 40-case data is development evidence now, not fresh held-out accuracy.
3. Delivery-only routing metadata versus genuinely missed unit/date information, cache configuration invalidation when worker labels/threshold change, bounded circuit cooldown (current endpoint has busy/timeout protection, **no circuit breaker**). Repeated product mentions and multi-item association remain conservative; never pick the first item/count to improve recall.
4. Instrument real L1 per-case calls and raw/normalized candidates; record real model/runtime output rather than infer hardware from endpoint name. Do not re-enable/deploy L2.
5. Full final BusinessContext business-field evaluation after review/persistence, new-message Review Drawer confirmation/restart verification on current merged host. Earlier real UI verification predates Main merge and does not prove the new host's production wiring.

For the earlier reported examples/root causes/commits and pre-Main-merge tests, see [EXTRACTION_PIPELINE_AUDIT.md](EXTRACTION_PIPELINE_AUDIT.md). Do not repeat those completed investigations or reuse their old passing counts as current aggregate validation.
