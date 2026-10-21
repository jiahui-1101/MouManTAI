"""Explicit synthetic production evidence, separate from the shared demo.

These parameter values are test data, never inferred operational facts or a
P5-approved fixture. Existing P2 regression fixtures remain unchanged.
"""

from datetime import datetime

from app.core.schemas import Commitment

from .fixtures import build_supplier_delay_scenario
from .production import EvaluationSnapshot


def build_production_example() -> tuple[EvaluationSnapshot, Commitment]:
    data = build_supplier_delay_scenario().before.model_dump(exclude_computed_fields=True)
    data['confirmed_commitments'] = data['confirmed_commitments'][:1]
    data['reservations'] = ()
    data['incoming_deliveries'] = ()
    data['inventory_lots'][0]['quantity'] = '100'
    for source in data['sources']:
        source['supplier_delivery_evidence'] = ()
    # Explicit continuous shifts; the older 480-minute daily total did not
    # locate breaks and is intentionally insufficient for interval scheduling.
    for calendar in data['capacity_calendars']:
        for window in calendar['windows']:
            window['available_minutes'] = '600'
    tenant = data['tenant_id']
    sources = tuple(dict(
        source_id='production-' + kind, tenant_id=tenant, kind=kind,
        source_ref='synthetic://p2/phase3/' + kind, observed_at=data['captured_at'],
        valid_through=datetime.fromisoformat('2026-10-26T00:00:00+08:00'),
        evidence_refs=(ref,),
    ) for kind, ref in (
        ('resources', 'synthetic-exclusive-line-v1'),
        ('processes', 'synthetic-production-rate-v1'),
        ('jobs', 'synthetic-complete-job-ledger-v1'),
        ('plans', 'synthetic-fixed-booking-and-dispatch-v1'),
    ))
    commitment = Commitment.model_validate(dict(
        tenant_id=tenant, commitment_id='com-001', order_id='synthetic-order-001',
        customer_id='synthetic-customer-001', terms=dict(sku='BURGER', quantity='100', unit='pcs',
            deadline=data['confirmed_commitments'][0]['delivery_deadline']),
        agreement_state='CONFIRMED', feasibility_state='NOT_ASSESSED', risk_state='NORMAL',
        recovery_state='NONE', fulfilment_state='NOT_STARTED', commitment_version=1,
        evidence_refs=['synthetic-confirmation-001'], updated_at=data['captured_at'],
    ))
    snapshot = EvaluationSnapshot.model_validate(dict(
        operational=data, as_of=data['captured_at'], current_snapshot_version=1,
        production=dict(tenant_id=tenant, sources=sources,
            resources=(dict(resource_id='kitchen-line-1', tenant_id=tenant, source_refs=('production-resources',)),),
            processes=(dict(process_id='burger-process', tenant_id=tenant, sku_id='BURGER', unit='pcs',
                resource_ids=('kitchen-line-1',), minutes_per_unit='1', setup_minutes='0',
                delivery_lead_minutes='30', source_refs=('production-processes',)),),
            plans=(dict(tenant_id=tenant, commitment_id='com-001', commitment_version=1,
                line_id='com-001-line-1', start_at=datetime.fromisoformat('2026-10-23T09:00:00+08:00'),
                dispatch_cutoff_at=datetime.fromisoformat('2026-10-23T17:00:00+08:00'), source_refs=('production-plans',)),),
            jobs=(), jobs_covered_from=data['captured_at'],
            jobs_covered_through=datetime.fromisoformat('2026-10-26T00:00:00+08:00')),
    ))
    return snapshot, commitment
