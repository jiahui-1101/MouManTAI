"""Tenant-scoped synthetic planning assumptions for the local portfolio demo."""
from datetime import date, datetime
from decimal import Decimal
from app.db.base import Base
from sqlalchemy import CheckConstraint, Date, DateTime, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column


class PortfolioDemoBOMRecord(Base):
    __tablename__ = "portfolio_demo_bom"
    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    sku: Mapped[str] = mapped_column(String(128), primary_key=True)
    resource_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    quantity_per_unit: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    provenance: Mapped[str] = mapped_column(String(32), nullable=False, default="DEMO_ONLY")
    seed_key: Mapped[str] = mapped_column(String(64), nullable=False)
    __table_args__ = (CheckConstraint("quantity_per_unit > 0", name="ck_portfolio_bom_positive"),
                      CheckConstraint("provenance = 'DEMO_ONLY'", name="ck_portfolio_bom_demo_only"))


class PortfolioDemoFinancialRecord(Base):
    __tablename__ = "portfolio_demo_financials"
    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    sku: Mapped[str] = mapped_column(String(128), primary_key=True)
    unit_revenue: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit_total_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="MYR")
    provenance: Mapped[str] = mapped_column(String(32), nullable=False, default="DEMO_ONLY")
    seed_key: Mapped[str] = mapped_column(String(64), nullable=False)
    __table_args__ = (CheckConstraint("unit_revenue >= 0 AND unit_total_cost >= 0", name="ck_portfolio_financial_nonnegative"),
                      CheckConstraint("provenance = 'DEMO_ONLY'", name="ck_portfolio_financial_demo_only"))


class PortfolioDemoLotRecord(Base):
    __tablename__ = "portfolio_demo_lots"
    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    lot_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    resource_id: Mapped[str] = mapped_column(String(128), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    expires_on: Mapped[date] = mapped_column(Date, nullable=False)
    provenance: Mapped[str] = mapped_column(String(32), nullable=False, default="DEMO_ONLY")
    seed_key: Mapped[str] = mapped_column(String(64), nullable=False)
    __table_args__ = (UniqueConstraint("tenant_id", "lot_id", name="uq_portfolio_lot_tenant_id"),
                      CheckConstraint("quantity > 0", name="ck_portfolio_lot_positive"),
                      CheckConstraint("provenance = 'DEMO_ONLY'", name="ck_portfolio_lot_demo_only"))


class PortfolioDemoCapacityRecord(Base):
    __tablename__ = "portfolio_demo_capacity"
    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    capacity_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    horizon_start: Mapped[date] = mapped_column(Date, nullable=False)
    horizon_end: Mapped[date] = mapped_column(Date, nullable=False)
    max_units: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False, default="pcs")
    provenance: Mapped[str] = mapped_column(String(32), nullable=False, default="DEMO_ONLY")
    seed_key: Mapped[str] = mapped_column(String(64), nullable=False)
    __table_args__ = (CheckConstraint("horizon_end >= horizon_start", name="ck_portfolio_capacity_dates"),
                      CheckConstraint("max_units > 0", name="ck_portfolio_capacity_positive"),
                      CheckConstraint("provenance = 'DEMO_ONLY'", name="ck_portfolio_capacity_demo_only"))
