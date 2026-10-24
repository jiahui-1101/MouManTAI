"""P4 Orders database persistence model.

Explicitly owned by P4 (Orders & Planning).
Does not mutate P1 or Core tables or assume verified commercial acceptance.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class P4OrderRecord(Base):
    __tablename__ = "p4_orders"

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    commitment_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    customer_display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    requested_items: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    requested_delivery_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lifecycle_status: Mapped[str] = mapped_column(String(64), nullable=False, default="UNKNOWN")
    source_channel: Mapped[str] = mapped_column(String(64), nullable=False, default="SYNTHETIC")
    evidence_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    integration_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="SYNTHETIC")
    evidence_tier: Mapped[str] = mapped_column(String(32), nullable=False, default="DEMO-ONLY")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_p4_orders_tenant_delivery", "tenant_id", "requested_delivery_at"),
        Index("ix_p4_orders_tenant_commitment", "tenant_id", "commitment_id"),
    )
