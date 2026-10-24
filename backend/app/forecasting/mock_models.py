"""Persisted synthetic demand history, independent of production authority."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MockForecastDatasetRecord(Base):
    __tablename__ = "mock_forecast_datasets"

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    sku_id: Mapped[str] = mapped_column(String(128), nullable=False)
    unit: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    observations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_mock_forecast_tenant_sku", "tenant_id", "sku_id"),)


class MockForecastAuditRecord(Base):
    __tablename__ = "mock_forecast_audit"

    audit_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    dataset_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    evidence_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
