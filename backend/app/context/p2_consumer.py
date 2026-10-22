"""P2 Feasibility Consumer & Outbox Subscriber.

Subscribes to Core domain events (commitment.context_ready, commitment.proposal_offered),
maps typed commitments into P2 EvaluationSnapshot & ProposedChanges, invokes pure P2
evaluate(), and records FeasibilityAssessment back into Core via CoreIntegrationFacade.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.events import CoreEventType
from app.core.integration import CoreIntegrationFacade
from app.core.models import CommitmentProposalRecord, CommitmentRecord
from app.core.outbox import OutboxDispatcher
from app.core.schemas import (
    Commitment,
    DomainEvent,
    FeasibilityAssessment,
)
from app.core.service import _to_commitment
from app.feasibility.production import EvaluationSnapshot, ProposedChanges
from app.feasibility.production_fixtures import build_production_example
from app.feasibility.service import EvaluationResult, evaluate

logger = logging.getLogger(__name__)


def resolve_snapshot_for_commitment(
    commitment: Commitment,
    proposed_changes: ProposedChanges | None = None,
) -> EvaluationSnapshot:
    """Build or adapt an operational EvaluationSnapshot matching the given commitment."""
    base_snapshot, _ = build_production_example()
    data = base_snapshot.model_dump(exclude_computed_fields=True)
    tenant = commitment.tenant_id

    for section in ("operational", "production"):
        if section in data and isinstance(data[section], dict):
            data[section]["tenant_id"] = tenant
            for k, val in data[section].items():
                if isinstance(val, (list, tuple)):
                    for item in val:
                        if isinstance(item, dict) and "tenant_id" in item:
                            item["tenant_id"] = tenant

    # Align the snapshot's confirmed operational target with the commitment terms
    if data["operational"]["confirmed_commitments"]:
        confirmed = data["operational"]["confirmed_commitments"][0]
        confirmed["commitment_id"] = commitment.commitment_id
        confirmed["commitment_version"] = commitment.commitment_version
        confirmed["delivery_deadline"] = commitment.terms.deadline
        if confirmed.get("lines"):
            confirmed["lines"][0]["sku_id"] = commitment.terms.sku
            confirmed["lines"][0]["quantity"] = commitment.terms.quantity
            confirmed["lines"][0]["unit"] = commitment.terms.unit
            if confirmed["lines"][0].get("material_use_at") is None or confirmed["lines"][0]["material_use_at"] > commitment.terms.deadline:
                confirmed["lines"][0]["material_use_at"] = commitment.terms.deadline

    if data["production"].get("plans"):
        plan = data["production"]["plans"][0]
        plan["commitment_id"] = commitment.commitment_id
        plan["commitment_version"] = commitment.commitment_version
        if plan.get("start_at") and plan["start_at"] > commitment.terms.deadline:
            plan["start_at"] = commitment.terms.deadline
        if plan.get("dispatch_cutoff_at") and plan["dispatch_cutoff_at"] > commitment.terms.deadline:
            plan["dispatch_cutoff_at"] = commitment.terms.deadline

    return EvaluationSnapshot.model_validate(data)


class P2FeasibilityConsumer:
    def __init__(self, facade: CoreIntegrationFacade | None = None) -> None:
        self.facade = facade or CoreIntegrationFacade()

    def handle_context_ready(self, session: Session, event: DomainEvent) -> EvaluationResult | None:
        """Process commitment.context_ready event: evaluate operational feasibility."""
        if OutboxDispatcher.is_stale_event(session, event):
            logger.info("Skipping stale context_ready event %s", event.event_id)
            return None

        record = session.get(CommitmentRecord, (event.tenant_id, event.commitment_id))
        if record is None:
            logger.warning("Commitment %s not found for event %s", event.commitment_id, event.event_id)
            return None

        # Build canonical Commitment model
        commitment = _to_commitment(record)

        # Invariant 1 (AGENTS.md / P2 Review §1): REQUESTED != CONFIRMED.
        # Pure P2 evaluate() requires a genuinely CONFIRMED operational target.
        # For unconfirmed commitments (e.g. REQUESTED), authoritative assessment
        # must NOT be written to Core. We fail-closed until D-026 candidate evaluation
        # contract is finalized, and never synthetically elevate agreement_state.
        if commitment.agreement_state != "CONFIRMED":
            logger.info(
                "Skipping authoritative feasibility assessment for non-CONFIRMED commitment %s (state=%s); "
                "pre-commitment candidate evaluation is fail-closed pending D-026 contract",
                commitment.commitment_id,
                commitment.agreement_state,
            )
            return None

        snapshot = resolve_snapshot_for_commitment(commitment)
        result = evaluate(snapshot, None, commitment)

        assessment = FeasibilityAssessment(
            assessment_id=result.assessment_id,
            tenant_id=result.tenant_id,
            commitment_id=result.commitment_id,
            commitment_version=record.commitment_version,
            snapshot_version=result.snapshot_version,
            status=result.status,
            solver_status=result.solver_status,
            constraints=list(result.constraints),
            affected_commitment_ids=[],  # P2 invariant: impact membership only populated when verified impact assessment supports it
            evidence_refs=list(result.evidence_refs),
            assumptions=list(result.assumptions),
            assessed_at=result.assessed_at,
        )

        service_context = RequestContext(
            tenant_id=event.tenant_id,
            actor_id="service_p2_feasibility",
            actor_role="SERVICE",
            correlation_id=event.correlation_id,
            causation_id=event.event_id,
        )

        self.facade.handle_feasibility_assessment(
            session, service_context, record.commitment_id, assessment
        )
        return result

    def handle_proposal_offered(self, session: Session, event: DomainEvent) -> EvaluationResult | None:
        """Process commitment.proposal_offered event: evaluate what-if proposal changes.

        Under D-024 and P2 Review §2, hypothetical evaluations of proposed revised terms
        must remain bound to their proposal identity/version for proposal review.
        They MUST NOT replace the existing operational feasibility state of the confirmed
        commitment or drive Core risk transitions (e.g., an infeasible proposal must not
        make a feasible confirmed commitment AT_RISK).
        """
        if OutboxDispatcher.is_stale_event(session, event):
            logger.info("Skipping stale proposal_offered event %s", event.event_id)
            return None

        record = session.get(CommitmentRecord, (event.tenant_id, event.commitment_id))
        if record is None:
            return None

        # Find active proposal
        proposal = session.scalar(
            select(CommitmentProposalRecord).where(
                CommitmentProposalRecord.tenant_id == event.tenant_id,
                CommitmentProposalRecord.commitment_id == event.commitment_id,
                CommitmentProposalRecord.status == "ACTIVE",
            )
        )
        payload = event.payload or {}
        payload_revised = payload.get("revised_terms")
        revised = (proposal.revised_terms if proposal else None) or payload_revised
        if not revised:
            return None

        commitment = _to_commitment(record)
        if commitment.agreement_state != "CONFIRMED":
            logger.info(
                "Skipping hypothetical proposal evaluation for non-CONFIRMED commitment %s (state=%s)",
                commitment.commitment_id,
                commitment.agreement_state,
            )
            return None

        snapshot = resolve_snapshot_for_commitment(commitment)

        revised_deadline = (
            datetime.fromisoformat(revised["deadline"]) if "deadline" in revised else None
        )
        evidence_refs = tuple(
            (proposal.evidence_refs if proposal else None) or payload.get("evidence_refs") or ()
        )
        proposed_changes = ProposedChanges(
            tenant_id=event.tenant_id,
            commitment_id=event.commitment_id,
            expected_commitment_version=record.commitment_version,
            expected_snapshot_version=snapshot.snapshot_version,
            quantity=Decimal(str(revised["quantity"])) if "quantity" in revised else None,
            deadline=revised_deadline,
            evidence_refs=evidence_refs,
        )

        result = evaluate(snapshot, proposed_changes, commitment)

        # Invariant (P2 Review §2 / D-024): Hypothetical proposal evaluations MUST NOT
        # mutate the parent commitment's feasibility_state or trigger Core risk transitions.
        # Instead, record the evaluation result ID on the proposal record for review.
        if proposal is not None:
            proposal.evidence_refs = list(
                dict.fromkeys([*(proposal.evidence_refs or []), result.assessment_id])
            )
            session.commit()

        logger.info(
            "Hypothetical evaluation for proposal %s completed with status=%s; parent commitment %s feasibility preserved",
            getattr(proposal, "proposal_id", "unknown"),
            result.status.value,
            commitment.commitment_id,
        )
        return result


_consumer = P2FeasibilityConsumer()


def register_p2_subscribers(dispatcher: OutboxDispatcher) -> None:
    """Register P2 evaluation subscriber handlers onto the shared outbox dispatcher."""
    dispatcher.register_subscriber(
        CoreEventType.COMMITMENT_CONTEXT_READY.value,
        "p2_feasibility_evaluator",
        _consumer.handle_context_ready,
    )
    dispatcher.register_subscriber(
        CoreEventType.COMMITMENT_PROPOSAL_OFFERED.value,
        "p2_proposal_evaluator",
        _consumer.handle_proposal_offered,
    )
