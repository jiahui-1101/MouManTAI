"""Automatic, read-only portfolio demo comparison over persisted demo inputs."""
from __future__ import annotations
from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
import os
from typing import Annotated
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from app.core.dependencies import get_db
from app.core.errors import DomainError
from app.core.models import CommitmentRecord, ResourceStockRecord
from app.orders.api import Context
from app.orders.models import P4OrderRecord
from app.orders.portfolio_models import (PortfolioDemoBOMRecord, PortfolioDemoCapacityRecord,
    PortfolioDemoFinancialRecord, PortfolioDemoLotRecord)

router = APIRouter(prefix="/v1/planning/portfolio", tags=["portfolio-planning-demo"])
DB = Annotated[Session, Depends(get_db)]

class CompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot_ref: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")
    order_ids: list[str] = Field(default_factory=list, max_length=20)

def _demo_only():
    if os.getenv("ENVIRONMENT", "").lower() in {"prod", "production"}:
        raise DomainError("PORTFOLIO_DEMO_DISABLED", "Demo planning comparison is disabled in production", status_code=503)

def _read(db: Session, tenant: str):
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(text("SET TRANSACTION READ ONLY"))
    all_orders = db.scalars(select(P4OrderRecord).where(P4OrderRecord.tenant_id == tenant)
        .order_by(P4OrderRecord.received_at, P4OrderRecord.order_id)).all()
    commits = db.scalars(select(CommitmentRecord).where(CommitmentRecord.tenant_id == tenant)).all()
    by_commit = {c.commitment_id: c for c in commits}
    excluded = []
    orders = []
    for order in all_orders:
        status = str(order.lifecycle_status).upper()
        commit = by_commit.get(order.commitment_id)
        fulfilment = str(commit.fulfilment_state).upper() if commit else ""
        agreement = str(commit.agreement_state).upper() if commit else ""
        if status in {"FULFILLED", "COMPLETED", "CANCELLED", "CANCELED"} or fulfilment in {"FULFILLED", "COMPLETED", "CANCELLED", "CANCELED"} or agreement in {"CANCELLED", "CANCELED"}:
            excluded.append({"id": order.order_id, "reason_code": "ALREADY_FULFILLED_OR_CANCELLED"})
        elif order.integration_mode != "SYNTHETIC" or order.evidence_tier != "DEMO-ONLY":
            excluded.append({"id": order.order_id, "reason_code": "NON_DEMO_ORDER"})
        else:
            orders.append(order)
    stocks = db.scalars(select(ResourceStockRecord).where(ResourceStockRecord.tenant_id == tenant).order_by(ResourceStockRecord.resource_id)).all()
    bom = db.scalars(select(PortfolioDemoBOMRecord).where(PortfolioDemoBOMRecord.tenant_id == tenant).order_by(PortfolioDemoBOMRecord.sku, PortfolioDemoBOMRecord.resource_id)).all()
    finance = db.scalars(select(PortfolioDemoFinancialRecord).where(PortfolioDemoFinancialRecord.tenant_id == tenant).order_by(PortfolioDemoFinancialRecord.sku)).all()
    lots = db.scalars(select(PortfolioDemoLotRecord).where(PortfolioDemoLotRecord.tenant_id == tenant).order_by(PortfolioDemoLotRecord.resource_id, PortfolioDemoLotRecord.expires_on, PortfolioDemoLotRecord.lot_id)).all()
    capacities = db.scalars(select(PortfolioDemoCapacityRecord).where(PortfolioDemoCapacityRecord.tenant_id == tenant).order_by(PortfolioDemoCapacityRecord.horizon_start, PortfolioDemoCapacityRecord.capacity_id)).all()
    data = {"orders": [(o.order_id,o.updated_at.isoformat(),o.received_at.isoformat(),o.requested_delivery_at.isoformat(),o.requested_items,o.lifecycle_status,o.commitment_id) for o in all_orders],
        "stocks": [(s.resource_id,str(s.total_quantity),str(s.reserved_quantity),s.unit,s.snapshot_version,s.updated_at.isoformat()) for s in stocks],
        "bom": [(x.sku,x.resource_id,str(x.quantity_per_unit),x.unit,x.seed_key) for x in bom],
        "financial": [(x.sku,str(x.unit_revenue),str(x.unit_total_cost),x.currency,x.seed_key) for x in finance],
        "lots": [(x.lot_id,x.resource_id,str(x.quantity),x.unit,x.expires_on.isoformat(),x.seed_key) for x in lots],
        "capacity": [(x.capacity_id,x.horizon_start.isoformat(),x.horizon_end.isoformat(),str(x.max_units),x.unit,x.seed_key) for x in capacities]}
    ref = sha256(json.dumps(data,sort_keys=True,separators=(",",":" )).encode()).hexdigest()
    return all_orders, orders, excluded, stocks, bom, finance, lots, capacities, ref

def _inputs(context, data):
    all_orders, orders, excluded, stocks, bom, finance, lots, capacities, ref = data
    return {"tenant_id":context.tenant_id,"actor_id":context.actor_id,"snapshot_ref":ref,
        "source":"persisted://postgresql/p4_orders+resource_stocks+portfolio_demo_planning",
        "integration_mode":"SYNTHETIC","evidence_tier":"DEMO-ONLY",
        "orders":[{"id":o.order_id,"received_at":o.received_at.isoformat(),"requested_delivery_at":o.requested_delivery_at.isoformat(),"lifecycle_status":o.lifecycle_status,"items":o.requested_items,"evidence_refs":o.evidence_refs} for o in orders],
        "excluded_orders":excluded,"total_orders":len(all_orders),"eligible_orders":len(orders),
        "stocks":[{"resource_id":s.resource_id,"unit":s.unit,"total":str(s.total_quantity),"reserved":str(s.reserved_quantity),"free":str(max(Decimal(0),s.total_quantity-s.reserved_quantity)),"snapshot_version":s.snapshot_version} for s in stocks],
        "planning_data_available":bool(bom and finance and lots and capacities),
        "planning_horizon":({"from":capacities[0].horizon_start.isoformat(),"to":capacities[0].horizon_end.isoformat(),"max_units":str(capacities[0].max_units),"unit":capacities[0].unit,"provenance":"DEMO_ONLY"} if capacities else None),
        "limitations":["DEMO_ONLY planning inputs are synthetic and are not an approved BOM, price book, expiry record, or production capacity.","Results are advisory simulations; P2 does not validate this portfolio and no acceptance or reservation is created."]}

@router.get("/inputs")
def portfolio_inputs(context: Context, db: DB):
    _demo_only()
    return _inputs(context,_read(db,context.tenant_id))

def _comparison(data, role: str):
    all_orders, orders, excluded, stocks, bom_rows, finance_rows, lots_rows, capacities, ref = data
    resources={s.resource_id:s for s in stocks}; bom={}
    for r in bom_rows: bom.setdefault(r.sku,[]).append(r)
    finances={r.sku:r for r in finance_rows}
    lots_by_resource={}
    for lot in lots_rows: lots_by_resource.setdefault(lot.resource_id,[]).append(lot)
    capacity=capacities[0] if capacities else None
    skus={str(i['sku']) for o in orders for i in o.requested_items}
    missing=[]
    if not orders: missing.append("NO_ELIGIBLE_ORDERS")
    if skus-set(bom): missing.append("BOM_INCOMPLETE")
    if skus-set(finances): missing.append("FINANCIAL_INPUT_INCOMPLETE")
    if not capacity: missing.append("CAPACITY_UNAVAILABLE")
    if capacity and any(str(item.get("unit", "")).lower() != capacity.unit.lower() for order in orders for item in order.requested_items):
        missing.append("ORDER_CAPACITY_UNIT_MISMATCH")
    for sku in skus:
        for rule in bom.get(sku,[]):
            stock=resources.get(rule.resource_id)
            if not stock or stock.unit != rule.unit: missing.append("BOM_RESOURCE_MISMATCH")
    for resource, stock in resources.items():
        lots=lots_by_resource.get(resource,[])
        if sum((x.quantity for x in lots),Decimal(0)) != stock.total_quantity or any(x.unit != stock.unit for x in lots): missing.append("LOT_STOCK_RECONCILIATION_FAILED")
    if not lots_rows: missing.append("LOT_EXPIRY_INPUT_UNAVAILABLE")
    missing=list(dict.fromkeys(missing))
    if missing:
        return [{"strategy":s,"status":"INSUFFICIENT_INPUT","reason_codes":missing,"allocations":[],"allocated_count":None,"deferred_count":None,"allocation_rate":None,"units_allocated":None,"contribution":None,"resource_consumed":None,"remaining_resources":None,"capacity_used":None,"near_expiry_consumed":None,"candidate_sequence":[],"schedule_status":"UNAVAILABLE"} for s in ("FCFS","PROFIT","EXPIRY_AWARE")]
    today=date.today(); horizon=30
    def demand(o):
        needed={}
        for item in o.requested_items:
            for rule in bom[item['sku']]:
                needed[rule.resource_id]=needed.get(rule.resource_id,Decimal(0))+Decimal(str(item['quantity']))*rule.quantity_per_unit
        return needed
    def margin(o):
        return sum((Decimal(str(item['quantity']))*(finances[item['sku']].unit_revenue-finances[item['sku']].unit_total_cost) for item in o.requested_items),Decimal(0))
    def urgency(o):
        need=demand(o); use=Decimal(0); earliest=date.max
        for rid,qty in need.items():
            lots=lots_by_resource[rid]
            fresh=[l for l in lots if l.expires_on>=today]
            earliest=min(earliest,min((l.expires_on for l in fresh),default=date.max))
            near=sum((l.quantity for l in fresh if (l.expires_on-today).days<=horizon),Decimal(0))
            use+=min(qty,near)
        return (-use,earliest,o.received_at,o.order_id)
    def run(strategy):
        if strategy=="PROFIT" and role=="STAFF":
            return {"strategy":strategy,"status":"INSUFFICIENT_INPUT","reason_codes":["FINANCIAL_ACCESS_REDACTED"],"allocations":[],"allocated_count":None,"deferred_count":None,"allocation_rate":None,"units_allocated":None,"contribution":None,"resource_consumed":None,"remaining_resources":None,"capacity_used":None,"near_expiry_consumed":None,"candidate_sequence":[],"schedule_status":"UNAVAILABLE"}
        ordered=sorted(orders,key=(lambda o:(-margin(o),o.received_at,o.order_id)) if strategy=="PROFIT" else urgency if strategy=="EXPIRY_AWARE" else (lambda o:(o.received_at,o.order_id)))
        remaining={}
        for rid, resource_lots in lots_by_resource.items():
            valid=[l for l in resource_lots if l.expires_on>=today]
            reserved=resources[rid].reserved_quantity
            for lot in sorted(valid,key=lambda x:(x.expires_on,x.lot_id)):
                available=lot.quantity
                # Reservations are backed out of the latest lots first to retain FEFO stock.
                latest_reserved=min(reserved,available); reserved-=latest_reserved
                remaining[lot.lot_id]=available-latest_reserved
        start_remaining=dict(remaining); cap_left=capacity.max_units; allocations=[]; consumed={}; near_used={}; total_units=Decimal(0); total_margin=Decimal(0)
        def consume(order, needed, commit=False):
            trial={}; expired_short=[]
            for rid,qty in needed.items():
                left=qty
                candidates=sorted(lots_by_resource[rid],key=lambda x:(x.expires_on,x.lot_id))
                for lot in candidates:
                    available=remaining.get(lot.lot_id,Decimal(0))
                    take=min(left,available)
                    if take:
                        trial[lot.lot_id]=take; left-=take
                    if left<=0: break
                if left>0:
                    expired_total=sum((l.quantity for l in candidates if l.expires_on<today),Decimal(0))
                    expired_short.append(rid if expired_total else rid)
                    return None,expired_short
            if commit:
                for lot_id,qty in trial.items():
                    remaining[lot_id]-=qty
                    lot=next(x for x in lots_rows if x.lot_id==lot_id)
                    consumed[lot.resource_id]=consumed.get(lot.resource_id,Decimal(0))+qty
                    if (lot.expires_on-today).days<=horizon: near_used[lot.resource_id]=near_used.get(lot.resource_id,Decimal(0))+qty
            return trial,[]
        for order in ordered:
            qty=sum((Decimal(str(i['quantity'])) for i in order.requested_items),Decimal(0)); need=demand(order)
            trial,short=consume(order,need)
            reason=None
            if short: reason="MATERIAL_SHORTAGE:"+",".join(short)
            elif qty>cap_left: reason="CAPACITY_LIMIT"
            else:
                consume(order,need,True); cap_left-=qty; total_units+=qty
                if role!="STAFF": total_margin+=margin(order)
            allocations.append({"order_id":order.order_id,"customer_display_name":order.customer_display_name,
                "items":order.requested_items,"membership":"ALLOCATE" if reason is None else "DEFER",
                "reason_code":reason or "WITHIN_DEMO_RESOURCE_AND_CAPACITY_LIMITS",
                "requested_delivery_at":order.requested_delivery_at.isoformat(),"resource_usage":{k:str(v) for k,v in sorted(need.items())} if reason is None else {},"sequence":len(allocations)+1})
        allocated=sum(a['membership']=='ALLOCATE' for a in allocations)
        remaining_resource={rid:str(sum((remaining.get(l.lot_id,Decimal(0)) for l in lots),Decimal(0))) for rid,lots in lots_by_resource.items()}
        used_capacity=capacity.max_units-cap_left
        return {"strategy":strategy,"status":"COMPUTED_SIMULATION","reason_codes":[],"allocations":allocations,
            "allocated_count":allocated,"deferred_count":len(orders)-allocated,"allocation_rate":str(Decimal(allocated)/Decimal(len(orders))),
            "units_allocated":str(total_units),"contribution":None if role=="STAFF" else str(total_margin),
            "resource_consumed":{k:str(v) for k,v in sorted(consumed.items())},"remaining_resources":remaining_resource,
            "capacity_used":str(used_capacity),"capacity_total":str(capacity.max_units),"near_expiry_consumed":{k:str(v) for k,v in sorted(near_used.items())},
            "candidate_sequence":[a['order_id'] for a in allocations],"schedule_status":"SEQUENCE_ONLY_NO_COMPLETION_TIME"}
    return [run(s) for s in ("FCFS","PROFIT","EXPIRY_AWARE")]

@router.post("/compare")
def compare_portfolio(request: CompareRequest, context: Context, db: DB):
    _demo_only(); data=_read(db,context.tenant_id)
    if request.snapshot_ref!=data[-1]: raise DomainError("PORTFOLIO_SNAPSHOT_STALE","Portfolio inputs changed; refresh before comparison",status_code=409)
    known={o.order_id for o in data[1]}; ids=request.order_ids
    if len(set(ids))!=len(ids): raise DomainError("INVALID_ORDER_SELECTION","Duplicate order IDs",status_code=422)
    if not set(ids).issubset(known): raise DomainError("ORDER_NOT_FOUND","Selected order unavailable in this tenant",status_code=404)
    if ids:
        selected=set(ids); filtered=tuple([[o for o in data[0] if o.order_id in selected],[o for o in data[1] if o.order_id in selected],*data[2:]])
        data=filtered
    return {"tenant_id":context.tenant_id,"actor_id":context.actor_id,"snapshot_ref":data[-1],
        "source":"persisted://postgresql/p4_orders+resource_stocks+portfolio_demo_planning","integration_mode":"SYNTHETIC","evidence_tier":"DEMO-ONLY",
        "assumptions_provenance":"SEEDED_DEMO_ONLY","validation_status":"UNVERIFIED_BY_P2","read_only":True,
        "orders_considered":[o.order_id for o in data[1]],"excluded_orders":data[2],"scenarios":_comparison(data,context.actor_role),
        "limitations":["Demo-only BOM, financial, lot expiry and capacity rows are illustrative synthetic assumptions.","Expiry-aware ranks demand consuming materials with stock lots expiring within 30 days, then FEFO consumes the earliest-expiring lots.","No P2 joint verifier or accepted workload; candidate sequence is not a production schedule and has no completion-time or on-time guarantee.","No acceptance, reservation, inventory update, supplier/customer message or production plan is persisted."]}
