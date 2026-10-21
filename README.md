# MouManTAI — Intelligent Commitment Assurance & Recovery for SMEs

[![CI](https://github.com/jiahui-1101/MouManTAI/actions/workflows/ci.yml/badge.svg)](https://github.com/jiahui-1101/MouManTAI/actions/workflows/ci.yml)

MouManTAI is an SME commitment assurance and recovery platform. It detects, assesses, and resolves operational disruptions that threaten customer commitments when messages, suppliers, inventory, and kitchen/production systems are disconnected.

---

## 1. System Architecture & Core Invariants

- **Authoritative Commitment Core**: Maintains five independent state dimensions: `Agreement`, `Feasibility`, `Risk`, `Recovery`, and `Fulfilment`.
- **Core Invariants**:
  - `REQUESTED ≠ CONFIRMED`: Customer requests require verified context and terms before confirmation.
  - `FEASIBLE` is snapshot-specific: Resource feasibility is evaluated deterministically against current inventory and lead times.
  - `CONFIRMED + AT_RISK` coexist: A confirmed customer order can become at-risk without canceling the agreement.
  - `SENT ≠ ACCEPTED ≠ FULFILLED`: Sending a proposal does not mean acceptance; acceptance does not mean goods delivered.
  - `APPROVED ≠ EXECUTED`: Manager approval authorizes recovery actions but does not substitute for operational execution.
  - `UNKNOWN ≠ INFEASIBLE`: Missing telemetry creates an attention item rather than a false risk alert.
- **Transactional Outbox & Audit**: Every lifecycle mutation writes an immutable audit event and a transactional outbox event atomically in the same database transaction.

---

## 2. Repository Layout & Module Ownership

| Path | Primary Owner | Module & Responsibilities |
|---|---|---|
| `backend/app/context/`, `frontend/src/features/context/` | **P1** | Ingestion, message normalization, identity linking, context extraction. |
| `backend/app/feasibility/`, `frontend/src/features/feasibility/` | **P2** | ATP/BOM calculation, deterministic solver, impact evaluation (`POST /v1/commitments/{id}/assess`). |
| `backend/app/recovery/`, `frontend/src/features/recovery/` | **P3** | Recovery plan generation, ranking, and manager authorization. |
| `backend/app/communication/`, `frontend/src/features/communication/` | **P4** | Customer message dispatch, response parsing, and proposal confirmation. |
| `backend/app/core/`, `backend/app/db/`, `contracts/`, `frontend/src/shared/`, `frontend/src/app/` | **P5** | Shared Commitment Registry, application shell, audit/outbox, auth/policy, integration facade, CI/CD. |

---

## 3. Quickstart with Docker Compose (`DEV-1`)

The easiest way to start MouManTAI with all backing services is via Docker Compose.

```bash
docker compose up --build
```

This single command:
1. Starts **PostgreSQL 16** on host port `5433` (to avoid conflicting with local port 5432).
2. Starts the **Backend API** on port `8000`, running:
   - Automated Alembic migrations (`alembic upgrade head`)
   - Automated synthetic demo seed data (`python scripts/seed_demo.py`)
   - FastAPI server with active `/health` healthcheck
3. Starts the **Outbox Worker** polling and dispatching domain events.

To verify the running API:
```bash
curl http://localhost:8000/health
# Returns: {"status":"ok","service":"moumantai-api","version":"0.1.0"}
```

---

## 4. Local Development Setup (`DEV-2`, `DEV-3`)

### Prerequisites
- **Python 3.11+** (Python 3.12 recommended)
- **Node.js 20+** and **npm**
- **Docker Desktop** (for PostgreSQL) or local SQLite fallback

### Step 1: Environment Configuration
Copy the placeholder template:
```bash
# Windows (PowerShell / CMD):
copy .env.example .env

# Linux / macOS:
cp .env.example .env
```

### Step 2: Backend Setup
```powershell
# Create and activate virtual environment
python -m venv backend\.venv
.\backend\.venv\Scripts\Activate.ps1   # Windows PowerShell
# source backend/.venv/bin/activate    # Linux / macOS

# Install backend in editable mode with development dependencies
pip install -e "./backend[dev]"

# Run database migrations
alembic -c backend/alembic.ini upgrade head

# Seed synthetic demo data
python scripts/seed_demo.py

# Launch FastAPI development server
uvicorn app.main:app --app-dir backend --reload --port 8000
```

### Step 3: Frontend Setup
```powershell
cd frontend
npm install
npm run dev
```
The frontend is available at `http://localhost:5173` and connects to the backend API at `http://localhost:8000`.

---

## 5. Windows PowerShell DevEx Guide (`DEV-4`)

> [!IMPORTANT]
> **Windows ExecutionPolicy Issue (`npm.ps1`)**:
> If Windows PowerShell displays an error like:
> `File ...\npm.ps1 cannot be loaded because running scripts is disabled on this system`
>
> Run npm commands via `cmd /c` or use `npm.cmd`:
> ```powershell
> # Instead of: npm install
> cmd /c npm install
>
> # Instead of: npm run dev
> cmd /c npm run dev
>
> # Instead of: npm test
> cmd /c npm test
>
> # Instead of: npm run build
> cmd /c npm run build
>
> # Instead of: npm run typecheck
> cmd /c npm run typecheck
> ```
> Alternatively, execute `npm.cmd install`, `npm.cmd run dev`, etc.

---

## 6. Synthetic Demo Dataset (`BE-03f`)

The database seed (`python scripts/seed_demo.py`) creates 5 canonical demo commitments illustrating the platform's core operational scenarios:

| Commitment ID | Order ID | State Dimensions | Scenario Description |
|---|---|---|---|
| `com_normal_01` | `ord_normal_01` | `CONFIRMED` · `FEASIBLE` · `NORMAL` · `NOT_STARTED` | Standard feasible order; stock confirmed. |
| `com_001` | `ord_hero_001` | `CONFIRMED` · `INFEASIBLE` · `AT_RISK` · `RECOVERY_REQUIRED` | Material shortage of 40 beef patties triggering recovery. |
| `com_delay_01` | `ord_delay_01` | `CONFIRMED` · `INFEASIBLE` · `AT_RISK` · `PENDING_APPROVAL` | Supplier delay with 2 alternate recovery proposals (expedite vs reschedule). |
| `com_ambiguous_01` | `ord_ambiguous_01` | `OFFERED` · `FEASIBLE` · `NORMAL` · `NOT_STARTED` | Ambiguous customer reply ("ok sure maybe"); flagged for manual review (`SENT ≠ ACCEPTED ≠ FULFILLED`). |
| `com_fulfilled_01` | `ord_fulfilled_01` | `CONFIRMED` · `FEASIBLE` · `RESOLVED` · `FULFILLED` | Verified operational delivery with signed courier Proof of Delivery (`ev_ops_delivery_pod_*`). |

To reset and re-seed the test database at any time:
```powershell
python scripts/seed_demo.py
```

---

## 7. Testing & Quality Gates

Run the automated test suites locally before submitting changes:

```powershell
# 1. Backend test suite (pytest: unit, concurrency, outbox, E2E journey, identity guards)
pytest -v backend/tests

# 2. Frontend TypeScript typecheck
cd frontend
cmd /c npm run typecheck

# 3. Frontend unit tests (Vitest)
cmd /c npm test -- --run

# 4. Frontend production bundle build
cmd /c npm run build

# 5. (Optional) Live-API network smoke suite (requires running backend on port 8000)
cmd /c "set LIVE_API=1&& npm test"
```

---

## 8. Continuous Integration (`DEV-5`)

Every push and Pull Request triggers the GitHub Actions CI pipeline ([.github/workflows/ci.yml](file:///.github/workflows/ci.yml)) running three parallel jobs:
1. **`backend-tests`**: Python 3.12, installs dependencies, compiles all modules, and runs the complete `pytest` suite.
2. **`frontend-checks`**: Node.js 20, runs `npm ci`, TypeScript typecheck (`tsc --noEmit`), Vitest unit tests, and production build (`vite build`).
3. **`hygiene-check`**: Scans `.env.example` for unmasked secrets/tokens and verifies zero deprecated legacy branding (`PromiseFlow`) exists across UI and source files.
