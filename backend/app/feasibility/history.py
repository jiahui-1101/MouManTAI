"""P2 history domain and canonical mapping; reference storage is synthetic only.

No implementation here is registered with the public router. P5 must implement
the repository inside its approved durable Core/audit/outbox transaction.
"""

from threading import RLock
from typing import Literal, Protocol

from pydantic import model_validator

from app.core.schemas import Commitment, FeasibilityAssessment

from .impact import ImpactAssessment, ImpactEventIntent, impact_input_digest
from .models import FrozenModel
from .production import EvaluationSnapshot, ProposedChanges
from .service import EvaluationResult, evaluation_identity
from .supplier_pipeline import SupplierDelayInputs


def to_core_assessment(result: EvaluationResult, *, impact: ImpactAssessment | None = None) -> FeasibilityAssessment:
    """Map without inferring actual affected IDs from the assessment's scope.

    Supplying impact requires the exact after-result for this commitment, not a
    similarly versioned result from a different calculation or hypothetical plan.
    """
    result = EvaluationResult.model_validate(result.model_dump(exclude_computed_fields=True))
    affected = []
    if impact is not None:
        impact = ImpactAssessment.model_validate(impact.model_dump(exclude_computed_fields=True))
        row = next((row for row in impact.impacts if row.commitment_id == result.commitment_id), None)
        if (impact.tenant_id != result.tenant_id or impact.after_snapshot_id != result.snapshot_id
                or impact.after_snapshot_version != result.snapshot_version
                or row is None or row.after_assessment != result):
            raise ValueError('assessment/impact binding mismatch')
        affected = list(impact.confirmed_impacted_commitment_ids)
    fields = ('assessment_id', 'tenant_id', 'commitment_id', 'commitment_version', 'snapshot_version',
              'status', 'constraints', 'evidence_refs', 'solver_status', 'assumptions', 'assessed_at')
    data = result.model_dump(include=set(fields))
    return FeasibilityAssessment.model_validate({**data, 'affected_commitment_ids': affected})


class AssessmentRecord(FrozenModel):
    snapshot: EvaluationSnapshot
    commitment: Commitment
    result: EvaluationResult
    proposed_changes: ProposedChanges | None = None
    currentness: Literal['HISTORICAL_UNVERIFIED'] = 'HISTORICAL_UNVERIFIED'

    @model_validator(mode='after')
    def bindings(self):
        op, c, r = self.snapshot.operational, self.commitment, self.result
        if (r.tenant_id, r.commitment_id, r.commitment_version, r.snapshot_id, r.snapshot_version, r.assessed_at) != (
                c.tenant_id, c.commitment_id, c.commitment_version, op.snapshot_id, op.snapshot_version, self.snapshot.as_of
        ) or c.tenant_id != op.tenant_id:
            raise ValueError('history result/input binding mismatch')
        target = next((row for row in op.confirmed_commitments if row.commitment_id == c.commitment_id), None)
        if (target is None or target.commitment_version != c.commitment_version or len(target.lines) != 1
                or (target.lines[0].sku_id, target.lines[0].quantity, target.lines[0].unit, target.delivery_deadline) != (
                    c.terms.sku, c.terms.quantity, c.terms.unit, c.terms.deadline)):
            raise ValueError('history Core/snapshot binding mismatch')
        p = self.proposed_changes
        if p is not None and (p.tenant_id, p.commitment_id, p.expected_commitment_version, p.expected_snapshot_version) != (
                c.tenant_id, c.commitment_id, c.commitment_version, op.snapshot_version):
            raise ValueError('history proposal binding mismatch')
        if r.assessment_id != evaluation_identity(self.snapshot, p, c):
            raise ValueError('history calculation content/proposal binding mismatch')
        return self


class HistoryRepository(Protocol):
    def append_assessment(self, record: AssessmentRecord) -> bool: ...
    def list_assessments(self, tenant_id: str, commitment_id: str) -> tuple[AssessmentRecord, ...]: ...
    def append_impact(self, inputs: SupplierDelayInputs, result: ImpactAssessment) -> tuple[ImpactEventIntent, ...]: ...
    def get_impact(self, tenant_id: str, impact_id: str) -> ImpactAssessment | None: ...


class SyntheticHistoryRepository:
    """Process-local reference semantics, no durability, auth or outbox delivery.

    Store serialized copies: frozen outer models alone do not freeze shared Core
    constraint/Commitment objects nested inside them. Reads return fresh objects.
    RLock only serializes this instance, not multiple processes or a database.
    """

    def __init__(self):
        self._assessments: dict[tuple[str, str], str] = {}
        self._impacts: dict[tuple[str, str], str] = {}
        self._causes: dict[tuple[str, str], tuple[str, str]] = {}
        self._lock = RLock()

    def append_assessment(self, record: AssessmentRecord) -> bool:
        record = AssessmentRecord.model_validate(record.model_dump(exclude_computed_fields=True))
        payload = record.model_dump_json(exclude_computed_fields=True)
        key = (record.result.tenant_id, record.result.assessment_id)
        with self._lock:
            previous = self._assessments.get(key)
            if previous is not None:
                if previous != payload:
                    raise ValueError('assessment identity payload conflict')
                return False
            self._assessments[key] = payload
            return True

    def list_assessments(self, tenant_id: str, commitment_id: str) -> tuple[AssessmentRecord, ...]:
        with self._lock:
            rows = [AssessmentRecord.model_validate_json(payload) for (tenant, _), payload in self._assessments.items()
                    if tenant == tenant_id]
        return tuple(sorted((r for r in rows if r.result.commitment_id == commitment_id),
                            key=lambda r: (r.result.assessed_at, r.result.assessment_id)))

    def append_impact(self, inputs: SupplierDelayInputs, result: ImpactAssessment) -> tuple[ImpactEventIntent, ...]:
        inputs = SupplierDelayInputs.model_validate(inputs.model_dump(exclude_computed_fields=True))
        result = ImpactAssessment.model_validate(result.model_dump(exclude_computed_fields=True))
        change = inputs.request.change
        if result.calculation_input_digest != impact_input_digest(
                inputs.before, inputs.after, change, inputs.before_commitments, inputs.after_commitments):
            raise ValueError('impact complete calculation input binding conflict')
        if (result.tenant_id, result.event_id, result.correlation_id, result.before_snapshot_id,
            result.before_snapshot_version, result.after_snapshot_id, result.after_snapshot_version) != (
                change.tenant_id, change.event_id, change.correlation_id, inputs.before_snapshot_id,
                change.before_snapshot_version, inputs.after_snapshot_id, change.after_snapshot_version):
            raise ValueError('impact input binding conflict')
        for row in result.impacts:
            for snapshot, commitments, assessment in (
                    (inputs.before, inputs.before_commitments, row.before_assessment),
                    (inputs.after, inputs.after_commitments, row.after_assessment)):
                if assessment is not None:
                    commitment = next((c for c in commitments if c.commitment_id == row.commitment_id), None)
                    if commitment is None:
                        raise ValueError('impact calculation Core binding mismatch')
                    AssessmentRecord(snapshot=snapshot, commitment=commitment, result=assessment)
        input_payload = inputs.model_dump_json(exclude_computed_fields=True)
        payload = result.model_dump_json(exclude_computed_fields=True)
        cause, key = (result.tenant_id, result.event_id), (result.tenant_id, result.impact_id)
        with self._lock:
            previous = self._causes.get(cause)
            if previous is not None:
                if previous != (input_payload, payload):
                    raise ValueError('event identity payload conflict')
                return ()
            if key in self._impacts and self._impacts[key] != payload:
                raise ValueError('impact identity payload conflict')
            self._causes[cause] = (input_payload, payload)
            self._impacts[key] = payload
            return result.event_intents

    def get_impact(self, tenant_id: str, impact_id: str) -> ImpactAssessment | None:
        with self._lock:
            payload = self._impacts.get((tenant_id, impact_id))
        return None if payload is None else ImpactAssessment.model_validate_json(payload)
