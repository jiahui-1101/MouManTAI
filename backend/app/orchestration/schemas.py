"""Versioned reference-only API contracts for business orchestration."""

from typing import Any, Literal

from pydantic import Field

from app.core.schemas import ContractModel, OffsetAwareDatetime


class ImpactLinkView(ContractModel):
    schema_version: Literal[1] = 1
    tenant_id: str
    impact_id: str
    event_id: str
    idempotency_key: str
    correlation_id: str
    commitment_id: str
    commitment_version: int | None
    classification: str
    link_status: Literal[
        "LINKED_ACCEPTED_ORDER",
        "LINKED_ACCEPTED_ORDER_UNAFFECTED",
        "UNRESOLVED_IMPACT",
        "UNRESOLVED_P2_SOURCE_COMMITMENT",
        "UNRESOLVED_COMMITMENT_TERMS",
        "UNRESOLVED_ORDER_ACCEPTANCE",
    ]
    order_request_id: str | None = None
    order_request_version: int | None = None
    customer_ref: str | None = None
    before_snapshot_id: str
    before_snapshot_version: int
    after_snapshot_id: str
    after_snapshot_version: int
    resource_refs: list[str]
    evidence_refs: list[str]
    reason_codes: list[str]
    source_provenance: dict[str, Any]
    authorization_context: dict[str, Any]
    occurred_at: OffsetAwareDatetime
    integration_mode: Literal["SYNTHETIC"] = "SYNTHETIC"
    evidence_tier: Literal["DEMO-ONLY"] = "DEMO-ONLY"


class ImpactResolutionView(ContractModel):
    schema_version: Literal[1] = 1
    tenant_id: str
    impact_id: str
    event_id: str
    discovery_complete: bool
    overall_status: Literal["LINKED", "UNRESOLVED_HUMAN_REVIEW"]
    links: list[ImpactLinkView]


class NotificationIntentView(ContractModel):
    schema_version: Literal[1] = 1
    intent_id: str
    tenant_id: str
    source_event_id: str
    idempotency_key: str
    source_event_type: str
    correlation_id: str
    causation_id: str | None
    commitment_id: str
    commitment_version: int
    notification_type: str
    status: Literal["UNRESOLVED_ORDER_ACCEPTANCE", "PENDING_P4_REVIEW"]
    blocker_codes: list[str]
    review_requirements: list[str]
    customer_ref: str | None
    contact_ref: str | None
    channel_ref: str | None
    original_channel_ref: str | None
    consent_ref: str | None
    verified_change: dict[str, Any]
    evidence_refs: list[str]
    source_provenance: dict[str, Any]
    authorization_context: dict[str, Any]
    order_request_id: str | None
    order_request_version: int | None
    integration_mode: Literal["SYNTHETIC", "MOCK"]
    evidence_tier: Literal["DEMO-ONLY"]
    verification_status: Literal["INTERNALLY-VERIFIED"]
    created_at: OffsetAwareDatetime
    delivery_status: Literal["NOT_SENT"] = "NOT_SENT"


class TimelineEntry(ContractModel):
    event_id: str
    correlation_id: str | None = None
    event_type: str
    status: str
    entity_id: str
    commitment_id: str
    commitment_version: int | None
    occurred_at: OffsetAwareDatetime
    evidence_refs: list[str] = Field(default_factory=list)
    source_provenance: dict[str, Any] = Field(default_factory=dict)
    authorization_context: dict[str, Any] = Field(default_factory=dict)
    integration_mode: Literal["SYNTHETIC", "MOCK", "MIXED"]
    evidence_tier: Literal["DEMO-ONLY", "INTERNALLY-VERIFIED"]


class CommitmentTimelineView(ContractModel):
    schema_version: Literal[1] = 1
    tenant_id: str
    commitment_id: str
    current_commitment_version: int
    overall_readiness: Literal["PARTIAL", "UNRESOLVED_HUMAN_REVIEW"]
    entries: list[TimelineEntry]
