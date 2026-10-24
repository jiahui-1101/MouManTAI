"""Immutable references to owner records; never an operational source of truth."""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Domain(StrEnum):
    ORDER = "ORDER"
    SUPPLIER = "SUPPLIER"
    CAPACITY = "CAPACITY"
    RECOVERY = "RECOVERY"


CONTEXT_FIELDS = {
    Domain.ORDER: {"order_category", "requirements", "terms_change", "agreement_dependency"},
    Domain.SUPPLIER: {"product_category", "spec_category", "availability", "needed_by"},
    Domain.CAPACITY: {"resource", "time_window", "booking_conflict", "production_constraint"},
    Domain.RECOVERY: {"disruption", "resource", "urgency", "response", "approval_requirement"},
}


class OutcomeClass(StrEnum):
    VERIFIED_SUCCESS = "VERIFIED_SUCCESS"
    VERIFIED_FAILURE = "VERIFIED_FAILURE"
    PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED"
    REPORTED_ONLY = "REPORTED_ONLY"
    UNKNOWN = "UNKNOWN"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"


class SourceMode(StrEnum):
    DEMO_ONLY = "DEMO_ONLY"
    LIVE = "LIVE"


class Evidence(FrozenModel):
    evidence_id: str = Field(min_length=1)
    owner: str = Field(min_length=1)
    subject_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    source_version: int = Field(ge=1)
    occurred_at: AwareDatetime
    corrects_id: str | None = None
    authenticated: bool = False  # A reader assertion; never sufficient on its own.


class Event(FrozenModel):
    event_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    commitment_id: str | None = None
    recovery_case_id: str | None = None
    plan_id: str | None = None
    plan_version: int | None = Field(default=None, ge=1)
    subject_id: str | None = None
    source_snapshot_id: str = Field(min_length=1)
    source_snapshot_version: int = Field(ge=1)
    kind: Literal["SITUATION", "ALTERNATIVE", "DECISION", "APPROVAL", "EXECUTION", "OUTCOME"]
    ref: str = Field(min_length=1)
    occurred_at: AwareDatetime
    actor_ref: str | None = None
    selected_ref: str | None = None
    status: str | None = None
    evidence_ids: tuple[str, ...] = ()
    corrects_id: str | None = None


class SourceManifest(FrozenModel):
    tenant_id: str = Field(min_length=1)
    source_reader_id: str = Field(min_length=1)
    source_snapshot_id: str = Field(min_length=1)
    source_snapshot_version: int = Field(ge=1)
    source_version: int = Field(ge=1)
    source_watermark: AwareDatetime
    covered_time_start: AwareDatetime
    covered_time_end: AwareDatetime
    as_of: AwareDatetime
    pagination_complete: bool
    source_population_complete: bool
    missing_source_names: tuple[str, ...] = ()
    integration_mode: SourceMode
    evidence_maturity: str = Field(min_length=1)
    provenance_refs: tuple[str, ...] = ()


class CaseInput(FrozenModel):
    memory_case_id: str = Field(min_length=1)
    case_version: int = Field(ge=1)
    domain: Domain
    tenant_id: str = Field(min_length=1)
    commitment_id: str | None = None
    order_id: str | None = None
    supplier_id: str | None = None
    recovery_case_id: str | None = None
    business_context_ref: str = Field(min_length=1)
    business_context_version: int = Field(ge=1)
    context_schema: str = Field(min_length=1)
    # Only versioned categorical keys approved by the reader belong here.
    context: tuple[tuple[str, str], ...]
    hard_constraints: tuple[tuple[str, str], ...]
    events: tuple[Event, ...]
    evidence: tuple[Evidence, ...]

    @model_validator(mode="after")
    def unique_features(self):
        for pairs in (self.context, self.hard_constraints):
            if len(dict(pairs)) != len(pairs):
                raise ValueError("duplicate context key")
        if not set(dict(self.context)) <= CONTEXT_FIELDS[self.domain]:
            raise ValueError("unapproved similarity feature")
        if any(len(value) > 64 for _, value in self.context):
            raise ValueError("oversized similarity value")
        return self


class DecisionMemoryCase(FrozenModel):
    tenant_id: str
    memory_case_id: str
    case_version: int
    decision_domain: Domain
    commitment_id: str | None
    order_id: str | None
    supplier_id: str | None
    recovery_case_id: str | None
    situation_ref: str
    situation_timestamp: AwareDatetime
    business_context_ref: str
    business_context_version: int
    context_schema: str
    context: tuple[tuple[str, str], ...]
    hard_constraints: tuple[tuple[str, str], ...]
    source_snapshot_id: str
    source_snapshot_version: int
    alternatives_refs: tuple[str, ...]
    selected_alternative_ref: str
    sme_actor_ref: str
    sme_decision_ref: str
    decision_reason_ref: str | None
    decision_timestamp: AwareDatetime
    plan_id: str | None
    plan_version: int | None
    approval_ref: str | None
    approval_version: int | None
    approval_granted: bool
    execution_ref: str | None
    execution_version: int | None
    execution_status: str
    outcome_ref: str | None
    outcome_evidence_refs: tuple[str, ...]
    outcome_timestamp: AwareDatetime | None
    outcome_verification_status: OutcomeClass
    integration_mode: SourceMode
    evidence_maturity: str
    source_watermark: AwareDatetime
    created_at: AwareDatetime
    observed_as_of: AwareDatetime
    provenance_refs: tuple[str, ...]


class RetrievalPolicy(FrozenModel):
    policy_id: str = Field(min_length=1)
    policy_version: int = Field(ge=1)
    tenant_id: str = Field(min_length=1)
    domain: Domain
    minimum_eligible_cases: int = Field(ge=1)
    required_attributes: tuple[str, ...]
    permitted_dimensions: tuple[str, ...]
    required_outcome_evidence: bool = True
    max_age_days: int = Field(gt=0, le=3650)
    max_candidates: int = Field(gt=0, le=1000)
    max_results: int = Field(gt=0, le=50)
    retention_ref: str = Field(min_length=1)
    privacy_ref: str = Field(min_length=1)
    approval_ref: str = Field(min_length=1)
    effective_at: AwareDatetime
    expires_at: AwareDatetime
    test_only: bool = False


class CurrentSituation(FrozenModel):
    tenant_id: str
    domain: Domain
    situation_version: int = Field(ge=1)
    business_context_ref: str
    context_schema: str
    context: tuple[tuple[str, str], ...]
    hard_constraints: tuple[tuple[str, str], ...]
    evidence_refs: tuple[str, ...]
    as_of: AwareDatetime


class Match(FrozenModel):
    memory_case_id: str
    domain: Domain
    case_version: int
    selected_historical_alternative: str
    historical_decision_ref: str
    historical_outcome_class: OutcomeClass
    actual_outcome_ref: str
    verified_evidence_refs: tuple[str, ...]
    matching_attributes: tuple[str, ...]
    differing_attributes: tuple[str, ...]
    unknown_attributes: tuple[str, ...]
    reason_codes: tuple[str, ...]
    source_freshness: datetime
    evidence_maturity: str
    limitations: tuple[str, ...] = ("ADVISORY_ONLY", "PAST_DECISION_IS_NOT_CURRENT_AUTHORITY")


class RetrievalResult(FrozenModel):
    status: str
    eligible_count: int
    matches: tuple[Match, ...] = ()
    limitations: tuple[str, ...] = ()
