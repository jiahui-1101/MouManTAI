"""Allowlisted, version-checked synthetic internal review task execution."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKeyConstraint, Integer, JSON, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.action_evidence import stage_failed_internal_task, stage_verified_internal_task
from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.manager_approval import ManagerApprovalService, trusted_isolated_manager
from app.core.models import CommitmentRecord
from app.core.service import CommitmentService
from app.db.base import Base
from app.feasibility.persisted_sources import read_snapshot
from app.feasibility.production import ProposedChanges
from app.feasibility.service import evaluate

from .durable_plans import RecoveryPlanRecord
from .models import RecoveryPlanVersion


class InternalRecoveryTaskRecord(Base):
    __tablename__ = "internal_recovery_tasks"

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    commitment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    plan_id: Mapped[str] = mapped_column(String(128), nullable=False)
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "plan_id", "plan_version"],
            ["recovery_plan_versions.tenant_id", "recovery_plan_versions.plan_id",
             "recovery_plan_versions.plan_version"], name="fk_internal_task_plan", ondelete="RESTRICT",
        ),
    )


class RecoveryActionExecutionRecord(Base):
    __tablename__ = "recovery_action_executions"

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    execution_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    commitment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    plan_id: Mapped[str] = mapped_column(String(128), nullable=False)
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False)
    approval_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    task_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    receipt_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    audit_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "plan_id", "plan_version"],
            ["recovery_plan_versions.tenant_id", "recovery_plan_versions.plan_id",
             "recovery_plan_versions.plan_version"], name="fk_recovery_action_plan", ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_recovery_action_key"),
    )


class DurableActionService:
    @staticmethod
    def _create_task(
        db: Session, *, tenant_id: str, commitment_id: str,
        plan: RecoveryPlanRecord, payload: dict,
    ) -> InternalRecoveryTaskRecord:
        task = InternalRecoveryTaskRecord(
            tenant_id=tenant_id, task_id=f"task_{uuid4().hex[:16]}",
            commitment_id=commitment_id, plan_id=plan.plan_id,
            plan_version=plan.plan_version, task_type="INTERNAL_REVIEW",
            status="OPEN", payload=payload, created_at=datetime.now(timezone.utc),
        )
        db.add(task)
        db.flush()
        db.expire(task)
        verified = db.get(InternalRecoveryTaskRecord, (tenant_id, task.task_id))
        if verified is None or verified.status != "OPEN" or verified.payload != payload:
            raise DomainError("ACTION_RECEIPT_UNVERIFIED", "Internal task could not be verified", status_code=500)
        return verified

    def execute(
        self, db: Session, context: RequestContext, key: str | None,
        plan_id: str, *, expected_plan_version: int,
        expected_commitment_version: int, expected_snapshot_version: int,
        idempotency_key: str,
    ) -> RecoveryActionExecutionRecord:
        actor_id = trusted_isolated_manager(context, key)
        if not idempotency_key:
            raise DomainError("ACTION_KEY_REQUIRED", "An idempotency key is required", status_code=422)
        previous = db.scalar(select(RecoveryActionExecutionRecord).where(
            RecoveryActionExecutionRecord.tenant_id == context.tenant_id,
            RecoveryActionExecutionRecord.idempotency_key == idempotency_key,
        ))
        if previous is not None and (previous.plan_id, previous.plan_version) != (
            plan_id, expected_plan_version,
        ):
            raise DomainError("ACTION_KEY_CONFLICT", "Idempotency key belongs to another plan", status_code=409)
        plan = db.get(RecoveryPlanRecord, (context.tenant_id, plan_id, expected_plan_version))
        if plan is None:
            raise DomainError("RECOVERY_PLAN_NOT_FOUND", "Recovery plan was not found", status_code=404)
        if (expected_commitment_version, expected_snapshot_version) != (
            plan.core_commitment_version, plan.snapshot_version,
        ):
            raise DomainError("ACTION_KEY_CONFLICT", "Action request differs from its plan version", status_code=409)
        if previous is not None and previous.status == "SUCCEEDED":
            task = db.get(InternalRecoveryTaskRecord, (context.tenant_id, previous.task_id))
            if task is None or task.status != "OPEN":
                raise DomainError("ACTION_RECEIPT_UNVERIFIED", "Saved task is missing", status_code=500)
            return previous
        commitment = db.scalar(select(CommitmentRecord).where(
            CommitmentRecord.tenant_id == context.tenant_id,
            CommitmentRecord.commitment_id == plan.commitment_id,
        ).with_for_update())
        if commitment is None:
            raise DomainError("COMMITMENT_NOT_FOUND", "Commitment was not found", status_code=404)
        snapshot = read_snapshot(db, context.tenant_id)
        if (plan.core_commitment_version, expected_commitment_version,
            commitment.commitment_version) != (commitment.commitment_version,) * 3:
            raise DomainError("COMMITMENT_VERSION_CONFLICT", "Action plan is stale", status_code=409)
        if (plan.snapshot_id, plan.snapshot_version, expected_snapshot_version) != (
            snapshot.operational.snapshot_id, snapshot.operational.snapshot_version,
            snapshot.operational.snapshot_version,
        ):
            raise DomainError("SNAPSHOT_DRIFT_CONFLICT", "Action source is stale", status_code=409)
        typed = RecoveryPlanVersion.model_validate(plan.payload)
        if typed.option_id != "revised_schedule" or typed.actions[0].type != "CREATE_INTERNAL_REVIEW_TASK":
            raise DomainError("ACTION_NOT_ALLOWLISTED", "Only an internal review task may be created", status_code=409)
        approval = ManagerApprovalService().require_active(db, context, plan)
        if approval.approved_amount < typed.estimated_extra_cost:
            raise DomainError("APPROVAL_COST_LIMIT_EXCEEDED", "Approval does not cover plan cost", status_code=409)
        source = next((row for row in snapshot.operational.confirmed_commitments
                       if row.commitment_id == plan.commitment_id), None)
        if source is None or source.commitment_version != plan.evaluated_commitment_version:
            raise DomainError("P2_COMMITMENT_BINDING_MISMATCH", "P2 source commitment changed", status_code=409)
        core = CommitmentService().get(db, context, plan.commitment_id)
        historical = core.model_copy(update={"commitment_version": plan.evaluated_commitment_version})
        proposal_data = typed.actions[0].parameters.get("proposal")
        proposal = ProposedChanges.model_validate(proposal_data) if proposal_data else None
        result = evaluate(snapshot, proposal, historical)
        if (result.status, result.solver_status.value, result.snapshot_id,
            result.commitment_version) != (
            typed.evaluation.feasibility_status, typed.evaluation.solver_status,
            plan.snapshot_id, plan.evaluated_commitment_version,
        ) or result.status not in {"FEASIBLE", "CONDITIONAL"}:
            raise DomainError("PLAN_REVALIDATION_FAILED", "P2 result changed or is not safe for review", status_code=409)
        actual_constraints = {f"{item.code}:{item.resource_id}" for item in result.constraints}
        if not actual_constraints.issubset(set(typed.evaluation.constraints)) or not set(result.evidence_refs).issubset(set(typed.evaluation.evidence_refs)):
            raise DomainError("PLAN_REVALIDATION_FAILED", "P2 evidence or constraints changed", status_code=409)
        # The locked Commitment row serializes competing executions on PostgreSQL.
        # A new key must never create a second task for the same plan version.
        already_succeeded = db.scalar(select(RecoveryActionExecutionRecord).where(
            RecoveryActionExecutionRecord.tenant_id == context.tenant_id,
            RecoveryActionExecutionRecord.plan_id == plan_id,
            RecoveryActionExecutionRecord.plan_version == expected_plan_version,
            RecoveryActionExecutionRecord.status == "SUCCEEDED",
        ).limit(1))
        if already_succeeded is not None:
            raise DomainError("ACTION_ALREADY_EXECUTED", "Plan version already has a verified internal task", status_code=409)
        now = datetime.now(timezone.utc)
        execution = previous or RecoveryActionExecutionRecord(
            tenant_id=context.tenant_id, execution_id=f"act_{uuid4().hex[:16]}",
            idempotency_key=idempotency_key, commitment_id=plan.commitment_id,
            plan_id=plan_id, plan_version=plan.plan_version, approval_id=approval.approval_id,
            status="IN_PROGRESS", attempts=0, created_at=now, updated_at=now,
        )
        execution.attempts += 1
        execution.updated_at = now
        db.add(execution)
        attempt_number = execution.attempts
        execution_id = execution.execution_id
        try:
            task = self._create_task(
                db, tenant_id=context.tenant_id, commitment_id=plan.commitment_id,
                plan=plan,
                payload={"plan_id": plan_id, "plan_version": plan.plan_version,
                         "strategy": typed.strategy.value,
                         "customer_acceptance_required_for_terms_change": True,
                         "approved_by": actor_id},
            )
            receipt = "receipt_" + sha256(
                f"{context.tenant_id}:{task.task_id}:{plan_id}:{approval.approval_id}".encode(),
            ).hexdigest()[:32]
            audit_id = stage_verified_internal_task(
                db, context, commitment_id=plan.commitment_id,
                expected_commitment_version=plan.core_commitment_version,
                plan_id=plan_id, approval_id=approval.approval_id,
                task_id=task.task_id, receipt_ref=receipt,
            )
            execution.status = "SUCCEEDED"
            execution.task_id = task.task_id
            execution.receipt_ref = receipt
            execution.audit_id = audit_id
            execution.last_error = None
            db.commit()
        except Exception as exc:
            db.rollback()
            # The attempted task and success evidence rolled back together.
            # Preserve a separate failed-attempt record for safe keyed retry.
            try:
                failed = db.scalar(select(RecoveryActionExecutionRecord).where(
                    RecoveryActionExecutionRecord.tenant_id == context.tenant_id,
                    RecoveryActionExecutionRecord.idempotency_key == idempotency_key,
                ))
                if failed is None:
                    failed = RecoveryActionExecutionRecord(
                        tenant_id=context.tenant_id, execution_id=execution_id,
                        idempotency_key=idempotency_key, commitment_id=plan.commitment_id,
                        plan_id=plan_id, plan_version=plan.plan_version,
                        approval_id=approval.approval_id, status="FAILED",
                        attempts=attempt_number, created_at=now, updated_at=datetime.now(timezone.utc),
                    )
                    db.add(failed)
                else:
                    failed.status = "FAILED"
                    failed.attempts = attempt_number
                    failed.updated_at = datetime.now(timezone.utc)
                failed.last_error = type(exc).__name__[:128]
                stage_failed_internal_task(
                    db, context, commitment_id=plan.commitment_id, plan_id=plan_id,
                    execution_id=execution_id, error_code=failed.last_error,
                )
                db.commit()
            except Exception:
                db.rollback()
            raise
        return execution

    def history(self, db: Session, context: RequestContext, plan_id: str) -> list[RecoveryActionExecutionRecord]:
        if db.scalar(select(RecoveryPlanRecord).where(
            RecoveryPlanRecord.tenant_id == context.tenant_id,
            RecoveryPlanRecord.plan_id == plan_id,
        ).limit(1)) is None:
            raise DomainError("RECOVERY_PLAN_NOT_FOUND", "Recovery plan was not found", status_code=404)
        return db.scalars(select(RecoveryActionExecutionRecord).where(
            RecoveryActionExecutionRecord.tenant_id == context.tenant_id,
            RecoveryActionExecutionRecord.plan_id == plan_id,
        ).order_by(RecoveryActionExecutionRecord.created_at)).all()
