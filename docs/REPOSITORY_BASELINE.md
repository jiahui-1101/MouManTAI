# v2.2 implementation baseline

- Fresh fetch: `git fetch origin main` advanced origin/main from 70f4827 to `ec3ffbc970ab38abca8468abfe0466ff0464b998` (PR #45 SQLite concurrency fix).
- Original checkout `D:/dunno/0.SDC/MouManTAI`, branch `feat/p2-7b4b-confirmed-consumer`, clean at audit; preserved.
- Dedicated managed worktree: `C:/Users/User/.codex/worktrees/backend-v2-2/MouManTAI`; branch `codex/feat-v2-2-backend` from freshly fetched origin/main.
- Pack extracted outside repository; all six Markdown files and CODEX_PROMPT.md read completely. Root six files are canonical originals; source SHA256 in `docs/V2_2_SOURCE_CHECKSUMS.json`. Prior rules archived as `docs/legacy/AGENT_RULES_V1.md`; `docs/REQUIREMENTS_SYSTEM.md` explicitly legacy. Person requirements remain historical compatibility references.
- Python 3.14.3, installed FastAPI/Pydantic/SQLAlchemy/Alembic/psycopg/pytest; Docker 29.8.0 with cached PostgreSQL 16. `gh` unavailable; GitHub connector available.
- `python -m alembic heads` (backend): single `0017_p1_real_channel_provenance`. Actual migrations include branch merges 0013/0014 and P1 migrations 0016/0017. No new migration planned before ownership review.
- 86 mounted OpenAPI paths (default environment), recorded compactly in `BACKEND_ROUTE_INVENTORY.json`; ORM declarations in `BACKEND_SCHEMA_INVENTORY.md`. Inventories are code observations, not proof of a running production DB.
- P1 `create_p1_engine` now falls back from P1_DATABASE_URL to DATABASE_URL. Compose supplies DATABASE_URL. Earlier missing-variable blocker is obsolete on this SHA. P1 still requires PostgreSQL; no SQLite fallback in P1.
- Core request headers map static actors and are synthetic development context, not verified production authentication. P3 approval actor provider fails closed outside isolated key mode. New HTTP contracts must not grant authority from headers.
- Production worker does not register the isolated P2/P3 mandatory consumers. Existing isolated registration and persisted source checks are preserved.
- PR state checked through GitHub: #38 MERGED; #39 OPEN DRAFT (isolated upstream fixture, not main); #40 OPEN DRAFT; #42 OPEN DRAFT stacked on #40. No code copied from those branches.
- Baseline: `python -m pytest tests/test_smoke.py tests/test_outbox_events.py tests/test_assess_identity_guards.py app/feasibility/tests/test_consumer.py -o addopts= -q` -> **68 passed**, 5 existing deprecation warnings (5.47s). Full suite and PG results tracked in living handoff as run.
- Frontend inspected for API ownership only, unchanged. CI explicitly selects backend/tests, feasibility and communication; default pytest additionally selects context. New tests go under backend/tests/v2_2 to run in both CI backend jobs.

Safe dependency order: A immutable terms/port DTOs + negative guards; B deterministic reply and clarification mechanisms (no send/state authority); C server-gated read-only API adapters and persisted Core projections. Acceptance saga/portfolio/supplier/CTA changes require reviewed shared contracts and owner decisions. Proposed forecasts/memory/RFQ remain full target, not implemented or silently dropped.

Current risks: unratified S1–S5 policy; no authenticated production actor provider; commercial terms not represented in Core; no order reservation saga; no official live Orbyte/Replit endpoint; no joint P2 ConstraintSpec compiler. These prevent honest acceptance/optimization/live claims, but do not block safe contract and pure validation work.
