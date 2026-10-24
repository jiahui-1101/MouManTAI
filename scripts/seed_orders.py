"""Idempotent seed script for P4 synthetic orders in PostgreSQL 5433.

Seeds 5 canonical synthetic orders corresponding to the 5 Core commitments.
Does not mutate or delete existing Core commitments, proposals, audits or resource stocks.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.orders.models import P4OrderRecord


def _mask_url(url: str) -> str:
    """Mask password in connection URL for safe logging."""
    if "@" in url and "://" in url:
        scheme_user, rest = url.split("@", 1)
        scheme, user_pass = scheme_user.split("://", 1)
        user = user_pass.split(":", 1)[0]
        return f"{scheme}://{user}:***@{rest}"
    return url


def seed_orders(db_url: str | None = None) -> int:
    database_url = db_url or os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://moumantai:moumantai@127.0.0.1:5433/moumantai",
    )
    print(f"[seed_orders] Target database: {_mask_url(database_url)}")

    engine_kwargs: dict[str, object] = {"pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        engine_kwargs["connect_args"] = {"check_same_thread": False}

    engine = create_engine(database_url, **engine_kwargs)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    fixture_path = (
        Path(__file__).resolve().parent.parent
        / "backend"
        / "app"
        / "orders"
        / "fixtures"
        / "orders_demo_v1.json"
    )
    with open(fixture_path, "r", encoding="utf-8") as f:
        fixture_data = json.load(f)

    tenant_id = fixture_data.get("tenant_id", "tenant_demo_01")
    orders_data = fixture_data.get("orders", [])
    target_order_ids = {o["order_id"] for o in orders_data}

    now = datetime.now(timezone.utc)

    with session_factory() as session:
        # Idempotent cleanup of existing synthetic demo orders only
        existing = session.scalars(
            select(P4OrderRecord).where(
                P4OrderRecord.tenant_id == tenant_id,
                P4OrderRecord.order_id.in_(target_order_ids),
            )
        ).all()
        for r in existing:
            session.delete(r)
        session.flush()

        # Insert canonical orders
        for o in orders_data:
            req_delivery = datetime.fromisoformat(o["requested_delivery_at"].replace("Z", "+00:00"))
            received_at = datetime.fromisoformat(o["received_at"].replace("Z", "+00:00"))
            record = P4OrderRecord(
                tenant_id=tenant_id,
                order_id=o["order_id"],
                commitment_id=o.get("commitment_id"),
                customer_display_name=o["customer_display_name"],
                requested_items=o["requested_items"],
                requested_delivery_at=req_delivery,
                received_at=received_at,
                lifecycle_status=o.get("lifecycle_status", "UNKNOWN"),
                source_channel=o.get("source_channel", "SYNTHETIC"),
                evidence_refs=o.get("evidence_refs", []),
                integration_mode=fixture_data.get("integration_mode", "SYNTHETIC"),
                evidence_tier=fixture_data.get("evidence_tier", "DEMO-ONLY"),
                created_at=now,
                updated_at=now,
            )
            session.add(record)

        session.commit()

        # Verification
        count = session.scalars(
            select(P4OrderRecord).where(
                P4OrderRecord.tenant_id == tenant_id,
                P4OrderRecord.order_id.in_(target_order_ids),
            )
        ).all()
        print(f"[seed_orders] Successfully seeded {len(count)} orders in {tenant_id}.")
        return len(count)


if __name__ == "__main__":
    url_arg = sys.argv[1] if len(sys.argv) > 1 else None
    seed_orders(url_arg)
