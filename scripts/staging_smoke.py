"""Safe, synthetic persistence and outbox smoke against an isolated staging DB."""
from datetime import datetime, timezone
import os
import time
from uuid import uuid4

from sqlalchemy import text

from app.core.models import OutboxEventRecord
from app.db.session import SessionLocal


def main() -> None:
    if os.getenv("ENVIRONMENT") != "staging":
        raise SystemExit("Smoke is restricted to the staging environment")
    event_id = f"staging_smoke_{uuid4().hex}"
    with SessionLocal() as db:
        version = db.scalar(text("SHOW server_version_num"))
        if not str(version).startswith("16"):
            raise SystemExit("PostgreSQL 16 is required")
        revision = db.scalar(text("SELECT version_num FROM alembic_version"))
        if not revision:
            raise SystemExit("Alembic version is missing")
        schema = db.scalar(text("SELECT to_regclass('p1_dev.inbound_messages')"))
        if schema is None:
            raise SystemExit("Canonical P1 message table is missing")
        indexes = set(db.scalars(text("SELECT indexname FROM pg_indexes WHERE schemaname = 'p1_dev' AND tablename = 'inbound_messages'")))
        if not {'uq_p1_delivery_scoped', 'uq_p1_delivery_telegram_scoped'} <= indexes:
            raise SystemExit("Canonical P1 scoped delivery indexes are missing")
        db.add(OutboxEventRecord(
            event_id=event_id,
            tenant_id="synthetic_tenant_a",
            event_type="staging.noop",
            commitment_id=None,
            commitment_version=None,
            correlation_id=event_id,
            causation_id=None,
            occurred_at=datetime.now(timezone.utc),
            payload={"synthetic": True},
            status="PENDING",
        ))
        db.commit()

    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        with SessionLocal() as db:
            status = db.scalar(text("SELECT status FROM outbox_events WHERE event_id = :id"), {"id": event_id})
        if status == "PUBLISHED":
            print(f"PostgreSQL 16; Alembic {revision}; P1 indexes present; outbox worker published synthetic no-op event")
            return
        time.sleep(0.5)
    raise SystemExit("Outbox worker did not publish the synthetic no-op event")


if __name__ == "__main__":
    main()
