"""P2 request validation for the local feasibility router.

These request models reuse Core Commitment and event types where defined.
They do not replace the shared FeasibilityAssessment or DomainEvent contracts.
"""

from pydantic import Field, model_validator

from app.core.schemas import Commitment, ContractModel

from .impact import OperationalChange, OperationalChangeType, ResourceKind
from .models import SupplierDeliveryEvidence, SupplierDeliveryEvidenceType
from .production import EvaluationSnapshot, ProposedChanges


class FeasibilityEvaluateRequest(ContractModel):
    """Pure calculation input; an authority adapter must verify supplied data."""

    snapshot: EvaluationSnapshot
    commitment: Commitment
    proposed_changes: ProposedChanges | None = None


class AssessCommitmentRequest(ContractModel):
    expected_commitment_version: int = Field(ge=1)


class SupplierDelayRequest(ContractModel):
    change: OperationalChange
    source_evidence: SupplierDeliveryEvidence

    @model_validator(mode="after")
    def supplier_delay_is_scoped_and_source_typed(self) -> "SupplierDelayRequest":
        change = self.change
        if change.event_type is not OperationalChangeType.SUPPLIER_DELIVERY_CHANGED:
            raise ValueError("supplier-delay route accepts only supplier.delivery_changed")
        if change.after_snapshot_version <= change.before_snapshot_version:
            raise ValueError("supplier delay must advance the snapshot version")
        if len(change.resource_keys) != 1 or change.resource_keys[0].kind is not ResourceKind.SUPPLIER_DELIVERY:
            raise ValueError("supplier-delay event must declare exactly one supplier delivery")
        evidence = self.source_evidence
        if evidence.evidence_type is not SupplierDeliveryEvidenceType.ETA_CHANGE:
            raise ValueError("supplier-delay requires typed ETA_CHANGE evidence")
        if evidence.tenant_id != change.tenant_id:
            raise ValueError("supplier-delay evidence tenant does not match event tenant")
        if evidence.delivery_id != change.resource_keys[0].resource_id:
            raise ValueError("supplier-delay evidence must match the changed delivery")
        if evidence.evidence_ref not in change.evidence_refs:
            raise ValueError("supplier-delay evidence reference must be declared by the event")
        return self
