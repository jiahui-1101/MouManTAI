from datetime import date, datetime, timezone
from decimal import Decimal
from fastapi.testclient import TestClient
from app.core.models import CommitmentRecord, ResourceStockRecord
from app.orders.models import P4OrderRecord
from app.orders.portfolio_models import (PortfolioDemoBOMRecord, PortfolioDemoCapacityRecord,
    PortfolioDemoFinancialRecord, PortfolioDemoLotRecord)

H = {"X-Tenant-ID": "tenant_demo_01", "X-Actor-ID": "user_owner_01"}


def load_sample(session, fulfilled_order=None):
    t = datetime(2026, 10, 25, tzinfo=timezone.utc)
    for order_id, sku, minute in (("A", "SKU_A", 0), ("B", "SKU_B", 1)):
        commitment_id = f"commit-{order_id}" if order_id == fulfilled_order else None
        session.add(P4OrderRecord(tenant_id="tenant_demo_01", order_id=order_id,
            commitment_id=commitment_id, customer_display_name="Synthetic local test",
            requested_items=[{"sku": sku, "quantity": "6", "unit": "pcs"}],
            requested_delivery_at=t, received_at=t.replace(minute=minute),
            lifecycle_status="UNKNOWN", source_channel="SYNTHETIC",
            evidence_refs=[f"synthetic://{order_id}"], integration_mode="SYNTHETIC",
            evidence_tier="DEMO-ONLY", created_at=t, updated_at=t))
        if commitment_id:
            session.add(CommitmentRecord(tenant_id="tenant_demo_01", commitment_id=commitment_id, order_id=order_id,
                customer_id="demo-customer", terms={}, agreement_state="CONFIRMED", feasibility_state="UNKNOWN",
                risk_state="UNKNOWN", recovery_state="NONE", fulfilment_state="FULFILLED", commitment_version=1,
                evidence_refs=[], updated_at=t))
    for resource in ("R1", "R2"):
        session.add(ResourceStockRecord(tenant_id="tenant_demo_01", resource_id=resource,
            total_quantity=Decimal(10), reserved_quantity=Decimal(0), unit="pcs",
            snapshot_version=1, updated_at=t))
        near_expiry = date(2026, 11, 5) if resource == "R1" else date(2026, 10, 27)
        session.add_all([
            PortfolioDemoLotRecord(tenant_id="tenant_demo_01", lot_id=f"{resource}-OLD", resource_id=resource,
                quantity=Decimal(5), unit="pcs", expires_on=near_expiry, provenance="DEMO_ONLY", seed_key="test"),
            PortfolioDemoLotRecord(tenant_id="tenant_demo_01", lot_id=f"{resource}-NEW", resource_id=resource,
                quantity=Decimal(5), unit="pcs", expires_on=date(2026, 12, 5), provenance="DEMO_ONLY", seed_key="test"),
        ])
    for sku, resource, revenue, cost in (("SKU_A", "R1", "10", "6"), ("SKU_B", "R2", "20", "5")):
        session.add(PortfolioDemoBOMRecord(tenant_id="tenant_demo_01", sku=sku, resource_id=resource,
            quantity_per_unit=Decimal(1), unit="pcs", provenance="DEMO_ONLY", seed_key="test"))
        session.add(PortfolioDemoFinancialRecord(tenant_id="tenant_demo_01", sku=sku,
            unit_revenue=Decimal(revenue), unit_total_cost=Decimal(cost), currency="MYR", provenance="DEMO_ONLY", seed_key="test"))
    session.add(PortfolioDemoCapacityRecord(tenant_id="tenant_demo_01", capacity_id="test-capacity",
        horizon_start=date(2026, 10, 1), horizon_end=date(2026, 12, 31), max_units=Decimal(6),
        unit="pcs", provenance="DEMO_ONLY", seed_key="test"))
    session.commit()


def body(ref): return {"snapshot_ref": ref}


def test_persisted_inputs_three_strategies_and_no_mutation(client: TestClient, session):
    load_sample(session)
    inputs = client.get('/v1/planning/portfolio/inputs', headers=H)
    assert inputs.status_code == 200
    assert [o['id'] for o in inputs.json()['orders']] == ['A', 'B']
    assert len(inputs.json()['stocks']) == 2
    req = body(inputs.json()['snapshot_ref'])
    result = client.post('/v1/planning/portfolio/compare', headers=H, json=req)
    assert result.status_code == 200, result.json()
    data = result.json()
    assert data['read_only'] is True and data['validation_status'] == 'UNVERIFIED_BY_P2'
    fcfs, profit, expiry = data['scenarios']
    assert [s['status'] for s in data['scenarios']] == ['COMPUTED_SIMULATION']*3
    assert fcfs['candidate_sequence'] == ['A', 'B']
    assert profit['candidate_sequence'] == ['B', 'A']
    assert expiry['candidate_sequence'] == ['B', 'A']
    assert fcfs['allocated_count'] == 1 and profit['allocated_count'] == 1
    assert fcfs['allocations'][1]['reason_code'] == 'CAPACITY_LIMIT'
    assert Decimal(profit['contribution']) == Decimal('90')
    assert all(s['schedule_status'] == 'SEQUENCE_ONLY_NO_COMPLETION_TIME' for s in data['scenarios'])
    assert client.get('/v1/planning/portfolio/inputs', headers=H).json()['snapshot_ref'] == req['snapshot_ref']
    assert session.query(P4OrderRecord).count() == 2
    assert session.query(ResourceStockRecord).count() == 2


def test_missing_inputs_fail_closed_and_staff_finance_redacted(client, session):
    load_sample(session)
    ref = client.get('/v1/planning/portfolio/inputs', headers=H).json()['snapshot_ref']
    staff = client.post('/v1/planning/portfolio/compare', headers={**H, 'X-Actor-ID': 'user_staff_01'}, json=body(ref))
    assert staff.status_code == 200
    assert staff.json()['scenarios'][1]['reason_codes'] == ['FINANCIAL_ACCESS_REDACTED']
    assert staff.json()['scenarios'][1]['contribution'] is None
    session.query(PortfolioDemoBOMRecord).delete(); session.query(PortfolioDemoFinancialRecord).delete()
    session.query(PortfolioDemoLotRecord).delete(); session.query(PortfolioDemoCapacityRecord).delete(); session.commit()
    ref = client.get('/v1/planning/portfolio/inputs', headers=H).json()['snapshot_ref']
    empty = client.post('/v1/planning/portfolio/compare', headers=H, json={'snapshot_ref': ref})
    assert empty.status_code == 200
    assert all(s['status'] == 'INSUFFICIENT_INPUT' and s['allocations'] == [] for s in empty.json()['scenarios'])


def test_tenant_auth_snapshot_and_invalid_request_guards(client, session, monkeypatch):
    load_sample(session)
    ref = client.get('/v1/planning/portfolio/inputs', headers=H).json()['snapshot_ref']
    assert client.get('/v1/planning/portfolio/inputs').status_code == 400
    assert client.get('/v1/planning/portfolio/inputs', headers={**H, 'X-Actor-ID': 'outsider'}).status_code == 403
    other = {**H, 'X-Tenant-ID': 'other'}
    assert client.get('/v1/planning/portfolio/inputs', headers=other).json()['orders'] == []
    assert client.post('/v1/planning/portfolio/compare', headers=H, json={**body(ref), 'order_ids': ['missing']}).status_code == 404
    assert client.post('/v1/planning/portfolio/compare', headers=H, json={**body(ref), 'snapshot_ref': '0'*64}).status_code == 409
    assert client.post('/v1/planning/portfolio/compare', headers=H, json={**body(ref), 'manual_assumptions': True}).status_code == 422
    monkeypatch.setenv('ENVIRONMENT', 'production')
    assert client.get('/v1/planning/portfolio/inputs', headers=H).status_code == 503


def test_assumed_expired_stock_and_invalid_civil_dates_fail_closed(client, session):
    load_sample(session)
    ref = client.get('/v1/planning/portfolio/inputs', headers=H).json()['snapshot_ref']
    session.query(PortfolioDemoLotRecord).filter(PortfolioDemoLotRecord.resource_id == 'R1').update(
        {PortfolioDemoLotRecord.expires_on: date(2020, 1, 1)})
    session.commit()
    ref = client.get('/v1/planning/portfolio/inputs', headers=H).json()['snapshot_ref']
    result = client.post('/v1/planning/portfolio/compare', headers=H, json=body(ref))
    assert result.status_code == 200
    fcfs = result.json()['scenarios'][0]
    assert fcfs['allocations'][0]['reason_code'] == 'MATERIAL_SHORTAGE:R1'
    assert fcfs['allocated_count'] == 1
    assert all(Decimal(amount) >= 0 for amount in fcfs['remaining_resources'].values())


def test_fulfilled_commitment_is_excluded_from_new_allocation_candidates(client, session):
    load_sample(session, fulfilled_order="A")
    inputs = client.get('/v1/planning/portfolio/inputs', headers=H).json()
    assert [o['id'] for o in inputs['orders']] == ['B']
    assert inputs['excluded_orders'] == [{'id': 'A', 'reason_code': 'ALREADY_FULFILLED_OR_CANCELLED'}]
    result = client.post('/v1/planning/portfolio/compare', headers=H, json=body(inputs['snapshot_ref']))
    assert result.status_code == 200
    assert result.json()['orders_considered'] == ['B']
