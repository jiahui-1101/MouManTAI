"""Persist a confirmed commitment's P2 evaluation in the dispatcher transaction."""

from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.feasibility_adapters import AuthoritativeAssessmentWriter
from app.core.schemas import DomainEvent
from app.core.service import CommitmentService

from .api_schemas import AssessCommitmentRequest
from .currentness import require_current_snapshot
from .persisted_sources import read_snapshot
from .service import evaluate


class PersistedConfirmedEvaluator:
    def __init__(self) -> None:
        self.writer = AuthoritativeAssessmentWriter()
        self.service = CommitmentService()

    def persist(self, db: Session, event: DomainEvent) -> None:
        if event.event_type != "commitment.confirmed" or not event.commitment_id or event.commitment_version is None:
            raise DomainError("CONFIRMED_EVENT_INVALID", "Confirmed event identity is incomplete", status_code=409)
        context = RequestContext(
            tenant_id=event.tenant_id,
            actor_id="service_p2_confirmed_evaluator",
            actor_role="SERVICE",
            correlation_id=event.correlation_id,
            causation_id=event.event_id,
        )
        commitment = self.service.get(db, context, event.commitment_id)
        if commitment.commitment_version != event.commitment_version or commitment.agreement_state.value != "CONFIRMED":
            raise DomainError("COMMITMENT_VERSION_CONFLICT", "Confirmed event is stale", status_code=409)
        snapshot = read_snapshot(db, event.tenant_id)
        require_current_snapshot(snapshot, correlation_id=event.correlation_id)
        result = evaluate(snapshot, None, commitment)
        self.writer.assess(
            db, context, commitment,
            AssessCommitmentRequest(
                expected_commitment_version=event.commitment_version,
                expected_snapshot_version=snapshot.operational.snapshot_version,
            ),
            snapshot=snapshot, result=result, commit=False,
        )
