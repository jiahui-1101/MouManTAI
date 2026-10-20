"""Validated, immutable P2-local operational snapshot models.

This module deliberately does not define shared persistence or Commitment state.
P5 owns those contracts; this shape is an input adapter for P2's later pure
calculation phases.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, ClassVar, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    computed_field,
    field_validator,
    model_validator,
)


PositiveQuantity = Annotated[Decimal, Field(gt=0)]


class SourceKind(StrEnum):
    SKU_CATALOG = "sku_catalog"
    BOM = "bom"
    INVENTORY = "inventory"
    RESERVATIONS = "reservations"
    INCOMING_DELIVERIES = "incoming_deliveries"
    CAPACITY_CALENDARS = "capacity_calendars"
    CONFIRMED_COMMITMENTS = "confirmed_commitments"
    LOGISTICS_CUTOFF = "logistics_cutoff"


class FreshnessStatus(StrEnum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    MISSING = "MISSING"


class SnapshotValidationStatus(StrEnum):
    VALID = "VALID"
    INCOMPLETE = "INCOMPLETE"


class IssueSeverity(StrEnum):
    WARNING = "WARNING"
    INCOMPLETE = "INCOMPLETE"


class SkuSupplyType(StrEnum):
    PURCHASED = "PURCHASED"
    MANUFACTURED = "MANUFACTURED"


class ReservationStatus(StrEnum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    CONSUMED = "CONSUMED"


class DeliveryConfirmationStatus(StrEnum):
    CONFIRMED = "CONFIRMED"
    UNCONFIRMED = "UNCONFIRMED"


class FrozenModel(BaseModel):
    """Pydantic value object with immutable fields and aware timestamps."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    @field_validator("*", mode="before")
    @classmethod
    def quantities_must_not_use_binary_floats(cls, value: object, info: ValidationInfo) -> object:
        if info.field_name in {"quantity", "available_minutes"} and isinstance(value, float):
            raise ValueError("quantities must be a decimal value or integer, not a float")
        return value

    @field_validator("*", mode="after")
    @classmethod
    def datetime_values_must_be_offset_aware(cls, value: object) -> object:
        if isinstance(value, datetime) and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("datetime values must be offset-aware")
        return value


def _utc(value: datetime) -> datetime:
    """Normalize instants for comparisons without depending on host timezone."""

    return value.astimezone(timezone.utc)


class SourceEvidence(FrozenModel):
    """One captured source observation; business rows refer to its source_id."""

    source_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    kind: SourceKind
    source_ref: str | None
    observed_at: datetime | None
    valid_through: datetime | None
    evidence_refs: tuple[str, ...] = ()

    @model_validator(mode="after")
    def source_metadata_is_consistent(self) -> Self:
        if self.source_ref is None:
            if self.observed_at is not None or self.valid_through is not None or self.evidence_refs:
                raise ValueError("missing source cannot claim observation times or evidence refs")
            return self
        if not self.source_ref:
            raise ValueError("source_ref must be non-empty when a source is present")
        if self.observed_at is None or self.valid_through is None:
            raise ValueError("present source requires observed_at and valid_through freshness bounds")
        if _utc(self.valid_through) < _utc(self.observed_at):
            raise ValueError("source valid_through cannot precede observed_at")
        if any(not ref.strip() for ref in self.evidence_refs):
            raise ValueError("source evidence refs must be non-empty")
        return self

    def freshness_at(self, captured_at: datetime) -> FreshnessStatus:
        if self.source_ref is None:
            return FreshnessStatus.MISSING
        assert self.valid_through is not None
        if _utc(self.valid_through) < _utc(captured_at):
            return FreshnessStatus.STALE
        return FreshnessStatus.CURRENT


class SnapshotIssue(FrozenModel):
    code: str
    severity: IssueSeverity
    message: str
    resource_id: str | None = None
    evidence_refs: tuple[str, ...] = ()


class Sku(FrozenModel):
    sku_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    base_unit: str = Field(min_length=1)
    supply_type: SkuSupplyType
    source_refs: tuple[str, ...]


class BomComponent(FrozenModel):
    component_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    parent_sku_id: str = Field(min_length=1)
    component_sku_id: str = Field(min_length=1)
    quantity: PositiveQuantity
    unit: str = Field(min_length=1)
    source_refs: tuple[str, ...]


class InventoryLot(FrozenModel):
    lot_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    sku_id: str = Field(min_length=1)
    quantity: PositiveQuantity
    unit: str = Field(min_length=1)
    warehouse_id: str | None = None
    expires_at: datetime | None = None
    source_refs: tuple[str, ...]

    def is_expired_at(self, instant: datetime) -> bool:
        return self.expires_at is not None and _utc(self.expires_at) <= _utc(instant)


class Reservation(FrozenModel):
    reservation_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    inventory_lot_id: str = Field(min_length=1)
    commitment_id: str = Field(min_length=1)
    quantity: PositiveQuantity
    unit: str = Field(min_length=1)
    status: ReservationStatus
    source_refs: tuple[str, ...]


class IncomingDelivery(FrozenModel):
    delivery_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    supplier_id: str = Field(min_length=1)
    sku_id: str = Field(min_length=1)
    quantity: PositiveQuantity
    unit: str = Field(min_length=1)
    confirmation_status: DeliveryConfirmationStatus
    confirmed_at: datetime | None = None
    expected_at: datetime
    source_refs: tuple[str, ...]

    @model_validator(mode="after")
    def confirmation_evidence_matches_status(self) -> Self:
        if self.confirmation_status is DeliveryConfirmationStatus.CONFIRMED and self.confirmed_at is None:
            raise ValueError("confirmed delivery requires confirmed_at evidence time")
        if self.confirmation_status is DeliveryConfirmationStatus.UNCONFIRMED and self.confirmed_at is not None:
            raise ValueError("unconfirmed delivery cannot claim confirmed_at")
        return self


class CapacityWindow(FrozenModel):
    start_at: datetime
    end_at: datetime
    available_minutes: PositiveQuantity

    @model_validator(mode="after")
    def window_has_positive_duration(self) -> Self:
        duration = _utc(self.end_at) - _utc(self.start_at)
        duration_microseconds = (
            (duration.days * 86_400 + duration.seconds) * 1_000_000
            + duration.microseconds
        )
        if duration_microseconds <= 0:
            raise ValueError("capacity window end_at must be after start_at")
        elapsed_minutes = Decimal(duration_microseconds) / Decimal(60_000_000)
        if self.available_minutes > elapsed_minutes:
            raise ValueError("available_minutes cannot exceed elapsed capacity window duration")
        return self


class CapacityCalendar(FrozenModel):
    calendar_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    resource_id: str = Field(min_length=1)
    timezone_name: str = Field(min_length=1)
    windows: tuple[CapacityWindow, ...]
    source_refs: tuple[str, ...]

    @field_validator("timezone_name")
    @classmethod
    def timezone_must_be_known(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError(f"unknown IANA timezone: {value}") from error
        return value


class CommitmentLine(FrozenModel):
    line_id: str = Field(min_length=1)
    sku_id: str = Field(min_length=1)
    quantity: PositiveQuantity
    unit: str = Field(min_length=1)
    material_use_at: datetime


class ConfirmedCommitment(FrozenModel):
    commitment_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    commitment_version: int = Field(gt=0)
    delivery_deadline: datetime
    lines: tuple[CommitmentLine, ...] = Field(min_length=1)
    source_refs: tuple[str, ...]


class OperationalSnapshot(FrozenModel):
    """Immutable, versioned P2 input; not a shared or persisted P5 contract."""

    REQUIRED_SOURCE_KINDS: ClassVar[tuple[SourceKind, ...]] = tuple(SourceKind)

    snapshot_id: str = Field(min_length=1)
    snapshot_version: int = Field(gt=0)
    tenant_id: str = Field(min_length=1)
    captured_at: datetime
    sources: tuple[SourceEvidence, ...]
    sku_catalog: tuple[Sku, ...]
    bom_components: tuple[BomComponent, ...]
    inventory_lots: tuple[InventoryLot, ...]
    reservations: tuple[Reservation, ...]
    incoming_deliveries: tuple[IncomingDelivery, ...]
    capacity_calendars: tuple[CapacityCalendar, ...]
    confirmed_commitments: tuple[ConfirmedCommitment, ...]
    logistics_cutoff_at: datetime

    @model_validator(mode="after")
    def validate_snapshot_references_and_tenant_scope(self) -> Self:
        _ensure_unique(self.sources, "source_id", "source")
        _ensure_unique(self.sku_catalog, "sku_id", "SKU")
        _ensure_unique(self.bom_components, "component_id", "BOM component")
        _ensure_unique(self.inventory_lots, "lot_id", "inventory lot")
        _ensure_unique(self.reservations, "reservation_id", "reservation")
        _ensure_unique(self.incoming_deliveries, "delivery_id", "incoming delivery")
        _ensure_unique(self.capacity_calendars, "calendar_id", "capacity calendar")
        _ensure_unique(self.confirmed_commitments, "commitment_id", "confirmed commitment")

        all_rows: tuple[FrozenModel, ...] = (
            *self.sources,
            *self.sku_catalog,
            *self.bom_components,
            *self.inventory_lots,
            *self.reservations,
            *self.incoming_deliveries,
            *self.capacity_calendars,
            *self.confirmed_commitments,
        )
        for row in all_rows:
            if getattr(row, "tenant_id") != self.tenant_id:
                raise ValueError(
                    f"tenant scope mismatch for {row.__class__.__name__} "
                    f"{getattr(row, 'tenant_id')} != snapshot {self.tenant_id}"
                )

        sources_by_id = {source.source_id: source for source in self.sources}
        for source in self.sources:
            if source.observed_at is not None and _utc(source.observed_at) > _utc(self.captured_at):
                raise ValueError(f"source {source.source_id} observation is after snapshot capture")

        sku_by_id = {sku.sku_id: sku for sku in self.sku_catalog}
        lot_by_id = {lot.lot_id: lot for lot in self.inventory_lots}
        commitment_by_id = {row.commitment_id: row for row in self.confirmed_commitments}

        for sku in self.sku_catalog:
            _validate_source_refs(sku.source_refs, sources_by_id, SourceKind.SKU_CATALOG, self.captured_at)
        for component in self.bom_components:
            _validate_source_refs(component.source_refs, sources_by_id, SourceKind.BOM, self.captured_at)
            parent = sku_by_id.get(component.parent_sku_id)
            child = sku_by_id.get(component.component_sku_id)
            if parent is None or child is None:
                raise ValueError(f"BOM component {component.component_id} references an unknown SKU")
            if component.unit != child.base_unit:
                raise ValueError(f"unit mismatch for BOM component {component.component_id}")
            if parent.supply_type is not SkuSupplyType.MANUFACTURED:
                raise ValueError(f"purchased SKU {parent.sku_id} cannot own a BOM component")

        for lot in self.inventory_lots:
            _validate_source_refs(lot.source_refs, sources_by_id, SourceKind.INVENTORY, self.captured_at)
            sku = sku_by_id.get(lot.sku_id)
            if sku is None:
                raise ValueError(f"inventory lot {lot.lot_id} references an unknown SKU")
            if lot.unit != sku.base_unit:
                raise ValueError(f"unit mismatch for inventory lot {lot.lot_id}")

        active_reserved_by_lot: dict[str, Decimal] = {}
        for reservation in self.reservations:
            _validate_source_refs(
                reservation.source_refs, sources_by_id, SourceKind.RESERVATIONS, self.captured_at
            )
            lot = lot_by_id.get(reservation.inventory_lot_id)
            if lot is None:
                raise ValueError(f"reservation {reservation.reservation_id} references an unknown lot")
            if reservation.commitment_id not in commitment_by_id:
                raise ValueError(
                    f"reservation {reservation.reservation_id} has no confirmed commitment owner"
                )
            if reservation.unit != lot.unit:
                raise ValueError(f"unit mismatch for reservation {reservation.reservation_id}")
            if reservation.status is ReservationStatus.ACTIVE:
                if lot.is_expired_at(self.captured_at):
                    raise ValueError(f"active reservation {reservation.reservation_id} uses an expired lot")
                active_reserved_by_lot[lot.lot_id] = (
                    active_reserved_by_lot.get(lot.lot_id, Decimal("0")) + reservation.quantity
                )

        for lot_id, reserved in active_reserved_by_lot.items():
            if reserved > lot_by_id[lot_id].quantity:
                raise ValueError(
                    f"overlapping active reservations exceed inventory lot {lot_id}: "
                    f"{reserved} > {lot_by_id[lot_id].quantity}"
                )

        for delivery in self.incoming_deliveries:
            _validate_source_refs(
                delivery.source_refs, sources_by_id, SourceKind.INCOMING_DELIVERIES, self.captured_at
            )
            if delivery.confirmed_at is not None and _utc(delivery.confirmed_at) > _utc(self.captured_at):
                raise ValueError(
                    f"confirmed_at for delivery {delivery.delivery_id} is after snapshot capture"
                )
            sku = sku_by_id.get(delivery.sku_id)
            if sku is None:
                raise ValueError(f"incoming delivery {delivery.delivery_id} references an unknown SKU")
            if delivery.unit != sku.base_unit:
                raise ValueError(f"unit mismatch for incoming delivery {delivery.delivery_id}")

        resource_windows: dict[str, list[CapacityWindow]] = {}
        for calendar in self.capacity_calendars:
            _validate_source_refs(
                calendar.source_refs, sources_by_id, SourceKind.CAPACITY_CALENDARS, self.captured_at
            )
            resource_windows.setdefault(calendar.resource_id, []).extend(calendar.windows)
        for resource_id, windows in resource_windows.items():
            ordered = sorted(windows, key=lambda window: _utc(window.start_at))
            for previous, current in zip(ordered, ordered[1:]):
                if _utc(current.start_at) < _utc(previous.end_at):
                    raise ValueError(f"overlapping capacity windows for resource {resource_id}")

        for commitment in self.confirmed_commitments:
            _validate_source_refs(
                commitment.source_refs,
                sources_by_id,
                SourceKind.CONFIRMED_COMMITMENTS,
                self.captured_at,
            )
            _ensure_unique(commitment.lines, "line_id", f"commitment {commitment.commitment_id} line")
            for line in commitment.lines:
                if _utc(line.material_use_at) > _utc(commitment.delivery_deadline):
                    raise ValueError(
                        f"material_use_at for commitment line {line.line_id} is after "
                        "commitment delivery_deadline"
                    )
                sku = sku_by_id.get(line.sku_id)
                if sku is None:
                    raise ValueError(
                        f"commitment line {line.line_id} references an unknown SKU"
                    )
                if line.unit != sku.base_unit:
                    raise ValueError(f"unit mismatch for commitment line {line.line_id}")

        return self

    @computed_field
    @property
    def freshness_status(self) -> FreshnessStatus:
        statuses = [self.source_freshness(kind) for kind in self.REQUIRED_SOURCE_KINDS]
        if FreshnessStatus.MISSING in statuses:
            return FreshnessStatus.MISSING
        if FreshnessStatus.STALE in statuses:
            return FreshnessStatus.STALE
        return FreshnessStatus.CURRENT

    @computed_field
    @property
    def validation_status(self) -> SnapshotValidationStatus:
        if any(issue.severity is IssueSeverity.INCOMPLETE for issue in self.validation_issues):
            return SnapshotValidationStatus.INCOMPLETE
        return SnapshotValidationStatus.VALID

    @computed_field
    @property
    def validation_issues(self) -> tuple[SnapshotIssue, ...]:
        issues: list[SnapshotIssue] = []
        for kind in self.REQUIRED_SOURCE_KINDS:
            matching = tuple(source for source in self.sources if source.kind is kind)
            if not matching or self.source_freshness(kind) is FreshnessStatus.MISSING:
                issues.append(
                    SnapshotIssue(
                        code="MISSING_SOURCE",
                        severity=IssueSeverity.INCOMPLETE,
                        message=f"No current source is available for {kind.value}.",
                        resource_id=kind.value,
                    )
                )
                continue
            for source in matching:
                if source.freshness_at(self.captured_at) is FreshnessStatus.STALE:
                    issues.append(
                        SnapshotIssue(
                            code="STALE_SOURCE",
                            severity=IssueSeverity.INCOMPLETE,
                            message=f"Source {source.source_id} was stale when the snapshot was captured.",
                            resource_id=source.source_id,
                            evidence_refs=source.evidence_refs,
                        )
                    )

        bom_parent_ids = {component.parent_sku_id for component in self.bom_components}
        for sku in self.sku_catalog:
            if sku.supply_type is SkuSupplyType.MANUFACTURED and sku.sku_id not in bom_parent_ids:
                issues.append(
                    SnapshotIssue(
                        code="MISSING_BOM",
                        severity=IssueSeverity.INCOMPLETE,
                        message=f"Manufactured SKU {sku.sku_id} has no BOM components in this snapshot.",
                        resource_id=sku.sku_id,
                        evidence_refs=sku.source_refs,
                    )
                )

        for lot in self.inventory_lots:
            if lot.is_expired_at(self.captured_at):
                issues.append(
                    SnapshotIssue(
                        code="EXPIRED_LOT",
                        severity=IssueSeverity.WARNING,
                        message=f"Inventory lot {lot.lot_id} expired by snapshot capture and is unusable.",
                        resource_id=lot.lot_id,
                        evidence_refs=lot.source_refs,
                    )
                )
        return tuple(issues)

    @computed_field
    @property
    def expired_lot_ids(self) -> tuple[str, ...]:
        return tuple(lot.lot_id for lot in self.inventory_lots if lot.is_expired_at(self.captured_at))

    def source_freshness(self, kind: SourceKind | str) -> FreshnessStatus:
        normalized = kind if isinstance(kind, SourceKind) else SourceKind(kind.lower())
        matching = tuple(source for source in self.sources if source.kind is normalized)
        if not matching:
            return FreshnessStatus.MISSING
        statuses = tuple(source.freshness_at(self.captured_at) for source in matching)
        if FreshnessStatus.MISSING in statuses:
            return FreshnessStatus.MISSING
        if FreshnessStatus.STALE in statuses:
            return FreshnessStatus.STALE
        return FreshnessStatus.CURRENT


def _ensure_unique(rows: tuple[BaseModel, ...], attribute: str, label: str) -> None:
    values = [getattr(row, attribute) for row in rows]
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate {label} identifier")


def _validate_source_refs(
    refs: tuple[str, ...],
    sources_by_id: dict[str, SourceEvidence],
    expected_kind: SourceKind,
    captured_at: datetime,
) -> None:
    if not refs:
        raise ValueError(f"source evidence is required for {expected_kind.value} row")
    for source_id in refs:
        source = sources_by_id.get(source_id)
        if source is None:
            raise ValueError(f"unknown source evidence reference: {source_id}")
        if source.kind is not expected_kind:
            raise ValueError(
                f"source reference {source_id} has kind {source.kind.value}; "
                f"expected {expected_kind.value}"
            )
        if source.freshness_at(captured_at) is FreshnessStatus.MISSING:
            raise ValueError(f"row cannot cite missing source evidence: {source_id}")
