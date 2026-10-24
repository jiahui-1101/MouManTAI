"""Fail closed before a staging process can touch a non-staging database."""
import os
from sqlalchemy.engine import make_url


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"Staging preflight failed: {message}")


url = os.getenv("DATABASE_URL", "")
require(bool(url), "DATABASE_URL is required")
try:
    parsed = make_url(url)
except Exception:
    raise SystemExit("Staging preflight failed: DATABASE_URL is invalid") from None

require(parsed.drivername == "postgresql+psycopg", "PostgreSQL psycopg is required")
require(parsed.host == "db" and parsed.database == "moumantai_staging", "database target must be the isolated staging service")
require(parsed.username == os.getenv("STAGING_DB_USER"), "database user mismatch")
require(os.getenv("P1_DATABASE_URL") == url, "P1 and shared database URLs must match")
require(os.getenv("ENVIRONMENT") == "staging", "ENVIRONMENT must be staging")
require(os.getenv("MOUMANTAI_SYNTHETIC_MODE") == "1", "only the synthetic staging mode is supported")
require(os.getenv("MOUMANTAI_ISOLATED_E2E") == "0", "isolated mutation endpoints are disabled")
require(os.getenv("P1_AI_ENABLED") == "false", "external AI calls are disabled for initial staging")
for name in ("TELEGRAM_OUTBOUND_ENABLED", "WHATSAPP_OUTBOUND_ENABLED", "RESEND_OUTBOUND_ENABLED"):
    require(os.getenv(name) == "false", f"{name} must remain disabled")
print("Staging preflight passed (isolated PostgreSQL, synthetic mode, outbound disabled)")
