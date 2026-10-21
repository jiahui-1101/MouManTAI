"""Synthetic test data models, not domain repositories or shared contracts."""

from typing import Literal

from pydantic import Field, model_validator

from .schemas import BusinessContext, ContextReview, Identifier, NormalizedMessage, P1Model, RequestedItem


class CustomerFixture(P1Model):
    tenant_id: Identifier
    customer_id: Identifier
    alias: Identifier
    verified_identity_ids: list[Identifier]


class SkuFixture(P1Model):
    tenant_id: Identifier
    sku: Identifier
    label: Identifier
    unit: Literal["pcs", "kg", "box"]


class OrderFixture(P1Model):
    tenant_id: Identifier
    order_id: Identifier
    customer_id: Identifier
    items: list[RequestedItem]
    commitment_ref: str | None = None
    agreement_state: Literal["REQUESTED", "CONFIRMED"]


class InboxRecord(P1Model):
    scenario_id: Identifier
    title: Identifier
    message: NormalizedMessage
    context: BusinessContext
    review: ContextReview

    @model_validator(mode="after")
    def consistent_local_references(self):
        if len({self.message.raw.tenant_id, self.context.tenant_id, self.review.tenant_id}) != 1:
            raise ValueError("fixture record must not mix tenants")
        if self.review.context_id != self.context.context_id:
            raise ValueError("review must reference the record context")
        if self.review.expected_context_version != self.context.context_version:
            raise ValueError("fixture review must reference current context version")
        if self.message.message_id not in self.context.source_message_ids:
            raise ValueError("context must reference its message")
        evidence_ids = {e.evidence_id for f in self.message.fields for e in f.evidence}
        if any(ref not in evidence_ids for refs in self.context.field_evidence.values() for ref in refs):
            raise ValueError("context evidence references must resolve in this preview")
        return self


class ScenarioExpectation(P1Model):
    scenario_id: Identifier
    behavior: Identifier
    expected_readiness: Literal["READY", "PARTIAL", "CONFLICT", "UNRESOLVED"]
    expected_order_id: str | None
    candidate_order_ids: list[str] = Field(default_factory=list)
    duplicate_of: str | None = None
    expected_quantity: str | None = None
    expected_delivery_at: str | None = None
    expected_next_action: Identifier


class FixtureCatalog(P1Model):
    mode: Literal["SYNTHETIC_FIXTURES"]
    business_timezone: Literal["Asia/Kuala_Lumpur"]
    customers: list[CustomerFixture]
    skus: list[SkuFixture]
    orders: list[OrderFixture]
    records: list[InboxRecord]
    expectations: list[ScenarioExpectation]


class InboxPreview(P1Model):
    mode: Literal["SYNTHETIC_FIXTURES"]
    business_timezone: Literal["Asia/Kuala_Lumpur"]
    records: list[InboxRecord]
