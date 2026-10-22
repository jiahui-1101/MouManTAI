"""Caller-session bridge from verified Core risk events to P3 SQL storage.

The persisted lookup is explicit and this adapter is not registered at app
startup. P5 owns subscriber activation, the processed marker and transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.feasibility_adapters import AuthoritativeAssessmentHistoryReader
from app.core.models import AuditEventRecord, OutboxEventRecord
from app.core.outbox import to_domain_event
from app.core.schemas import DomainEvent, FeasibilityAssessment, FeasibilityState

from .integrations import CommitmentReader, P5CommitmentReader
from .models import RecoveryCase, RecoveryTriggerReference
from .persistence import RecoveryCaseTriggerRecord, SqlAlchemyRecoveryRepository
from .service import RecoveryPlanner
from .triggers import (
    CommitmentAtRiskEvent,
    RecoveryTriggerConsumer,
    canonical_domain_event_digest,
)


@dataclass(frozen=True)
class SyntheticAssessmentProof:
    """Test-only evidence; never a substitute for a trusted P2 history lookup."""

    assessment: FeasibilityAssessment
    snapshot_id: str
    caused_event_id: str


class SyntheticAssessmentLookup(Protocol):
    def lookup(
        self,
        session: Session,
        tenant_id: str,
        commitment_id: str,
        assessment_id: str,
        event_id: str,
    ) -> SyntheticAssessmentProof | None: ...


@dataclass(frozen=True)
class PersistedAssessmentProof:
    assessment: FeasibilityAssessment
    snapshot_id: str
    caused_event_id: str


class PersistedCoreAssessmentLookup:
    """Bind one Core risk outbox row to its persisted authoritative audit history."""

    def lookup(
        self, session: Session, tenant_id: str, commitment_id: str,
        assessment_id: str, event_id: str,
    ) -> PersistedAssessmentProof | None:
        row = session.get(OutboxEventRecord, event_id)
        if row is None or (
            row.tenant_id != tenant_id
            or row.commitment_id != commitment_id
            or row.event_type != "commitment.at_risk"
            or row.payload.get("assessment_id") != assessment_id
        ):
            return None
        event = to_domain_event(row)
        if event.event_id != event_id:
            return None
        context = RequestContext(
            tenant_id=tenant_id, actor_id="service_core", actor_role="SERVICE",
            correlation_id=row.correlation_id, causation_id=row.causation_id,
        )
        audits = session.scalars(select(AuditEventRecord).where(
            AuditEventRecord.tenant_id == tenant_id,
            AuditEventRecord.commitment_id == commitment_id,
            AuditEventRecord.event_type == "commitment.at_risk",
        )).all()
        matching = [audit for audit in audits if (
            isinstance(audit.new_state, dict)
            and audit.new_state.get("assessment_id") == assessment_id
            and audit.correlation_id == row.correlation_id
            and audit.causation_id == row.causation_id
            and audit.new_state.get("commitment_version") == row.commitment_version
            and audit.new_state.get("assessment_commitment_version")
                == row.payload.get("assessment_commitment_version")
            and audit.new_state.get("snapshot_id") == row.payload.get("snapshot_id")
            and audit.new_state.get("snapshot_version") == row.payload.get("snapshot_version")
            and audit.evidence_refs == row.payload.get("evidence_refs")
        )]
        if len(matching) != 1:
            return None
        audit = matching[0]
        assessment = AuthoritativeAssessmentHistoryReader().get_assessment(
            session, context, commitment_id, assessment_id,
        )
        return PersistedAssessmentProof(
            assessment=assessment,
            snapshot_id=audit.new_state["snapshot_id"],
            caused_event_id=event_id,
        )


class SessionScopedRecoveryTriggerAdapter:
    """Persist only verified trigger/case rows in a dispatcher-owned Session.

    An authoritative lookup can be supplied for isolated integration runs.
    There is no production subscriber binding or automatic activation.
"""

    live_ready = False

    def __init__(
        self,
        *,
        repository: SqlAlchemyRecoveryRepository | None = None,
        commitment_reader: CommitmentReader | None = None,
        authoritative_assessment_lookup: PersistedCoreAssessmentLookup | None = None,
        synthetic_assessment_lookup: SyntheticAssessmentLookup | None = None,
        allow_synthetic_for_tests: bool = False,
    ) -> None:
        self.repository = repository or SqlAlchemyRecoveryRepository()
        self.commitment_reader = commitment_reader or P5CommitmentReader()
        self._authoritative_lookup = authoritative_assessment_lookup
        self._synthetic_lookup = synthetic_assessment_lookup
        self._allow_synthetic_for_tests = allow_synthetic_for_tests

    def persist(self, session: Session, event: DomainEvent) -> tuple[RecoveryCase, bool, bool]:
        """Return (case, created, duplicate); never commit or write P5 markers."""
        try:
            trigger = CommitmentAtRiskEvent.from_domain_event(event)
        except (ValidationError, ValueError, TypeError) as exc:
            raise DomainError("RECOVERY_TRIGGER_MALFORMED", str(exc), status_code=400) from exc

        # Even an existing fixture-backed row must never become a successful
        # production acknowledgment by accidental subscriber registration.
        if self._authoritative_lookup is None and (
            not self._allow_synthetic_for_tests or self._synthetic_lookup is None
        ):
            raise DomainError(
                "AUTHORITATIVE_ASSESSMENT_LOOKUP_UNAVAILABLE",
                "A trusted causal P2 Assessment lookup is required before consuming a trigger",
                status_code=503,
            )

        digest = canonical_domain_event_digest(event)
        if self._authoritative_lookup is not None:
            stored = session.get(OutboxEventRecord, trigger.event_id)
            if stored is None or canonical_domain_event_digest(to_domain_event(stored)) != digest:
                raise DomainError(
                    "RECOVERY_EVENT_IDENTITY_UNVERIFIABLE",
                    "Trigger does not match the durable Core outbox event",
                    status_code=409,
                )
        prior = session.get(RecoveryCaseTriggerRecord, (trigger.tenant_id, trigger.event_id))
        if prior is not None:
            if prior.source_event_digest is None:
                raise DomainError(
                    "RECOVERY_EVENT_IDENTITY_UNVERIFIABLE",
                    "Stored trigger lacks a complete source-event digest",
                    status_code=409,
                )
            if prior.source_event_digest != digest:
                raise DomainError(
                    "RECOVERY_EVENT_ID_CONFLICT",
                    "Event ID was redelivered with different DomainEvent content",
                    status_code=409,
                )
            case = self.repository.get_case_by_id(session, trigger.tenant_id, prior.case_id)
            if case is None:
                raise DomainError(
                    "RECOVERY_CASE_HISTORY_ORPHANED", "Trigger has no Recovery Case", status_code=500
                )
            return case, False, True

        context = RequestContext(
            tenant_id=trigger.tenant_id,
            actor_id="service_core",
            actor_role="SERVICE",
            correlation_id=trigger.correlation_id,
            causation_id=trigger.causation_id,
        )
        commitment = self.commitment_reader.get_commitment(session, context, trigger.commitment_id)
        if (commitment.tenant_id, commitment.commitment_id) != (
            trigger.tenant_id, trigger.commitment_id
        ):
            raise DomainError("TENANT_SCOPE_VIOLATION", "Core Commitment identity mismatch", status_code=403)
        if commitment.commitment_version != trigger.commitment_version:
            raise DomainError("RECOVERY_TRIGGER_VERSION_CONFLICT", "At-risk event is not current", status_code=409)
        if not RecoveryTriggerConsumer._eligible(commitment):
            raise DomainError("RECOVERY_TRIGGER_INELIGIBLE", "Core Commitment is not eligible", status_code=409)

        lookup = self._authoritative_lookup or self._synthetic_lookup
        assert lookup is not None
        proof = lookup.lookup(
            session, trigger.tenant_id, trigger.commitment_id, trigger.payload.assessment_id,
            trigger.event_id,
        )
        if proof is None or not proof.snapshot_id or proof.caused_event_id != trigger.event_id:
            raise DomainError(
                "RECOVERY_ASSESSMENT_PROVENANCE_MISSING",
                "No causally linked assessment and snapshot evidence exists",
                status_code=503,
            )
        assessment = proof.assessment
        if (assessment.tenant_id, assessment.commitment_id, assessment.assessment_id) != (
            trigger.tenant_id, trigger.commitment_id, trigger.payload.assessment_id
        ):
            raise DomainError("RECOVERY_ASSESSMENT_SCOPE_CONFLICT", "Assessment identity mismatch", status_code=409)
        if assessment.status != FeasibilityState.INFEASIBLE:
            raise DomainError("RECOVERY_ASSESSMENT_STATUS_CONFLICT", "Assessment is not INFEASIBLE", status_code=409)
        if (assessment.commitment_version >= trigger.commitment_version
                or assessment.snapshot_version != trigger.payload.snapshot_version
                or (trigger.payload.assessed_commitment_version is not None
                    and assessment.commitment_version != trigger.payload.assessed_commitment_version)
                or (trigger.payload.snapshot_id is not None
                    and proof.snapshot_id != trigger.payload.snapshot_id)):
            raise DomainError("RECOVERY_ASSESSMENT_VERSION_CONFLICT", "Assessment/event versions differ", status_code=409)
        if (trigger.payload.constraints != assessment.constraints
                or trigger.payload.affected_commitment_ids != assessment.affected_commitment_ids
                or (trigger.payload.evidence_refs
                    and trigger.payload.evidence_refs != assessment.evidence_refs)
                or (trigger.payload.assessment_evidence_refs
                    and trigger.payload.assessment_evidence_refs != assessment.evidence_refs)):
            raise DomainError("RECOVERY_ASSESSMENT_CONTENT_CONFLICT", "Assessment/event content differs", status_code=409)
        evidence_refs = list(dict.fromkeys([
            *assessment.evidence_refs,
            *(ref for constraint in assessment.constraints for ref in constraint.evidence_refs),
        ]))
        if not evidence_refs:
            raise DomainError("RECOVERY_ASSESSMENT_EVIDENCE_MISSING", "Assessment has no evidence", status_code=503)

        # The shared P3 reference can only label source versions UNVERIFIED.
        # The separate test proof does not promote it to production authority.
        reference = RecoveryTriggerReference(
            event_id=trigger.event_id,
            tenant_id=trigger.tenant_id,
            commitment_id=trigger.commitment_id,
            commitment_version=trigger.commitment_version,
            assessment_id=assessment.assessment_id,
            assessment_commitment_version=assessment.commitment_version,
            source_event_digest=digest,
            assessment_provenance_status=(
                "VERIFIED_AUTHORITATIVE" if self._authoritative_lookup is not None
                else "SOURCE_COMMITMENT_VERSION_RECORDED_UNVERIFIED"
            ),
            snapshot_id=proof.snapshot_id,
            snapshot_version=assessment.snapshot_version,
            constraints=assessment.constraints,
            affected_commitment_ids=assessment.affected_commitment_ids,
            correlation_id=trigger.correlation_id,
            causation_id=trigger.causation_id,
            evidence_refs=evidence_refs,
            occurred_at=trigger.occurred_at,
        )
        candidate = RecoveryPlanner.build_trigger_case(commitment, reference)
        return self.repository.create_or_get_active_case(session, candidate, reference)
