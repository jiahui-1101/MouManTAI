"""Immutable consumer contracts. P2, not this module, owns their business meaning."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class Strategy(StrEnum):
    FCFS = "FCFS"
    PROFIT = "PROFIT"
    EXPIRY_AWARE = "EXPIRY_AWARE"


class SolverStatus(StrEnum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    OPTIMAL = "OPTIMAL"
    FEASIBLE_NOT_PROVEN_OPTIMAL = "FEASIBLE_NOT_PROVEN_OPTIMAL"
    INFEASIBLE = "INFEASIBLE"
    UNKNOWN = "UNKNOWN"
    MODEL_INVALID = "MODEL_INVALID"
    SOLVER_UNAVAILABLE = "SOLVER_UNAVAILABLE"


class CandidateLine(Frozen):
    line_id: str = Field(min_length=1)
    sku_id: str = Field(min_length=1)
    quantity: Decimal = Field(gt=0)
    unit: str = Field(min_length=1)


class FinancialEvidence(Frozen):
    order_request_id: str = Field(min_length=1)
    request_version: int = Field(gt=0)
    terms_hash: str = Field(min_length=1)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    revenue: Decimal = Field(ge=0)
    material_cost: Decimal = Field(ge=0)
    labor_cost: Decimal = Field(ge=0)
    freight_cost: Decimal = Field(ge=0)
    price_revision: str = Field(min_length=1)
    valid_through: datetime
    approved_policy_id: str = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(min_length=1)

    @field_validator("valid_through")
    @classmethod
    def valid_through_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("financial evidence time must be offset-aware")
        return value


class PendingOrderCandidate(Frozen):
    order_request_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    request_version: int = Field(gt=0)
    terms_revision: int = Field(gt=0)
    terms_hash: str = Field(min_length=1)
    lines: tuple[CandidateLine, ...] = Field(min_length=1)
    deadline: datetime
    received_at: datetime
    received_at_verified: bool
    source_identity: str = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    decision_readiness: Literal["READY", "INCOMPLETE", "UNKNOWN"]
    state: Literal["PENDING", "ACCEPTED", "CANCELLED"]
    financial: FinancialEvidence | None = None

    @model_validator(mode="after")
    def unique_lines(self) -> Self:
        if len({line.line_id for line in self.lines}) != len(self.lines):
            raise ValueError("duplicate candidate line")
        if self.financial is not None and (
            self.financial.order_request_id != self.order_request_id
            or self.financial.request_version != self.request_version
            or self.financial.terms_hash != self.terms_hash
        ):
            raise ValueError("financial evidence does not bind exact order terms")
        return self


class SolverConfig(Frozen):
    max_seconds: Decimal = Field(gt=0, le=30)
    random_seed: int = Field(ge=0, le=2**31 - 1)
    workers: Literal[1] = 1
    quantity_scale: int = Field(ge=1, le=1_000_000)
    currency_scale: int = Field(ge=1, le=1_000_000)
    max_candidates: int = Field(ge=1, le=20)
    max_lots: int = Field(ge=1, le=100)
    max_skus: int = Field(default=100, ge=1, le=100)
    max_requirements: int = Field(default=200, ge=1, le=200)
    max_tasks: int = Field(default=100, ge=1, le=100)
    max_fixed_jobs: int = Field(default=200, ge=0, le=200)
    max_resources: int = Field(ge=1, le=30)
    max_horizon_minutes: int = Field(ge=1, le=60 * 24 * 31)

    @model_validator(mode="after")
    def decimal_scales(self) -> Self:
        for scale in (self.quantity_scale, self.currency_scale):
            if scale != 10 ** (len(str(scale)) - 1):
                raise ValueError("solver scales must be powers of ten")
        return self


class PortfolioRequest(Frozen):
    tenant_id: str = Field(min_length=1)
    portfolio_run_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    actor_scope_verified: bool
    snapshot_id: str = Field(min_length=1)
    snapshot_version: int = Field(gt=0)
    constraint_spec_version: str = Field(min_length=1)
    assessment_watermark: str = Field(min_length=1)
    business_timezone: str = Field(min_length=1)
    evaluated_at: datetime
    source_valid_through: datetime
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    integration_mode: Literal["LIVE", "SYNTHETIC"]
    comparison_requested: bool
    solver: SolverConfig
    candidates: tuple[PendingOrderCandidate, ...] = Field(min_length=1)

    @field_validator("business_timezone")
    @classmethod
    def timezone_known(cls, value: str) -> str:
        ZoneInfo(value)
        return value

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        if not self.actor_scope_verified:
            raise ValueError("actor scope must be verified by an authoritative reader")
        if len(self.candidates) > self.solver.max_candidates:
            raise ValueError("candidate limit exceeded")
        if sum(len(c.lines) for c in self.candidates) > self.solver.max_requirements:
            raise ValueError("candidate line limit exceeded")
        if len({c.order_request_id for c in self.candidates}) != len(self.candidates):
            raise ValueError("duplicate order request")
        if any(c.tenant_id != self.tenant_id for c in self.candidates):
            raise ValueError("candidate tenant mismatch")
        if any(c.state != "PENDING" or c.decision_readiness != "READY" for c in self.candidates):
            raise ValueError("only ready pending orders may be optimized")
        if any(not c.received_at_verified for c in self.candidates):
            raise ValueError("unverified FCFS received timestamp")
        instants = (
            self.evaluated_at,
            self.source_valid_through,
            *(c.deadline for c in self.candidates),
            *(c.received_at for c in self.candidates),
        )
        if any(t.tzinfo is None or t.utcoffset() is None for t in instants):
            raise ValueError("timestamps must be offset-aware")
        if self.source_valid_through < self.evaluated_at:
            raise ValueError("stale source")
        if any(c.received_at > self.evaluated_at for c in self.candidates):
            raise ValueError("future received timestamp")
        return self


class AuthorizedLot(Frozen):
    lot_id: str = Field(min_length=1)
    sku_id: str = Field(min_length=1)
    warehouse_id: str = Field(min_length=1)
    free_quantity: Decimal = Field(ge=0)  # P2 has already protected accepted reservations.
    unit: str = Field(min_length=1)
    available_minute: int = Field(ge=0)
    expires_minute: int | None = Field(default=None, gt=0)  # exclusive material-use boundary
    evidence_refs: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def valid_interval(self) -> Self:
        if self.expires_minute is not None and self.expires_minute <= self.available_minute:
            raise ValueError("lot expires before it becomes available")
        return self


class MaterialRequirement(Frozen):
    order_request_id: str = Field(min_length=1)
    line_id: str = Field(min_length=1)
    sku_id: str = Field(min_length=1)
    quantity: Decimal = Field(gt=0)
    unit: str = Field(min_length=1)
    compatible_lot_ids: tuple[str, ...]
    material_use_task_id: str = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(min_length=1)


class ResourceWindow(Frozen):
    start_minute: int = Field(ge=0)
    end_minute: int = Field(gt=0)

    @model_validator(mode="after")
    def valid_interval(self) -> Self:
        if self.end_minute <= self.start_minute:
            raise ValueError("empty resource window")
        return self


class AuthorizedResource(Frozen):
    resource_id: str = Field(min_length=1)
    windows: tuple[ResourceWindow, ...] = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(min_length=1)


class FixedJob(Frozen):
    job_id: str = Field(min_length=1)
    resource_ids: tuple[str, ...] = Field(min_length=1)
    start_minute: int = Field(ge=0)
    end_minute: int = Field(gt=0)
    evidence_refs: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def valid_interval(self) -> Self:
        if self.end_minute <= self.start_minute:
            raise ValueError("empty fixed job")
        return self


class ProductionTask(Frozen):
    task_id: str = Field(min_length=1)
    order_request_id: str = Field(min_length=1)
    line_id: str = Field(min_length=1)
    resource_ids: tuple[str, ...] = Field(min_length=1)
    duration_minutes: int = Field(gt=0)  # P2-owned duration, including approved setup.
    earliest_start_minute: int = Field(ge=0)
    latest_end_minute: int = Field(gt=0)  # P2-owned dispatch/deadline bound.
    evidence_refs: tuple[str, ...] = Field(min_length=1)


class CandidateBinding(Frozen):
    order_request_id: str = Field(min_length=1)
    request_version: int = Field(gt=0)
    terms_revision: int = Field(gt=0)
    terms_hash: str = Field(min_length=1)
    source_identity: str = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(min_length=1)


class P2ConstraintSpec(Frozen):
    """P2-owned semantic result consumed verbatim; fixture values are test-only."""

    owner: Literal["P2", "SYNTHETIC_TEST_FIXTURE"]
    tenant_id: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    snapshot_version: int = Field(gt=0)
    spec_version: str = Field(min_length=1)
    assessment_watermark: str = Field(min_length=1)
    candidate_bindings: tuple[CandidateBinding, ...] = Field(min_length=1)
    horizon_minutes: int = Field(gt=0)
    lots: tuple[AuthorizedLot, ...]
    requirements: tuple[MaterialRequirement, ...]
    resources: tuple[AuthorizedResource, ...]
    fixed_jobs: tuple[FixedJob, ...]
    tasks: tuple[ProductionTask, ...]
    accepted_reservations_protected: bool
    source_refs: tuple[str, ...] = Field(min_length=1)


class LotAllocation(Frozen):
    order_request_id: str
    line_id: str
    lot_id: str
    quantity: Decimal


class ScheduledTask(Frozen):
    task_id: str
    order_request_id: str
    start_minute: int
    end_minute: int


class ProjectedPortfolio(Frozen):
    tenant_id: str
    portfolio_run_id: str
    snapshot_id: str
    snapshot_version: int
    spec_version: str
    assessment_watermark: str
    selected_order_ids: tuple[str, ...]
    selected_order_bindings: tuple[CandidateBinding, ...]
    allocations: tuple[LotAllocation, ...]
    schedule: tuple[ScheduledTask, ...]


class JointVerificationResult(Frozen):
    status: Literal["P2_VALIDATED", "FIXTURE_VALIDATED", "P2_REJECTED", "UNKNOWN"]
    tenant_id: str
    snapshot_id: str
    snapshot_version: int
    constraint_spec_version: str
    assessment_watermark: str
    portfolio_run_id: str
    validated_order_ids: tuple[str, ...]
    validated_order_bindings: tuple[CandidateBinding, ...]
    allocation_digest: str
    schedule_digest: str
    projected_portfolio_digest: str
    portfolio_validation_id: str | None
    evidence_refs: tuple[str, ...]
    evaluated_at: datetime
    valid_through: datetime
    source_authority: Literal["P2", "SYNTHETIC_TEST_FIXTURE"]
    source_version: str
    reason_codes: tuple[str, ...] = ()

    @field_validator("evaluated_at", "valid_through")
    @classmethod
    def receipt_times_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("receipt timestamps must be offset-aware")
        return value


class Exclusion(Frozen):
    order_request_id: str
    reason_code: str


class PortfolioScenario(Frozen):
    strategy: Strategy
    tenant_id: str = ""
    snapshot_id: str = ""
    snapshot_version: int = 0
    constraint_spec_version: str = ""
    integration_mode: Literal["LIVE", "SYNTHETIC"] = "SYNTHETIC"
    solver_implementation: str = "OR-Tools CP-SAT"
    solver_version: str = ""
    selected_order_ids: tuple[str, ...] = ()
    exclusions: tuple[Exclusion, ...] = ()
    allocations: tuple[LotAllocation, ...] = ()
    schedule: tuple[ScheduledTask, ...] = ()
    solver_status: SolverStatus = SolverStatus.NOT_APPLICABLE
    validation_status: str = "NOT_VALIDATED"
    validation_id: str | None = None
    objective_value: Decimal | None = None
    objective_unit: str | None = None
    evidence_refs: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    evidence_maturity: Literal["TEST_FIXTURE", "P2_VERIFIED", "UNVERIFIED"] = "UNVERIFIED"
    diagnostics: tuple[str, ...] = ()
    recommendation_only: Literal[True] = True


class ComparisonResult(Frozen):
    tenant_id: str
    portfolio_run_id: str
    snapshot_id: str
    snapshot_version: int
    constraint_spec_version: str
    trigger: str
    integration_mode: Literal["LIVE", "SYNTHETIC"]
    scenarios: tuple[PortfolioScenario, ...] = ()
    limitation_codes: tuple[str, ...] = ()
    recommendation_only: Literal[True] = True
