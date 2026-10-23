"""P4 evidence reader/worker port. The P5 command remains the only Core writer.

No default consumer registration: current Core denies approved P3 proposals
without an owner-provided verified-evidence command port.
"""
from typing import Protocol
from sqlalchemy import select
from .models import ConfirmationSessionRecord, ConfirmationDecisionRecord, ConfirmationAttemptRecord
from .confirmation_schemas import ConfirmationBasis
from .demo_policy import deny
from app.core.models import OutboxEventRecord, AuditEventRecord
from app.core.schemas import ProposalConfirmRequest
from app.core.service import CommitmentService
from app.core.outbox import to_domain_event


class VerifiedCoreConfirmationPort(Protocol):
    def apply(self, db, event, evidence):
        """P5-owned authenticated command; participate in consumer UoW, no commit."""
        ...


def read_confirmation_evidence(db, event):
    if event.schema_version != 1 or event.event_type not in {"confirmation.accepted", "confirmation.rejected", "confirmation.counteroffer_received"}:
        deny("CONFIRMATION_EVENT_UNSUPPORTED", "Expected canonical terminal evidence event", 422)
    persisted = db.get(OutboxEventRecord, event.event_id, populate_existing=True)
    if persisted is None or to_domain_event(persisted) != event:
        deny("CONFIRMATION_EVENT_UNTRUSTED", "Persisted source event must match", 409)
    decision = db.get(ConfirmationDecisionRecord, (event.tenant_id, event.payload.get("decision_id")), populate_existing=True)
    session = db.get(ConfirmationSessionRecord, (event.tenant_id, event.payload.get("confirmation_id")), populate_existing=True)
    if session is None or decision is None or decision.confirmation_id != session.confirmation_id or not session.consumed_at:
        deny("CONFIRMATION_EVIDENCE_MISSING", "Terminal session and exact decision are required", 409)
    attempt = db.get(ConfirmationAttemptRecord, (event.tenant_id, decision.attempt_id), populate_existing=True)
    basis = ConfirmationBasis.model_validate(session.binding)
    audits = db.scalars(select(AuditEventRecord).where(AuditEventRecord.tenant_id == event.tenant_id,
        AuditEventRecord.event_type == event.event_type, AuditEventRecord.commitment_id == event.commitment_id)).all()
    if (attempt is None or attempt.confirmation_id != session.confirmation_id or
        event.payload.get("attempt_id") != attempt.attempt_id or event.causation_id != attempt.inbound_message_id or
        event.payload.get("terms_digest") != basis.terms_digest or
        (event.commitment_id, event.commitment_version, event.payload.get("proposal_id"), event.payload.get("proposal_version")) !=
        (basis.reference.commitment_id, basis.reference.commitment_version, basis.reference.proposal_id, basis.reference.proposal_version) or
        event.payload.get("intent") != decision.intent or event.payload.get("evidence_refs") != attempt.evidence_refs or
        not any(audit.new_state == event.payload for audit in audits)):
        deny("CONFIRMATION_EVIDENCE_MISMATCH", "Event differs from durable response/audit/proposal binding", 409)
    return {"session": session, "decision": decision, "attempt": attempt, "basis": basis}


def build_core_confirmation_consumer(port: VerifiedCoreConfirmationPort | None):
    def consume(db, event):
        evidence = read_confirmation_evidence(db, event)
        if port is None:
            deny("P5_VERIFIED_CONFIRMATION_PORT_UNAVAILABLE", "P5 must supply its verified Core command port", 503)
        return port.apply(db, event, evidence)
    return consume


def attempt_existing_core_command(db, manager_context, event):
    """Integration probe, NOT a new consumer or a bypass for Core's 503 guard."""
    evidence = read_confirmation_evidence(db, event)
    if evidence["decision"].intent not in {"ACCEPT", "REJECT"}:
        deny("COUNTEROFFER_REQUIRES_P3", "P3 owns counteroffer resolution", 409)
    return CommitmentService().confirm_proposal(db, manager_context, event.commitment_id,
        ProposalConfirmRequest(proposal_id=event.payload["proposal_id"], proposal_version=event.payload["proposal_version"],
            expected_commitment_version=event.commitment_version, decision=evidence["decision"].intent,
            evidence_refs=event.payload["evidence_refs"], reason="Verified P4 response integration probe"), commit=False)
