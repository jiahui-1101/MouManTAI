"""P2-owned historical calculation boundary; no source writes or publication.

The caller resolves trusted immutable source snapshots. Typed evidence linkage
is validated here, but authenticity and transactional currentness belong to the
source provider/P5. This function is also usable with labelled synthetic data.
"""

from datetime import datetime

from app.core.schemas import Commitment

from .api_schemas import SupplierDelayRequest
from .impact import ImpactAssessment, assess_impact
from .models import FrozenModel
from .production import EvaluationSnapshot


class SupplierDelayInputs(FrozenModel):
    request: SupplierDelayRequest
    before_snapshot_id: str
    after_snapshot_id: str
    previous_eta: datetime
    updated_eta: datetime
    before: EvaluationSnapshot
    after: EvaluationSnapshot
    before_commitments: tuple[Commitment, ...]
    after_commitments: tuple[Commitment, ...]


def recalculate_supplier_delay(inputs: SupplierDelayInputs, *, tenant_id: str) -> ImpactAssessment:
    """Validate one delivery change, then use the single existing impact engine.

    Replays produce the same IDs/intents. No intents are delivered here; a
    transactional consumer must deduplicate them before producing side effects.
    """
    inputs = SupplierDelayInputs.model_validate(inputs.model_dump(exclude_computed_fields=True))
    change = inputs.request.change
    before, after = inputs.before.operational, inputs.after.operational
    if any(t != tenant_id for t in (change.tenant_id, before.tenant_id, after.tenant_id)):
        raise ValueError('supplier pipeline tenant mismatch')
    if (before.snapshot_id, after.snapshot_id) != (inputs.before_snapshot_id, inputs.after_snapshot_id):
        raise ValueError('supplier pipeline snapshot identity mismatch')
    if before.snapshot_id == after.snapshot_id:
        raise ValueError('before and after snapshot identities must differ')
    delivery_id = change.resource_keys[0].resource_id
    old = next((d for d in before.incoming_deliveries if d.delivery_id == delivery_id), None)
    new = next((d for d in after.incoming_deliveries if d.delivery_id == delivery_id), None)
    if old is None or new is None:
        raise ValueError('supplier delivery missing from before/after snapshot')
    # ETA-only notification must not smuggle a different supplier, SKU or supply.
    binding = ('tenant_id', 'delivery_id', 'supplier_id', 'sku_id', 'quantity', 'unit',
               'warehouse_id', 'confirmation_status', 'confirmed_at', 'confirmation_evidence_id')
    if any(getattr(old, field) != getattr(new, field) for field in binding):
        raise ValueError('supplier delivery resource identity/supply binding changed')
    if (old.expected_at, new.expected_at) != (inputs.previous_eta, inputs.updated_eta):
        raise ValueError('supplier ETA does not match source rows')
    if inputs.updated_eta <= inputs.previous_eta:
        raise ValueError('supplier delay must move ETA later')
    evidence = inputs.request.source_evidence
    linked = [claim for source in after.sources if source.source_id in new.source_refs
              for claim in source.supplier_delivery_evidence
              if claim.evidence_id in new.eta_change_evidence_ids]
    if evidence not in linked or evidence.supplier_id != new.supplier_id:
        raise ValueError('supplier evidence must exactly match a linked source claim')
    return assess_impact(inputs.before, inputs.after, change,
                         before_commitments=inputs.before_commitments,
                         after_commitments=inputs.after_commitments)
