"""P2 integration ports whose authoritative implementations belong to P5.

The defaults are deliberately absent until P5 supplies approved snapshot,
assessment-history, persistence, and outbox adapters.
"""

from typing import Protocol

from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.schemas import Commitment, FeasibilityAssessment

from .api_schemas import AssessCommitmentRequest, FeasibilityEvaluateRequest, SupplierDelayRequest
from .impact import ImpactAssessment
from .production import EvaluationSnapshot
from .service import EvaluationResult


class EvaluationInputAuthority(Protocol):
    """Resolve caller input against P5's current, authenticated source state.

    Implementations must not treat the request body as authority. They verify
    tenant membership, commitment identity/version, snapshot identity/current
    version, source completeness/freshness, and evidence linkage before return.
    """

    def resolve(
        self,
        context: RequestContext,
        request: FeasibilityEvaluateRequest,
    ) -> tuple[EvaluationSnapshot, Commitment]:
        """Return authoritative input after tenant, identity, and version checks."""

    def resolve_current(
        self,
        context: RequestContext,
        commitment_id: str,
        expected_commitment_version: int,
    ) -> tuple[EvaluationSnapshot, Commitment]:
        """Resolve the current trusted snapshot and commitment for an assessment."""


class AssessmentWriter(Protocol):
    """Persist through the approved P5 transaction boundary.

    The writer receives the exact snapshot and pure P2 evaluation calculated by
    the route. It must not substitute a different calculation. It re-reads/locks
    the commitment and snapshot versions inside the write transaction, appends
    immutable history, and commits audit/outbox records atomically before
    returning.

    Accept results only from the trusted server-side P2 evaluation execution
    boundary, never arbitrary caller-supplied assessment objects or input hashes.
    Input hashes bind inputs; they do not prove result integrity or source trust.
    The production writer must not independently recalculate or change the trusted
    P2 result. Reject changed input versions transactionally and return control to
    the P2 flow for any required new evaluation. Deterministic result verification
    in SyntheticHistoryRepository is a reference/test safeguard only.
    """

    def assess(
        self,
        db: Session,
        context: RequestContext,
        commitment: Commitment,
        request: AssessCommitmentRequest,
        *,
        snapshot: EvaluationSnapshot,
        result: EvaluationResult,
    ) -> FeasibilityAssessment:
        """Persist this exact P2 result or reject it if either version changed."""


class AssessmentHistoryReader(Protocol):
    """Read append-only versioned assessment history; never infer current risk."""

    def get_assessment(
        self,
        db: Session,
        context: RequestContext,
        commitment_id: str,
        assessment_id: str,
    ) -> FeasibilityAssessment:
        """Return this exact authoritative assessment or fail closed if unavailable/invalid."""

    def list_for_commitment(
        self,
        db: Session,
        context: RequestContext,
        commitment_id: str,
    ) -> list[FeasibilityAssessment]:
        """Return durable historical rows scoped to the authenticated tenant."""


class SupplierDelayProcessor(Protocol):
    """Atomically validate, deduplicate, update source state, and write outbox.

    The implementation checks event_id idempotency, current before-snapshot
    version, typed evidence against the authoritative delivery/source row, and
    tenant scope in one transaction. It calls P2's existing ``assess_impact``
    for before/after calculation and writes the result/events to the P5 outbox
    atomically with the snapshot version change.
    """

    def process(
        self,
        db: Session,
        context: RequestContext,
        request: SupplierDelayRequest,
    ) -> ImpactAssessment:
        """Return a result only after P5's transactional outbox operation commits."""


class ImpactReader(Protocol):
    def get(
        self,
        db: Session,
        context: RequestContext,
        impact_id: str,
    ) -> ImpactAssessment:
        """Read a durable impact record within the authenticated tenant."""
