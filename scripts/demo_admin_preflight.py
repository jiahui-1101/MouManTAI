"""Fail closed before the private synthetic API/worker starts for Demo Admin."""

import os
from sqlalchemy.engine import make_url


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise SystemExit(f"Demo Admin preflight failed: {reason}")


url = os.getenv("DATABASE_URL", "")
try:
    parsed = make_url(url)
except Exception:
    raise SystemExit("Demo Admin preflight failed: invalid database URL") from None
require(parsed.drivername == "postgresql+psycopg", "PostgreSQL psycopg required")
if os.getenv("MOUMANTAI_DEMO_HOSTING") in ("render", "render-free"):
    allowed_types = ("web",) if os.getenv("MOUMANTAI_DEMO_HOSTING") == "render-free" else ("pserv", "worker")
    require(os.getenv("RENDER_SERVICE_TYPE") in allowed_types, "Render service type mismatch")
    require(parsed.host not in (None, "localhost", "127.0.0.1", "db") and
            parsed.database == "moumantai_demo_staging", "isolated Render database required")
else:
    require(parsed.host == "db" and parsed.database == "moumantai_staging", "isolated staging database required")
require(parsed.username == os.getenv("STAGING_DB_USER"), "staging database user mismatch")
require(os.getenv("P1_DATABASE_URL") == url, "P1 and shared database must match")
require(os.getenv("ENVIRONMENT") == "staging" and os.getenv("APP_ENV") == "synthetic", "isolated staging environment required")
require(os.getenv("MOUMANTAI_SYNTHETIC_MODE") == "1", "synthetic data only")
require(os.getenv("MOUMANTAI_ISOLATED_E2E") == "1" and os.getenv("MOUMANTAI_DEMO_ADMIN_AUTH") == "1", "Demo Admin boundary required")
require(len(os.getenv("MOUMANTAI_ISOLATED_E2E_KEY", "")) >= 32, "private API key required")
require(bool(os.getenv("MOUMANTAI_ISOLATED_E2E_TENANT_ID")) and bool(os.getenv("MOUMANTAI_ISOLATED_E2E_MANAGER_ID")), "fixed tenant and manager required")
require(os.getenv("P1_AI_ENABLED") == "false", "external inference disabled for initial demo")
for name in ("TELEGRAM_OUTBOUND_ENABLED", "WHATSAPP_OUTBOUND_ENABLED", "RESEND_OUTBOUND_ENABLED"):
    require(os.getenv(name) == "false", f"{name} must remain disabled")
print("Demo Admin preflight passed: private synthetic API, fixed scope, outbound disabled")
