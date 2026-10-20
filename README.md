# MouManTAI

MouManTAI is an SME commitment assurance and recovery prototype. Phase 0 provides the
shared contracts, synthetic fixture, FastAPI/Vite foundation, PostgreSQL/Alembic setup,
and parallel feature boundaries. P1–P4 business modules are intentionally not implemented
by the shared-foundation work.

## Repository layout

- `backend/` — FastAPI app, Pydantic contracts, SQLAlchemy/Alembic foundation, tests.
- `frontend/` — React + TypeScript + Vite shell, routes, API client, smoke test.
- `contracts/` — synchronized TypeScript types and the shared synthetic fixture.
- `AGENTS.md` — the single canonical agent instruction file.
- `docs/` — system requirements, owner requirements, and the team execution log.

## Local development

Prerequisites: Python 3.11+, Node.js 20+, npm, and Docker Desktop for PostgreSQL.

```powershell
docker compose up -d db

backend\.venv\Scripts\python.exe -m pytest
backend\.venv\Scripts\python.exe -m alembic -c backend\alembic.ini upgrade head
backend\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload

cd frontend
npm install
npm run dev
```

The project PostgreSQL container maps to host port `5433` to avoid changing or replacing
an existing local PostgreSQL instance on port `5432`. Copy `.env.example` when local
overrides are needed. The frontend uses `VITE_API_BASE_URL=http://localhost:8000` by default.

## Checks

```powershell
backend\.venv\Scripts\python.exe -m pytest
cd frontend
npm run typecheck
npm test -- --run
npm run build
```
