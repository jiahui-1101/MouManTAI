"""Durable, explicitly synthetic supplier comparison and human choice evidence."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MockSupplierDatasetRecord(Base):
    __tablename__ = "mock_supplier_datasets"

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    dataset_version: Mapped[int] = mapped_column(Integer, nullable=False)
    category_id: Mapped[str] = mapped_column(String(128), nullable=False)
    spec: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    requirement: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    offers: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_through: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_mock_supplier_tenant_category", "tenant_id", "category_id"),)


class MockSupplierSelectionRecord(Base):
    __tablename__ = "mock_supplier_selections"

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    selection_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String(128), nullable=False)
    dataset_version: Mapped[int] = mapped_column(Integer, nullable=False)
    request_key: Mapped[str] = mapped_column(String(128), nullable=False)
    supplier_id: Mapped[str] = mapped_column(String(128), nullable=False)
    quote_id: Mapped[str] = mapped_column(String(128), nullable=False)
    quote_version: Mapped[int] = mapped_column(Integer, nullable=False)
    comparison_status: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    selected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "dataset_id"],
                             ["mock_supplier_datasets.tenant_id", "mock_supplier_datasets.dataset_id"],
                             name="fk_mock_supplier_selection_dataset", ondelete="RESTRICT"),
        UniqueConstraint("tenant_id", "dataset_id", name="uq_mock_supplier_one_selection"),
        UniqueConstraint("tenant_id", "request_key", name="uq_mock_supplier_selection_key"),
    )


class MockSupplierAuditRecord(Base):
    __tablename__ = "mock_supplier_audit"

    audit_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    dataset_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    evidence_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_mock_supplier_audit_tenant_dataset", "tenant_id", "dataset_id", "occurred_at"),
    )
