"""Version-bound durable approval for isolated synthetic recovery actions.

Production authority stays closed until P5 supplies authenticated principals.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKeyConstraint, Integer, JSON, Numeric, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.models import AuditEventRecord, CommitmentRecord
from app.db.base import Base
from app.feasibility.api_dependencies import require_isolated_e2e_key
from app.feasibility.persisted_sources import read_snapshot
from app.recovery.durable_plans import RecoveryPlanRecord


class ManagerApprovalRecord(Base):
    __tablename__ = "manager_approval_decisions"

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    approval_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    commitment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    case_id: Mapped[str] = mapped_column(String(128), nullable=False)
    plan_id: Mapped[str] = mapped_column(String(128), nullable=False)
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False)
    proposal_id: Mapped[str] = mapped_column(String(128), nullable=False)
    proposal_version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_id: Mapped[str] = mapped_column(String(128), nullable=False)
    snapshot_version: Mapped[int] = mapped_column(Integer, nullable=False)
    commitment_version: Mapped[int] = mapped_column(Integer, nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    action_scope: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    approved_terms: Mapped[dict] = mapped_column(JSON, nullable=False)
    approved_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(String(512), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    audit_id: Mapped[str] = mapped_column(String(128), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "plan_id", "plan_version"],
            ["recovery_plan_versions.tenant_id", "recovery_plan_versions.plan_id",
             "recovery_plan_versions.plan_version"],
            name="fk_manager_approval_plan", ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_manager_approval_key"),
    )


def trusted_isolated_manager(context: RequestContext, key: str | None) -> str:
    if os.getenv("MOUMANTAI_ISOLATED_E2E") != "1":
        raise DomainError("APPROVAL_AUTHORITY_UNAVAILABLE", "Trusted approval authority is unavailable", status_code=503)
    require_isolated_e2e_key(key)
    manager_id = os.getenv("MOUMANTAI_ISOLATED_E2E_MANAGER_ID")
    if not manager_id or context.actor_id != manager_id:
        raise DomainError("MANAGER_APPROVAL_REQUIRED", "Verified isolated Manager is required", status_code=403)
    return manager_id


class ManagerApprovalService:
    def decide(
        self, db: Session, context: RequestContext, key: str | None,
        plan_id: str, *, decision: str, expected_plan_version: int,
        expected_commitment_version: int, expected_snapshot_version: int,
        idempotency_key: str, reason: str,
    ) -> ManagerApprovalRecord:
        actor_id = trusted_isolated_manager(context, key)
        if decision not in {"APPROVED", "REJECTED", "REVISION_REQUESTED", "REVOKED"}:
            raise DomainError("APPROVAL_DECISION_INVALID", "Unsupported approval decision", status_code=422)
        if not idempotency_key or not reason:
            raise DomainError("APPROVAL_EVIDENCE_REQUIRED", "Decision key and reason are required", status_code=422)
        prior = db.scalar(select(ManagerApprovalRecord).where(
            ManagerApprovalRecord.tenant_id == context.tenant_id,
            ManagerApprovalRecord.idempotency_key == idempotency_key,
        ))
        if prior is not None:
            if (prior.plan_id, prior.plan_version, prior.decision, prior.reason) != (
                plan_id, expected_plan_version, decision, reason,
            ):
                raise DomainError("APPROVAL_KEY_CONFLICT", "Idempotency key has different content", status_code=409)
            return prior
        plan = db.get(RecoveryPlanRecord, (context.tenant_id, plan_id, expected_plan_version))
        if plan is None:
            raise DomainError("RECOVERY_PLAN_NOT_FOUND", "Recovery plan was not found", status_code=404)
        commitment = db.scalar(select(CommitmentRecord).where(
            CommitmentRecord.tenant_id == context.tenant_id,
            CommitmentRecord.commitment_id == plan.commitment_id,
        ).with_for_update())
        if commitment is None:
            raise DomainError("COMMITMENT_NOT_FOUND", "Commitment was not found", status_code=404)
        snapshot = read_snapshot(db, context.tenant_id)
        if (plan.core_commitment_version, commitment.commitment_version,
            expected_commitment_version) != (commitment.commitment_version,) * 3:
            raise DomainError("COMMITMENT_VERSION_CONFLICT", "Approval plan is stale", status_code=409)
        if (plan.snapshot_id, plan.snapshot_version, expected_snapshot_version) != (
            snapshot.operational.snapshot_id, snapshot.operational.snapshot_version,
            snapshot.operational.snapshot_version,
        ):
            raise DomainError("SNAPSHOT_DRIFT_CONFLICT", "Approval source is stale", status_code=409)
        from app.recovery.models import RecoveryPlanVersion

        typed = RecoveryPlanVersion.model_validate(plan.payload)
        if decision == "APPROVED" and (
            typed.feasibility_status not in {"FEASIBLE", "CONDITIONAL"}
            or typed.evaluation.validation_source != "REAL_P2_VALIDATED"
        ):
            raise DomainError("PLAN_NOT_APPROVABLE", "P2 has not validated this plan for review", status_code=409)
        history = db.scalars(select(ManagerApprovalRecord).where(
            ManagerApprovalRecord.tenant_id == context.tenant_id,
            ManagerApprovalRecord.plan_id == plan_id,
            ManagerApprovalRecord.plan_version == expected_plan_version,
        ).order_by(ManagerApprovalRecord.decided_at.desc())).all()
        latest = history[0] if history else None
        if decision == "REVOKED" and (latest is None or latest.decision != "APPROVED"):
            raise DomainError("APPROVAL_NOT_ACTIVE", "There is no active approval to revoke", status_code=409)
        if decision == "APPROVED" and latest is not None and latest.decision == "APPROVED":
            raise DomainError("APPROVAL_ALREADY_ACTIVE", "Plan already has an active approval", status_code=409)
        now = datetime.now(timezone.utc)
        approval_id = f"appr_{uuid4().hex[:16]}"
        audit_id = f"aud_{uuid4().hex[:16]}"
        scope = ["CREATE_INTERNAL_REVIEW_TASK"] if decision == "APPROVED" else []
        row = ManagerApprovalRecord(
            tenant_id=context.tenant_id, approval_id=approval_id, idempotency_key=idempotency_key,
            commitment_id=plan.commitment_id, case_id=plan.case_id,
            plan_id=plan_id, plan_version=expected_plan_version,
            proposal_id=plan_id, proposal_version=expected_plan_version,
            snapshot_id=plan.snapshot_id, snapshot_version=plan.snapshot_version,
            commitment_version=plan.core_commitment_version, decision=decision,
            action_scope=scope, approved_terms=dict(commitment.terms),
            approved_amount=typed.estimated_extra_cost, actor_id=actor_id, actor_role="MANAGER",
            reason=reason, decided_at=now,
            expires_at=now + timedelta(hours=1) if decision == "APPROVED" else None,
            audit_id=audit_id,
        )
        db.add(row)
        db.add(AuditEventRecord(
            audit_id=audit_id, tenant_id=context.tenant_id, commitment_id=plan.commitment_id,
            event_type=f"recovery.plan_{decision.lower()}", actor_id=actor_id,
            actor_role="MANAGER", dimension="recovery", previous_state={"plan_id": plan_id},
            new_state={"approval_id": approval_id, "decision": decision,
                       "plan_id": plan_id, "plan_version": expected_plan_version,
                       "snapshot_id": plan.snapshot_id,
                       "commitment_version": plan.core_commitment_version},
            evidence_refs=[plan.assessment_id, plan.snapshot_id], reason=reason,
            correlation_id=context.correlation_id, causation_id=context.causation_id,
            occurred_at=now,
        ))
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise
        return row

    def history(self, db: Session, context: RequestContext, plan_id: str) -> list[ManagerApprovalRecord]:
        plan = db.scalar(select(RecoveryPlanRecord).where(
            RecoveryPlanRecord.tenant_id == context.tenant_id,
            RecoveryPlanRecord.plan_id == plan_id,
        ).limit(1))
        if plan is None:
            raise DomainError("RECOVERY_PLAN_NOT_FOUND", "Recovery plan was not found", status_code=404)
        return db.scalars(select(ManagerApprovalRecord).where(
            ManagerApprovalRecord.tenant_id == context.tenant_id,
            ManagerApprovalRecord.plan_id == plan_id,
        ).order_by(ManagerApprovalRecord.decided_at)).all()

    def require_active(self, db: Session, context: RequestContext, plan: RecoveryPlanRecord) -> ManagerApprovalRecord:
        rows = self.history(db, context, plan.plan_id)
        if not rows:
            raise DomainError("MANAGER_APPROVAL_REQUIRED", "No durable approval exists", status_code=409)
        latest = rows[-1]
        now = datetime.now(timezone.utc)
        expiry = latest.expires_at
        if expiry is not None and expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if latest.decision != "APPROVED" or expiry is None or expiry <= now:
            raise DomainError("APPROVAL_NOT_ACTIVE", "Approval is expired or revoked", status_code=409)
        if (latest.plan_version, latest.snapshot_id, latest.snapshot_version,
            latest.commitment_version) != (
            plan.plan_version, plan.snapshot_id, plan.snapshot_version,
            plan.core_commitment_version,
        ) or "CREATE_INTERNAL_REVIEW_TASK" not in latest.action_scope:
            raise DomainError("APPROVAL_SCOPE_CONFLICT", "Approval is for different plan inputs", status_code=409)
        return latest
