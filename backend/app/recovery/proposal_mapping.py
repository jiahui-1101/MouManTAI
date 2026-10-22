"""P3-owned, fail-closed mapping from recovery plans to P2 proposals.

The actual P2 model is resolved lazily from P2's canonical module. This keeps
isolated P3 tests injectable while normal merged development uses the real
P2 schema. No P2 fields or feasibility rules are reimplemented here.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from importlib import import_module
from typing import Any

from app.core.errors import DomainError
from app.core.schemas import Commitment

from .integrations import VersionedSnapshot, validate_snapshot_binding
from .models import RecoveryPlanVersion, RecoveryStrategy


class ProposalMappingStatus(StrEnum):
    MAPPED = "MAPPED"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True)
class P2ProposalMapping:
    """P2 input plus P3 provenance, or an explicit unsupported outcome."""

    status: ProposalMappingStatus
    proposed_changes: object | None
    source_assessment_id: str
    evidence_refs: tuple[str, ...]
    assumptions: tuple[str, ...]
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if self.status is ProposalMappingStatus.MAPPED:
            if self.proposed_changes is None or self.reason_code is not None:
                raise ValueError("mapped proposals require a P2 model and no unsupported reason")
        elif self.proposed_changes is not None or not self.reason_code:
            raise ValueError("unsupported proposals require a reason and cannot contain P2 changes")


P2ModelFactory = Callable[..., object]


def _load_p2_proposed_changes() -> P2ModelFactory:
    try:
        module = import_module("app.feasibility.production")
        model = module.ProposedChanges
    except (ImportError, AttributeError) as exc:
        raise DomainError(
            "P2_PROPOSAL_SCHEMA_UNAVAILABLE",
            "P2 ProposedChanges is unavailable in this Python environment; verify the P2 module installation and branch sync",
            status_code=503,
        ) from exc
    if not callable(model):
        raise DomainError("P2_PROPOSAL_SCHEMA_INVALID", "P2 ProposedChanges is not constructible", status_code=503)
    return model


def _aware_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError as exc:
            raise DomainError("P2_PROPOSAL_DATE_INVALID", f"{field_name} must be an ISO 8601 timestamp", status_code=422) from exc
    else:
        raise DomainError("P2_PROPOSAL_DATE_INVALID", f"{field_name} must be an ISO 8601 timestamp", status_code=422)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DomainError("P2_PROPOSAL_DATE_INVALID", f"{field_name} must include an explicit UTC offset", status_code=422)
    return parsed


def _positive_decimal(value: Any, field_name: str) -> Decimal:
    if isinstance(value, (float, bool)):
        raise DomainError("P2_PROPOSAL_QUANTITY_INVALID", f"{field_name} must use an exact decimal value", status_code=422)
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise DomainError("P2_PROPOSAL_QUANTITY_INVALID", f"{field_name} must be a decimal quantity", status_code=422) from exc
    if not parsed.is_finite() or parsed <= 0:
        raise DomainError("P2_PROPOSAL_QUANTITY_INVALID", f"{field_name} must be positive and finite", status_code=422)
    return parsed


class RecoveryPlanProposedChangesBuilder:
    """Map only fields P2 actually models; never add supply to an evaluation."""

    _RESCHEDULE_ACTION = "CREATE_DELIVERY_CHANGE_PROPOSAL"
    _RESCHEDULE_FIELDS = frozenset({"partial_quantity", "new_deadline", "deadline", "production_start_at"})

    def __init__(self, model_factory: P2ModelFactory | None = None) -> None:
        self._model_factory = model_factory

    def _factory(self) -> P2ModelFactory:
        return self._model_factory or _load_p2_proposed_changes()

    @staticmethod
    def _validate_bindings(
        plan: RecoveryPlanVersion,
        snapshot: VersionedSnapshot,
        commitment: Commitment,
    ) -> Any:
        if (plan.tenant_id, plan.commitment_id) != (commitment.tenant_id, commitment.commitment_id):
            raise DomainError("P2_PROPOSAL_SCOPE_MISMATCH", "Plan and commitment identity do not match", status_code=409)
        if (snapshot.tenant_id, snapshot.commitment_id) != (commitment.tenant_id, commitment.commitment_id):
            raise DomainError("P2_PROPOSAL_SCOPE_MISMATCH", "Snapshot and commitment identity do not match", status_code=409)
        if (plan.evaluation.commitment_version, snapshot.commitment_version) != (
            commitment.commitment_version, commitment.commitment_version
        ):
            raise DomainError("COMMITMENT_VERSION_CONFLICT", "Plan or snapshot is stale for the commitment", status_code=409)
        if plan.snapshot_version != snapshot.snapshot_version:
            raise DomainError("SNAPSHOT_VERSION_CONFLICT", "Plan was generated from a different snapshot version", status_code=409)
        if not plan.based_on_assessment_id.strip():
            raise DomainError("P2_ASSESSMENT_REFERENCE_REQUIRED", "Plan must retain its source assessment reference", status_code=409)

        validate_snapshot_binding(snapshot, commitment)
        p2_snapshot = snapshot.snapshot
        operational = getattr(p2_snapshot, "operational", None)
        if operational is None:
            raise DomainError("P2_EVALUATION_SNAPSHOT_REQUIRED", "Snapshot must be a typed P2 EvaluationSnapshot", status_code=409)
        current_version = getattr(p2_snapshot, "current_snapshot_version", None)
        if current_version is None:
            raise DomainError("CURRENT_SNAPSHOT_VERSION_REQUIRED", "P2 snapshot has no authoritative current-version token", status_code=503)
        if current_version != snapshot.snapshot_version:
            raise DomainError("SNAPSHOT_VERSION_CONFLICT", "P2 snapshot is not the current operational version", status_code=409)
        commitments = getattr(operational, "confirmed_commitments", ())
        target = next((item for item in commitments if item.commitment_id == commitment.commitment_id), None)
        if target is None or target.commitment_version != commitment.commitment_version:
            raise DomainError("P2_COMMITMENT_BINDING_MISMATCH", "Commitment/version is absent from the P2 snapshot", status_code=409)
        return p2_snapshot

    @staticmethod
    def _references(plan: RecoveryPlanVersion) -> tuple[str, ...]:
        values = [
            f"assessment:{plan.based_on_assessment_id}",
            f"evaluation:{plan.evaluation.evaluation_id}",
            *plan.evidence_refs,
            *plan.evaluation.evidence_refs,
        ]
        return tuple(dict.fromkeys(value.strip() for value in values if value and value.strip()))

    def build(
        self,
        plan: RecoveryPlanVersion,
        snapshot: VersionedSnapshot,
        commitment: Commitment,
    ) -> P2ProposalMapping:
        self._validate_bindings(plan, snapshot, commitment)
        refs = self._references(plan)
        if not refs:
            raise DomainError("P2_PROPOSAL_EVIDENCE_REQUIRED", "A recovery proposal requires evidence references", status_code=422)

        if plan.strategy is RecoveryStrategy.ALTERNATIVE_SUPPLY:
            return P2ProposalMapping(
                status=ProposalMappingStatus.UNSUPPORTED,
                proposed_changes=None,
                source_assessment_id=plan.based_on_assessment_id,
                evidence_refs=refs,
                assumptions=(
                    "P2 cannot represent alternative-supplier substitution in ProposedChanges; no supplier quantity was added to the snapshot.",
                    "Supplier availability remains unconfirmed and is not treated as inventory.",
                ),
                reason_code="P2_ALTERNATIVE_SUPPLY_UNSUPPORTED",
            )

        if plan.strategy is not RecoveryStrategy.RESCHEDULE_PARTIAL_FULFILMENT:
            return P2ProposalMapping(
                status=ProposalMappingStatus.UNSUPPORTED,
                proposed_changes=None,
                source_assessment_id=plan.based_on_assessment_id,
                evidence_refs=refs,
                assumptions=("P2 has no agreed proposal mapping for this recovery strategy.",),
                reason_code="P2_RECOVERY_STRATEGY_UNSUPPORTED",
            )

        if len(plan.actions) != 1 or plan.actions[0].type != self._RESCHEDULE_ACTION:
            raise DomainError("P2_PROPOSAL_ACTION_UNSUPPORTED", "Reschedule mapping requires one delivery-change proposal action", status_code=422)
        parameters = dict(plan.actions[0].parameters)
        unsupported = set(parameters) - self._RESCHEDULE_FIELDS
        if unsupported:
            raise DomainError(
                "P2_PROPOSAL_FIELD_UNSUPPORTED",
                f"P2 proposal contains unsupported strategy fields: {', '.join(sorted(unsupported))}",
                status_code=422,
            )
        if "new_deadline" in parameters and "deadline" in parameters:
            raise DomainError("P2_PROPOSAL_FIELD_AMBIGUOUS", "Provide either new_deadline or deadline, not both", status_code=422)

        changes: dict[str, Any] = {
            "tenant_id": commitment.tenant_id,
            "commitment_id": commitment.commitment_id,
            "expected_commitment_version": commitment.commitment_version,
            "expected_snapshot_version": snapshot.snapshot_version,
            "evidence_refs": refs,
        }
        deadline_value = parameters.get("new_deadline", parameters.get("deadline"))
        if deadline_value is not None:
            deadline = _aware_datetime(deadline_value, "deadline")
            if deadline <= snapshot.snapshot.as_of:
                raise DomainError("P2_PROPOSAL_DATE_INVALID", "deadline must be later than the snapshot assessment time", status_code=422)
            changes["deadline"] = deadline

        if "production_start_at" in parameters:
            start = _aware_datetime(parameters["production_start_at"], "production_start_at")
            if start <= snapshot.snapshot.as_of:
                raise DomainError("P2_PROPOSAL_DATE_INVALID", "production_start_at must be later than the snapshot assessment time", status_code=422)
            if deadline_value is not None and start >= changes["deadline"]:
                raise DomainError("P2_PROPOSAL_DATE_INVALID", "production_start_at must precede the proposed deadline", status_code=422)
            changes["production_start_at"] = start

        if "partial_quantity" in parameters:
            quantity = _positive_decimal(parameters["partial_quantity"], "partial_quantity")
            if quantity >= commitment.terms.quantity:
                raise DomainError(
                    "P2_PROPOSAL_QUANTITY_INVALID",
                    "partial_quantity must be less than the confirmed commitment quantity",
                    status_code=422,
                )
            changes["quantity"] = quantity

        if not any(changes.get(key) is not None for key in ("quantity", "deadline", "production_start_at")):
            raise DomainError("P2_PROPOSAL_CHANGE_REQUIRED", "Reschedule requires a supported hypothetical change", status_code=422)

        try:
            proposed_changes = self._factory()(**changes)
        except DomainError:
            raise
        except Exception as exc:  # P2's Pydantic model is authoritative for its own schema.
            raise DomainError("P2_PROPOSED_CHANGES_INVALID", "P2 rejected the mapped ProposedChanges fields", status_code=422) from exc

        assumptions = [
            "This is a hypothetical P2 ProposedChanges evaluation only; it does not mutate confirmed Commitment terms.",
            "A quantity value changes the hypothetical target commitment-line quantity; it is not an executed partial shipment, fulfillment, or customer acceptance.",
        ]
        return P2ProposalMapping(
            status=ProposalMappingStatus.MAPPED,
            proposed_changes=proposed_changes,
            source_assessment_id=plan.based_on_assessment_id,
            evidence_refs=refs,
            assumptions=tuple(assumptions),
        )
