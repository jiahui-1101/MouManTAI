"""Persistent Mock constraints for genuine advisory CP-SAT comparisons."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from itertools import pairwise
from typing import Literal
from uuid import uuid4

from pydantic import Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.models import OutboxEventRecord
from app.optimization.mock_models import MockOptimizationAuditRecord, MockOptimizationDatasetRecord
from app.optimization.models import (
    ComparisonResult,
    JointVerificationResult,
    P2ConstraintSpec,
    PortfolioRequest,
    ProjectedPortfolio,
)
from app.optimization.service import (
    allocation_digest,
    compare,
    projected_portfolio_digest,
    schedule_digest,
)
from app.optimization.validation import validate_spec
from app.orders.models import MockOrderSourceRecord, OrderRequestRecord
from app.orders.terms import ImmutableContract, OrderTerms


class MockOptimizationDatasetCreate(ImmutableContract):
    dataset_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    request: PortfolioRequest
    constraints: P2ConstraintSpec

    @field_validator("request", "constraints", mode="before")
    @classmethod
    def parse_strict_json_contract(cls, value, info):
        if isinstance(value, dict):
            model = PortfolioRequest if info.field_name == "request" else P2ConstraintSpec
            return model.model_validate_json(json.dumps(value, allow_nan=False))
        return value


class MockOptimizationDatasetView(MockOptimizationDatasetCreate):
    tenant_id: str
    actor_id: str
    evidence_tier: Literal["DEMO-ONLY"] = "DEMO-ONLY"
    operational_action_authorized: Literal[False] = False


class MockOptimizationComparisonView(ImmutableContract):
    dataset_id: str
    result: ComparisonResult
    evidence_tier: Literal["DEMO-ONLY"] = "DEMO-ONLY"
    operational_action_authorized: Literal[False] = False


def _synthetic(refs) -> bool:
    return bool(refs) and all(ref.startswith("synthetic://") for ref in refs)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _bind_orders(db: Session, context: RequestContext, request: PortfolioRequest) -> None:
    now = datetime.now(UTC)
    for candidate in request.candidates:
        row = db.get(OrderRequestRecord, (context.tenant_id, candidate.order_request_id))
        if row is None:
            raise DomainError("MOCK_OPTIMIZATION_ORDER_NOT_FOUND", "Eligible OrderRequest not found",
                              status_code=404)
        source = db.get(MockOrderSourceRecord, (context.tenant_id, row.source_id))
        if (source is None or source.status != "CURRENT"
                or not _utc(source.observed_at) <= now < _utc(source.valid_through)
                or source.source_version != row.source_version):
            raise DomainError("MOCK_OPTIMIZATION_ORDER_STALE", "Mock order source expired",
                              status_code=409)
        terms = OrderTerms.model_validate(row.terms)
        source_terms = OrderTerms.model_validate(source.terms)
        lines = sorted((line.sku, line.quantity, line.unit) for line in terms.items)
        candidate_lines = sorted((line.sku_id, line.quantity, line.unit) for line in candidate.lines)
        if (row.decision_status != "REVIEWED" or row.request_version != candidate.request_version
                or row.terms_hash != candidate.terms_hash
                or source_terms.terms_hash != row.terms_hash
                or terms.terms_revision != candidate.terms_revision
                or terms.window_end != candidate.deadline
                or _utc(row.created_at) != _utc(candidate.received_at)
                or candidate.source_identity != f"synthetic://{row.source_id}"
                or lines != candidate_lines
                or (candidate.financial is not None and
                    (candidate.financial.revenue != terms.total
                     or candidate.financial.currency != terms.currency))):
            raise DomainError("MOCK_OPTIMIZATION_ORDER_BINDING_MISMATCH",
                              "Portfolio candidate does not match reviewed OrderRequest",
                              status_code=409)


def _validate_fixture(db: Session, context: RequestContext, command: MockOptimizationDatasetCreate
                      ) -> tuple[PortfolioRequest, P2ConstraintSpec]:
    request, spec = command.request, command.constraints
    now = datetime.now(UTC)
    if (request.integration_mode != "SYNTHETIC" or spec.owner != "SYNTHETIC_TEST_FIXTURE"
            or request.tenant_id != context.tenant_id or spec.tenant_id != context.tenant_id
            or request.actor_id != context.actor_id
            or request.evaluated_at > now or request.source_valid_through <= now
            or not _synthetic(request.evidence_refs) or not _synthetic(spec.source_refs)
            or any(candidate.tenant_id != context.tenant_id
                   or not candidate.source_identity.startswith("synthetic://")
                   or not _synthetic(candidate.evidence_refs)
                   or (candidate.financial is not None
                       and (not _synthetic(candidate.financial.evidence_refs)
                            or not candidate.financial.approved_policy_id.startswith("synthetic://")))
                   for candidate in request.candidates)
            or any(not _synthetic(item.evidence_refs) for group in (
                spec.lots, spec.requirements, spec.resources, spec.fixed_jobs, spec.tasks)
                   for item in group)):
        raise DomainError("MOCK_OPTIMIZATION_SOURCE_INVALID",
                          "Portfolio constraints must be current, tenant-bound and synthetic",
                          status_code=422)
    # Input scope flags have no authority. Rebind the isolated server principal.
    request = PortfolioRequest.model_validate(request.model_dump() | {
        "tenant_id": context.tenant_id, "actor_id": context.actor_id,
        "actor_scope_verified": True,
    })
    try:
        validate_spec(request, spec)
    except ValueError as exc:
        raise DomainError("MOCK_OPTIMIZATION_CONSTRAINT_INVALID", str(exc),
                          status_code=422) from exc
    _bind_orders(db, context, request)
    return request, spec


def _view(row: MockOptimizationDatasetRecord) -> MockOptimizationDatasetView:
    return MockOptimizationDatasetView(
        tenant_id=row.tenant_id, dataset_id=row.dataset_id, actor_id=row.actor_id,
        request=PortfolioRequest.model_validate_json(json.dumps(row.request_payload)),
        constraints=P2ConstraintSpec.model_validate_json(json.dumps(row.constraint_payload)),
    )


def seed_dataset(db: Session, context: RequestContext,
                 command: MockOptimizationDatasetCreate) -> MockOptimizationDatasetView:
    request, spec = _validate_fixture(db, context, command)
    request_payload, constraint_payload = request.model_dump(mode="json"), spec.model_dump(mode="json")
    existing = db.get(MockOptimizationDatasetRecord, (context.tenant_id, command.dataset_id))
    if existing is not None:
        if (existing.request_payload, existing.constraint_payload) != (request_payload, constraint_payload):
            raise DomainError("MOCK_OPTIMIZATION_DATASET_CONFLICT", "Dataset ID has other facts",
                              status_code=409)
        return _view(existing)
    now = datetime.now(UTC)
    row = MockOptimizationDatasetRecord(
        tenant_id=context.tenant_id, dataset_id=command.dataset_id,
        request_payload=request_payload, constraint_payload=constraint_payload,
        actor_id=context.actor_id, created_at=now,
    )
    db.add(row)
    audit_id = f"aud_{uuid4().hex}"
    db.add(MockOptimizationAuditRecord(
        audit_id=audit_id, tenant_id=context.tenant_id, dataset_id=command.dataset_id,
        actor_id=context.actor_id, event_type="optimization.mock_constraints_seeded",
        evidence_refs=list(spec.source_refs), reason="Controlled synthetic CP-SAT input",
        occurred_at=now,
    ))
    db.add(OutboxEventRecord(
        event_id=f"evt_{uuid4().hex}", tenant_id=context.tenant_id,
        event_type="optimization.mock_constraints_seeded", commitment_id=None,
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
                dataset_id: str) -> MockOptimizationDatasetRecord:
    row = db.scalar(select(MockOptimizationDatasetRecord).where(
        MockOptimizationDatasetRecord.tenant_id == context.tenant_id,
        MockOptimizationDatasetRecord.dataset_id == dataset_id,
    ))
    if row is None:
        raise DomainError("MOCK_OPTIMIZATION_DATASET_NOT_FOUND", "Portfolio dataset not found",
                          status_code=404)
    return row


class PersistedConstraintProvider:
    def __init__(self, spec: P2ConstraintSpec):
        self.spec = spec

    def build_for_portfolio(self, request: PortfolioRequest) -> P2ConstraintSpec:
        return self.spec


class SyntheticJointVerifier:
    """Check the entire proposed portfolio against the saved synthetic constraints."""

    authority = "SYNTHETIC_TEST_FIXTURE"

    def __init__(self, spec: P2ConstraintSpec, dataset_id: str):
        self.spec = spec
        self.dataset_id = dataset_id

    def verify(self, request: PortfolioRequest,
               projection: ProjectedPortfolio) -> JointVerificationResult:
        spec = self.spec
        selected = set(projection.selected_order_ids)
        if (len(selected) != len(projection.selected_order_ids)
                or not selected <= {c.order_request_id for c in request.candidates}):
            raise ValueError("MOCK_JOINT_SELECTION_INVALID")
        scheduled = {task.task_id: task for task in projection.schedule}
        if len(scheduled) != len(projection.schedule):
            raise ValueError("MOCK_JOINT_SCHEDULE_DUPLICATE")
        required_tasks = {task.task_id for task in spec.tasks if task.order_request_id in selected}
        if set(scheduled) != required_tasks:
            raise ValueError("MOCK_JOINT_SCHEDULE_INCOMPLETE")
        used: dict[str, Decimal] = {}
        for allocation in projection.allocations:
            if allocation.order_request_id not in selected:
                raise ValueError("MOCK_JOINT_ALLOCATION_OUTSIDE_SELECTION")
            used[allocation.lot_id] = used.get(allocation.lot_id, Decimal(0)) + allocation.quantity
        lots = {lot.lot_id: lot for lot in spec.lots}
        required_pairs = {(item.order_request_id, item.line_id) for item in spec.requirements
                          if item.order_request_id in selected}
        if any((item.order_request_id, item.line_id) not in required_pairs
               for item in projection.allocations):
            raise ValueError("MOCK_JOINT_ALLOCATION_UNBOUND")
        if set(used) - set(lots) or any(used.get(lot_id, 0) > lot.free_quantity or used.get(lot_id, 0) < 0
                                       for lot_id, lot in lots.items()):
            raise ValueError("MOCK_JOINT_LOT_CAPACITY")
        for requirement in spec.requirements:
            if requirement.order_request_id not in selected:
                continue
            rows = [item for item in projection.allocations
                    if (item.order_request_id, item.line_id) ==
                    (requirement.order_request_id, requirement.line_id)]
            if sum((item.quantity for item in rows), Decimal(0)) != requirement.quantity:
                raise ValueError("MOCK_JOINT_BOM_QUANTITY")
            for item in rows:
                if item.lot_id not in requirement.compatible_lot_ids or item.quantity <= 0:
                    raise ValueError("MOCK_JOINT_LOT_COMPATIBILITY")
                lot = lots[item.lot_id]
                start = scheduled[requirement.material_use_task_id].start_minute
                if start < lot.available_minute or (lot.expires_minute is not None
                                                    and start >= lot.expires_minute):
                    raise ValueError("MOCK_JOINT_LOT_TIME")
        resources = {resource.resource_id: resource for resource in spec.resources}
        occupied: dict[str, list[tuple[int, int]]] = {name: [] for name in resources}
        for job in spec.fixed_jobs:
            for name in job.resource_ids:
                occupied[name].append((job.start_minute, job.end_minute))
        for task in spec.tasks:
            if task.order_request_id not in selected:
                continue
            scheduled_task = scheduled[task.task_id]
            start, end = scheduled_task.start_minute, scheduled_task.end_minute
            if (scheduled_task.order_request_id != task.order_request_id
                    or end - start != task.duration_minutes
                    or start < task.earliest_start_minute or end > task.latest_end_minute):
                raise ValueError("MOCK_JOINT_TASK_TIME")
            for name in task.resource_ids:
                resource = resources[name]
                if not any(window.start_minute <= start and end <= window.end_minute
                           for window in resource.windows):
                    raise ValueError("MOCK_JOINT_RESOURCE_WINDOW")
                occupied[name].append((start, end))
        if any(any(a[1] > b[0] for a, b in pairwise(sorted(intervals)))
               for intervals in occupied.values()):
            raise ValueError("MOCK_JOINT_RESOURCE_CONTENTION")
        return JointVerificationResult(
            status="FIXTURE_VALIDATED", tenant_id=request.tenant_id,
            snapshot_id=request.snapshot_id, snapshot_version=request.snapshot_version,
            constraint_spec_version=request.constraint_spec_version,
            assessment_watermark=request.assessment_watermark,
            portfolio_run_id=request.portfolio_run_id,
            validated_order_ids=projection.selected_order_ids,
            validated_order_bindings=projection.selected_order_bindings,
            allocation_digest=allocation_digest(projection),
            schedule_digest=schedule_digest(projection),
            projected_portfolio_digest=projected_portfolio_digest(projection),
            portfolio_validation_id=f"synthetic://{self.dataset_id}/{projected_portfolio_digest(projection)}",
            evidence_refs=spec.source_refs,
            evaluated_at=request.evaluated_at,
            valid_through=request.source_valid_through,
            source_authority="SYNTHETIC_TEST_FIXTURE", source_version=self.dataset_id,
        )


def compare_dataset(db: Session, context: RequestContext,
                    dataset_id: str) -> MockOptimizationComparisonView:
    row = get_dataset(db, context, dataset_id)
    request = PortfolioRequest.model_validate_json(json.dumps(row.request_payload))
    spec = P2ConstraintSpec.model_validate_json(json.dumps(row.constraint_payload))
    if request.source_valid_through <= datetime.now(UTC):
        raise DomainError("MOCK_OPTIMIZATION_SOURCE_STALE", "Mock constraints expired",
                          status_code=409)
    _bind_orders(db, context, request)
    result = compare(request, provider=PersistedConstraintProvider(spec),
                     verifier=SyntheticJointVerifier(spec, dataset_id))
    return MockOptimizationComparisonView(dataset_id=dataset_id, result=result)
