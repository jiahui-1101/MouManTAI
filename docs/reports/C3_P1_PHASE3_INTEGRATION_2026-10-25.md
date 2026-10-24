# Phase 3 C3 + P1 reliability integration (2026-10-25)

Status: integration candidate, **NO-GO for live C3 semantic processing or outbound**. Baseline: Main `1cd91bf` includes #90, #96 and #95; #102 and #103 remain unmerged as PRs. Worktree branch `codex/c3-p1-integration-20261025` preserves both PR histories with normal merge commits.

## Reuse and overlap matrix (recorded before integration edits)

| Concern | #102 | #103 | Canonical decision |
| --- | --- | --- | --- |
| P1 source | accepts `StoredMessage`, association and attachment extraction snapshots | existing P1 current-message inference | Read exact current tenant-scoped P1 rows; no second store |
| Classification | deterministic intent plus strict inquiry/delay/review contracts | field extraction proposals | Retain C3 business classifier and candidate contracts |
| Qwen/Gemini | separate C3 HTTP clients, retries, spend cap and fallback | P1 Qwen primary and Gemini technical fallback | P1 owns production provider activation; remove C3 production HTTP clients |
| Privacy/evidence | C3 span/document claim checks | same-length masking and original-offset checks | C3 uses P1 masking; preserve its stricter typed candidate evidence validation |
| Diagnostics/review | ephemeral attempt list and review candidate | durable P1 extraction diagnostics and conflict review | P1 is canonical durable path; C3 review writer remains unapproved/unwired |
| Business authority | no mutations/sends | P1 proposals only | exact read-only handoffs; P2/P4 contracts remain gated |

## Implementation and conflicts

- #103 merged into Main with one append-only `docs/TEAM_LOG.md` conflict; both entries were retained. #102 merged without a textual conflict. No published PR history was rewritten.
- P1's identifier mask now requires an explicit separator (`PO-450` remains masked); ordinary words such as `possible` and `supplier` are no longer masked. Masking remains same-length, and evidence crossing masked spans fails closed.
- C3 now calls the P1 masking function. The independent C3 retry/fallback loop and budget/provider clients were removed. P1 owns the Qwen/Gemini technical fallback policy; C3 accepts only a future reviewed semantic gateway result and validates its schema, deterministic consistency, source spans and document IDs. Deterministic conflicts are routed to review without a model vote.
- Removed C3 production Qwen/Gemini HTTP clients and environment activation. `MessageIntelligenceService.from_env()` constructs deterministic analysis only. This avoids a second live reliability pipeline, but P1's current inference schema supports extraction fields, not C3 intent/claims; a reviewed shared semantic task contract is required before C3 semantic activation. Fixture semantic gateway results exercise C3 candidate/schema/evidence behavior; P1 fixture tests exercise fallback behavior.
- Added `CurrentP1MessageReader` and read-only inquiry/supplier handoffs. They re-read exact source hash, account-bound native message provenance, attachment/extraction snapshots and customer association version. Draft text comes only from an injected approved public fact with evidence/version. Supplier validation requires a tenant/supplier/reference matched current P2 snapshot. Both return previews only. No P2 event or P4 send is performed.
- No migration, shared Core/P2/P4 schema or frontend DTO was changed. The #102 Human Review candidate remains ephemeral. Existing P1 context review is for context corrections and cannot safely persist a generic C3 task without an approved contract.

## Validation and release blockers

See the final turn for exact local command results and exact-head CI status. All provider tests use synthetic fixtures; **LIVE_PROVIDER = NOT_RUN**. No credentials or privacy authorization were used.

Required before GO: P1/P5 owner-approved shared semantic classification task and bounded provider configuration; durable C3 review-task mapping preserving source version, reasons, evidence and model provenance; trusted production business fact and supplier/P2 readers; current identity and source freshness review; P4 verified recipient, purpose consent, explicit authorization, durable outbox/idempotency and unknown-outcome receipt contract; frontend candidate/review integration; migrated PostgreSQL and exact-head CI validation. Do not enable real sends through C2 transports.


### Local verification on integration candidate

- `python -m pytest -o addopts= backend/tests/test_message_intelligence.py backend/app/context/tests/test_ai_provider_reliability.py -q --tb=short`: **34 passed, 1 skipped** (the opt-in live-provider smoke). Synthetic fixture data only.
- Earlier selected migrated PostgreSQL C1/C2/P1/C3 suite, with `REQUIRE_POSTGRES=1`, task-owned PostgreSQL 16, and a task-local pytest base temp directory: **117 passed, 1 deselected**, 24 warnings, 122.01s. The deselected case was only `opt_in_live_gemini_smoke`. This run covered `test_message_intelligence.py`, P1 source reader, C2 provider/security, C1 persistence/framing, C2 canonical integration, P1 provider reliability/integration and P1 Alembic migration.
- Initial selected C1/C2/P1 attempt: **45 passed, 5 setup errors** due to Windows permission denial on the global pytest temp directory; the five C2 fixture cases reran with task-local base temp and passed **5/5**. This was a local temp-path issue, not an application assertion. A broad `backend/tests` PostgreSQL run was interrupted after the C3 gateway refactor and is **NOT_RUN to completion** for this final code.
- Frontend `npm run typecheck`: passed. `npm test -- --run`: **1,232 passed, 5 skipped**. `npm run build`: passed with existing large-chunk advisory.
- `ruff check`, `ruff format --check`, `compileall`, `git diff --check`, and `alembic heads` passed; sole Alembic head: `0025_merge_c1_business_orch`.
- Exact-head GitHub Actions: **PENDING** until this branch is published and checks finish. Live Qwen/Gemini, channel provider E2E and real P4 outbound: **NOT_RUN** (credentials/privacy and P4 authorization unavailable).
