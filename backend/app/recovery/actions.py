"""Internal, in-memory synthetic action adapters for P3.

These handlers create demo business records only. They are not mounted on the
public API and do not provide durable, crash-safe, or exactly-once execution.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from threading import RLock
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import ConfigDict, Field, ValidationError, model_validator

from app.core.errors import DomainError
from app.core.schemas import ContractModel, NonNegativeDecimal, OffsetAwareDatetime, PositiveDecimal

from .integrations import ActorContext, require_verified_actor
from .models import (
    ApprovalDecisionInput,
    RecoveryPlanVersion,
    ValidationSource,
)
from .service import RecoveryPlanner


class RecoveryActionType(StrEnum):
    CREATE_PURCHASE_REQUEST = "CREATE_PURCHASE_REQUEST"
    CREATE_PRODUCTION_TASK = "CREATE_PRODUCTION_TASK"
    CREATE_FOLLOWUP_TASK = "CREATE_FOLLOWUP_TASK"


class ActionStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    NEEDS_RECONCILIATION = "NEEDS_RECONCILIATION"


class FailureMode(StrEnum):
    NONE = "NONE"
    BEFORE_WRITE = "BEFORE_WRITE"
    TIMEOUT_AFTER_WRITE = "TIMEOUT_AFTER_WRITE"


SafeRef = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")]


class PurchaseRequestParameters(ContractModel):
    action_type: Literal[RecoveryActionType.CREATE_PURCHASE_REQUEST] = RecoveryActionType.CREATE_PURCHASE_REQUEST
    resource_id: SafeRef
    supplier_id: SafeRef
    quantity: PositiveDecimal
    unit: SafeRef
    estimated_cost_myr: NonNegativeDecimal


class ProductionTaskParameters(ContractModel):
    action_type: Literal[RecoveryActionType.CREATE_PRODUCTION_TASK] = RecoveryActionType.CREATE_PRODUCTION_TASK
    resource_id: SafeRef
    quantity: PositiveDecimal
    unit: SafeRef
    due_at: OffsetAwareDatetime


class FollowupTaskParameters(ContractModel):
    action_type: Literal[RecoveryActionType.CREATE_FOLLOWUP_TASK] = RecoveryActionType.CREATE_FOLLOWUP_TASK
    task_code: SafeRef
    owner_team: SafeRef
    due_at: OffsetAwareDatetime


ActionParameters = Annotated[
    PurchaseRequestParameters | ProductionTaskParameters | FollowupTaskParameters,
    Field(discriminator="action_type"),
]


class SyntheticActionCommand(ContractModel):
    action_id: SafeRef
    tenant_id: SafeRef
    commitment_id: SafeRef
    plan_id: SafeRef
    plan_version: int = Field(ge=1)
    action_type: RecoveryActionType
    parameters: ActionParameters
    idempotency_key: SafeRef
    evidence_refs: tuple[SafeRef, ...] = ()

    @model_validator(mode="after")
    def action_and_parameter_types_match(self) -> SyntheticActionCommand:
        if self.parameters.action_type != self.action_type:
            raise ValueError("action_type must match the typed parameter discriminator")
        return self


class SyntheticBusinessRecord(ContractModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, populate_by_name=True, frozen=True)

    operation_ref: SafeRef
    tenant_id: SafeRef
    commitment_id: SafeRef
    plan_id: SafeRef
    plan_version: int = Field(ge=1)
    action_id: SafeRef
    action_type: RecoveryActionType
    parameters: ActionParameters
    created_at: OffsetAwareDatetime


class ActionAttemptRecord(ContractModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, populate_by_name=True, frozen=True)

    attempt_id: SafeRef
    action_id: SafeRef
    status: ActionStatus
    started_at: OffsetAwareDatetime
    completed_at: OffsetAwareDatetime
    operation_ref: SafeRef | None = None
    evidence_refs: tuple[SafeRef, ...] = ()
    error_code: str | None = None


class ActionResult(ContractModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, populate_by_name=True, frozen=True)

    action_id: SafeRef
    tenant_id: SafeRef
    commitment_id: SafeRef
    plan_id: SafeRef
    plan_version: int = Field(ge=1)
    action_type: RecoveryActionType
    parameters: ActionParameters
    idempotency_key: SafeRef
    status: ActionStatus
    operation_ref: SafeRef | None = None
    evidence_refs: tuple[SafeRef, ...] = ()
    attempts: tuple[ActionAttemptRecord, ...] = ()
    created_at: OffsetAwareDatetime
    updated_at: OffsetAwareDatetime
    persistence_mode: Literal["IN_MEMORY_NON_DURABLE"] = "IN_MEMORY_NON_DURABLE"


class SyntheticBusinessRecordRepository:
    """Tenant-scoped synthetic records and an in-process idempotency index."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, str], SyntheticBusinessRecord] = {}
        self._keys: dict[tuple[str, str], str] = {}
        self._results: dict[tuple[str, str], list[ActionResult]] = {}
        self._lock = RLock()

    @property
    def durable(self) -> bool:
        return False

    def get_record(self, tenant_id: str, operation_ref: str) -> SyntheticBusinessRecord | None:
        with self._lock:
            return self._records.get((tenant_id, operation_ref))

    def results_for(self, tenant_id: str, idempotency_key: str) -> tuple[ActionResult, ...]:
        with self._lock:
            return tuple(self._results.get((tenant_id, idempotency_key), ()))

    def _append(self, result: ActionResult) -> None:
        key = (result.tenant_id, result.idempotency_key)
        self._results.setdefault(key, []).append(result)


class SyntheticActionAdapter:
    """Allowlisted P3 handlers; deliberately not an API route or live executor."""

    def __init__(self, planner: RecoveryPlanner, repository: SyntheticBusinessRecordRepository | None = None) -> None:
        self.planner = planner
        self.repository = repository or SyntheticBusinessRecordRepository()
        self._handlers = {
            RecoveryActionType.CREATE_PURCHASE_REQUEST: self._create_purchase_request,
            RecoveryActionType.CREATE_PRODUCTION_TASK: self._create_production_task,
            RecoveryActionType.CREATE_FOLLOWUP_TASK: self._create_followup_task,
        }

    @staticmethod
    def _validate_command_plan(
        command: SyntheticActionCommand, plan: RecoveryPlanVersion, *, allow_test_simulation: bool = False,
    ) -> None:
        if (command.tenant_id, command.commitment_id, command.plan_id, command.plan_version) != (
            plan.tenant_id, plan.commitment_id, plan.plan_id, plan.plan_version
        ):
            raise DomainError("ACTION_PLAN_BINDING_MISMATCH", "Action does not match the approved plan", status_code=409)
        if (plan.evaluation.validation_source != ValidationSource.REAL_P2_VALIDATED
                and not (allow_test_simulation
                         and plan.evaluation.validation_source == ValidationSource.TEST_DOUBLE_VALIDATED)):
            raise DomainError("AUTHORITATIVE_VALIDATION_REQUIRED", "Synthetic P2 results cannot authorize execution", status_code=409)
        planned = next((a for a in plan.actions if a.action_id == command.action_id), None)
        if planned is None or planned.type != command.action_type.value:
            raise DomainError("ACTION_NOT_IN_PLAN", "Action is not allowlisted by this plan version", status_code=409)
        try:
            expected_params = type(command.parameters).model_validate(planned.parameters)
        except ValidationError as exc:
            raise DomainError("ACTION_PARAMETERS_INVALID", "Approved plan contains invalid action parameters", status_code=409) from exc
        if expected_params != command.parameters:
            raise DomainError("ACTION_PARAMETERS_MISMATCH", "Action parameters differ from the approved plan", status_code=409)

    @staticmethod
    def _create_purchase_request(command: SyntheticActionCommand, now: datetime) -> SyntheticBusinessRecord:
        if not isinstance(command.parameters, PurchaseRequestParameters):
            raise DomainError("ACTION_PARAMETERS_INVALID", "Purchase parameters are required")
        return SyntheticActionAdapter._record(command, now)

    @staticmethod
    def _create_production_task(command: SyntheticActionCommand, now: datetime) -> SyntheticBusinessRecord:
        if not isinstance(command.parameters, ProductionTaskParameters):
            raise DomainError("ACTION_PARAMETERS_INVALID", "Production-task parameters are required")
        return SyntheticActionAdapter._record(command, now)

    @staticmethod
    def _create_followup_task(command: SyntheticActionCommand, now: datetime) -> SyntheticBusinessRecord:
        if not isinstance(command.parameters, FollowupTaskParameters):
            raise DomainError("ACTION_PARAMETERS_INVALID", "Follow-up-task parameters are required")
        return SyntheticActionAdapter._record(command, now)

    @staticmethod
    def _record(command: SyntheticActionCommand, now: datetime) -> SyntheticBusinessRecord:
        return SyntheticBusinessRecord(
            operation_ref=f"synop_{uuid4().hex}", tenant_id=command.tenant_id,
            commitment_id=command.commitment_id, plan_id=command.plan_id,
            plan_version=command.plan_version, action_id=command.action_id,
            action_type=command.action_type, parameters=command.parameters, created_at=now,
        )

    def execute(
        self,
        actor: ActorContext,
        command: SyntheticActionCommand,
        approval_check: ApprovalDecisionInput,
        *,
        failure_mode: FailureMode = FailureMode.NONE,
        allow_test_simulation: bool = False,
    ) -> ActionResult:
        require_verified_actor(actor)
        if actor.actor_role.upper() not in {"OWNER", "MANAGER"}:
            raise DomainError("ACTION_FORBIDDEN", "Only a verified owner or manager may execute this action", status_code=403)
        if actor.tenant_id != command.tenant_id:
            raise DomainError("TENANT_SCOPE_VIOLATION", "Action is outside the verified tenant", status_code=404)
        with self.repository._lock:
            key = (command.tenant_id, command.idempotency_key)
            key_action = self.repository._keys.get(key)
            history = self.repository._results.get(key, [])
            if key_action is not None and key_action != command.action_id:
                raise DomainError("IDEMPOTENCY_KEY_REUSED", "Idempotency key belongs to another action", status_code=409)
            if history:
                latest = history[-1]
                if latest.action_id != command.action_id or latest.parameters != command.parameters or latest.plan_version != command.plan_version:
                    raise DomainError("IDEMPOTENCY_KEY_REUSED", "Idempotency key was reused with different action data", status_code=409)
            plan = self.planner.get_plan(actor.tenant_id, command.plan_id)
            self._validate_command_plan(command, plan, allow_test_simulation=allow_test_simulation)
            approval = self.planner.get_active_approval(
                actor, command.plan_id, approval_check, allow_test_double=allow_test_simulation,
            )
            if command.action_type.value not in approval.action_scope:
                raise DomainError("APPROVAL_SCOPE_MISMATCH", "Approval does not cover this action type", status_code=409)
            if isinstance(command.parameters, PurchaseRequestParameters):
                amount = command.parameters.estimated_cost_myr
                if approval.approved_cost_limit is None or amount > approval.approved_cost_limit:
                    raise DomainError("APPROVAL_COST_LIMIT_EXCEEDED", "Purchase request exceeds approved amount", status_code=409)

            self.repository._keys[key] = command.action_id
            if history:
                latest = history[-1]
                if latest.action_id != command.action_id or latest.parameters != command.parameters or latest.plan_version != command.plan_version:
                    raise DomainError("IDEMPOTENCY_KEY_REUSED", "Idempotency key was reused with different action data", status_code=409)
                if latest.status == ActionStatus.SUCCEEDED:
                    return latest
                if latest.status == ActionStatus.NEEDS_RECONCILIATION:
                    return latest

            now = datetime.now(UTC)
            attempt_id = f"attempt_{uuid4().hex}"
            previous_attempts = history[-1].attempts if history else ()
            pending = ActionResult(
                action_id=command.action_id, tenant_id=command.tenant_id,
                commitment_id=command.commitment_id, plan_id=command.plan_id,
                plan_version=command.plan_version, action_type=command.action_type,
                parameters=command.parameters, idempotency_key=command.idempotency_key,
                status=ActionStatus.PENDING, evidence_refs=command.evidence_refs,
                attempts=previous_attempts, created_at=history[0].created_at if history else now,
                updated_at=now,
            )
            self.repository._append(pending)
            running = pending.model_copy(update={"status": ActionStatus.RUNNING, "updated_at": datetime.now(UTC)})
            self.repository._append(running)
            attempt_status = ActionStatus.FAILED
            operation_ref: str | None = None
            error_code: str | None = None
            evidence = list(command.evidence_refs)
            if failure_mode == FailureMode.BEFORE_WRITE:
                error_code = "SYNTHETIC_FAILURE_BEFORE_WRITE"
                status = ActionStatus.FAILED
            else:
                record = self._handlers[command.action_type](command, now)
                self.repository._records[(record.tenant_id, record.operation_ref)] = record
                operation_ref = record.operation_ref
                if failure_mode == FailureMode.TIMEOUT_AFTER_WRITE:
                    status = ActionStatus.NEEDS_RECONCILIATION
                    attempt_status = ActionStatus.NEEDS_RECONCILIATION
                    error_code = "AMBIGUOUS_TIMEOUT"
                else:
                    readback = self.repository.get_record(command.tenant_id, record.operation_ref)
                    if readback != record:
                        status = ActionStatus.FAILED
                        error_code = "SYNTHETIC_READBACK_MISMATCH"
                    else:
                        status = ActionStatus.SUCCEEDED
                        attempt_status = ActionStatus.SUCCEEDED
                        evidence.append(f"synthetic_record:{record.operation_ref}")
            completed = datetime.now(UTC)
            attempt = ActionAttemptRecord(
                attempt_id=attempt_id, action_id=command.action_id, status=attempt_status,
                started_at=now, completed_at=completed, operation_ref=operation_ref,
                evidence_refs=tuple(evidence), error_code=error_code,
            )
            result = ActionResult(
                action_id=command.action_id, tenant_id=command.tenant_id,
                commitment_id=command.commitment_id, plan_id=command.plan_id,
                plan_version=command.plan_version, action_type=command.action_type,
                parameters=command.parameters, idempotency_key=command.idempotency_key,
                status=status, operation_ref=operation_ref,
                evidence_refs=tuple(evidence if status == ActionStatus.SUCCEEDED else command.evidence_refs),
                attempts=previous_attempts + (attempt,), created_at=pending.created_at,
                updated_at=completed,
            )
            self.repository._append(result)
            return result

    def reconcile(self, tenant_id: str, idempotency_key: str) -> ActionResult:
        """Resolve an ambiguous synthetic timeout by readback; never replay the write."""
        with self.repository._lock:
            key = (tenant_id, idempotency_key)
            history = self.repository._results.get(key, [])
            if not history or history[-1].status != ActionStatus.NEEDS_RECONCILIATION:
                raise DomainError("RECONCILIATION_NOT_REQUIRED", "No ambiguous action needs reconciliation", status_code=409)
            prior = history[-1]
            record = self.repository.get_record(tenant_id, prior.operation_ref or "")
            now = datetime.now(UTC)
            record_verified = record is not None and (
                record.tenant_id == prior.tenant_id
                and record.commitment_id == prior.commitment_id
                and record.plan_id == prior.plan_id
                and record.plan_version == prior.plan_version
                and record.action_id == prior.action_id
                and record.action_type == prior.action_type
                and record.parameters == prior.parameters
            )
            attempt = ActionAttemptRecord(
                attempt_id=f"attempt_{uuid4().hex}", action_id=prior.action_id,
                status=ActionStatus.SUCCEEDED if record_verified else ActionStatus.FAILED,
                started_at=now, completed_at=now, operation_ref=prior.operation_ref,
                evidence_refs=(f"synthetic_record:{record.operation_ref}",) if record_verified else (),
                error_code=None if record_verified else "SYNTHETIC_RECORD_NOT_VERIFIED",
            )
            result = prior.model_copy(update={
                "status": attempt.status, "evidence_refs": attempt.evidence_refs,
                "attempts": prior.attempts + (attempt,), "updated_at": now,
            })
            self.repository._append(result)
            return result
