"""P3-owned integration boundaries for P2 feasibility and P5 Core.

These adapters intentionally depend on public call shapes, not on unmerged P2
implementation modules. P2's current evaluator requires a complete evaluation
snapshot and typed proposal; P3's synthetic planner input is not sufficient.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.schemas import Commitment, DomainEvent
from app.core.service import CommitmentService


class IntegrationSource(StrEnum):
    AUTHORITATIVE = "AUTHORITATIVE"
    SYNTHETIC_FIXTURE = "SYNTHETIC_FIXTURE"
    SYNTHETIC_TEST_DOUBLE = "SYNTHETIC_TEST_DOUBLE"


@dataclass(frozen=True)
class VersionedSnapshot:
    """A P2 evaluation snapshot plus the identity/version it represents."""

    snapshot: Any
    tenant_id: str
    commitment_id: str
    commitment_version: int
    snapshot_id: str
    snapshot_version: int
    captured_at: datetime
    source: IntegrationSource


@dataclass(frozen=True)
class ActorContext:
    tenant_id: str
    actor_id: str
    actor_role: str
    correlation_id: str
    causation_id: str | None
    verified: bool


class FeasibilityEvaluator(Protocol):
    """P2-compatible pure evaluator signature; it owns all feasibility math."""

    def evaluate(
        self,
        snapshot: Any,
        proposed_changes: Any | None,
        commitment: Commitment,
    ) -> Any: ...


class P2EvaluationFunction(Protocol):
    """The P2 branch currently exports evaluate as a module-level function."""

    def __call__(self, snapshot: Any, proposed_changes: Any | None, commitment: Commitment) -> Any: ...


class OperationalSnapshotProvider(Protocol):
    def get_snapshot(
        self,
        context: RequestContext,
        commitment: Commitment,
        *,
        expected_snapshot_version: int | None = None,
    ) -> VersionedSnapshot: ...


class CommitmentReader(Protocol):
    def get_commitment(
        self,
        db: Session,
        context: RequestContext,
        commitment_id: str,
        *,
        expected_commitment_version: int | None = None,
    ) -> Commitment: ...


class RecoveryEventPublisher(Protocol):
    def publish(self, db: Session, context: RequestContext, event: DomainEvent) -> None: ...


class VerifiedActorContextProvider(Protocol):
    def get_verified_context(self, context: RequestContext) -> ActorContext: ...


def validate_snapshot_binding(snapshot: VersionedSnapshot, commitment: Commitment) -> None:
    if snapshot.tenant_id != commitment.tenant_id:
        raise DomainError("TENANT_SCOPE_VIOLATION", "Snapshot tenant does not match commitment", status_code=403)
    if snapshot.commitment_id != commitment.commitment_id:
        raise DomainError("COMMITMENT_SCOPE_MISMATCH", "Snapshot is for a different commitment", status_code=409)
    if snapshot.commitment_version != commitment.commitment_version:
        raise DomainError(
            "COMMITMENT_VERSION_CONFLICT",
            "Snapshot was captured for a different commitment version",
            status_code=409,
            details={"snapshot_commitment_version": snapshot.commitment_version,
                     "commitment_version": commitment.commitment_version},
        )
    inner = getattr(snapshot.snapshot, "operational", snapshot.snapshot)
    inner_version = getattr(inner, "snapshot_version", None)
    inner_id = getattr(inner, "snapshot_id", None)
    inner_tenant = getattr(inner, "tenant_id", None)
    if (inner_version, inner_id, inner_tenant) != (
        snapshot.snapshot_version, snapshot.snapshot_id, snapshot.tenant_id
    ):
        raise DomainError("SNAPSHOT_VERSION_MISMATCH", "Snapshot envelope does not match its payload", status_code=409)


def validate_proposal_binding(proposal: Any | None, snapshot: VersionedSnapshot, commitment: Commitment) -> None:
    if proposal is None:
        return
    expected = (
        getattr(proposal, "tenant_id", None),
        getattr(proposal, "commitment_id", None),
        getattr(proposal, "expected_commitment_version", None),
        getattr(proposal, "expected_snapshot_version", None),
    )
    actual = (commitment.tenant_id, commitment.commitment_id,
              commitment.commitment_version, snapshot.snapshot_version)
    if expected != actual:
        raise DomainError(
            "STALE_EVALUATION_INPUT",
            "P2 proposal tenant, commitment, or expected versions do not match the authoritative inputs",
            status_code=409,
            details={"proposal_binding": list(expected), "input_binding": list(actual)},
        )


class P2FeasibilityEvaluatorAdapter:
    """Thin adapter to the P2 evaluate() call; never computes feasibility."""

    def __init__(
        self,
        evaluator: P2EvaluationFunction | FeasibilityEvaluator | Callable[..., Any],
        *,
        allow_test_double: bool = False,
    ) -> None:
        self._evaluator = evaluator
        self._allow_test_double = allow_test_double

    def evaluate(self, snapshot: VersionedSnapshot, proposed_changes: Any | None,
                 commitment: Commitment) -> Any:
        if snapshot.source is IntegrationSource.SYNTHETIC_TEST_DOUBLE and not self._allow_test_double:
            raise DomainError(
                "AUTHORITATIVE_INPUT_REQUIRED",
                "Test doubles are available only to explicitly isolated tests",
                status_code=409,
            )
        if snapshot.source not in (
            IntegrationSource.AUTHORITATIVE,
            IntegrationSource.SYNTHETIC_FIXTURE,
            IntegrationSource.SYNTHETIC_TEST_DOUBLE,
        ):
            raise DomainError("P2_INPUT_PROVENANCE_INVALID", "P2 input provenance is unsupported", status_code=409)
        validate_snapshot_binding(snapshot, commitment)
        validate_proposal_binding(proposed_changes, snapshot, commitment)
        current_version = getattr(snapshot.snapshot, "current_snapshot_version", None)
        if snapshot.source is IntegrationSource.AUTHORITATIVE and current_version is None:
            raise DomainError(
                "CURRENT_SNAPSHOT_VERSION_REQUIRED",
                "Authoritative P2 evaluation requires a current snapshot version token",
                status_code=503,
            )
        if current_version is not None and current_version != snapshot.snapshot_version:
            raise DomainError(
                "SNAPSHOT_VERSION_CONFLICT",
                "P2 current snapshot token does not match the evaluated snapshot",
                status_code=409,
                details={"current_snapshot_version": current_version,
                         "snapshot_version": snapshot.snapshot_version},
            )
        # P2 expects EvaluationSnapshot, ProposedChanges | None, Commitment.
        evaluate = getattr(self._evaluator, "evaluate", self._evaluator)
        if not callable(evaluate):
            raise DomainError("P2_EVALUATOR_UNAVAILABLE", "Configured P2 evaluator has no evaluate() call", status_code=503)
        result = evaluate(snapshot.snapshot, proposed_changes, commitment)
        result_binding = (
            getattr(result, "tenant_id", None),
            getattr(result, "commitment_id", None),
            getattr(result, "commitment_version", None),
            getattr(result, "snapshot_id", None),
            getattr(result, "snapshot_version", None),
        )
        expected_binding = (commitment.tenant_id, commitment.commitment_id,
                            commitment.commitment_version, snapshot.snapshot_id, snapshot.snapshot_version)
        if result_binding != expected_binding:
            raise DomainError("P2_RESULT_VERSION_MISMATCH",
                              "P2 result identity or versions do not match the authoritative input",
                              status_code=409,
                              details={"result_binding": list(result_binding),
                                       "input_binding": list(expected_binding)})
        return result


class UnavailableOperationalSnapshotProvider:
    def get_snapshot(self, context: RequestContext, commitment: Commitment,
                     *, expected_snapshot_version: int | None = None) -> VersionedSnapshot:
        del context, commitment, expected_snapshot_version
        raise DomainError("OPERATIONAL_SNAPSHOT_UNAVAILABLE",
                          "No authoritative P2/P5 snapshot provider is connected", status_code=503)


class P5CommitmentReader:
    """Adapter for P5's existing public CommitmentService.get boundary."""

    def __init__(self, service: CommitmentService | None = None) -> None:
        self._service = service or CommitmentService()

    def get_commitment(self, db: Session, context: RequestContext, commitment_id: str,
                       *, expected_commitment_version: int | None = None) -> Commitment:
        commitment = self._service.get(db, context, commitment_id)
        if commitment.tenant_id != context.tenant_id:
            raise DomainError("TENANT_SCOPE_VIOLATION", "Commitment is outside the request tenant", status_code=403)
        if expected_commitment_version is not None and commitment.commitment_version != expected_commitment_version:
            raise DomainError("COMMITMENT_VERSION_CONFLICT", "Commitment version is stale", status_code=409,
                              details={"current_commitment_version": commitment.commitment_version})
        return commitment


class UnavailableRecoveryEventPublisher:
    """No public P5 append-to-outbox API exists for P3 recovery events yet."""

    def publish(self, db: Session, context: RequestContext, event: DomainEvent) -> None:
        del db, context, event
        raise DomainError("RECOVERY_EVENT_PUBLISHER_UNAVAILABLE",
                          "P5 has no agreed public transactional recovery-event publisher", status_code=503)


class UnverifiedP5ContextAdapter:
    """Preserves P5 context conventions without claiming header-derived identity is verified."""

    def get_verified_context(self, context: RequestContext) -> ActorContext:
        return ActorContext(context.tenant_id, context.actor_id, context.actor_role,
                            context.correlation_id, context.causation_id, verified=False)


def require_verified_actor(actor: ActorContext) -> None:
    if not actor.verified:
        raise DomainError("VERIFIED_ACTOR_REQUIRED",
                          "A verified P5 actor context is required for consequential actions", status_code=403)


@runtime_checkable
class SyntheticSnapshotProvider(Protocol):
    """Test-only provider contract; returned values must remain explicitly synthetic."""

    def get_snapshot(self, context: RequestContext, commitment: Commitment,
                     *, expected_snapshot_version: int | None = None) -> VersionedSnapshot: ...
