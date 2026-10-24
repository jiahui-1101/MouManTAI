"""Isolated persisted DEMO history for the existing decision-memory engine."""

from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.models import OutboxEventRecord
from app.decision_memory.assembly import assemble_case
from app.decision_memory.governance import ReviewProposal
from app.decision_memory.lessons import OutcomeInsight
from app.decision_memory.mock_models import MockMemoryAuditRecord, MockMemoryDatasetRecord
from app.decision_memory.models import (
    CaseInput,
    CurrentSituation,
    RetrievalPolicy,
    RetrievalResult,
    SourceManifest,
    SourceMode,
)
from app.decision_memory.service import DecisionMemoryService
from app.decision_memory.validation import HistoryValidationError, validate_source
from app.orders.terms import ImmutableContract


class MockMemoryDatasetCreate(ImmutableContract):
    dataset_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    manifest: SourceManifest
    cases: tuple[CaseInput, ...] = Field(min_length=1, max_length=1000)
    policy: RetrievalPolicy


class MockMemoryDatasetView(MockMemoryDatasetCreate):
    tenant_id: str
    actor_id: str
    evidence_tier: Literal["DEMO-ONLY"] = "DEMO-ONLY"
    operational_action_authorized: Literal[False] = False


class MockMemoryInsightView(ImmutableContract):
    dataset_id: str
    retrieval: RetrievalResult
    outcomes: OutcomeInsight | None
    review_proposal: ReviewProposal | None
    diagnostic: str | None
    evidence_tier: Literal["DEMO-ONLY"] = "DEMO-ONLY"
    operational_action_authorized: Literal[False] = False
    policy_update_authorized: Literal[False] = False


def _synthetic(refs) -> bool:
    return bool(refs) and all(ref.startswith("synthetic://") for ref in refs)


def _validate_fixture(context: RequestContext, command: MockMemoryDatasetCreate) -> None:
    manifest, policy = command.manifest, command.policy
    now = datetime.now(UTC)
    if (manifest.tenant_id != context.tenant_id or policy.tenant_id != context.tenant_id
            or manifest.source_reader_id != "MOCK_HISTORY"
            or manifest.integration_mode != SourceMode.DEMO_ONLY
            or manifest.evidence_maturity != "SYNTHETIC"
            or manifest.as_of > now or manifest.source_watermark > now
            or not _synthetic(manifest.provenance_refs)
            or not policy.test_only or not policy.approval_ref.startswith("synthetic://")
            or not policy.retention_ref.startswith("synthetic://")
            or not policy.privacy_ref.startswith("synthetic://")
            or any(case.tenant_id != context.tenant_id or case.domain != policy.domain
                   or not case.business_context_ref.startswith("synthetic://")
                   or any(event.tenant_id != context.tenant_id
                          or not event.ref.startswith("synthetic://")
                          or (event.selected_ref is not None
                              and not event.selected_ref.startswith("synthetic://"))
                          or (event.actor_ref is not None
                              and not event.actor_ref.startswith("synthetic://"))
                          or any(not ref.startswith("synthetic://") for ref in event.evidence_ids)
                          for event in case.events)
                   or any(proof.owner != "SYNTHETIC"
                          or not proof.evidence_id.startswith("synthetic://")
                          for proof in case.evidence)
                   for case in command.cases)):
        raise DomainError("MOCK_MEMORY_SOURCE_INVALID",
                          "Decision history must be tenant-bound, test-only and synthetic",
                          status_code=422)
    try:
        checked = validate_source(manifest, command.cases)
        for case in checked:
            assemble_case(case, manifest)
    except (HistoryValidationError, ValueError) as exc:
        raise DomainError("MOCK_MEMORY_SOURCE_INVALID", "Decision history failed validation",
                          status_code=422, details={"reason": str(exc)}) from exc


def _view(row: MockMemoryDatasetRecord) -> MockMemoryDatasetView:
    return MockMemoryDatasetView(
        tenant_id=row.tenant_id, dataset_id=row.dataset_id, actor_id=row.actor_id,
        manifest=SourceManifest.model_validate(row.manifest),
        cases=tuple(CaseInput.model_validate(item) for item in row.cases),
        policy=RetrievalPolicy.model_validate(row.policy),
    )


def seed_dataset(db: Session, context: RequestContext,
                 command: MockMemoryDatasetCreate) -> MockMemoryDatasetView:
    _validate_fixture(context, command)
    manifest = command.manifest.model_dump(mode="json")
    cases = [case.model_dump(mode="json") for case in command.cases]
    policy = command.policy.model_dump(mode="json")
    existing = db.get(MockMemoryDatasetRecord, (context.tenant_id, command.dataset_id))
    if existing is not None:
        if (existing.manifest, existing.cases, existing.policy) != (manifest, cases, policy):
            raise DomainError("MOCK_MEMORY_DATASET_CONFLICT", "Dataset ID has other facts",
                              status_code=409)
        return _view(existing)
    now = datetime.now(UTC)
    row = MockMemoryDatasetRecord(
        tenant_id=context.tenant_id, dataset_id=command.dataset_id,
        domain=command.policy.domain.value, manifest=manifest, cases=cases,
        policy=policy, actor_id=context.actor_id, created_at=now,
    )
    db.add(row)
    audit_id = f"aud_{uuid4().hex}"
    db.add(MockMemoryAuditRecord(
        audit_id=audit_id, tenant_id=context.tenant_id, dataset_id=command.dataset_id,
        actor_id=context.actor_id, event_type="memory.mock_history_seeded",
        evidence_refs=list(command.manifest.provenance_refs),
        reason="Controlled synthetic decision history", occurred_at=now,
    ))
    db.add(OutboxEventRecord(
        event_id=f"evt_{uuid4().hex}", tenant_id=context.tenant_id,
        event_type="memory.mock_history_seeded", commitment_id=None,
        commitment_version=None, correlation_id=context.correlation_id,
        causation_id=context.causation_id, occurred_at=now,
        payload={"dataset_id": command.dataset_id, "audit_id": audit_id,
                 "integration_mode": "SYNTHETIC", "evidence_tier": "DEMO-ONLY"},
        published_at=None, attempts=0, status="PENDING", last_error=None,
        next_retry_at=None,
    ))
    db.commit()
    return _view(row)


def get_dataset(db: Session, context: RequestContext,
                dataset_id: str) -> MockMemoryDatasetRecord:
    row = db.scalar(select(MockMemoryDatasetRecord).where(
        MockMemoryDatasetRecord.tenant_id == context.tenant_id,
        MockMemoryDatasetRecord.dataset_id == dataset_id,
    ))
    if row is None:
        raise DomainError("MOCK_MEMORY_DATASET_NOT_FOUND", "Decision dataset not found",
                          status_code=404)
    return row


class PersistedMockHistory:
    def __init__(self, row: MockMemoryDatasetRecord, context: RequestContext):
        self.row = row
        self.context = context

    def identity(self) -> tuple[str, str]:
        return self.context.tenant_id, self.context.actor_id

    def read(self, tenant_id: str, domain: str, as_of: str, limit: int):
        if (tenant_id != self.row.tenant_id or domain != self.row.domain
                or len(self.row.cases) > limit):
            raise LookupError("Synthetic history outside bound source")
        return (SourceManifest.model_validate(self.row.manifest),
                tuple(CaseInput.model_validate(item) for item in self.row.cases))

    def approved_policy(self, tenant_id: str, domain: str) -> RetrievalPolicy | None:
        return (RetrievalPolicy.model_validate(self.row.policy)
                if tenant_id == self.row.tenant_id and domain == self.row.domain else None)

    def verify(self, manifest: SourceManifest, cases: tuple[CaseInput, ...]) -> bool:
        return (manifest.integration_mode == SourceMode.DEMO_ONLY
                and manifest == SourceManifest.model_validate(self.row.manifest)
                and cases == tuple(CaseInput.model_validate(item) for item in self.row.cases))

    def verify_current(self, current: CurrentSituation, actor_id: str) -> bool:
        return bool(actor_id == self.context.actor_id
                    and current.tenant_id == self.context.tenant_id
                    and current.domain.value == self.row.domain
                    and current.as_of <= datetime.now(UTC)
                    and current.business_context_ref.startswith("synthetic://")
                    and _synthetic(current.evidence_refs))


def insights(db: Session, context: RequestContext, dataset_id: str,
             current: CurrentSituation) -> MockMemoryInsightView:
    row = get_dataset(db, context, dataset_id)
    adapter = PersistedMockHistory(row, context)
    service = DecisionMemoryService(identity=adapter, history=adapter,
                                    policy=adapter, authenticity=adapter)
    retrieval = service.retrieve_similar_cases(current, live=False)
    outcomes = service.summarize_verified_outcomes(current, live=False)
    proposal = service.propose_review_insights(current, live=False)
    diagnostic = next((item for item in (outcomes, proposal) if isinstance(item, str)), None)
    return MockMemoryInsightView(
        dataset_id=dataset_id, retrieval=retrieval,
        outcomes=None if isinstance(outcomes, str) else outcomes,
        review_proposal=None if isinstance(proposal, str) else proposal,
        diagnostic=diagnostic,
    )
