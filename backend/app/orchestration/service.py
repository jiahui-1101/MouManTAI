"""Evidence-preserving projections across the existing business authorities."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.communication.models import CommunicationRequestRecord, OutboundMessageRecord
from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.manager_approval import ManagerApprovalRecord
from app.core.models import AuditEventRecord, CommitmentRecord, OutboxEventRecord
from app.core.service import CommitmentService
from app.feasibility.impact import ImpactAssessment, ImpactClassification
from app.feasibility.persisted_sources import (
    OperationalSnapshotRecord,
    SupplierDelayEventRecord,
    _snapshot_from_record,
    read_snapshot,
)
from app.integrations.business_ports import ReservationReceipt
from app.orders.models import (
    MockOrbyteReservationRecord,
    OrderRequestAuditRecord,
    OrderRequestRecord,
)
from app.orders.status import read_status_preview
from app.orders.terms import OrderTerms
from app.recovery.durable_actions import InternalRecoveryTaskRecord, RecoveryActionExecutionRecord
from app.recovery.durable_plans import RecoveryPlanRecord
from app.recovery.persistence import RecoveryCaseRecord

from .models import BusinessImpactLinkRecord, BusinessNotificationIntentRecord
from .schemas import (
    CommitmentTimelineView,
    ImpactLinkView,
    ImpactResolutionView,
    NotificationIntentView,
    TimelineEntry,
)


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _stable_digest(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(raw.encode()).hexdigest()


def _source_resource_refs(impact_row: Any) -> list[str]:
    return sorted({
        path.resource_key.resource_id
        for path in impact_row.dependency_paths
    })


def _terms_match_source(core: Any, source_row: Any) -> bool:
    if len(source_row.lines) != 1:
        return False
    line = source_row.lines[0]
    terms = core.terms
    return (
        terms.sku == line.sku_id
        and terms.quantity == line.quantity
        and terms.unit == line.unit
        and terms.deadline == source_row.delivery_deadline
    )


def _accepted_order(db: Session, context: RequestContext, commitment_id: str,
                    source_row: Any) -> tuple[OrderRequestRecord | None, list[str], list[str]]:
    core_record = db.get(CommitmentRecord, (context.tenant_id, commitment_id))
    if core_record is None:
        return None, ["CORE_COMMITMENT_NOT_FOUND"], []
    core = CommitmentService().get(db, context, commitment_id)
    if not _terms_match_source(core, source_row):
        return None, ["P2_CORE_TERMS_MISMATCH"], []
    if core_record.agreement_state != "CONFIRMED":
        return None, ["CORE_COMMITMENT_NOT_CONFIRMED"], []
    requests = db.scalars(select(OrderRequestRecord).where(
        OrderRequestRecord.tenant_id == context.tenant_id,
        OrderRequestRecord.commitment_id == commitment_id,
        OrderRequestRecord.decision_status == "ACCEPTED",
    )).all()
    if not requests:
        return None, ["ACCEPTED_ORDER_RECORD_MISSING"], []
    if len(requests) != 1:
        return None, ["ACCEPTED_ORDER_REQUEST_NOT_UNIQUE"], []
    request = requests[0]
    try:
        accepted_terms = OrderTerms.model_validate(request.terms)
    except ValidationError:
        return None, ["ACCEPTED_ORDER_TERMS_INVALID"], []
    if accepted_terms.terms_hash != request.terms_hash:
        return None, ["ACCEPTED_ORDER_TERMS_HASH_MISMATCH"], []
    if (
        accepted_terms.tenant_id != context.tenant_id
        or accepted_terms.order_request_id != request.order_request_id
        or accepted_terms.customer_id != request.customer_id
        or len(accepted_terms.items) != 1
        or accepted_terms.items[0].sku != source_row.lines[0].sku_id
        or accepted_terms.items[0].quantity != source_row.lines[0].quantity
        or accepted_terms.items[0].unit != source_row.lines[0].unit
        or accepted_terms.window_end != source_row.delivery_deadline
    ):
        return None, ["ACCEPTED_ORDER_TERMS_P2_SOURCE_MISMATCH"], []
    try:
        status = read_status_preview(db, context, commitment_id)
    except DomainError:
        return None, ["ORDER_ACCEPTANCE_EVIDENCE_UNAVAILABLE"], []
    if not status.acceptance_verified:
        return None, ["ORDER_ACCEPTANCE_RESERVATION_AUDIT_UNVERIFIED"], []
    if (
        request.customer_id != core.customer_id
        or request.order_request_id != core_record.order_id
    ):
        return None, ["ORDER_CUSTOMER_REFERENCE_MISMATCH"], []
    reservations = db.scalars(select(MockOrbyteReservationRecord).where(
        MockOrbyteReservationRecord.tenant_id == context.tenant_id,
        MockOrbyteReservationRecord.order_request_id == request.order_request_id,
        MockOrbyteReservationRecord.status == "CONFIRMED",
    )).all()
    audits = db.scalars(select(AuditEventRecord).where(
        AuditEventRecord.tenant_id == context.tenant_id,
        AuditEventRecord.commitment_id == commitment_id,
        AuditEventRecord.event_type == "commitment.mock_order_accepted",
    )).all()
    if len(reservations) != 1 or len(audits) != 1:
        return None, ["ORDER_ACCEPTANCE_RECEIPT_NOT_UNIQUE"], []
    try:
        receipt = ReservationReceipt.model_validate(reservations[0].receipt)
    except ValidationError:
        return None, ["ORDER_RESERVATION_RECEIPT_INVALID"], []
    audit = audits[0]
    if (
        receipt.mode != "MOCK" or not receipt.reservation_confirmed
        or receipt.tenant_id != context.tenant_id
        or receipt.order_request_id != request.order_request_id
        or receipt.terms_hash != request.terms_hash
        or receipt.terms_hash != core_record.terms.get("mock_terms_hash")
        or receipt.request_version != core_record.terms.get("mock_order_request_version")
        or audit.new_state.get("reservation_operation_id") != receipt.operation_id
        or audit.new_state.get("order_request_id") != request.order_request_id
        or audit.new_state.get("terms_hash") != request.terms_hash
        or audit.new_state.get("request_version") != receipt.request_version
        or audit.actor_role not in {"OWNER", "MANAGER"}
        or not set(receipt.evidence_refs) <= set(core_record.evidence_refs)
    ):
        return None, ["ORDER_ACCEPTANCE_RECEIPT_BINDING_MISMATCH"], []
    refs = sorted({
        *request.source_evidence_refs, *receipt.evidence_refs,
        receipt.operation_id, audit.audit_id, *audit.evidence_refs,
    })
    return request, [], refs


def _p2_source_digest(payload: dict[str, Any]) -> str:
    source_fields = {
        "tenant_id": payload["tenant_id"],
        "impact_id": payload["impact_id"],
        "event_id": payload["event_id"],
        "commitment_id": payload["commitment_id"],
        "commitment_version": payload["commitment_version"],
        "classification": payload["classification"],
        "before_snapshot_id": payload["before_snapshot_id"],
        "before_snapshot_version": payload["before_snapshot_version"],
        "after_snapshot_id": payload["after_snapshot_id"],
        "after_snapshot_version": payload["after_snapshot_version"],
        "resource_refs": payload["resource_refs"],
        "p2_event_digest": payload["source_provenance"]["event_digest"],
    }
    return _stable_digest(source_fields)


def _impact_link_payload(
    db: Session, context: RequestContext, event_record: SupplierDelayEventRecord,
    impact: ImpactAssessment, impact_row: Any, source_row: Any | None,
) -> dict[str, Any]:
    reasons: list[str] = []
    request: OrderRequestRecord | None = None
    acceptance_refs: list[str] = []
    if impact_row.classification == ImpactClassification.UNKNOWN or not impact.discovery_complete:
        status = "UNRESOLVED_IMPACT"
        reasons.append("P2_IMPACT_DISCOVERY_INCOMPLETE")
    elif source_row is None:
        status = "UNRESOLVED_P2_SOURCE_COMMITMENT"
        reasons.append("P2_BEFORE_SNAPSHOT_HAS_NO_EXACT_COMMITMENT")
    elif impact_row.before_commitment_version != source_row.commitment_version:
        status = "UNRESOLVED_COMMITMENT_TERMS"
        reasons.append("P2_IMPACT_COMMITMENT_VERSION_MISMATCH")
    else:
        request, reasons, acceptance_refs = _accepted_order(db, context, impact_row.commitment_id, source_row)
        if request is None:
            status = "UNRESOLVED_ORDER_ACCEPTANCE"
        elif impact_row.classification == ImpactClassification.CONFIRMED_IMPACT:
            status = "LINKED_ACCEPTED_ORDER"
        else:
            status = "LINKED_ACCEPTED_ORDER_UNAFFECTED"

    outbox = db.get(OutboxEventRecord, event_record.event_id)
    event_payload = outbox.payload if outbox is not None and outbox.tenant_id == context.tenant_id else {}
    resource_refs = _source_resource_refs(impact_row)
    p2_evidence_refs = sorted({
        *impact_row.evidence_refs,
        event_record.evidence_ref,
        *event_payload.get("evidence_refs", []),
    })
    evidence_refs = sorted({
        *p2_evidence_refs,
        *acceptance_refs,
    })
    impact_version = impact_row.after_commitment_version or impact_row.before_commitment_version
    return {
        "schema_version": 1,
        "tenant_id": context.tenant_id,
        "impact_id": impact.impact_id,
        "event_id": event_record.event_id,
        "idempotency_key": event_record.event_id,
        "correlation_id": impact.correlation_id,
        "commitment_id": impact_row.commitment_id,
        "commitment_version": impact_version,
        "classification": impact_row.classification.value,
        "link_status": status,
        "order_request_id": request.order_request_id if request is not None else None,
        "order_request_version": request.request_version if request is not None else None,
        "customer_ref": request.customer_id if request is not None else None,
        "before_snapshot_id": impact.before_snapshot_id,
        "before_snapshot_version": impact.before_snapshot_version,
        "after_snapshot_id": impact.after_snapshot_id,
        "after_snapshot_version": impact.after_snapshot_version,
        "resource_refs": resource_refs,
        "evidence_refs": evidence_refs,
        "reason_codes": reasons,
        "source_provenance": {
            "p2_event_id": event_record.event_id,
            "event_digest": event_record.event_digest,
            "p2_evidence_ref": event_record.evidence_ref,
            "p2_before_snapshot": impact.before_snapshot_id,
            "p2_after_snapshot": impact.after_snapshot_id,
            "dependency_path_count": len(impact_row.dependency_paths),
        },
        "authorization_context": {
            "actor_id": context.actor_id,
            "actor_role": context.actor_role,
            "authority": "P5_READ_SIDE_LINK_ONLY",
        },
        "occurred_at": _utc(event_record.occurred_at).isoformat(),
        "integration_mode": "SYNTHETIC",
        "evidence_tier": "DEMO-ONLY",
    }


def _link_view(row: BusinessImpactLinkRecord) -> ImpactLinkView:
    return ImpactLinkView.model_validate(row.projection)


def resolve_impact_links(
    db: Session, context: RequestContext, impact_id: str,
) -> ImpactResolutionView:
    event_rows = db.scalars(select(SupplierDelayEventRecord).where(
        SupplierDelayEventRecord.tenant_id == context.tenant_id,
        SupplierDelayEventRecord.impact_id == impact_id,
    ).with_for_update()).all()
    if len(event_rows) != 1:
        raise DomainError("IMPACT_NOT_FOUND", "Persisted P2 impact was not found", status_code=404)
    event_record = event_rows[0]
    try:
        impact = ImpactAssessment.model_validate(event_record.impact_payload)
    except Exception as exc:
        raise DomainError("P2_IMPACT_CORRUPT", "Persisted P2 impact is invalid", status_code=500) from exc
    if impact.tenant_id != context.tenant_id or impact.impact_id != impact_id:
        raise DomainError("TENANT_SCOPE_MISMATCH", "Persisted impact identity does not match", status_code=403)

    before_record = db.get(OperationalSnapshotRecord, (
        context.tenant_id, event_record.before_snapshot_version,
    ))
    before = _snapshot_from_record(before_record) if before_record is not None else None
    source_by_commitment = {
        row.commitment_id: row for row in before.operational.confirmed_commitments
    } if before is not None else {}

    stored: list[BusinessImpactLinkRecord] = []
    unresolved = not impact.discovery_complete or not impact.impacts
    for impact_row in impact.impacts:
        if impact_row.tenant_id != context.tenant_id:
            raise DomainError("TENANT_SCOPE_MISMATCH", "P2 impact contains a foreign tenant", status_code=403)
        payload = _impact_link_payload(
            db, context, event_record, impact, impact_row,
            source_by_commitment.get(impact_row.commitment_id),
        )
        payload_json = json.loads(json.dumps(payload, sort_keys=True))
        digest = _p2_source_digest(payload_json)
        existing = db.get(BusinessImpactLinkRecord, (
            context.tenant_id, impact_id, impact_row.commitment_id,
        ))
        if existing is not None:
            if existing.source_digest != digest:
                raise DomainError("ORCHESTRATION_SOURCE_CONFLICT", "Persisted P2 impact source changed", status_code=409)
            can_reconcile = (
                existing.link_status.startswith("UNRESOLVED")
                and payload["link_status"].startswith("LINKED")
            )
            if can_reconcile:
                prior_status = existing.link_status
                existing.link_status = payload["link_status"]
                existing.classification = payload["classification"]
                existing.commitment_version = payload["commitment_version"]
                existing.evidence_refs = payload["evidence_refs"]
                existing.resource_refs = payload["resource_refs"]
                existing.reason_codes = payload["reason_codes"]
                existing.projection = payload_json
                db.add(AuditEventRecord(
                    audit_id=f"aud_{uuid4().hex[:16]}", tenant_id=context.tenant_id,
                    commitment_id=impact_row.commitment_id,
                    event_type="orchestration.impact_link_reconciled",
                    actor_id=context.actor_id, actor_role=context.actor_role,
                    dimension="orchestration",
                    previous_state={"impact_id": impact_id, "link_status": prior_status},
                    new_state={"impact_id": impact_id, "event_id": event_record.event_id,
                               "link_status": payload["link_status"],
                               "commitment_version": payload["commitment_version"]},
                    evidence_refs=payload["evidence_refs"],
                    reason="Previously unresolved linkage reconciled with exact accepted-order evidence",
                    correlation_id=impact.correlation_id, causation_id=event_record.event_id,
                    occurred_at=datetime.now(UTC),
                ))
            stored.append(existing)
            unresolved = unresolved or existing.link_status.startswith("UNRESOLVED")
            continue
        link = BusinessImpactLinkRecord(
            tenant_id=context.tenant_id, impact_id=impact_id,
            commitment_id=impact_row.commitment_id, event_id=event_record.event_id,
            commitment_version=payload["commitment_version"],
            link_status=payload["link_status"], classification=payload["classification"],
            evidence_refs=payload["evidence_refs"], resource_refs=payload["resource_refs"],
            reason_codes=payload["reason_codes"], projection=payload_json,
            source_digest=digest, created_at=datetime.now(UTC),
        )
        db.add(link)
        audit_id = f"aud_{uuid4().hex[:16]}"
        db.add(AuditEventRecord(
            audit_id=audit_id, tenant_id=context.tenant_id,
            commitment_id=impact_row.commitment_id,
            event_type=("orchestration.impact_linked" if payload["link_status"].startswith("LINKED")
                        else "orchestration.impact_link_unresolved"),
            actor_id=context.actor_id, actor_role=context.actor_role,
            dimension="orchestration", previous_state=None,
            new_state={"impact_id": impact_id, "event_id": event_record.event_id,
                       "link_status": payload["link_status"],
                       "commitment_version": payload["commitment_version"]},
            evidence_refs=payload["evidence_refs"],
            reason=("Exact P2 impact linkage materialized; no business state changed"
                    if payload["link_status"].startswith("LINKED")
                    else "Impact linkage unresolved; human evidence review required"),
            correlation_id=impact.correlation_id, causation_id=event_record.event_id,
            occurred_at=datetime.now(UTC),
        ))
        stored.append(link)
        unresolved = unresolved or payload["link_status"].startswith("UNRESOLVED")

    db.flush()
    return ImpactResolutionView(
        tenant_id=context.tenant_id, impact_id=impact_id, event_id=event_record.event_id,
        discovery_complete=impact.discovery_complete,
        overall_status="UNRESOLVED_HUMAN_REVIEW" if unresolved else "LINKED",
        links=[_link_view(row) for row in stored],
    )


def consume_verified_recovery_task(db: Session, event: Any) -> None:
    """Create a pending P4 handoff only from the exact verified P3 task receipt."""
    if event.event_type != "recovery.internal_task_created" or not event.commitment_id:
        raise DomainError("ORCHESTRATION_EVENT_INVALID", "Expected a recovery task event with a commitment", status_code=409)
    outbox = db.get(OutboxEventRecord, event.event_id)
    if outbox is None or (
        outbox.tenant_id != event.tenant_id
        or outbox.event_type != event.event_type
        or outbox.commitment_id != event.commitment_id
        or outbox.commitment_version != event.commitment_version
        or outbox.correlation_id != event.correlation_id
        or outbox.payload != event.payload
    ):
        raise DomainError("ORCHESTRATION_EVENT_UNVERIFIED", "Persisted outbox event differs from delivery", status_code=409)
    payload = event.payload
    required = ("plan_id", "approval_id", "task_id", "audit_id", "receipt_ref")
    if any(not isinstance(payload.get(key), str) or not payload[key] for key in required):
        raise DomainError("ORCHESTRATION_EVENT_INVALID", "Recovery event is missing exact receipt references", status_code=409)
    existing = db.scalar(select(BusinessNotificationIntentRecord).where(
        BusinessNotificationIntentRecord.tenant_id == event.tenant_id,
        BusinessNotificationIntentRecord.source_event_id == event.event_id,
    ))
    if existing is not None:
        if (existing.commitment_id, existing.receipt_ref, existing.audit_id) != (
            event.commitment_id, payload["receipt_ref"], payload["audit_id"],
        ):
            raise DomainError("NOTIFICATION_INTENT_EVENT_CONFLICT", "Event ID refers to different receipt data", status_code=409)
        return

    task = db.get(InternalRecoveryTaskRecord, (event.tenant_id, payload["task_id"]))
    if (task is None or task.status != "OPEN" or task.commitment_id != event.commitment_id
            or task.task_type != "INTERNAL_REVIEW"):
        raise DomainError("RECOVERY_TASK_RECEIPT_UNVERIFIED", "Persisted internal task does not match event", status_code=409)
    if task.plan_id != payload["plan_id"]:
        raise DomainError("RECOVERY_TASK_RECEIPT_UNVERIFIED", "Task plan reference differs from event", status_code=409)
    if task.payload.get("plan_id") != task.plan_id or task.payload.get("approved_by") is None:
        raise DomainError("RECOVERY_TASK_RECEIPT_UNVERIFIED", "Task payload lacks its exact plan and approving actor", status_code=409)
    plan = db.get(RecoveryPlanRecord, (event.tenant_id, task.plan_id, task.plan_version))
    if plan is None or plan.commitment_id != event.commitment_id:
        raise DomainError("RECOVERY_PLAN_RECEIPT_UNVERIFIED", "Persisted plan does not match task", status_code=409)
    commitment = db.get(CommitmentRecord, (event.tenant_id, event.commitment_id))
    if commitment is None or event.commitment_version != commitment.commitment_version:
        raise DomainError("RECOVERY_EXECUTION_VERSION_UNVERIFIED", "Core commitment differs from the execution event", status_code=409)
    approval = db.get(ManagerApprovalRecord, (event.tenant_id, payload["approval_id"]))
    if approval is None or (
        approval.commitment_id != event.commitment_id
        or approval.plan_id != task.plan_id
        or approval.plan_version != task.plan_version
        or approval.decision != "APPROVED"
        or approval.actor_role not in {"OWNER", "MANAGER"}
        or task.payload.get("approved_by") != approval.actor_id
    ):
        raise DomainError("RECOVERY_APPROVAL_RECEIPT_UNVERIFIED", "Approval does not authorize this exact task", status_code=409)
    audits = db.scalars(select(AuditEventRecord).where(
        AuditEventRecord.tenant_id == event.tenant_id,
        AuditEventRecord.audit_id == payload["audit_id"],
        AuditEventRecord.commitment_id == event.commitment_id,
        AuditEventRecord.event_type == "recovery.internal_task_created",
    )).all()
    if len(audits) != 1:
        raise DomainError("RECOVERY_AUDIT_RECEIPT_UNVERIFIED", "Core audit receipt is unavailable", status_code=409)
    audit = audits[0]
    if (
        audit.new_state.get("plan_id") != task.plan_id
        or audit.new_state.get("approval_id") != approval.approval_id
        or audit.new_state.get("task_id") != task.task_id
        or audit.correlation_id != event.correlation_id
        or audit.causation_id != event.causation_id
        or payload["receipt_ref"] not in audit.evidence_refs
        or approval.approval_id not in audit.evidence_refs
    ):
        raise DomainError("RECOVERY_AUDIT_RECEIPT_UNVERIFIED", "Core audit does not bind the exact task and approval", status_code=409)
    executions = db.scalars(select(RecoveryActionExecutionRecord).where(
        RecoveryActionExecutionRecord.tenant_id == event.tenant_id,
        RecoveryActionExecutionRecord.commitment_id == event.commitment_id,
        RecoveryActionExecutionRecord.plan_id == task.plan_id,
        RecoveryActionExecutionRecord.plan_version == task.plan_version,
        RecoveryActionExecutionRecord.approval_id == approval.approval_id,
        RecoveryActionExecutionRecord.task_id == task.task_id,
        RecoveryActionExecutionRecord.receipt_ref == payload["receipt_ref"],
        RecoveryActionExecutionRecord.audit_id == audit.audit_id,
        RecoveryActionExecutionRecord.status == "SUCCEEDED",
    )).all()
    if len(executions) != 1:
        raise DomainError("RECOVERY_EXECUTION_RECEIPT_UNVERIFIED", "P3 execution does not verify the exact task receipt", status_code=409)
    if event.commitment_version is None or event.commitment_version != plan.core_commitment_version:
        raise DomainError("RECOVERY_EXECUTION_VERSION_UNVERIFIED", "Execution event commitment version differs from plan", status_code=409)

    request_context = RequestContext(
        tenant_id=event.tenant_id, actor_id="service_core", actor_role="SERVICE",
        correlation_id=event.correlation_id, causation_id=event.event_id,
    )
    acceptance_verified = False
    customer_ref = None
    accepted_request = None
    acceptance_refs: list[str] = []
    try:
        source_snapshot = read_snapshot(db, event.tenant_id, plan.snapshot_version)
        source_commitment = next((row for row in source_snapshot.operational.confirmed_commitments
                                  if row.commitment_id == event.commitment_id), None)
        if source_commitment is not None:
            accepted_request, _, acceptance_refs = _accepted_order(
                db, request_context, event.commitment_id, source_commitment,
            )
            acceptance_verified = accepted_request is not None
    except DomainError:
        acceptance_verified = False
    if acceptance_verified and accepted_request is not None:
        customer_ref = accepted_request.customer_id
    blockers = [
        "INTERNAL_REVIEW_TASK_IS_NOT_A_CUSTOMER_VISIBLE_MILESTONE",
        "NO_STATUS_UPDATE_CHANNEL_OR_PURPOSE_SPECIFIC_CONSENT_BOUND",
    ]
    review_requirements = [
        "P4_OWNER_REVIEW_OF_STATUS_MILESTONE_CONTRACT",
        "HUMAN_REVIEW_BEFORE_ANY_DRAFT",
        "EXISTING_P4_SEND_AUTHORIZATION_REQUIRED",
    ]
    if not acceptance_verified:
        blockers.append("ORDER_ACCEPTANCE_EVIDENCE_UNRESOLVED")
    status = "PENDING_P4_REVIEW" if acceptance_verified else "UNRESOLVED_ORDER_ACCEPTANCE"
    evidence_refs = sorted({
        payload["receipt_ref"], approval.approval_id, audit.audit_id,
        *audit.evidence_refs, *acceptance_refs,
    })
    intent_id = f"ni_{uuid4().hex[:16]}"
    intent = BusinessNotificationIntentRecord(
        tenant_id=event.tenant_id, intent_id=intent_id,
        source_event_id=event.event_id, commitment_id=event.commitment_id,
        idempotency_key=event.event_id,
        commitment_version=event.commitment_version, correlation_id=event.correlation_id,
        causation_id=event.causation_id, source_event_type=event.event_type,
        notification_type="recovery_internal_review_created", status=status,
        blocker_codes=blockers, review_requirements=review_requirements,
        plan_id=task.plan_id, plan_version=task.plan_version,
        approval_id=approval.approval_id, task_id=task.task_id,
        receipt_ref=payload["receipt_ref"], audit_id=audit.audit_id,
        order_request_id=accepted_request.order_request_id if accepted_request else None,
        order_request_version=accepted_request.request_version if accepted_request else None,
        customer_ref=customer_ref, contact_ref=None, channel_ref=None,
        original_channel_ref=None, consent_ref=None,
        verified_change={
            "change_type": "INTERNAL_REVIEW_TASK_CREATED",
            "task_id": task.task_id,
            "task_status": task.status,
            "fulfillment_changed": False,
            "customer_terms_changed": False,
            "customer_visible_milestone_verified": False,
        },
        evidence_refs=evidence_refs,
        source_provenance={
            "p3_event_id": event.event_id,
            "p3_plan_id": plan.plan_id,
            "p3_plan_version": plan.plan_version,
            "p2_snapshot_id": plan.snapshot_id,
            "p2_snapshot_version": plan.snapshot_version,
            "core_audit_id": audit.audit_id,
        },
        authorization_context={
            "approval_id": approval.approval_id,
            "approved_by_actor_id": approval.actor_id,
            "approved_by_role": approval.actor_role,
            "plan_id": task.plan_id,
            "plan_version": task.plan_version,
            "authorization_source": "P3_MANAGER_APPROVAL",
        },
        integration_mode="SYNTHETIC", evidence_tier="DEMO-ONLY",
        verification_status="INTERNALLY-VERIFIED", created_at=datetime.now(UTC),
    )
    db.add(intent)
    db.add(AuditEventRecord(
        audit_id=f"aud_{uuid4().hex[:16]}", tenant_id=event.tenant_id,
        commitment_id=event.commitment_id,
        event_type="orchestration.notification_intent_created",
        actor_id="service_p5_orchestration", actor_role="SERVICE",
        dimension="communication", previous_state=None,
        new_state={"intent_id": intent_id, "status": status,
                   "notification_type": intent.notification_type,
                   "commitment_version": event.commitment_version},
        evidence_refs=evidence_refs,
        reason="Pending P4 handoff recorded; no message was drafted or sent",
        correlation_id=event.correlation_id, causation_id=event.event_id,
        occurred_at=datetime.now(UTC),
    ))


def notification_intent(db: Session, context: RequestContext, intent_id: str) -> NotificationIntentView:
    row = db.scalar(select(BusinessNotificationIntentRecord).where(
        BusinessNotificationIntentRecord.tenant_id == context.tenant_id,
        BusinessNotificationIntentRecord.intent_id == intent_id,
    ))
    if row is None:
        raise DomainError("NOTIFICATION_INTENT_NOT_FOUND", "Notification intent was not found", status_code=404)
    return _intent_view(row)


def _intent_view(row: BusinessNotificationIntentRecord) -> NotificationIntentView:
    created = _utc(row.created_at)
    return NotificationIntentView(
        intent_id=row.intent_id, tenant_id=row.tenant_id,
        source_event_id=row.source_event_id, idempotency_key=row.idempotency_key,
        source_event_type=row.source_event_type,
        correlation_id=row.correlation_id, causation_id=row.causation_id,
        commitment_id=row.commitment_id, commitment_version=row.commitment_version,
        notification_type=row.notification_type, status=row.status,
        blocker_codes=row.blocker_codes, review_requirements=row.review_requirements,
        customer_ref=row.customer_ref,
        order_request_id=row.order_request_id,
        order_request_version=row.order_request_version,
        contact_ref=row.contact_ref, channel_ref=row.channel_ref,
        original_channel_ref=row.original_channel_ref, consent_ref=row.consent_ref,
        verified_change=row.verified_change, evidence_refs=row.evidence_refs,
        source_provenance=row.source_provenance,
        authorization_context=row.authorization_context, integration_mode=row.integration_mode,
        evidence_tier=row.evidence_tier, verification_status=row.verification_status,
        created_at=created,
    )


def _entry(
    *, event_id: str, event_type: str, status: str, entity_id: str,
    commitment_id: str, commitment_version: int | None, occurred_at: datetime,
    correlation_id: str | None = None,
    evidence_refs: list[str] | tuple[str, ...] = (), source_provenance: dict[str, Any] | None = None,
    authorization_context: dict[str, Any] | None = None,
    integration_mode: str = "SYNTHETIC", evidence_tier: str = "DEMO-ONLY",
) -> TimelineEntry:
    return TimelineEntry(
        event_id=event_id, correlation_id=correlation_id,
        event_type=event_type, status=status, entity_id=entity_id,
        commitment_id=commitment_id, commitment_version=commitment_version,
        occurred_at=_utc(occurred_at), evidence_refs=sorted(set(evidence_refs)),
        source_provenance=source_provenance or {},
        authorization_context=authorization_context or {},
        integration_mode=integration_mode, evidence_tier=evidence_tier,
    )


def commitment_timeline(
    db: Session, context: RequestContext, commitment_id: str,
) -> CommitmentTimelineView:
    core = db.get(CommitmentRecord, (context.tenant_id, commitment_id))
    if core is None:
        raise DomainError("COMMITMENT_NOT_FOUND", "Commitment was not found", status_code=404)
    entries: list[TimelineEntry] = []

    for audit in db.scalars(select(AuditEventRecord).where(
        AuditEventRecord.tenant_id == context.tenant_id,
        AuditEventRecord.commitment_id == commitment_id,
    )).all():
        version = audit.new_state.get("commitment_version") if isinstance(audit.new_state, dict) else None
        approval_id = audit.new_state.get("approval_id") if isinstance(audit.new_state, dict) else None
        audit_status = (audit.new_state.get("link_status", "RECORDED")
                        if isinstance(audit.new_state, dict) else "RECORDED")
        entries.append(_entry(
            event_id=audit.audit_id, event_type=audit.event_type,
            status=audit_status, entity_id=audit.audit_id,
            correlation_id=audit.correlation_id,
            commitment_id=commitment_id, commitment_version=version if isinstance(version, int) else None,
            occurred_at=audit.occurred_at, evidence_refs=audit.evidence_refs,
            source_provenance={"store": "core.audit_events", "dimension": audit.dimension},
            authorization_context={"actor_id": audit.actor_id, "actor_role": audit.actor_role,
                                  "approval_id": approval_id},
            evidence_tier="INTERNALLY-VERIFIED" if audit.event_type.startswith("recovery.") else "DEMO-ONLY",
        ))

    for order_audit in db.scalars(select(OrderRequestRecord).where(
        OrderRequestRecord.tenant_id == context.tenant_id,
        OrderRequestRecord.commitment_id == commitment_id,
    )).all():
        for row in db.scalars(select(OrderRequestAuditRecord).where(
            OrderRequestAuditRecord.tenant_id == context.tenant_id,
            OrderRequestAuditRecord.order_request_id == order_audit.order_request_id,
        )).all():
            entries.append(_entry(
                event_id=row.audit_id, event_type=f"order.{row.event_type.lower()}",
                status=order_audit.decision_status, entity_id=order_audit.order_request_id,
                commitment_id=commitment_id, commitment_version=row.request_version,
                occurred_at=row.occurred_at, evidence_refs=row.evidence_refs,
                source_provenance={"store": "order_request_audit", "source_id": order_audit.source_id,
                                  "source_version": order_audit.source_version},
                authorization_context={"actor_id": row.actor_id},
                integration_mode="MOCK", evidence_tier="DEMO-ONLY",
            ))

    delay_events = db.scalars(select(SupplierDelayEventRecord).where(
        SupplierDelayEventRecord.tenant_id == context.tenant_id,
    )).all()
    for row in delay_events:
        try:
            impact = ImpactAssessment.model_validate(row.impact_payload)
        except ValidationError:
            # A corrupt P2 payload cannot safely be assigned to this commitment.
            continue
        match = next((item for item in impact.impacts if item.commitment_id == commitment_id), None)
        if match is None:
            continue
        entries.append(_entry(
            event_id=row.event_id, event_type=impact.event_type.value,
            status=match.classification.value, entity_id=impact.impact_id,
            correlation_id=impact.correlation_id,
            commitment_id=commitment_id,
            commitment_version=match.after_commitment_version or match.before_commitment_version,
            occurred_at=row.occurred_at,
            evidence_refs=sorted({row.evidence_ref, *match.evidence_refs}),
            source_provenance={"store": "p2_supplier_delay_events",
                              "before_snapshot_id": impact.before_snapshot_id,
                              "before_snapshot_version": impact.before_snapshot_version,
                              "after_snapshot_id": impact.after_snapshot_id,
                              "after_snapshot_version": impact.after_snapshot_version},
        ))

    for case in db.scalars(select(RecoveryCaseRecord).where(
        RecoveryCaseRecord.tenant_id == context.tenant_id,
        RecoveryCaseRecord.commitment_id == commitment_id,
    )).all():
        entries.append(_entry(
            event_id=case.opening_event_id, event_type="recovery.case_opened",
            status=case.status, entity_id=case.case_id, commitment_id=commitment_id,
            commitment_version=case.commitment_version, occurred_at=case.created_at,
            evidence_refs=list(case.case_payload.get("trigger_evidence_refs", [])),
            source_provenance={"store": "recovery_cases", "risk_episode_id": case.risk_episode_id},
        ))
    for plan in db.scalars(select(RecoveryPlanRecord).where(
        RecoveryPlanRecord.tenant_id == context.tenant_id,
        RecoveryPlanRecord.commitment_id == commitment_id,
    )).all():
        entries.append(_entry(
            event_id=f"{plan.plan_id}:v{plan.plan_version}", event_type="recovery.plan_created",
            status=plan.status, entity_id=plan.plan_id, commitment_id=commitment_id,
            commitment_version=plan.core_commitment_version, occurred_at=plan.created_at,
            evidence_refs=list(plan.payload.get("evidence_refs", [])),
            source_provenance={"store": "recovery_plan_versions", "case_id": plan.case_id,
                              "snapshot_id": plan.snapshot_id, "snapshot_version": plan.snapshot_version},
            authorization_context={"approval_required": True},
        ))
        for approval in db.scalars(select(ManagerApprovalRecord).where(
            ManagerApprovalRecord.tenant_id == context.tenant_id,
            ManagerApprovalRecord.plan_id == plan.plan_id,
            ManagerApprovalRecord.plan_version == plan.plan_version,
        )).all():
            entries.append(_entry(
                event_id=approval.approval_id, event_type="recovery.plan_approval",
                status=approval.decision, entity_id=approval.approval_id,
                commitment_id=commitment_id, commitment_version=approval.commitment_version,
                occurred_at=approval.decided_at,
                evidence_refs=[approval.audit_id],
                source_provenance={"store": "manager_approval_decisions", "plan_id": plan.plan_id,
                                  "plan_version": plan.plan_version, "action_scope": approval.action_scope},
                authorization_context={"actor_id": approval.actor_id, "actor_role": approval.actor_role,
                                      "approval_id": approval.approval_id},
                evidence_tier="INTERNALLY-VERIFIED",
            ))

    executions = db.scalars(select(RecoveryActionExecutionRecord).where(
        RecoveryActionExecutionRecord.tenant_id == context.tenant_id,
        RecoveryActionExecutionRecord.commitment_id == commitment_id,
    )).all()
    for execution in executions:
        execution_plan = db.get(RecoveryPlanRecord, (
            context.tenant_id, execution.plan_id, execution.plan_version,
        ))
        entries.append(_entry(
            event_id=execution.execution_id, event_type="recovery.action_execution",
            status=execution.status, entity_id=execution.execution_id,
            commitment_id=commitment_id,
            commitment_version=execution_plan.core_commitment_version if execution_plan is not None else None,
            occurred_at=execution.updated_at,
            evidence_refs=[ref for ref in (execution.receipt_ref, execution.audit_id, execution.approval_id) if ref],
            source_provenance={"store": "recovery_action_executions", "plan_id": execution.plan_id,
                              "plan_version": execution.plan_version, "task_id": execution.task_id},
            authorization_context={"approval_id": execution.approval_id},
            evidence_tier="INTERNALLY-VERIFIED" if execution.status == "SUCCEEDED" else "DEMO-ONLY",
        ))

    for intent in db.scalars(select(BusinessNotificationIntentRecord).where(
        BusinessNotificationIntentRecord.tenant_id == context.tenant_id,
        BusinessNotificationIntentRecord.commitment_id == commitment_id,
    )).all():
        entries.append(_entry(
            event_id=intent.source_event_id, event_type="communication.notification_intent",
            status=intent.status, entity_id=intent.intent_id, commitment_id=commitment_id,
            correlation_id=intent.correlation_id,
            commitment_version=intent.commitment_version, occurred_at=intent.created_at,
            evidence_refs=intent.evidence_refs,
            source_provenance={"store": "business_orchestration_notification_intents",
                              "source_event_id": intent.source_event_id,
                              "delivery_status": "NOT_SENT", "blocker_codes": intent.blocker_codes},
            authorization_context=intent.authorization_context,
        ))

    communication_rows = db.scalars(select(CommunicationRequestRecord).where(
        CommunicationRequestRecord.tenant_id == context.tenant_id,
        CommunicationRequestRecord.commitment_id == commitment_id,
    )).all()
    for comm in communication_rows:
        reference = comm.snapshot.get("reference", {}) if isinstance(comm.snapshot, dict) else {}
        entries.append(_entry(
            event_id=comm.communication_id, event_type="communication.request",
            status=comm.request_status, entity_id=comm.communication_id,
            commitment_id=commitment_id, commitment_version=reference.get("commitment_version"),
            occurred_at=comm.created_at,
            evidence_refs=list(comm.snapshot.get("approval_evidence_refs", []))
            + list(comm.snapshot.get("proposal_evidence_refs", [])),
            source_provenance={"store": "communication_requests", "proposal_id": comm.proposal_id,
                              "proposal_version": comm.proposal_version},
            integration_mode="MIXED", evidence_tier="DEMO-ONLY",
        ))
        for outbound in db.scalars(select(OutboundMessageRecord).where(
            OutboundMessageRecord.tenant_id == context.tenant_id,
            OutboundMessageRecord.communication_id == comm.communication_id,
        )).all():
            entries.append(_entry(
                event_id=outbound.outbound_id, event_type="communication.outbound_status",
                status=outbound.status, entity_id=outbound.outbound_id,
                commitment_id=commitment_id, commitment_version=reference.get("commitment_version"),
                occurred_at=outbound.updated_at,
                evidence_refs=list((outbound.authorization_evidence or {}).get("evidence_refs", [])),
                source_provenance={"store": "communication_outbound_messages",
                                  "provider_confirmed": outbound.provider_confirmed},
                integration_mode="MIXED",
                evidence_tier="INTERNALLY-VERIFIED" if outbound.provider_confirmed else "DEMO-ONLY",
            ))

    entries.sort(key=lambda item: (item.occurred_at, item.event_id))
    unresolved = any(
        entry.status == "UNRESOLVED_ORDER_ACCEPTANCE"
        or entry.status == "UNRESOLVED_HUMAN_REVIEW"
        or entry.status.startswith("UNRESOLVED_")
        or entry.status == "UNKNOWN"
        for entry in entries
    )
    return CommitmentTimelineView(
        tenant_id=context.tenant_id, commitment_id=commitment_id,
        current_commitment_version=core.commitment_version,
        overall_readiness="UNRESOLVED_HUMAN_REVIEW" if unresolved else "PARTIAL",
        entries=entries,
    )


def list_notification_intents(
    db: Session, context: RequestContext, commitment_id: str,
) -> list[NotificationIntentView]:
    rows = db.scalars(select(BusinessNotificationIntentRecord).where(
        BusinessNotificationIntentRecord.tenant_id == context.tenant_id,
        BusinessNotificationIntentRecord.commitment_id == commitment_id,
    ).order_by(BusinessNotificationIntentRecord.created_at)).all()
    return [_intent_view(row) for row in rows]
