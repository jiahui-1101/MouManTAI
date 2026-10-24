"""Controlled, repeatable synthetic Orbyte inventory/BOM/capacity fixture."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import uuid4

from pydantic import Field, field_validator
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.models import OutboxEventRecord
from app.feasibility.production import EvaluationSnapshot
from app.feasibility.production_fixtures import build_production_example
from app.orders.models import MockOrbyteStateRecord
from app.orders.terms import ImmutableContract


class MockResourceSeed(ImmutableContract):
    stock_quantity: Decimal = Field(ge=0, le=100000)
    next_reservation_outcome: Literal["NORMAL", "REJECT", "UNKNOWN"] = "NORMAL"

    @field_validator("stock_quantity", mode="before")
    @classmethod
    def exact_stock(cls, value):
        if isinstance(value, (float, bool)):
            raise ValueError("Mock stock must be an exact decimal string or integer")  # noqa: TRY004
        return value


def build_mock_resources(tenant_id: str, stock_quantity: Decimal) -> EvaluationSnapshot:
    """Move every dated synthetic fact together so evidence expires consistently."""
    original, _ = build_production_example()
    shift = datetime.now(UTC) - original.as_of - timedelta(minutes=1)

    def move(value):
        if isinstance(value, datetime):
            return value + shift
        if isinstance(value, dict):
            return {key: tenant_id if key == "tenant_id" else move(item)
                    for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [move(item) for item in value]
        return value

    payload = move(original.model_dump(exclude_computed_fields=True))
    payload["operational"]["inventory_lots"][0]["quantity"] = stock_quantity
    return EvaluationSnapshot.model_validate(payload)


def seed_mock_resources(db: Session, context: RequestContext,
                        command: MockResourceSeed) -> EvaluationSnapshot:
    if db.get(MockOrbyteStateRecord, context.tenant_id) is not None:
        raise DomainError("MOCK_RESOURCE_ALREADY_CONFIGURED",
                          "Synthetic resource state already exists for this tenant", status_code=409)
    now = datetime.now(UTC)
    snapshot = build_mock_resources(context.tenant_id, command.stock_quantity)
    db.add(MockOrbyteStateRecord(
        tenant_id=context.tenant_id, snapshot_version=1,
        snapshot_payload=snapshot.model_dump(mode="json", exclude_computed_fields=True),
        next_outcome=command.next_reservation_outcome, updated_at=now,
    ))
    db.add(OutboxEventRecord(
        event_id=f"evt_{uuid4().hex}", tenant_id=context.tenant_id,
        event_type="mock.resources_seeded", commitment_id=None, commitment_version=None,
        correlation_id=context.correlation_id, causation_id=context.causation_id,
        occurred_at=now,
        payload={"snapshot_id": snapshot.operational.snapshot_id, "snapshot_version": 1,
                 "stock_quantity": str(command.stock_quantity), "integration_mode": "MOCK",
                 "evidence_tier": "DEMO-ONLY"},
        published_at=None, attempts=0, status="PENDING", last_error=None, next_retry_at=None,
    ))
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return snapshot
