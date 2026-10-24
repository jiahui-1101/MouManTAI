"""Idempotently add isolated DEMO_ONLY planning assumptions for tenant_demo_01.

The lot quantities partition existing resource_stocks; they add no inventory.
Rows are inserted only when all four assumption tables are empty for this tenant.
"""
from datetime import date
from decimal import Decimal
from sqlalchemy import select
from app.db.session import SessionLocal, engine
from app.core.models import ResourceStockRecord
from app.orders.models import P4OrderRecord
from app.orders.portfolio_models import (PortfolioDemoBOMRecord, PortfolioDemoCapacityRecord,
    PortfolioDemoFinancialRecord, PortfolioDemoLotRecord)

TENANT = "tenant_demo_01"
SEED_KEY = "portfolio_demo_seed_v1"
EXPECTED_SKUS = {"BURGER_CLASSIC", "BURGER_PREMIUM", "BURGER_DELUXE", "BURGER_VEGAN", "BURGER_COMBO"}

BOM = {
    "BURGER_CLASSIC": {"BUN": ("1", "pcs"), "BURGER": ("1", "pcs"), "GREENS": ("0.05", "kg"), "PATTY": ("0.5", "pcs")},
    "BURGER_PREMIUM": {"BUN": ("1", "pcs"), "BURGER": ("1", "pcs"), "GREENS": ("0.08", "kg"), "PATTY": ("1", "pcs")},
    "BURGER_DELUXE": {"BUN": ("1", "pcs"), "BURGER": ("1", "pcs"), "GREENS": ("0.10", "kg"), "PATTY": ("1.5", "pcs")},
    "BURGER_VEGAN": {"BUN": ("1", "pcs"), "BURGER": ("0.8", "pcs"), "GREENS": ("0.12", "kg")},
    "BURGER_COMBO": {"BUN": ("2", "pcs"), "BURGER": ("1.5", "pcs"), "GREENS": ("0.10", "kg"), "PATTY": ("1.2", "pcs")},
}
FINANCIAL = {
    "BURGER_CLASSIC": ("25.00", "14.00"), "BURGER_PREMIUM": ("45.00", "25.00"),
    "BURGER_DELUXE": ("38.00", "24.00"), "BURGER_VEGAN": ("32.00", "18.00"),
    "BURGER_COMBO": ("55.00", "34.00"),
}
LOTS = {
    "BUN": [("400", "pcs", "2026-12-15"), ("600", "pcs", "2027-01-15")],
    "BURGER": [("120", "pcs", "2026-12-15"), ("180", "pcs", "2027-01-15")],
    "GREENS": [("10", "kg", "2026-10-26"), ("190", "kg", "2026-12-15")],
    "PATTY": [("200", "pcs", "2026-12-15"), ("300", "pcs", "2027-01-15")],
}


def run() -> None:
    url = engine.url
    if url.host not in {"localhost", "127.0.0.1"} or url.port != 5433 or url.database != "moumantai":
        raise SystemExit("Refusing seed: configured DB is not local 127.0.0.1:5433/moumantai")
    with SessionLocal.begin() as db:
        orders = db.scalars(select(P4OrderRecord).where(P4OrderRecord.tenant_id == TENANT)).all()
        actual_skus = {str(item["sku"]) for order in orders for item in order.requested_items}
        if actual_skus != EXPECTED_SKUS:
            raise SystemExit(f"Refusing seed: expected five known demo SKUs; found {sorted(actual_skus)}")
        stock = {r.resource_id: r for r in db.scalars(select(ResourceStockRecord).where(ResourceStockRecord.tenant_id == TENANT)).all()}
        if set(stock) != set(LOTS):
            raise SystemExit("Refusing seed: the tenant resource set does not match the verified demo stock")
        for resource, batches in LOTS.items():
            total = sum((Decimal(qty) for qty, _, _ in batches), Decimal(0))
            if total != stock[resource].total_quantity or any(unit != stock[resource].unit for _, unit, _ in batches):
                raise SystemExit(f"Refusing seed: lot partition does not reconcile with {resource} stock")
        models = (PortfolioDemoBOMRecord, PortfolioDemoFinancialRecord, PortfolioDemoLotRecord, PortfolioDemoCapacityRecord)
        existing = [db.scalars(select(model).where(model.tenant_id == TENANT)).all() for model in models]
        if all(existing):
            if any(any(row.seed_key != SEED_KEY for row in rows) for rows in existing):
                raise SystemExit("Refusing seed: tenant planning rows have a different provenance")
            expected = (sum(map(len, BOM.values())), len(FINANCIAL), sum(map(len, LOTS.values())), 1)
            if tuple(map(len, existing)) != expected:
                raise SystemExit("Refusing seed: existing portfolio planning rows are incomplete; no rows changed")
            # Reconcile only this script's own DEMO_ONLY rows to its versioned values.
            for row in existing[0]:
                quantity, unit = BOM[row.sku][row.resource_id]
                row.quantity_per_unit, row.unit = Decimal(quantity), unit
            for row in existing[1]:
                row.unit_revenue, row.unit_total_cost = map(Decimal, FINANCIAL[row.sku])
                row.currency = "MYR"
            for row in existing[2]:
                resource = row.resource_id
                batches = LOTS[resource]
                index = int(row.lot_id.rsplit("-", 1)[-1]) - 1
                quantity, unit, expiry = batches[index]
                row.quantity, row.unit, row.expires_on = Decimal(quantity), unit, date.fromisoformat(expiry)
            existing[3][0].horizon_start = date(2026, 10, 23)
            existing[3][0].horizon_end = date(2026, 11, 30)
            existing[3][0].max_units = Decimal("300")
            print("Reconciled only this seed's DEMO_ONLY rows; authoritative orders, commitments, and stocks were untouched.")
            return
            return
        if any(existing):
            raise SystemExit("Refusing seed: partial seed detected; no rows changed")
        db.add_all([PortfolioDemoBOMRecord(tenant_id=TENANT, sku=sku, resource_id=resource,
            quantity_per_unit=Decimal(qty), unit=unit, provenance="DEMO_ONLY", seed_key=SEED_KEY)
            for sku, rules in BOM.items() for resource, (qty, unit) in rules.items()])
        db.add_all([PortfolioDemoFinancialRecord(tenant_id=TENANT, sku=sku, unit_revenue=Decimal(price),
            unit_total_cost=Decimal(cost), currency="MYR", provenance="DEMO_ONLY", seed_key=SEED_KEY)
            for sku, (price, cost) in FINANCIAL.items()])
        db.add_all([PortfolioDemoLotRecord(tenant_id=TENANT, lot_id=f"demo-{resource.lower()}-{index}",
            resource_id=resource, quantity=Decimal(quantity), unit=unit, expires_on=date.fromisoformat(expiry),
            provenance="DEMO_ONLY", seed_key=SEED_KEY)
            for resource, batches in LOTS.items() for index, (quantity, unit, expiry) in enumerate(batches, 1)])
        db.add(PortfolioDemoCapacityRecord(tenant_id=TENANT, capacity_id="demo-horizon-2026-10",
            horizon_start=date(2026, 10, 23), horizon_end=date(2026, 11, 30), max_units=Decimal("300"),
            unit="pcs", provenance="DEMO_ONLY", seed_key=SEED_KEY))
    print(f"Seeded tenant={TENANT} BOM={sum(map(len, BOM.values()))} financial={len(FINANCIAL)} lots={sum(map(len, LOTS.values()))} capacity=1 seed={SEED_KEY}")


if __name__ == "__main__":
    run()
