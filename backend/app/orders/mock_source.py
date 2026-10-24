"""Controlled HTTP seeding of synthetic customer inquiry evidence."""

from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import AwareDatetime, Field
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.models import OutboxEventRecord
from app.orders.models import MockOrderSourceRecord, OrderRequestAuditRecord
from app.orders.terms import ImmutableContract, OrderTerms


class MockInquiryCreate(ImmutableContract):
    source_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    source_version: int = Field(ge=1, strict=True)
    terms: OrderTerms
    customer_request_ref: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    price_disclosure_ref: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    observed_at: AwareDatetime
    valid_through: AwareDatetime


class MockInquiryView(ImmutableContract):
    tenant_id: str
    source_id: str
    source_version: int
    order_request_id: str
    terms_hash: str
    valid_through: AwareDatetime
    integration_mode: Literal["MOCK"] = "MOCK"
    evidence_tier: Literal["DEMO-ONLY"] = "DEMO-ONLY"


def seed_mock_inquiry(db: Session, context: RequestContext, command: MockInquiryCreate) -> MockInquiryView:
    """Fixture administration only; records synthetic intent, never real assent."""
    now = datetime.now(UTC)
    terms = command.terms
    if (terms.tenant_id != context.tenant_id
            or not command.observed_at <= now < command.valid_through
            or command.customer_request_ref not in terms.evidence_refs
            or command.price_disclosure_ref not in terms.price_source.evidence_refs
            or command.price_disclosure_ref not in terms.evidence_refs
            or terms.price_source.disclosed_at > now):
        raise DomainError("MOCK_INQUIRY_INVALID", "Synthetic inquiry binding or freshness is invalid",
                          status_code=422)
    existing = db.get(MockOrderSourceRecord, (context.tenant_id, command.source_id))
    if existing is not None:
        if (existing.source_version != command.source_version
                or existing.terms != terms.model_dump(mode="json")
                or existing.customer_request_ref != command.customer_request_ref
                or existing.price_disclosure_ref != command.price_disclosure_ref):
            raise DomainError("MOCK_INQUIRY_CONFLICT", "Synthetic source ID already has other evidence",
                              status_code=409)
        return MockInquiryView(tenant_id=context.tenant_id, source_id=command.source_id,
                               source_version=command.source_version,
                               order_request_id=terms.order_request_id,
                               terms_hash=terms.terms_hash, valid_through=existing.valid_through)
    source = MockOrderSourceRecord(
        tenant_id=context.tenant_id, source_id=command.source_id,
        customer_id=terms.customer_id, source_version=command.source_version,
        terms=terms.model_dump(mode="json"),
        customer_request_ref=command.customer_request_ref,
        price_disclosure_ref=command.price_disclosure_ref,
        observed_at=command.observed_at, valid_through=command.valid_through,
        status="CURRENT",
    )
    audit_id = f"aud_{uuid4().hex}"
    db.add_all([
        source,
        OrderRequestAuditRecord(
            audit_id=audit_id, tenant_id=context.tenant_id,
            order_request_id=terms.order_request_id, event_type="mock.inquiry_seeded",
            actor_id=context.actor_id, request_version=command.source_version,
            evidence_refs=[command.customer_request_ref, command.price_disclosure_ref],
            reason="Controlled synthetic customer inquiry fixture", occurred_at=now,
        ),
        OutboxEventRecord(
            event_id=f"evt_{uuid4().hex}", tenant_id=context.tenant_id,
            event_type="mock.inquiry_seeded", commitment_id=None, commitment_version=None,
            correlation_id=context.correlation_id, causation_id=context.causation_id,
            occurred_at=now,
            payload={"order_request_id": terms.order_request_id, "source_id": command.source_id,
                     "source_version": command.source_version, "audit_id": audit_id,
                     "integration_mode": "MOCK"},
            published_at=None, attempts=0, status="PENDING", last_error=None, next_retry_at=None,
        ),
    ])
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return MockInquiryView(tenant_id=context.tenant_id, source_id=command.source_id,
                           source_version=command.source_version,
                           order_request_id=terms.order_request_id,
                           terms_hash=terms.terms_hash, valid_through=command.valid_through)
