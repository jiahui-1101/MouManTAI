"""Read-only, request-assumption planning simulation over persisted P4 orders and Core stock.

No P2 assessment, acceptance, reservation, lot authority or production schedule is inferred.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.errors import DomainError
from app.core.models import ResourceStockRecord
from app.orders.api import Context
from app.orders.models import P4OrderRecord

router = APIRouter(prefix="/v1/planning/portfolio", tags=["portfolio-planning-simulation"])
DB = Annotated[Session, Depends(get_db)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def _decimal_input(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d+(?:\.\d{1,4})?", value):
        raise ValueError("Use a non-negative decimal string with at most four places")
    return Decimal(value)


class MaterialRule(Strict):
    sku: str = Field(min_length=1, max_length=128)
    resource_id: str = Field(min_length=1, max_length=128)
    quantity_per_unit: Decimal = Field(gt=0, max_digits=18, decimal_places=4)

    @field_validator("quantity_per_unit", mode="before")
    @classmethod
    def exact_quantity(cls, value):
        return _decimal_input(value)


class FinancialRule(Strict):
    sku: str = Field(min_length=1, max_length=128)
    unit_revenue: Decimal = Field(ge=0, max_digits=18, decimal_places=4)
    unit_total_cost: Decimal = Field(ge=0, max_digits=18, decimal_places=4)
    currency: Literal["MYR"] = "MYR"

    @field_validator("unit_revenue", "unit_total_cost", mode="before")
    @classmethod
    def exact_amount(cls, value):
        return _decimal_input(value)


class ExpiryRule(Strict):
    resource_id: str = Field(min_length=1, max_length=128)
    assumed_whole_stock_expiry: date

    @field_validator("assumed_whole_stock_expiry", mode="before")
    @classmethod
    def civil_date(cls, value):
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("Use YYYY-MM-DD")
        return date.fromisoformat(value)


class CompareRequest(Strict):
    snapshot_ref: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")
    order_ids: list[str] = Field(default_factory=list, max_length=20)
    material_rules: list[MaterialRule] = Field(default_factory=list, max_length=100)
    financial_rules: list[FinancialRule] = Field(default_factory=list, max_length=20)
    expiry_rules: list[ExpiryRule] = Field(default_factory=list, max_length=100)
    max_total_units: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=4)
    treat_aggregate_stock_as_usable: bool = False
    assumptions_label: str = Field(default="Manual planning assumptions", min_length=1, max_length=100)

    @field_validator("max_total_units", mode="before")
    @classmethod
    def exact_capacity(cls, value):
        return None if value is None else _decimal_input(value)

    @model_validator(mode="after")
    def unique_inputs(self):
        for values, key in ((self.order_ids, lambda x: x),
                            (self.material_rules, lambda x: (x.sku, x.resource_id)),
                            (self.financial_rules, lambda x: x.sku),
                            (self.expiry_rules, lambda x: x.resource_id)):
            keys = [key(x) for x in values]
            if len(set(keys)) != len(keys):
                raise ValueError("Duplicate portfolio assumption key")
        return self


def _read_rows(db: Session, tenant: str):
    # This endpoint never writes even if an implementation later adds a helper.
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(text("SET TRANSACTION READ ONLY"))
    orders = db.scalars(select(P4OrderRecord).where(P4OrderRecord.tenant_id == tenant)
                        .order_by(P4OrderRecord.received_at, P4OrderRecord.order_id)).all()
    stocks = db.scalars(select(ResourceStockRecord).where(ResourceStockRecord.tenant_id == tenant)
                        .order_by(ResourceStockRecord.resource_id)).all()
    payload = {
        "orders": [(o.order_id, o.updated_at.isoformat(), o.received_at.isoformat(),
                    o.requested_delivery_at.isoformat(), o.requested_items, o.lifecycle_status)
                   for o in orders],
        "stocks": [(s.resource_id, str(s.total_quantity), str(s.reserved_quantity),
                    s.unit, s.snapshot_version, s.updated_at.isoformat()) for s in stocks],
    }
    ref = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return orders, stocks, ref


def _inputs(orders, stocks, ref):
    return {
        "snapshot_ref": ref,
        "source": "persisted://postgresql/p4_orders+resource_stocks",
        "integration_mode": "SYNTHETIC",
        "evidence_tier": "DEMO-ONLY",
        "orders": [{"id": o.order_id, "received_at": o.received_at.isoformat(),
                    "requested_delivery_at": o.requested_delivery_at.isoformat(),
                    "items": o.requested_items, "lifecycle_status": o.lifecycle_status,
                    "evidence_refs": o.evidence_refs} for o in orders],
        "stocks": [{"resource_id": s.resource_id, "unit": s.unit,
                    "total": str(s.total_quantity), "reserved": str(s.reserved_quantity),
                    "free": str(max(Decimal(0), s.total_quantity-s.reserved_quantity)),
                    "snapshot_version": s.snapshot_version} for s in stocks],
        "limitations": ["P4 lifecycle UNKNOWN is an unconfirmed request, not acceptance.",
                        "Aggregated Core stock is not lot-, quality-, or P2-verified.",
                        "No production timing, completed-on-time, or expiry waste can be inferred."],
    }


@router.get("/inputs")
def portfolio_inputs(context: Context, db: DB):
    orders, stocks, ref = _read_rows(db, context.tenant_id)
    return {"tenant_id": context.tenant_id, "actor_id": context.actor_id,
            **_inputs(orders, stocks, ref)}


def _run_strategy(strategy: str, orders, stocks, request: CompareRequest, actor_role: str):
    resources = {s.resource_id: max(Decimal(0), s.total_quantity-s.reserved_quantity) for s in stocks}
    material = {}
    for rule in request.material_rules:
        material.setdefault(rule.sku, []).append(rule)
    finance = {r.sku: r for r in request.financial_rules}
    expiry = {r.resource_id: r.assumed_whole_stock_expiry for r in request.expiry_rules}
    skus = {str(item["sku"]) for o in orders for item in o.requested_items}
    codes = []
    if not orders: codes.append("NO_ORDERS")
    if not request.treat_aggregate_stock_as_usable: codes.append("STOCK_USABILITY_NOT_ASSUMED")
    if request.max_total_units is None: codes.append("CAPACITY_ASSUMPTION_MISSING")
    if skus - material.keys() or any(r.resource_id not in resources for rows in material.values() for r in rows):
        codes.append("MATERIAL_MAPPING_INCOMPLETE")
    if strategy == "PROFIT" and (actor_role == "STAFF" or skus - finance.keys()):
        codes.append("FINANCIAL_INPUT_UNAVAILABLE" if actor_role != "STAFF" else "FINANCIAL_ACCESS_REDACTED")
    if strategy == "EXPIRY_AWARE" and (set(resources) & {r.resource_id for rows in material.values() for r in rows}) - expiry.keys():
        codes.append("EXPIRY_ASSUMPTION_INCOMPLETE")
    if codes:
        return {"strategy": strategy, "status": "INSUFFICIENT_INPUT", "reason_codes": codes,
                "allocations": [], "allocated_count": None, "allocation_rate": None,
                "units_allocated": None, "remaining_resources": None,
                "contribution": None, "candidate_sequence": [], "schedule_status": "UNAVAILABLE"}

    def demand(order):
        required = {}
        for item in order.requested_items:
            qty = Decimal(str(item["quantity"]))
            for rule in material[item["sku"]]:
                required[rule.resource_id] = required.get(rule.resource_id, Decimal(0)) + qty*rule.quantity_per_unit
        return required

    def order_profit(order):
        return sum((Decimal(str(item["quantity"])) *
                    (finance[item["sku"]].unit_revenue-finance[item["sku"]].unit_total_cost)
                    for item in order.requested_items), Decimal(0))

    if strategy == "PROFIT":
        ordered = sorted(orders, key=lambda o: (-order_profit(o), o.received_at, o.order_id))
    elif strategy == "EXPIRY_AWARE":
        ordered = sorted(orders, key=lambda o: (min(expiry[r] for r in demand(o)), o.received_at, o.order_id))
    else:
        ordered = sorted(orders, key=lambda o: (o.received_at, o.order_id))
    left = resources.copy()
    expired = {r for r, expiry_date in expiry.items() if expiry_date <= datetime.now(timezone.utc).date()}
    for resource_id in expired:
        left[resource_id] = Decimal(0)
    capacity_left = request.max_total_units
    allocations = []
    contribution = Decimal(0)
    units_allocated = Decimal(0)
    for o in ordered:
        qty = sum((Decimal(str(i["quantity"])) for i in o.requested_items), Decimal(0))
        needed = demand(o)
        shortage = sorted(r for r, amount in needed.items() if amount > left[r])
        reason = ("ASSUMED_LOT_EXPIRED" if any(r in expired for r in shortage) else "MATERIAL_SHORTAGE") if shortage else ("CAPACITY_LIMIT" if qty > capacity_left else None)
        if reason is None:
            for r, amount in needed.items(): left[r] -= amount
            capacity_left -= qty
            units_allocated += qty
            if strategy == "PROFIT": contribution += order_profit(o)
        allocations.append({"order_id": o.order_id, "membership": "INCLUDED" if reason is None else "EXCLUDED",
                            "reason_code": reason, "requested_delivery_at": o.requested_delivery_at.isoformat(),
                            "resource_usage": {r: str(v) for r, v in sorted(needed.items())} if reason is None else {},
                            "sequence": len(allocations)+1})
    included = sum(a["membership"] == "INCLUDED" for a in allocations)
    return {"strategy": strategy, "status": "COMPUTED_SIMULATION", "reason_codes": [],
            "allocations": allocations, "allocated_count": included,
            "allocation_rate": str(Decimal(included)/Decimal(len(orders))),
            "units_allocated": str(units_allocated),
            "remaining_resources": {r: str(v) for r, v in sorted(left.items())},
            "contribution": str(contribution) if strategy == "PROFIT" else None,
            "candidate_sequence": [a["order_id"] for a in allocations],
            "schedule_status": "SEQUENCE_ONLY_NO_COMPLETION_TIME"}


@router.post("/compare")
def compare_portfolio(request: CompareRequest, context: Context, db: DB):
    orders, stocks, ref = _read_rows(db, context.tenant_id)
    if request.snapshot_ref != ref:
        raise DomainError("PORTFOLIO_SNAPSHOT_STALE", "Portfolio inputs changed; refresh before comparison", status_code=409)
    ids = set(request.order_ids)
    if ids and len(ids) != len(request.order_ids):
        raise DomainError("INVALID_ORDER_SELECTION", "Duplicate order IDs", status_code=422)
    known = {o.order_id for o in orders}
    if not ids.issubset(known):
        raise DomainError("ORDER_NOT_FOUND", "Selected order unavailable in this tenant", status_code=404)
    selected = [o for o in orders if not ids or o.order_id in ids]
    if any(o.lifecycle_status != "UNKNOWN" or o.integration_mode != "SYNTHETIC" for o in selected):
        raise DomainError("ORDER_NOT_ELIGIBLE", "Only unconfirmed synthetic requests may enter this simulation", status_code=422)
    stock_ids = {s.resource_id for s in stocks}
    skus = {str(i["sku"]) for o in selected for i in o.requested_items}
    if any(r.sku not in skus or r.resource_id not in stock_ids for r in request.material_rules):
        raise DomainError("INVALID_MATERIAL_MAPPING", "Rule does not match selected orders and tenant resources", status_code=422)
    if any(r.sku not in skus for r in request.financial_rules) or any(r.resource_id not in stock_ids for r in request.expiry_rules):
        raise DomainError("INVALID_PLANNING_ASSUMPTION", "Assumption does not match selected inputs", status_code=422)
    return {"tenant_id": context.tenant_id, "actor_id": context.actor_id,
            "snapshot_ref": ref, "source": "persisted://postgresql/p4_orders+resource_stocks",
            "integration_mode": "SYNTHETIC", "evidence_tier": "DEMO-ONLY",
            "assumptions_provenance": "USER_ENTERED_NOT_PERSISTED", "assumptions_label": request.assumptions_label,
            "validation_status": "UNVERIFIED_BY_P2", "read_only": True,
            "coverage": "PARTIAL", "orders_considered": [o.order_id for o in selected],
            "stock_source_versions": {s.resource_id: s.snapshot_version for s in stocks},
            "scenarios": [_run_strategy(s, selected, stocks, request, context.actor_role)
                          for s in ("FCFS", "PROFIT", "EXPIRY_AWARE")],
            "limitations": ["Advisory simulation only; material ratios, aggregate usability, capacity, financial values and expiry are manual assumptions.",
                            "One Core stock row is treated as one assumed expiring lot only when expiry is provided.",
                            "No P2 joint verifier or fixed accepted workload; no completion date or on-time guarantee.",
                            "No acceptance, reservation, supplier/customer message or production schedule is written."]}


# Keep the established module entry point while using its PostgreSQL-backed seeded planner.
from app.orders.portfolio_auto import router as _automatic_portfolio_router
router = _automatic_portfolio_router
