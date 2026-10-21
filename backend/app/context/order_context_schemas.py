"""P1 OrderContext domain models, lifecycle enums, and review schemas."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ContextReadinessStatus = Literal[
    "INFORMATION_READY",
    "INFORMATION_PARTIAL",
    "CONFLICT",
    "UNRESOLVED",
]

ReviewAction = Literal[
    "ACCEPT_EXTRACTION",
    "EDIT_FIELD",
    "REQUEST_MORE_INFO",
    "MARK_UNRESOLVED",
]

ChangeType = Literal[
    "INITIAL_CREATION",
    "MESSAGE_MERGE",
    "HUMAN_EDIT",
    "ACCEPT_EXTRACTION",
    "EDIT_FIELD",
    "HUMAN_ACCEPT",
    "MARK_UNRESOLVED",
    "REQUEST_MORE_INFO",
]

CustomerIdentityStatus = Literal[
    "UNVERIFIED",
    "LINK_CANDIDATE",
    "LINK_VERIFIED",
    "CONFLICT",
]


class P1ContextModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)


class RequestedItem(P1ContextModel):
    sku: str = Field(min_length=1)
    quantity: str = Field(min_length=1)
    unit: str = Field(min_length=1)

    @field_validator("quantity")
    @classmethod
    def validate_positive_quantity(cls, value: str) -> str:
        try:
            val = Decimal(value)
            if val <= 0:
                raise ValueError("Quantity must be positive")
        except Exception:
            raise ValueError("Quantity must be a positive decimal string")
        return value


class FieldEvidenceSpan(P1ContextModel):
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    quote: str
    method: str


class OrderContextRecord(P1ContextModel):
    context_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    order_id: str | None = None
    customer_id: str | None = None
    customer_identity_status: CustomerIdentityStatus = "UNVERIFIED"
    status: ContextReadinessStatus = "UNRESOLVED"
    context_version: int = Field(ge=1, default=1)
    requested_items: list[RequestedItem] = Field(default_factory=list)
    requested_delivery_at: datetime | None = None
    delivery_qualifier: str | None = None
    special_instructions: str | None = None
    source_message_ids: list[str] = Field(default_factory=list)
    field_evidence: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    last_reviewed_by: str | None = None
    last_reviewed_role: str | None = None
    last_reviewed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class OrderContextVersionRecord(P1ContextModel):
    version_id: str = Field(min_length=1)
    context_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    context_version: int = Field(ge=1)
    snapshot: dict[str, Any]
    change_type: ChangeType
    actor_id: str | None = None
    actor_role: str | None = None
    reason: str | None = None
    created_at: datetime


class ContextReviewRecord(P1ContextModel):
    review_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    context_id: str = Field(min_length=1)
    context_version_before: int = Field(ge=1)
    context_version_after: int = Field(ge=1)
    action: ReviewAction
    actor_id: str
    actor_role: str
    field_changes: dict[str, dict[str, Any]] = Field(default_factory=dict)
    note: str | None = None
    created_at: datetime


class ContextReviewRequest(P1ContextModel):
    expected_context_version: int = Field(ge=1)
    action: ReviewAction
    field_edits: dict[str, Any] = Field(default_factory=dict)
    note: str | None = None


class ContextUpdateRequest(P1ContextModel):
    expected_context_version: int = Field(ge=1)
    requested_items: list[RequestedItem] | None = None
    requested_delivery_at: datetime | None = None
    delivery_qualifier: str | None = None
    special_instructions: str | None = None
    reason: str | None = None
