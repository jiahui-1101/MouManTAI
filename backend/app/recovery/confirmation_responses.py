"""P3 consumer for persisted P4 rejection and counteroffer evidence.

This adapter is intentionally not registered by the production worker. P4's
current producer is explicitly SYNTHETIC_ONLY, and P5 must approve the
``recovery.replan_required`` outbox boundary before any runtime binding.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.communication.confirmation_schemas import ConfirmationBasis
from app.communication.models import (
    ConfirmationAttemptRecord,
    ConfirmationDecisionRecord,
    ConfirmationSessionRecord,
)
from app.communication.response_rules import ProposedChanges as P4ProposedChanges
from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.manager_approval import ManagerApprovalRecord
from app.core.models import (
    AuditEventRecord,
    CommitmentProposalRecord,
    CommitmentRecord,
    OutboxEventRecord,
)
from app.core.schemas import DomainEvent
from app.core.service import CommitmentService
from app.recovery.eventing import (
    P3RecoveryEventPublisherPort,
    PendingRecoveryEventPublisher,
    PlanVersionReference,
    RecoveryEventCoordinator,
    RecoveryEventType,
    ReplanRequiredPayload,
)
from app.recovery.models import (
    CustomerResponseEvidence,
    RecoveryCase,
    RecoveryCaseStatus,
    RecoveryPlanVersion,
)

from .durable_plans import DurablePlanService, RecoveryPlanRecord
from .persistence import RecoveryCaseRecord, SqlAlchemyRecoveryRepository

_RESPONSE_INTENTS = {
    "confirmation.rejected": ("REJECT", "REJECTED"),
    "confirmation.counteroffer_received": ("COUNTEROFFER", "COUNTEROFFER_RECEIVED"),
}
CONSUMER_NAME = "p3.confirmation_response.v1"


class P3ConfirmationResponseConsumer:
    """Validate source provenance, then atomically invalidate or replan P3 state."""

    def __init__(
        self,
        publisher: P3RecoveryEventPublisherPort,
        *,
        plans: DurablePlanService | None = None,
    ) -> None:
        self.publisher = publisher
        self.plans = plans or DurablePlanService()

    def __call__(self, db: Session, event: DomainEvent) -> None:
        intent, _ = self._validate_p4_evidence(db, event)

        # D-041: lock the authoritative Commitment before any P2 snapshot reads.
        commitment_row = db.scalar(
            select(CommitmentRecord)
            .where(
                CommitmentRecord.tenant_id == event.tenant_id,
                CommitmentRecord.commitment_id == event.commitment_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if commitment_row is None:
            raise DomainError("COMMITMENT_NOT_FOUND", "Confirmation commitment was not found", status_code=404)

        proposal_id = event.payload["proposal_id"]
        proposal_version = event.payload["proposal_version"]
        proposal = db.get(CommitmentProposalRecord, (event.tenant_id, proposal_id))
        (case_record, case), (plan_record, plan) = self._case_and_plan(
            db, event, proposal_id, proposal_version,
        )

        if self._already_recorded(case, event.event_id):
            return

        stale = (
            event.commitment_version != commitment_row.commitment_version
            or proposal is None
            or proposal.commitment_id != event.commitment_id
            or proposal.proposal_version != proposal_version
            or proposal.status != "ACTIVE"
            or plan_record.status in {"NEEDS_REPLAN", "SUPERSEDED"}
            or plan.core_commitment_version is None
            or plan.core_commitment_version + 1 != event.commitment_version
        )
        if stale:
            result = CustomerResponseEvidence(
                event_id=event.event_id,
                confirmation_id=event.payload["confirmation_id"],
                proposal_id=proposal_id,
                proposal_version=proposal_version,
                intent=intent,
                outcome="STALE_IGNORED",
                proposed_terms=self._counteroffer_terms(db, event) if intent == "COUNTEROFFER" else None,
                evidence_refs=list(event.payload["evidence_refs"]),
                received_at=event.occurred_at,
            )
            case.customer_response_events.append(result)
            case.evidence_refs = list(dict.fromkeys([*case.evidence_refs, *result.evidence_refs]))
            case.case_version += 1
            case.updated_at = datetime.now(UTC)
            SqlAlchemyRecoveryRepository._copy_case_columns(case_record, case)
            self._audit(db, event, intent, result, previous_status=case.status.value)
            # A stale response is retained for audit, but cannot invalidate a newer
            # plan or emit an actionable replan command.
            return

        self._require_active_approval(db, event, plan_record, plan)
        prior_status = case.status.value
        if intent == "REJECT":
            plan_record.status = "NEEDS_REPLAN"
            case.status = RecoveryCaseStatus.NEEDS_REPLAN
            case.plans = [
                item.model_copy(update={
                    "approval_state": "INVALIDATED",
                    "execution_state": "NEEDS_REPLAN",
                }) if item.plan_id == plan.plan_id and item.plan_version == plan.plan_version else item
                for item in case.plans
            ]
            result = CustomerResponseEvidence(
                event_id=event.event_id,
                confirmation_id=event.payload["confirmation_id"],
                proposal_id=proposal_id,
                proposal_version=proposal_version,
                intent="REJECT",
                outcome="REPLAN_REQUIRED",
                evidence_refs=list(event.payload["evidence_refs"]),
                received_at=event.occurred_at,
            )
            invalidated = ((plan.plan_id, plan.plan_version),)
        else:
            prior_plan_version = plan.plan_version
            counteroffer = self._counteroffer_terms(db, event)
            updated = self.plans.apply_counteroffer(
                db,
                tenant_id=event.tenant_id,
                commitment=CommitmentService().get(
                    db,
                    RequestContext(
                        tenant_id=event.tenant_id,
                        actor_id="service_p3",
                        actor_role="SERVICE",
                        correlation_id=event.correlation_id,
                        causation_id=event.event_id,
                    ),
                    event.commitment_id,
                ),
                case_record=case_record,
                case=case,
                prior_plan_record=plan_record,
                prior_plan=plan,
                proposal=proposal,
                counteroffer=counteroffer,
                response_event=event,
            )
            plan_record = updated[0]
            case = updated[1]
            plan = updated[2]
            outcome = updated[3]
            result = CustomerResponseEvidence(
                event_id=event.event_id,
                confirmation_id=event.payload["confirmation_id"],
                proposal_id=proposal_id,
                proposal_version=proposal_version,
                intent="COUNTEROFFER",
                outcome=outcome,
                proposed_terms=counteroffer,
                evidence_refs=list(event.payload["evidence_refs"]),
                received_at=event.occurred_at,
            )
            case.status = (
                RecoveryCaseStatus.OPTIONS_READY if outcome == "REPLANNED"
                else RecoveryCaseStatus.NEEDS_REPLAN
            )
            case.customer_response_events.append(result)
            case.evidence_refs = list(dict.fromkeys([*case.evidence_refs, *result.evidence_refs]))
            case.case_version += 1
            case.commitment_version = commitment_row.commitment_version
            case.commitment = CommitmentService().get(
                db,
                RequestContext(
                    tenant_id=event.tenant_id,
                    actor_id="service_p3",
                    actor_role="SERVICE",
                    correlation_id=event.correlation_id,
                    causation_id=event.event_id,
                ),
                event.commitment_id,
            )
            case.updated_at = datetime.now(UTC)
            SqlAlchemyRecoveryRepository._copy_case_columns(case_record, case)
            invalidated = ((plan.plan_id, prior_plan_version),)

        if intent == "REJECT":
            case.customer_response_events.append(result)
            case.evidence_refs = list(dict.fromkeys([*case.evidence_refs, *result.evidence_refs]))
            case.case_version += 1
            case.commitment_version = commitment_row.commitment_version
            case.commitment = CommitmentService().get(
                db,
                RequestContext(
                    tenant_id=event.tenant_id,
                    actor_id="service_p3",
                    actor_role="SERVICE",
                    correlation_id=event.correlation_id,
                    causation_id=event.event_id,
                ),
                event.commitment_id,
            )
            case.updated_at = datetime.now(UTC)
            SqlAlchemyRecoveryRepository._copy_case_columns(case_record, case)

        self._audit(db, event, intent, result, previous_status=prior_status)
        self._publish_replan_event(db, event, case, plan, result, invalidated_plan_ids=invalidated)

    @staticmethod
    def _validate_p4_evidence(db: Session, event: DomainEvent) -> tuple[str, str]:
        expected = _RESPONSE_INTENTS.get(event.event_type)
        if expected is None or not event.commitment_id or event.commitment_version is None:
            raise DomainError("P4_RESPONSE_EVENT_INVALID", "Unsupported or unbound P4 response event", status_code=422)
        intent, response_state = expected
        payload = event.payload
        required = {
            "confirmation_id", "communication_id", "outbound_id", "proposal_id", "proposal_version",
            "terms_digest", "response_state", "evidence_refs", "evidence_scope", "integration_mode",
            "decision_id", "attempt_id", "intent",
        }
        if not required.issubset(payload) or (
            payload.get("response_state") != response_state
            or payload.get("evidence_scope") != "P4_EVIDENCE_ONLY"
            or payload.get("integration_mode") != "SYNTHETIC_ONLY"
            or payload.get("intent") != intent
            or not isinstance(payload.get("proposal_version"), int)
            or not isinstance(payload.get("evidence_refs"), list)
            or not payload["evidence_refs"]
        ):
            raise DomainError("P4_RESPONSE_EVENT_INVALID", "P4 response evidence is incomplete or untrusted", status_code=422)

        source = db.get(OutboxEventRecord, event.event_id)
        if source is None or (
            source.tenant_id != event.tenant_id
            or source.event_type != event.event_type
            or source.commitment_id != event.commitment_id
            or source.commitment_version != event.commitment_version
            or source.correlation_id != event.correlation_id
            or source.causation_id != event.causation_id
            or source.payload != payload
        ):
            raise DomainError("P4_RESPONSE_SOURCE_MISSING", "P4 outbox source does not match the event", status_code=409)

        session = db.get(ConfirmationSessionRecord, (event.tenant_id, payload["confirmation_id"]))
        attempt = db.get(ConfirmationAttemptRecord, (event.tenant_id, payload["attempt_id"]))
        decision = db.get(ConfirmationDecisionRecord, (event.tenant_id, payload["decision_id"]))
        if session is None or attempt is None or decision is None:
            raise DomainError("P4_RESPONSE_SOURCE_MISSING", "P4 confirmation evidence rows are incomplete", status_code=409)
        try:
            basis = ConfirmationBasis.model_validate(session.binding)
        except Exception as exc:
            raise DomainError("P4_RESPONSE_BINDING_INVALID", "P4 binding evidence is invalid", status_code=409) from exc
        reference = basis.reference
        if (
            session.confirmation_id != payload["confirmation_id"]
            or session.communication_id != payload["communication_id"]
            or session.outbound_id != payload["outbound_id"]
            or session.state != response_state
            or session.consumed_at is None
            or decision.confirmation_id != session.confirmation_id
            or decision.attempt_id != attempt.attempt_id
            or decision.terminal_confirmation_id != session.confirmation_id
            or decision.intent != intent
            or attempt.confirmation_id != session.confirmation_id
            or attempt.evidence_refs != payload["evidence_refs"]
            or event.causation_id != attempt.inbound_message_id
            or reference.tenant_id != event.tenant_id
            or reference.commitment_id != event.commitment_id
            or reference.commitment_version != event.commitment_version
            or reference.proposal_id != payload["proposal_id"]
            or reference.proposal_version != payload["proposal_version"]
            or basis.terms_digest != payload["terms_digest"]
            or not attempt.source_digest
        ):
            raise DomainError("P4_RESPONSE_BINDING_MISMATCH", "P4 response does not match its stored proposal and evidence", status_code=409)

        audit = db.scalar(select(AuditEventRecord).where(
            AuditEventRecord.tenant_id == event.tenant_id,
            AuditEventRecord.commitment_id == event.commitment_id,
            AuditEventRecord.event_type == event.event_type,
            AuditEventRecord.correlation_id == event.correlation_id,
            AuditEventRecord.causation_id == event.causation_id,
            AuditEventRecord.new_state == payload,
        ).limit(1))
        if audit is None:
            raise DomainError("P4_RESPONSE_AUDIT_MISSING", "P4 response audit evidence is missing", status_code=409)
        return intent, response_state

    @staticmethod
    def _counteroffer_terms(db: Session, event: DomainEvent) -> dict[str, str]:
        row = db.get(ConfirmationDecisionRecord, (event.tenant_id, event.payload["decision_id"]))
        if row is None or row.proposed_changes is None:
            raise DomainError("COUNTEROFFER_TERMS_MISSING", "P4 counteroffer terms are unavailable", status_code=409)
        try:
            terms = P4ProposedChanges.model_validate(row.proposed_changes).model_dump(mode="json", exclude_none=True)
        except Exception as exc:
            raise DomainError("COUNTEROFFER_TERMS_INVALID", "P4 counteroffer terms are invalid", status_code=409) from exc
        if not terms:
            raise DomainError("COUNTEROFFER_TERMS_MISSING", "P4 counteroffer terms are empty", status_code=409)
        return terms

    @staticmethod
    def _case_and_plan(db: Session, event: DomainEvent, proposal_id: str, proposal_version: int):
        rows = db.scalars(select(RecoveryPlanRecord).where(
            RecoveryPlanRecord.tenant_id == event.tenant_id,
            RecoveryPlanRecord.commitment_id == event.commitment_id,
        ).order_by(RecoveryPlanRecord.plan_id, RecoveryPlanRecord.plan_version.desc())).all()
        matches = []
        for candidate in rows:
            try:
                plan = RecoveryPlanVersion.model_validate(candidate.payload)
            except ValidationError as exc:
                raise DomainError(
                    "RECOVERY_PLAN_INTEGRITY_ERROR",
                    "Persisted P3 plan payload is invalid",
                    status_code=500,
                ) from exc
            bound_id = plan.proposal_id or plan.plan_id
            bound_version = plan.proposal_version or plan.plan_version
            if (bound_id, bound_version) == (proposal_id, proposal_version):
                matches.append((candidate, plan))
        if len(matches) != 1:
            raise DomainError("RECOVERY_PROPOSAL_PLAN_AMBIGUOUS", "Proposal does not resolve to one persisted P3 plan", status_code=409)
        plan_record, plan = matches[0]
        case_record = db.scalar(select(RecoveryCaseRecord).where(
            RecoveryCaseRecord.tenant_id == event.tenant_id,
            RecoveryCaseRecord.case_id == plan.recovery_case_id,
            RecoveryCaseRecord.commitment_id == event.commitment_id,
        ).with_for_update())
        if case_record is None:
            raise DomainError("RECOVERY_CASE_NOT_FOUND", "P3 Recovery Case was not found", status_code=404)
        case = SqlAlchemyRecoveryRepository._case_from_record(case_record).model_copy(update={
            "trigger_events": SqlAlchemyRecoveryRepository().list_case_triggers(
                db, event.tenant_id, case_record.case_id,
            ),
        })
        if case.tenant_id != event.tenant_id or case.commitment_id != event.commitment_id:
            raise DomainError("RECOVERY_CASE_IDENTITY_CONFLICT", "P3 Recovery Case identity does not match P4", status_code=409)
        return (case_record, case), (plan_record, plan)

    @staticmethod
    def _already_recorded(case: RecoveryCase, event_id: str) -> bool:
        return any(item.event_id == event_id for item in case.customer_response_events)

    @staticmethod
    def _require_active_approval(db: Session, event: DomainEvent, plan_record: RecoveryPlanRecord,
                                 plan: RecoveryPlanVersion) -> None:
        decisions = db.scalars(select(ManagerApprovalRecord).where(
            ManagerApprovalRecord.tenant_id == event.tenant_id,
            ManagerApprovalRecord.plan_id == plan.plan_id,
            ManagerApprovalRecord.plan_version == plan.plan_version,
        ).order_by(ManagerApprovalRecord.decided_at.desc())).all()
        latest = decisions[0] if decisions else None
        expires = latest.expires_at if latest else None
        if expires is not None and expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        decided_at = latest.decided_at if latest else None
        if decided_at is not None and decided_at.tzinfo is None:
            decided_at = decided_at.replace(tzinfo=UTC)
        if (
            latest is None
            or latest.decision != "APPROVED"
            or latest.plan_id != plan.plan_id
            or latest.plan_version != plan.plan_version
            or latest.proposal_id != plan.plan_id
            or latest.proposal_version != plan.plan_version
            or latest.actor_role not in {"MANAGER", "OWNER"}
            or decided_at is None
            or decided_at > event.occurred_at
            or expires is None
            or expires < event.occurred_at
            or latest.snapshot_id != plan_record.snapshot_id
            or latest.snapshot_version != plan_record.snapshot_version
            or latest.commitment_version != plan_record.core_commitment_version
            or "CREATE_DELIVERY_CHANGE_PROPOSAL" not in latest.action_scope
        ):
            raise DomainError("P3_APPROVAL_PROVENANCE_MISSING", "Current P3 manager approval is not proven", status_code=409)

    @staticmethod
    def _audit(db: Session, event: DomainEvent, intent: str, response: CustomerResponseEvidence,
               *, previous_status: str) -> None:
        db.add(AuditEventRecord(
            audit_id=f"aud_p3_response_{uuid4().hex[:20]}",
            tenant_id=event.tenant_id,
            commitment_id=event.commitment_id or "com_none",
            event_type=f"recovery.customer_{intent.lower()}",
            actor_id="service_p3_confirmation",
            actor_role="SERVICE",
            dimension="recovery",
            previous_state={"recovery_status": previous_status},
            new_state={
                "event_id": response.event_id,
                "confirmation_id": response.confirmation_id,
                "proposal_id": response.proposal_id,
                "proposal_version": response.proposal_version,
                "intent": response.intent,
                "outcome": response.outcome,
            },
            evidence_refs=response.evidence_refs,
            reason="P3 consumed persisted P4 response evidence; Core Agreement state remains P5-owned",
            correlation_id=event.correlation_id,
            causation_id=event.event_id,
            occurred_at=event.occurred_at,
        ))

    def _publish_replan_event(self, db: Session, event: DomainEvent, case: RecoveryCase,
                              plan: RecoveryPlanVersion, response: CustomerResponseEvidence,
                              *, invalidated_plan_ids: tuple[tuple[str, int], ...]) -> None:
        reason_code = (
            "CUSTOMER_REJECTED_PROPOSAL" if response.intent == "REJECT"
            else "CUSTOMER_COUNTEROFFER_REPLANNED" if response.outcome == "REPLANNED"
            else "CUSTOMER_COUNTEROFFER_REQUIRES_MANUAL_REPLAN"
        )
        output = RecoveryEventCoordinator.prepare(
            event_type=RecoveryEventType.REPLAN_REQUIRED,
            tenant_id=event.tenant_id,
            commitment_id=event.commitment_id or "",
            commitment_version=case.commitment_version,
            recovery_case_id=case.case_id,
            plan_id=plan.plan_id,
            plan_version=plan.plan_version,
            snapshot_version=plan.snapshot_version,
            correlation_id=event.correlation_id,
            causation_id=event.event_id,
            evidence_refs=response.evidence_refs,
            payload=ReplanRequiredPayload(
                reason_code=reason_code,
                source_event_id=event.event_id,
                invalidated_plan_ids=tuple(item[0] for item in invalidated_plan_ids),
                invalidated_plan_versions=tuple(
                    PlanVersionReference(plan_id=plan_id, plan_version=version)
                    for plan_id, version in invalidated_plan_ids
                ),
            ),
            occurred_at=datetime.now(UTC),
        )
        receipt = self.publisher.publish(
            output,
            db=db,
            context=RequestContext(
                tenant_id=event.tenant_id,
                actor_id="service_p3_confirmation",
                actor_role="SERVICE",
                correlation_id=event.correlation_id,
                causation_id=event.event_id,
            ),
        )
        if receipt.status.value != "PUBLISHED":
            raise DomainError(
                "P3_REPLAN_OUTBOX_UNAVAILABLE",
                "P5 atomic replan outbox boundary is unavailable",
                status_code=503,
            )


def register_p3_confirmation_response_consumer(dispatcher, publisher: P3RecoveryEventPublisherPort) -> None:
    """Explicit integration hook for reviewed isolated workers and tests only."""
    consumer = P3ConfirmationResponseConsumer(publisher)
    for event_type in _RESPONSE_INTENTS:
        dispatcher.register_subscriber(event_type, CONSUMER_NAME, consumer)


def pending_p5_confirmation_response_consumer() -> P3ConfirmationResponseConsumer:
    """Construct the fail-closed adapter used until P5 injects its outbox boundary."""
    return P3ConfirmationResponseConsumer(PendingRecoveryEventPublisher())
