# Orders & Planning — local and teammate setup

This branch contains the shared SYNTHETIC backend dataset/API, frontend adapters,
Detail Phase 2/3A/3B, and Calendar requested-delivery mapping. It does not depend on
an agent's validation directory. Do not copy a running test directory over a checkout.

## Requirements and safety

- Windows PowerShell, Docker/PostgreSQL, Node/npm and an existing project Python virtualenv.
- Use the SAME reviewed integration commit on every machine. This branch has not
  been pushed automatically: the owner must distribute/push it after review.
- Each developer needs their OWN explicitly disposable database:
  `127.0.0.1:5434/moumantai_demo`; never point these commands at 5433/moumantai.
- Core and P1 must target that same database. Do not copy another Windows user's
  DPAPI file: DPAPI credentials are user/machine scoped.
- No database creation, migration or seed is performed by either startup script.
- Existing `scripts/seed_demo.py` DELETEs/recreates its five canonical demo
  commitments and related synthetic rows; its idempotency comment does NOT mean
  it preserves edited records. It is only suitable for a verified NEW EMPTY
  disposable database. Never rerun against the current populated Demo database.
- Existing normal Backend 8000 must use ordinary synthetic local identity, isolated
  E2E disabled, external channels/autostart/AI disabled, and no sending workers.
  The separate Orders backend 8001 enforces read-only SQL and HTTP methods.
- No private server key is supplied to the frontend. Do not use host 0.0.0.0 or
  expose this synthetic header identity runtime to an untrusted network.

## Once per teammate: database preparation (manual, not automatic)

Provision a separate Docker Compose project `moumantai-uat` with its own named
volume `moumantai-uat-postgres`, database/user `moumantai_demo`, bound ONLY to
`127.0.0.1:5434`. First inspect project/volume/port ownership and stop if occupied
by an unrelated service. Preserve any existing database; never reset it.
Use a unique local password, kept out of Git and shell command arguments.

From the repository root, securely set process-local connection settings. This is
also the portable alternative to the original developer's DPAPI mechanism:

```powershell
$taskSecure = Read-Host 'Your isolated Demo database password' -AsSecureString
$taskPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($taskSecure)
try {
  $taskPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($taskPtr)
  $env:DATABASE_URL = 'postgresql+psycopg://moumantai_demo:' + [Uri]::EscapeDataString($taskPassword) + '@127.0.0.1:5434/moumantai_demo'
  $env:P1_DATABASE_URL = $env:DATABASE_URL
} finally {
  [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($taskPtr)
  $taskPassword = $null
}
```

Verify `current_database()`, host, port, volume and that ALL business tables are
empty before initial preparation. Install the repository's pinned dependencies
in this clone using its normal documented virtualenv/npm setup. Then, only for
that verified new empty database, run Alembic from backend:

```powershell
Push-Location backend
.\.venv\Scripts\python.exe -B -m alembic heads
# Expected current integration baseline: 0017_p1_real_channel_provenance
.\.venv\Scripts\python.exe -B -m alembic upgrade head
.\.venv\Scripts\python.exe -B -m alembic current
Pop-Location
```

The owner must separately approve the one-time canonical `seed_demo.py` call on
that empty database. It provides the five Core commitment IDs listed below,
four resource stocks, proposals/audit and synthetic outbox fixtures. It prints
its connection string: capture/redact its output before display or logging. Do
not pass the URL as a command-line argument. Communication seeding is optional,
not required by these Orders pages. No seeding is needed on the current machine.

A newly seeded teammate's Core timestamps are generated at seed time; the shared
request fixture is versioned immutable demonstration data. They are separately
sourced, not automatically assumed to be exact agreed terms. Do not edit fixture
provenance/freshness to conceal missing current operational evidence.

## Start the reviewed application

1. Keep/configure the normal app Backend 8000 against the isolated Demo database.
   Both DATABASE_URL and P1_DATABASE_URL must be explicitly set. Use
   MOUMANTAI_SYNTHETIC_MODE=1, MOUMANTAI_ISOLATED_E2E=0; disable external channel
   credentials/autostart and sending workers. No startup migration/seed is needed.
2. Start the isolated Orders read-only Backend from THIS repository:

```powershell
./scripts/Start-OrdersReadOnlyDemo.ps1
# Or -PythonPath 'path/to/your/existing/python.exe'
Invoke-RestMethod http://127.0.0.1:8001/health
```

The script accepts DATABASE_URL already in the current process; otherwise it
uses this Windows user's existing DPAPI Demo credential. Python validates exact
5434/moumantai_demo before connecting, sets Core/P1 URLs identically and forces
read-only SQL. Errors fail closed. Logs are in LOCALAPPDATA/MouManTAI-Demo-UAT,
not an agent directory or a plaintext credential file. A PID is not proof of
startup: /health must pass. An occupied 8001 is not killed/replaced automatically.

3. Inspect/stop only the intended Vite on 5173, then:

```powershell
./scripts/Start-OrdersPlanningFrontend.ps1
# http://localhost:5173/orders
```

This launcher resolves repository-relative paths, requires healthy 8000/8001,
refuses an occupied frontend port and changes only child-process flags:
MODE=demo, VITE_ORDERS_DEMO=1, same-origin API base. It disables isolated E2E proxy
key injection. No repository .env files are created/edited.

Vite routes `/v1/demo/orders...` ONLY in explicit demo SERVE mode to 8001; existing
shared `/v1` and `/health` remain on 8000. Production builds and ordinary `npm run
dev` do not opt in. Do not set a global VITE_API_BASE_URL to 8001, because that
would also redirect unrelated module APIs to the read-only server.

## Verify

```powershell
$taskHeaders = @{'X-Tenant-ID'='tenant_demo_01';'X-Actor-ID'='user_owner_01'}
(Invoke-RestMethod http://localhost:5173/v1/demo/orders -Headers $taskHeaders).orders.Count
# 5
(Invoke-RestMethod http://localhost:5173/v1/overview -Headers $taskHeaders).commitments.Count
# 5 after the approved one-time seed
./backend/.venv/Scripts/python.exe -B scripts/verify_orders_readonly_demo.py
```

Expected shared identities:
- ord_normal_01 -> com_normal_01
- ord_hero_001 -> com_001
- ord_delay_01 -> com_delay_01
- ord_ambiguous_01 -> com_ambiguous_01
- ord_fulfilled_01 -> com_fulfilled_01

Queue reads five requests with explicit DEMO-ONLY/SYNTHETIC and UNKNOWN lifecycle.
Detail uses the latest Workspace and actual linked Core history. Calendar uses
these same Order IDs, requested deadlines and TENTATIVE/REQUESTED authority.
Portfolio remains honestly unavailable: no scenario/optimization is fabricated.

Manual checklist: search / clear, status, FCFS/deadline sort, advanced filters,
Reset, Detail tabs/return links, Back/Forward, data Refresh, actor/tenant isolation,
Calendar views/drill-down/refresh, Portfolio unavailable, Dashboard five rows.
Existing hard-reload limitation: Queue preferences are in an identity-epoch
WeakMap; a full browser reload invalidates its opaque URL marker and resets
preferences. Navigation Back/Forward retains them within the live identity epoch.
This pre-existing behavior was not weakened to revive old identity preferences.

Fixture Calendar validity expires 2026-11-24T08:02:48.832001Z. After expiry, events
are withheld; a reviewed shared source revision is required. Missing P1 contexts,
verified P2 request/snapshot bindings, exact order commands/reservations and
portfolio contracts remain blockers. Local reviews/seeded Core states are not
trusted customer assent, execution or delivery evidence.

## Restore ordinary mode

Inspect the PID/command before stopping only these launcher's frontend/8001
processes. Restart `npm run dev -- --host 127.0.0.1 --port 5173 --strictPort`
without VITE_ORDERS_DEMO. Leave Backend 8000 and all database containers/volumes
alone. No reset, migration, seed, git clean or credential file is needed.
