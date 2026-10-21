"""Schemas for Batch 2: Verified Identity and Order Association.

Strictly distinguishes:
- Platform identity (channel + sender phone/id)
- Customer account (tenant-scoped business entity)
- Verified link (cryptographically or administratively confirmed binding)
- Suggested match (candidate hypothesis requiring review)

Never establishes identity from name similarity or model output alone.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class IdentityLinkStatus(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    LINK_CANDIDATE = "LINK_CANDIDATE"
    LINK_VERIFIED = "LINK_VERIFIED"
    CONFLICT = "CONFLICT"


class MatchType(StrEnum):
    TRUSTED_SENDER = "TRUSTED_SENDER"
    EXTRACTED_ORDER_REF = "EXTRACTED_ORDER_REF"
    THREAD_LINK = "THREAD_LINK"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"


class PlatformIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel: str = Field(min_length=1, max_length=20)
    sender_identity_id: str = Field(min_length=1, max_length=200)
    sender_alias: str = Field(min_length=1, max_length=200)


class CustomerAccount(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customer_id: str = Field(min_length=1, max_length=100)
    tenant_id: str = Field(min_length=1, max_length=100)
    legal_name: str = Field(min_length=1, max_length=200)
    display_name: str = Field(min_length=1, max_length=200)
    active: bool = True
    verified_channels: list[str] = Field(default_factory=list)


class OrderReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_id: str = Field(min_length=1, max_length=100)
    customer_id: str = Field(min_length=1, max_length=100)
    tenant_id: str = Field(min_length=1, max_length=100)
    status: str = Field(min_length=1, max_length=30)
    description: str = Field(default="", max_length=500)


class AssociationCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customer_id: str = Field(min_length=1, max_length=100)
    customer_name: str = Field(min_length=1, max_length=200)
    order_id: str | None = Field(default=None, max_length=100)
    match_type: MatchType
    reasons: list[str] = Field(min_length=1)
    evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class AssociationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["CONFIRMED", "REJECTED"]
    target_customer_id: str | None = None
    target_order_id: str | None = None
    actor_id: str = Field(min_length=1, max_length=100)
    actor_role: str = Field(min_length=1, max_length=50)
    reason: str = Field(min_length=1, max_length=1000)
    decided_at: datetime


class MessageAssociationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    association_id: str
    tenant_id: str
    message_id: str
    status: IdentityLinkStatus
    verified_customer: CustomerAccount | None = None
    verified_order: OrderReference | None = None
    candidates: list[AssociationCandidate] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    last_decision: AssociationDecision | None = None
    version: int = Field(ge=1)
    updated_at: datetime


class AssociationDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["CONFIRMED", "REJECTED"]
    target_customer_id: str | None = None
    target_order_id: str | None = None
    reason: str = Field(min_length=1, max_length=1000)
    expected_version: int = Field(ge=1)
