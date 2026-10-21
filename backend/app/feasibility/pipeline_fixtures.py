"""Complete, explicit synthetic evidence for Phase 7A; never production authority.

Production assumptions reproduce Phase 4's complete-evidence test fixture:
one exclusive line, one minute/unit, 30 minute delivery lead, 07–17 continuous
shifts and an evidenced empty job ledger through 26 Oct. Historical material-only
fixtures remain unchanged and still evaluate UNKNOWN without these additions.
"""

from datetime import datetime, timedelta

from app.core.schemas import Commitment

from .api_schemas import SupplierDelayRequest
from .fixtures import build_supplier_delay_scenario, build_two_affected_scenario
from .impact import OperationalChange, OperationalChangeType, ResourceKey, ResourceKind
from .models import OperationalSnapshot
from .production import EvaluationSnapshot
from .supplier_pipeline import SupplierDelayInputs


def complete_production(snapshot: OperationalSnapshot) -> EvaluationSnapshot:
    data = snapshot.model_dump(exclude_computed_fields=True)
    zone = snapshot.captured_at.tzinfo
    days = sorted({line.material_use_at.date() for c in snapshot.confirmed_commitments for line in c.lines})
    for calendar in data['capacity_calendars']:
        calendar['resource_id'] = 'p7-line'
        calendar['windows'] = tuple(dict(
            start_at=datetime.combine(day, datetime.min.time()).replace(hour=7, tzinfo=zone),
            end_at=datetime.combine(day, datetime.min.time()).replace(hour=17, tzinfo=zone),
            available_minutes='600') for day in days)
    sources = tuple(dict(source_id='p7-' + kind, tenant_id=snapshot.tenant_id, kind=kind,
                         source_ref='synthetic://p2/phase7/' + kind, observed_at=snapshot.captured_at,
                         valid_through=datetime.fromisoformat('2026-10-26T00:00:00+08:00'),
                         evidence_refs=('synthetic-p7-' + kind,))
                    for kind in ('resources', 'processes', 'plans', 'jobs'))
    plans = tuple(dict(tenant_id=snapshot.tenant_id, commitment_id=c.commitment_id,
                       commitment_version=c.commitment_version, line_id=line.line_id,
                       start_at=line.material_use_at,
                       dispatch_cutoff_at=line.material_use_at.replace(hour=17, minute=0),
                       source_refs=('p7-plans',))
                  for c in snapshot.confirmed_commitments for line in c.lines)
    return EvaluationSnapshot.model_validate(dict(
        operational=data, as_of=snapshot.captured_at, current_snapshot_version=snapshot.snapshot_version,
        production=dict(tenant_id=snapshot.tenant_id, sources=sources,
                        resources=(dict(resource_id='p7-line', tenant_id=snapshot.tenant_id,
                                        source_refs=('p7-resources',)),),
                        processes=(dict(process_id='p7-burger', tenant_id=snapshot.tenant_id,
                                        sku_id='BURGER', unit='pcs', resource_ids=('p7-line',),
                                        minutes_per_unit='1', setup_minutes='0', delivery_lead_minutes='30',
                                        source_refs=('p7-processes',)),),
                        plans=plans, jobs=(), jobs_covered_from=snapshot.captured_at,
                        jobs_covered_through=datetime.fromisoformat('2026-10-26T00:00:00+08:00'))))


def synthetic_commitments(snapshot: OperationalSnapshot) -> tuple[Commitment, ...]:
    return tuple(Commitment.model_validate(dict(
        tenant_id=snapshot.tenant_id, commitment_id=c.commitment_id,
        order_id='synthetic-order-' + c.commitment_id, customer_id='synthetic-customer-' + c.commitment_id,
        terms=dict(sku=c.lines[0].sku_id, quantity=c.lines[0].quantity, unit=c.lines[0].unit,
                   deadline=c.delivery_deadline), agreement_state='CONFIRMED', feasibility_state='NOT_ASSESSED',
        risk_state='NORMAL', recovery_state='NONE', fulfilment_state='NOT_STARTED',
        commitment_version=c.commitment_version, evidence_refs=['synthetic-confirmation-' + c.commitment_id],
        updated_at=snapshot.captured_at)) for c in snapshot.confirmed_commitments)


def build_pipeline_example(*, two_affected: bool = False, mode: str = 'complete') -> SupplierDelayInputs:
    if mode not in {'complete', 'material_only', 'missing_supplier', 'stale_inventory',
                    'stale_production', 'confounded', 'preexisting'}:
        raise ValueError('unsupported synthetic mode')
    scenario = build_two_affected_scenario() if two_affected else build_supplier_delay_scenario()
    before_data = scenario.before.model_dump(exclude_computed_fields=True)
    after_data = scenario.after.model_dump(exclude_computed_fields=True)
    if two_affected:
        # The older material-only fixture intentionally has simultaneous use
        # times. This NEW complete fixture explicitly books the second order
        # after the first 100-minute job, still before the delayed 11:00 receipt.
        # Both baseline bookings are feasible; neither old fixture is rewritten.
        for data in (before_data, after_data):
            for commitment in data['confirmed_commitments']:
                if commitment['commitment_id'] == 'com-002':
                    commitment['lines'][0]['material_use_at'] = datetime.fromisoformat(
                        '2026-10-23T10:40:00+08:00')
    if mode == 'missing_supplier':
        # Known rows still have valid claims, but a required supplier-ledger
        # source is unavailable. Empty/missing ledger evidence is not completeness.
        for data in (before_data, after_data):
            data['sources'] += (dict(source_id='missing-supplier-ledger', tenant_id=data['tenant_id'],
                                    kind='incoming_deliveries', source_ref=None, observed_at=None,
                                    valid_through=None, evidence_refs=()),)
    if mode == 'stale_inventory':
        for source in after_data['sources']:
            if source['kind'] == 'inventory':
                source['valid_through'] = scenario.before.captured_at
    if mode in {'confounded', 'preexisting'}:
        for data in ((before_data, after_data) if mode == 'preexisting' else (after_data,)):
            for delivery in data['incoming_deliveries']:
                if delivery['delivery_id'] == scenario.changed_delivery_id:
                    # Both ETAs are after material use in the preexisting case.
                    delivery['expected_at'] += timedelta(days=2)
            for lot in data['inventory_lots']:
                if lot['sku_id'] == 'PATTY':
                    lot['quantity'] = '50'
        if mode == 'confounded':
            # The stock reduction is separately evidenced, outside supplier scope.
            for source in after_data['sources']:
                if source['kind'] == 'inventory':
                    source['observed_at'] = scenario.after.captured_at
                    source['evidence_refs'] += ('synthetic-independent-stock-change',)
    old_op, new_op = (OperationalSnapshot.model_validate(d) for d in (before_data, after_data))
    if mode == 'material_only':
        before, after = (EvaluationSnapshot(operational=op, as_of=op.captured_at,
                                           current_snapshot_version=op.snapshot_version) for op in (old_op, new_op))
    else:
        before, after = complete_production(old_op), complete_production(new_op)
    if mode == 'stale_production':
        data = after.model_dump(exclude_computed_fields=True)
        for source in data['production']['sources']:
            source['valid_through'] = old_op.captured_at
            source['observed_at'] = old_op.captured_at
        after = EvaluationSnapshot.model_validate(data)
    old = next(d for d in old_op.incoming_deliveries if d.delivery_id == scenario.changed_delivery_id)
    new = next(d for d in new_op.incoming_deliveries if d.delivery_id == scenario.changed_delivery_id)
    claim = next(e for s in new_op.sources for e in s.supplier_delivery_evidence
                 if e.evidence_id in new.eta_change_evidence_ids)
    change = OperationalChange(event_id='synthetic-eta-' + scenario.scenario_id + '-' + mode,
                               tenant_id=new_op.tenant_id, correlation_id='synthetic-p7-' + mode,
                               event_type=OperationalChangeType.SUPPLIER_DELIVERY_CHANGED,
                               occurred_at=new_op.captured_at, before_snapshot_version=old_op.snapshot_version,
                               after_snapshot_version=new_op.snapshot_version,
                               resource_keys=(ResourceKey(kind=ResourceKind.SUPPLIER_DELIVERY,
                                                          resource_id=new.delivery_id),),
                               evidence_refs=(claim.evidence_ref,))
    return SupplierDelayInputs(request=SupplierDelayRequest(change=change, source_evidence=claim),
                               before_snapshot_id=before.operational.snapshot_id,
                               after_snapshot_id=after.operational.snapshot_id,
                               previous_eta=old.expected_at, updated_eta=new.expected_at,
                               before=before, after=after,
                               before_commitments=synthetic_commitments(before.operational),
                               after_commitments=synthetic_commitments(after.operational))
