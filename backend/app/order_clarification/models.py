"""Values supplied by a future trusted P1/P4 adapter, never raw model extraction."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("offset-aware timestamp required")
    return value


class FieldGroup(StrEnum):
    SKU = "SKU"
    QUANTITY = "QUANTITY"
    DELIVERY = "DELIVERY"
    FULFILMENT = "FULFILMENT"


class IssueState(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    HUMAN_REVIEW = "HUMAN_REVIEW"


class Decision(StrEnum):
    RESOLVED = "RESOLVED"
    VALIDATED_PROGRESS = "VALIDATED_PROGRESS"
    NO_PROGRESS = "NO_PROGRESS"
    IGNORED = "IGNORED"
    HUMAN_REVIEW = "HUMAN_REVIEW"


class Issue(StrictModel):
    tenant_id: str = Field(min_length=1)
    customer_id: str = Field(min_length=1)
    draft_id: str = Field(min_length=1)
    issue_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    field_group: FieldGroup
    allowed_candidates: tuple[str, ...] = ()
    resolved_values: dict[str, str] = Field(default_factory=dict)
    verified_fields: tuple[str, ...] = ()
    consecutive_no_progress: int = Field(default=0, ge=0)
    question_count: int = Field(default=0, ge=0)
    question_id: str | None = None
    question_version: int | None = Field(default=None, ge=1)
    question_sent_at: datetime | None = None
    processed_answer_ids: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    state: IssueState = IssueState.OPEN
    review_reasons: tuple[str, ...] = ()
    draft_created_at: datetime
    created_at: datetime
    updated_at: datetime

    @field_validator("draft_created_at", "created_at", "updated_at", "question_sent_at")
    @classmethod
    def check_time(cls, value: datetime | None) -> datetime | None:
        return aware(value) if value is not None else None


class ValidationPolicy(StrictModel):
    tenant_id: str = Field(min_length=1)
    catalog_skus: frozenset[str]
    permitted_units: frozenset[str]
    max_quantity: Decimal = Field(gt=0)
    business_timezone: str = Field(min_length=1)
    earliest_delivery_at: datetime
    latest_delivery_at: datetime
    max_delivery_window_seconds: int = Field(gt=0)
    required_address_fields: frozenset[str]
    permitted_fulfilment_methods: frozenset[str]
    max_questions: int = Field(gt=0)
    max_age_seconds: int = Field(gt=0)

    @field_validator("earliest_delivery_at", "latest_delivery_at")
    @classmethod
    def check_time(cls, value: datetime) -> datetime:
        return aware(value)


class AnswerEvent(StrictModel):
    tenant_id: str = Field(min_length=1)
    customer_id: str = Field(min_length=1)
    draft_id: str = Field(min_length=1)
    issue_id: str = Field(min_length=1)
    issue_version: int = Field(ge=1)
    question_id: str = Field(min_length=1)
    question_version: int = Field(ge=1)
    answer_id: str = Field(min_length=1)
    response_source_ref: str = Field(min_length=1)
    verified_customer_link: bool
    linked_to_question: bool
    question_send_succeeded: bool
    answered_at: datetime
    evidence_refs: tuple[str, ...] = ()
    selected_sku: str | None = None
    remaining_candidates: tuple[str, ...] | None = None
    quantity: Decimal | None = None
    unit: str | None = None
    delivery_start: datetime | None = None
    delivery_end: datetime | None = None
    delivery_timezone: str | None = None
    address_fields: dict[str, str] = Field(default_factory=dict)
    verified_address_fields: frozenset[str] = frozenset()
    fulfilment_method: str | None = None

    @field_validator("answered_at", "delivery_start", "delivery_end")
    @classmethod
    def check_time(cls, value: datetime | None) -> datetime | None:
        return aware(value) if value is not None else None


class Transition(StrictModel):
    decision: Decision
    reason: str
    issues: tuple[Issue, ...]
