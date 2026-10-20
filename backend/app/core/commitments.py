from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from .dependencies import RequestContext
from .models import CommitmentRecord, OutboxEventRecord
from .schemas import (
    AgreementState,
    AttentionCategory,
    AttentionItem,
    AttentionSeverity,
    CommitmentTerms,
    FeasibilityState,
    FulfilmentState,
    OverviewCommitmentSummary,
    OverviewCounts,
    OverviewResponse,
    RecoveryState,
    RiskState,
)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def build_attention_queue(
    commitments: list[CommitmentRecord],
    failed_outbox_events: list[OutboxEventRecord],
) -> list[AttentionItem]:
    items: list[AttentionItem] = []

    for c in commitments:
        dt = _aware(c.updated_at)

        # 1. Unknown feasibility
        if c.feasibility_state == FeasibilityState.UNKNOWN.value:
            items.append(
                AttentionItem(
                    commitment_id=c.commitment_id,
                    order_id=c.order_id,
                    category=AttentionCategory.UNKNOWN_FEASIBILITY,
                    severity=AttentionSeverity.HIGH,
                    summary=f"Commitment {c.commitment_id} feasibility is UNKNOWN; constraint evaluation required",
                    deep_link_path=f"/impact/{c.commitment_id}",
                    updated_at=dt,
                )
            )

        # 2. Recovery required (stale plan / invalidated)
        if c.recovery_state == RecoveryState.RECOVERY_REQUIRED.value:
            items.append(
                AttentionItem(
                    commitment_id=c.commitment_id,
                    order_id=c.order_id,
                    category=AttentionCategory.STALE_PLAN,
                    severity=AttentionSeverity.CRITICAL,
                    summary=f"Commitment {c.commitment_id} recovery required after plan invalidation",
                    deep_link_path=f"/recovery/{c.commitment_id}",
                    updated_at=dt,
                )
            )

        # 3. Pending approval
        elif c.recovery_state == RecoveryState.PENDING_APPROVAL.value:
            items.append(
                AttentionItem(
                    commitment_id=c.commitment_id,
                    order_id=c.order_id,
                    category=AttentionCategory.MANUAL_REVIEW,
                    severity=AttentionSeverity.HIGH,
                    summary=f"Commitment {c.commitment_id} recovery plan pending manager approval",
                    deep_link_path=f"/recovery/{c.commitment_id}",
                    updated_at=dt,
                )
            )

        # 4. Awaiting customer confirmation on offered proposal
        if c.agreement_state == AgreementState.OFFERED.value:
            items.append(
                AttentionItem(
                    commitment_id=c.commitment_id,
                    order_id=c.order_id,
                    category=AttentionCategory.UNRESOLVED_CONFIRMATION,
                    severity=AttentionSeverity.MEDIUM,
                    summary=f"Commitment {c.commitment_id} proposal offered; awaiting customer confirmation",
                    deep_link_path=f"/confirmations/{c.commitment_id}",
                    updated_at=dt,
                )
            )

        # 5. At Risk or Breached without pending approval already flagged
        if c.risk_state in (RiskState.AT_RISK.value, RiskState.BREACHED.value):
            if c.recovery_state not in (
                RecoveryState.PENDING_APPROVAL.value,
                RecoveryState.RECOVERY_REQUIRED.value,
            ):
                sev = (
                    AttentionSeverity.CRITICAL
                    if c.risk_state == RiskState.BREACHED.value
                    else AttentionSeverity.HIGH
                )
                items.append(
                    AttentionItem(
                        commitment_id=c.commitment_id,
                        order_id=c.order_id,
                        category=AttentionCategory.MANUAL_REVIEW,
                        severity=sev,
                        summary=f"Commitment {c.commitment_id} is {c.risk_state}; manual operational review required",
                        deep_link_path=f"/commitments/{c.commitment_id}",
                        updated_at=dt,
                    )
                )

    # 6. Failed executions from outbox dispatcher
    for evt in failed_outbox_events:
        items.append(
            AttentionItem(
                commitment_id=evt.commitment_id or "unknown",
                order_id="system",
                category=AttentionCategory.FAILED_EXECUTION,
                severity=AttentionSeverity.CRITICAL,
                summary=f"Event {evt.event_id} ({evt.event_type}) failed: {evt.last_error or 'dispatch error'}",
                deep_link_path="/activity",
                updated_at=_aware(evt.occurred_at),
            )
        )

    # Sort attention items: CRITICAL first, then HIGH, then MEDIUM, then LOW
    severity_order = {
        AttentionSeverity.CRITICAL: 0,
        AttentionSeverity.HIGH: 1,
        AttentionSeverity.MEDIUM: 2,
        AttentionSeverity.LOW: 3,
    }
    items.sort(key=lambda item: (severity_order.get(item.severity, 4), item.updated_at))
    return items


def get_overview(db: Session, context: RequestContext) -> OverviewResponse:
    # 1. SQL aggregate counts for the 7 authoritative buckets
    stmt = (
        select(
            func.coalesce(
                func.sum(case((CommitmentRecord.agreement_state == AgreementState.REQUESTED.value, 1), else_=0)),
                0,
            ).label("requested"),
            func.coalesce(
                func.sum(case((CommitmentRecord.agreement_state == AgreementState.CONFIRMED.value, 1), else_=0)),
                0,
            ).label("confirmed"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            CommitmentRecord.risk_state.in_(
                                [RiskState.AT_RISK.value, RiskState.BREACHED.value]
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("at_risk"),
            func.coalesce(
                func.sum(
                    case((CommitmentRecord.recovery_state == RecoveryState.PENDING_APPROVAL.value, 1), else_=0)
                ),
                0,
            ).label("pending_approval"),
            func.coalesce(
                func.sum(
                    case((CommitmentRecord.recovery_state == RecoveryState.EXECUTING.value, 1), else_=0)
                ),
                0,
            ).label("execution_in_progress"),
            func.coalesce(
                func.sum(
                    case((CommitmentRecord.agreement_state == AgreementState.OFFERED.value, 1), else_=0)
                ),
                0,
            ).label("awaiting_confirmation"),
            func.coalesce(
                func.sum(
                    case((CommitmentRecord.fulfilment_state == FulfilmentState.FULFILLED.value, 1), else_=0)
                ),
                0,
            ).label("fulfilled"),
        )
        .where(CommitmentRecord.tenant_id == context.tenant_id)
    )

    row = db.execute(stmt).first()
    if row:
        counts = OverviewCounts(
            requested=int(row.requested or 0),
            confirmed=int(row.confirmed or 0),
            at_risk=int(row.at_risk or 0),
            pending_approval=int(row.pending_approval or 0),
            execution_in_progress=int(row.execution_in_progress or 0),
            awaiting_confirmation=int(row.awaiting_confirmation or 0),
            fulfilled=int(row.fulfilled or 0),
        )
    else:
        counts = OverviewCounts(
            requested=0,
            confirmed=0,
            at_risk=0,
            pending_approval=0,
            execution_in_progress=0,
            awaiting_confirmation=0,
            fulfilled=0,
        )

    # 2. Fetch commitments for this tenant
    commitments = db.scalars(
        select(CommitmentRecord)
        .where(CommitmentRecord.tenant_id == context.tenant_id)
        .order_by(CommitmentRecord.updated_at.desc())
    ).all()

    # 3. Fetch failed outbox events for this tenant
    failed_events = db.scalars(
        select(OutboxEventRecord)
        .where(
            OutboxEventRecord.tenant_id == context.tenant_id,
            OutboxEventRecord.status.in_(["FAILED", "DEAD_LETTER"]),
        )
        .order_by(OutboxEventRecord.occurred_at.desc())
    ).all()

    # 4. Build attention queue
    attention_queue = build_attention_queue(commitments, failed_events)

    # 5. Build summary list
    summaries = [
        OverviewCommitmentSummary(
            commitment_id=c.commitment_id,
            order_id=c.order_id,
            customer_id=c.customer_id,
            agreement_state=AgreementState(c.agreement_state),
            feasibility_state=FeasibilityState(c.feasibility_state),
            risk_state=RiskState(c.risk_state),
            recovery_state=RecoveryState(c.recovery_state),
            fulfilment_state=FulfilmentState(c.fulfilment_state),
            commitment_version=c.commitment_version,
            terms=CommitmentTerms.model_validate(c.terms),
            evidence_refs=c.evidence_refs or [],
            updated_at=_aware(c.updated_at),
        )
        for c in commitments
    ]

    return OverviewResponse(
        tenant_id=context.tenant_id,
        actor_id=context.actor_id,
        actor_role=context.actor_role,
        integration_mode="SYNTHETIC",
        last_updated_at=datetime.now(timezone.utc),
        counts=counts,
        attention_queue=attention_queue,
        commitments=summaries,
    )
