"""Evidence-backed, P2-local dependency discovery and impact recalculation.

This module returns calculations and future DomainEvent intents only. It does
not persist snapshots, publish events, reserve stock, or update Core state.
Every before/after feasibility result comes from the existing ``evaluate``
service; the graph is an invalidation index, never a second calculator.
"""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
import json
from typing import Literal

from pydantic import Field, ValidationError, field_validator, model_validator

from app.core.schemas import Commitment, DomainEvent, FeasibilityState

from .bom import explode_bom
from .models import (
    DeliveryConfirmationStatus,
    FrozenModel,
    OperationalSnapshot,
    SourceKind,
    SupplierDeliveryEvidenceType,
    _utc,
)
from .production import EvaluationSnapshot, ProductionData
from .quantities import subtract
from .service import EvaluationResult, evaluate


class ResourceKind(StrEnum):
    SUPPLIER_DELIVERY = "SUPPLIER_DELIVERY"
    SKU = "SKU"
    INVENTORY_LOT = "INVENTORY_LOT"
    PRODUCTION_RESOURCE = "PRODUCTION_RESOURCE"
    PRODUCTION_JOB = "PRODUCTION_JOB"
    PRODUCTION_PLAN = "PRODUCTION_PLAN"
    ORDER = "ORDER"
    COMMITMENT = "COMMITMENT"


class OperationalChangeType(StrEnum):
    SUPPLIER_DELIVERY_CHANGED = "supplier.delivery_changed"
    INVENTORY_CHANGED = "inventory.changed"
    CAPACITY_CHANGED = "capacity.changed"
    ORDER_REQUEST_CHANGED = "order.request_changed"


class ImpactClassification(StrEnum):
    CONFIRMED_IMPACT = "CONFIRMED_IMPACT"
    VERIFIED_UNAFFECTED = "VERIFIED_UNAFFECTED"
    PRE_EXISTING_UNCHANGED = "PRE_EXISTING_UNCHANGED"
    NO_NEW_ADVERSE_DELTA = "NO_NEW_ADVERSE_DELTA"
    UNKNOWN = "UNKNOWN"


class ResourceKey(FrozenModel):
    kind: ResourceKind
    resource_id: str = Field(min_length=1)


class OperationalChange(FrozenModel):
    """P2-local notification of a source-backed change between two snapshots."""

    event_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    event_type: OperationalChangeType
    occurred_at: datetime
    before_snapshot_version: int = Field(ge=1)
    after_snapshot_version: int = Field(ge=1)
    resource_keys: tuple[ResourceKey, ...] = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(min_length=1)

    @field_validator("resource_keys")
    @classmethod
    def unique_resource_keys(cls, values):
        if len({(value.kind, value.resource_id) for value in values}) != len(values):
            raise ValueError("duplicate changed resource key")
        return values

    @field_validator("evidence_refs")
    @classmethod
    def valid_evidence_refs(cls, values):
        if any(not value.strip() for value in values) or len(values) != len(set(values)):
            raise ValueError("change evidence references must be nonempty and unique")
        return tuple(sorted(values))

    @model_validator(mode="after")
    def event_resource_types_match(self):
        allowed = {
            OperationalChangeType.SUPPLIER_DELIVERY_CHANGED: {ResourceKind.SUPPLIER_DELIVERY},
            OperationalChangeType.INVENTORY_CHANGED: {ResourceKind.INVENTORY_LOT, ResourceKind.SKU},
            OperationalChangeType.CAPACITY_CHANGED: {ResourceKind.PRODUCTION_RESOURCE, ResourceKind.PRODUCTION_JOB},
            OperationalChangeType.ORDER_REQUEST_CHANGED: {ResourceKind.ORDER, ResourceKind.COMMITMENT},
        }[self.event_type]
        if any(key.kind not in allowed for key in self.resource_keys):
            raise ValueError("change event type does not match its resource key")
        return self


class DependencyEdge(FrozenModel):
    tenant_id: str = Field(min_length=1)
    source: ResourceKey
    target: ResourceKey
    relationship: str = Field(min_length=1)
    evidence_refs: tuple[str, ...] = ()


class DependencyPath(FrozenModel):
    resource_key: ResourceKey
    nodes: tuple[ResourceKey, ...] = Field(min_length=1)
    relationships: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()


class DependencyGraph(FrozenModel):
    tenant_id: str
    snapshot_id: str
    snapshot_version: int
    commitment_ids: tuple[str, ...]
    edges: tuple[DependencyEdge, ...]
    material_dependencies_complete: bool
    capacity_dependencies_complete: bool
    order_dependencies_complete: bool

    def paths_from(self, resource_keys: tuple[ResourceKey, ...]) -> tuple[DependencyPath, ...]:
        """Return one stable evidence path per changed resource/commitment pair."""
        adjacency: dict[ResourceKey, list[DependencyEdge]] = defaultdict(list)
        for edge in self.edges:
            adjacency[edge.source].append(edge)
        priority = {
            ResourceKind.SKU: 0,
            ResourceKind.PRODUCTION_RESOURCE: 1,
            ResourceKind.PRODUCTION_JOB: 2,
            ResourceKind.PRODUCTION_PLAN: 3,
            ResourceKind.ORDER: 4,
            ResourceKind.COMMITMENT: 5,
            ResourceKind.INVENTORY_LOT: 6,
            ResourceKind.SUPPLIER_DELIVERY: 7,
        }
        for rows in adjacency.values():
            rows.sort(key=lambda edge: (priority[edge.target.kind], edge.relationship,
                                        edge.target.resource_id, edge.evidence_refs))

        output: dict[tuple[ResourceKey, str], DependencyPath] = {}
        known_commitments = set(self.commitment_ids)
        for start in sorted(resource_keys, key=_resource_sort_key):
            if start.kind is ResourceKind.COMMITMENT:
                if start.resource_id in known_commitments:
                    output[(start, start.resource_id)] = DependencyPath(
                        resource_key=start, nodes=(start,))
                continue
            queue = deque([(start, (start,), (), ())])
            visited = {start}
            while queue:
                node, nodes, relationships, evidence = queue.popleft()
                if node.kind is ResourceKind.COMMITMENT:
                    if node.resource_id in known_commitments:
                        output.setdefault((start, node.resource_id), DependencyPath(
                            resource_key=start, nodes=nodes, relationships=relationships,
                            evidence_refs=tuple(sorted(set(evidence)))))
                    continue
                for edge in adjacency.get(node, ()):
                    if edge.tenant_id != self.tenant_id or edge.target in visited:
                        continue
                    visited.add(edge.target)
                    queue.append((edge.target, (*nodes, edge.target),
                                  (*relationships, edge.relationship),
                                  (*evidence, *edge.evidence_refs)))
        return tuple(output[key] for key in sorted(
            output, key=lambda item: (_resource_sort_key(item[0]), item[1])))


class ImpactDelta(FrozenModel):
    kind: Literal["MATERIAL_SHORTAGE", "HARD_CONSTRAINT"]
    resource_id: str
    line_id: str | None = None
    code: str | None = None
    before_shortage: Decimal | None
    after_shortage: Decimal | None
    delta: Decimal | None
    unit: str | None = None
    deadline: datetime | None = None
    is_new: bool = False
    evidence_refs: tuple[str, ...] = ()


class ImpactBuffer(FrozenModel):
    resource_id: str
    kind: Literal["MATERIAL", "CAPACITY", "TIME"]
    value: Decimal
    unit: str
    evidence_refs: tuple[str, ...] = ()


class ImpactEventIntent(FrozenModel):
    """A deterministic shared-envelope proposal; it is never published here."""

    deduplication_key: str
    event: DomainEvent


class CommitmentImpact(FrozenModel):
    tenant_id: str
    commitment_id: str
    before_commitment_version: int | None
    after_commitment_version: int | None
    before_snapshot_id: str
    before_snapshot_version: int
    after_snapshot_id: str
    after_snapshot_version: int
    classification: ImpactClassification
    verified_material_deterioration: bool = False
    before_assessment: EvaluationResult | None = None
    after_assessment: EvaluationResult | None = None
    material_deltas: tuple[ImpactDelta, ...] = ()
    hard_constraint_deltas: tuple[ImpactDelta, ...] = ()
    buffers: tuple[ImpactBuffer, ...] = ()
    dependency_paths: tuple[DependencyPath, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    event_intents: tuple[ImpactEventIntent, ...] = ()


class ImpactAssessment(FrozenModel):
    impact_id: str
    tenant_id: str
    event_id: str
    correlation_id: str
    event_type: OperationalChangeType
    before_snapshot_id: str
    before_snapshot_version: int
    after_snapshot_id: str
    after_snapshot_version: int
    discovery_complete: bool
    candidate_commitment_ids: tuple[str, ...]
    impacts: tuple[CommitmentImpact, ...]
    event_intents: tuple[ImpactEventIntent, ...]
    shared_assessment_status: str = "P2_LOCAL_ONLY_P5_FEASIBILITY_ASSESSMENT_ADAPTER_PENDING"

    @property
    def confirmed_impacted_commitment_ids(self) -> tuple[str, ...]:
        return tuple(row.commitment_id for row in self.impacts
                     if row.classification is ImpactClassification.CONFIRMED_IMPACT)

    @property
    def verified_unaffected_commitment_ids(self) -> tuple[str, ...]:
        return tuple(row.commitment_id for row in self.impacts
                     if row.classification is ImpactClassification.VERIFIED_UNAFFECTED)

    @property
    def unknown_commitment_ids(self) -> tuple[str, ...]:
        return tuple(row.commitment_id for row in self.impacts
                     if row.classification is ImpactClassification.UNKNOWN)

    @property
    def pre_existing_unchanged_commitment_ids(self) -> tuple[str, ...]:
        return tuple(row.commitment_id for row in self.impacts
                     if row.classification is ImpactClassification.PRE_EXISTING_UNCHANGED)


def _resource_sort_key(key: ResourceKey) -> tuple[str, str]:
    return key.kind.value, key.resource_id


def _expanded_operational_evidence(snapshot: OperationalSnapshot, refs: tuple[str, ...]) -> tuple[str, ...]:
    sources = {row.source_id: row for row in snapshot.sources}
    found = set(refs)
    for ref in refs:
        source = sources.get(ref)
        if source is not None:
            found.update(source.evidence_refs)
            for claim in source.supplier_delivery_evidence:
                found.update((claim.evidence_id, claim.evidence_ref))
    return tuple(sorted(found))


def _expanded_production_evidence(production: ProductionData | None,
                                  refs: tuple[str, ...]) -> tuple[str, ...]:
    found = set(refs)
    if production is not None:
        sources = {row.source_id: row for row in production.sources}
        for ref in refs:
            source = sources.get(ref)
            if source is not None:
                found.update(source.evidence_refs)
    return tuple(sorted(found))


def _core_matches(snapshot: EvaluationSnapshot, commitment: Commitment | None,
                  commitment_id: str) -> bool:
    if commitment is None or commitment.tenant_id != snapshot.operational.tenant_id:
        return False
    target = next((row for row in snapshot.operational.confirmed_commitments
                   if row.commitment_id == commitment_id), None)
    if target is None or target.commitment_version != commitment.commitment_version:
        return False
    if commitment.agreement_state != "CONFIRMED" or len(target.lines) != 1:
        return False
    line = target.lines[0]
    return (line.sku_id, line.quantity, line.unit, target.delivery_deadline) == (
        commitment.terms.sku, commitment.terms.quantity, commitment.terms.unit,
        commitment.terms.deadline)


def build_dependency_graph(snapshot: EvaluationSnapshot,
                           commitments: tuple[Commitment, ...]) -> DependencyGraph:
    """Build a deterministic, tenant-local graph from the supplied evidence."""
    snapshot = EvaluationSnapshot.model_validate(snapshot.model_dump(exclude_computed_fields=True))
    operational, production = snapshot.operational, snapshot.production
    validated_commitments = tuple(Commitment.model_validate(row.model_dump()) for row in commitments)
    if any(row.tenant_id != operational.tenant_id for row in validated_commitments):
        raise ValueError("dependency graph tenant scope mismatch")
    if len({row.commitment_id for row in validated_commitments}) != len(validated_commitments):
        raise ValueError("duplicate Core commitment in dependency graph")
    core_by_id = {row.commitment_id: row for row in validated_commitments}
    op_commitments = {row.commitment_id: row for row in operational.confirmed_commitments}
    sources = {row.source_id: row for row in operational.sources}
    skus = {row.sku_id: row for row in operational.sku_catalog}
    components = {row.component_id: row for row in operational.bom_components}

    edge_rows: dict[tuple[ResourceKey, ResourceKey, str], set[str]] = {}

    def edge(source: ResourceKey, target: ResourceKey, relation: str,
             evidence_refs: tuple[str, ...] = ()) -> None:
        key = (source, target, relation)
        edge_rows.setdefault(key, set()).update(evidence_refs)

    expansion = explode_bom(operational, tenant_id=operational.tenant_id)
    material_complete = expansion.status == "COMPLETE"

    # Supplier receipts and inventory lots point to the SKU whose supply they
    # represent. Raw evidence and source-row IDs travel with each edge.
    for delivery in operational.incoming_deliveries:
        delivery_node = ResourceKey(kind=ResourceKind.SUPPLIER_DELIVERY,
                                    resource_id=delivery.delivery_id)
        sku_node = ResourceKey(kind=ResourceKind.SKU, resource_id=delivery.sku_id)
        refs = _expanded_operational_evidence(operational, delivery.source_refs)
        claims = [claim for source in operational.sources for claim in source.supplier_delivery_evidence
                  if claim.delivery_id == delivery.delivery_id]
        refs = tuple(sorted({*refs, *(ref for claim in claims
                                      for ref in (claim.evidence_id, claim.evidence_ref))}))
        edge(delivery_node, sku_node, "SUPPLIES_SKU", refs)
    for lot in operational.inventory_lots:
        edge(ResourceKey(kind=ResourceKind.INVENTORY_LOT, resource_id=lot.lot_id),
             ResourceKey(kind=ResourceKind.SKU, resource_id=lot.sku_id), "STOCKS_SKU",
             _expanded_operational_evidence(operational, lot.source_refs))

    # A component shortage propagates from the purchased leaf to each parent.
    if material_complete:
        for requirement in expansion.requirements:
            for path, component_path in zip(requirement.paths, requirement.component_paths):
                for index in range(len(path) - 1, 0, -1):
                    child, parent = path[index], path[index - 1]
                    component = components.get(component_path[index - 1])
                    refs = _expanded_operational_evidence(operational,
                        component.source_refs if component is not None else requirement.evidence_refs)
                    edge(ResourceKey(kind=ResourceKind.SKU, resource_id=child),
                         ResourceKey(kind=ResourceKind.SKU, resource_id=parent),
                         "BOM_INPUT_TO_PARENT", refs)

    production_by_sku = {row.sku_id: row for row in production.processes} if production else {}
    plans_by_line = {(row.commitment_id, row.line_id): row for row in production.plans} if production else {}
    for commitment_id, committed in sorted(op_commitments.items()):
        core = core_by_id.get(commitment_id)
        commitment_node = ResourceKey(kind=ResourceKind.COMMITMENT, resource_id=commitment_id)
        order_node = ResourceKey(kind=ResourceKind.ORDER, resource_id=core.order_id) if core else None
        committed_refs = _expanded_operational_evidence(operational, committed.source_refs)
        if core and order_node:
            edge(order_node, commitment_node, "ORDER_CONTAINS_COMMITMENT",
                 tuple(sorted({*committed_refs, *core.evidence_refs})))

        for line in committed.lines:
            root_sku = ResourceKey(kind=ResourceKind.SKU, resource_id=line.sku_id)
            process = production_by_sku.get(line.sku_id)
            plan = plans_by_line.get((commitment_id, line.line_id))
            if process is None or plan is None:
                # Material dependencies remain discoverable even when complete
                # production proof is absent. The evaluator will return UNKNOWN.
                target = order_node or commitment_node
                edge(root_sku, target, "MATERIAL_DEMAND", committed_refs)
                continue

            process_refs = _expanded_production_evidence(production, process.source_refs)
            plan_refs = _expanded_production_evidence(production, plan.source_refs)
            plan_node = ResourceKey(kind=ResourceKind.PRODUCTION_PLAN,
                                    resource_id=f"{commitment_id}/{line.line_id}")
            for resource_id in process.resource_ids:
                resource_node = ResourceKey(kind=ResourceKind.PRODUCTION_RESOURCE, resource_id=resource_id)
                edge(root_sku, resource_node, "PROCESSED_ON_RESOURCE", process_refs)
                edge(resource_node, plan_node, "FIXED_PRODUCTION_BOOKING",
                     tuple(sorted({*process_refs, *plan_refs})))
            edge(plan_node, order_node or commitment_node, "PLAN_FOR_ORDER", tuple(sorted({*plan_refs, *committed_refs})))

    if production is not None:
        production_sources = {row.source_id: row for row in production.sources}
        for job in production.jobs or ():
            job_node = ResourceKey(kind=ResourceKind.PRODUCTION_JOB, resource_id=job.job_id)
            job_refs = _expanded_production_evidence(production, job.source_refs)
            for resource_id in job.resource_ids:
                resource_node = ResourceKey(kind=ResourceKind.PRODUCTION_RESOURCE, resource_id=resource_id)
                edge(resource_node, job_node, "USES_PRODUCTION_RESOURCE", job_refs)
                # A job on a shared exclusive resource is a candidate dependency
                # for every booking there; evaluate() decides whether its actual
                # interval creates a conflict.
                for commitment in sorted(op_commitments.values(), key=lambda row: row.commitment_id):
                    for line in commitment.lines:
                        process = production_by_sku.get(line.sku_id)
                        plan = plans_by_line.get((commitment.commitment_id, line.line_id))
                        if process is None or plan is None or resource_id not in process.resource_ids:
                            continue
                        plan_node = ResourceKey(kind=ResourceKind.PRODUCTION_PLAN,
                                                resource_id=f"{commitment.commitment_id}/{line.line_id}")
                        edge(job_node, plan_node, "SHARES_EXCLUSIVE_RESOURCE",
                             tuple(sorted({*job_refs, *_expanded_production_evidence(production, plan.source_refs)})))

    order_complete = (set(core_by_id) == set(op_commitments)
                      and all(_core_matches(snapshot, core_by_id.get(key), key) for key in op_commitments))
    production_kinds = {row.kind for row in production.sources} if production else set()
    capacity_complete = bool(production is not None and production.jobs is not None
        and {"resources", "processes", "jobs", "plans"}.issubset(production_kinds)
        and all(_utc(row.valid_through) >= _utc(snapshot.as_of) for row in production.sources)
        and all(ref in production_sources for row in (*production.resources, *production.processes,
                    *production.plans, *(production.jobs or ())) for ref in row.source_refs))

    edges = tuple(sorted((DependencyEdge(tenant_id=operational.tenant_id,
        source=source, target=target, relationship=relation,
        evidence_refs=tuple(sorted(refs)))
        for (source, target, relation), refs in edge_rows.items()),
        key=lambda row: (_resource_sort_key(row.source), _resource_sort_key(row.target),
                         row.relationship, row.evidence_refs)))
    return DependencyGraph(tenant_id=operational.tenant_id, snapshot_id=operational.snapshot_id,
        snapshot_version=operational.snapshot_version,
        commitment_ids=tuple(sorted(op_commitments)), edges=edges,
        material_dependencies_complete=material_complete,
        capacity_dependencies_complete=capacity_complete,
        order_dependencies_complete=order_complete)


def _snapshot_rows(snapshot: OperationalSnapshot, kind: ResourceKind, resource_id: str):
    if kind is ResourceKind.SUPPLIER_DELIVERY:
        return tuple(row.model_dump_json() for row in snapshot.incoming_deliveries
                     if row.delivery_id == resource_id)
    if kind is ResourceKind.INVENTORY_LOT:
        return tuple(row.model_dump_json() for row in snapshot.inventory_lots if row.lot_id == resource_id)
    if kind is ResourceKind.SKU:
        rows = [row.model_dump_json() for row in snapshot.sku_catalog if row.sku_id == resource_id]
        rows.extend(row.model_dump_json() for row in snapshot.inventory_lots if row.sku_id == resource_id)
        rows.extend(row.model_dump_json() for row in snapshot.incoming_deliveries if row.sku_id == resource_id)
        rows.extend(row.model_dump_json() for row in snapshot.bom_components
                    if row.parent_sku_id == resource_id or row.component_sku_id == resource_id)
        rows.extend(row.model_dump_json() for row in snapshot.unit_conversions if row.sku_id == resource_id)
        return tuple(sorted(rows))
    if kind is ResourceKind.PRODUCTION_RESOURCE:
        return tuple(row.model_dump_json() for row in snapshot.capacity_calendars
                     if row.resource_id == resource_id)
    if kind in (ResourceKind.ORDER, ResourceKind.COMMITMENT):
        return tuple()
    return tuple()


def _production_rows(production: ProductionData | None, kind: ResourceKind, resource_id: str):
    if production is None:
        return ()
    if kind is ResourceKind.PRODUCTION_JOB:
        return tuple(row.model_dump_json() for row in production.jobs or () if row.job_id == resource_id)
    if kind is ResourceKind.PRODUCTION_RESOURCE:
        rows = [row.model_dump_json() for row in production.resources if row.resource_id == resource_id]
        rows.extend(row.model_dump_json() for row in production.processes if resource_id in row.resource_ids)
        rows.extend(row.model_dump_json() for row in production.jobs or () if resource_id in row.resource_ids)
        return tuple(sorted(rows))
    return ()


def _core_rows(commitments: tuple[Commitment, ...], kind: ResourceKind, resource_id: str):
    if kind is ResourceKind.COMMITMENT:
        return tuple(row.model_dump_json() for row in commitments if row.commitment_id == resource_id)
    if kind is ResourceKind.ORDER:
        return tuple(row.model_dump_json() for row in commitments if row.order_id == resource_id)
    return ()


def _actual_change_exists(before: EvaluationSnapshot, after: EvaluationSnapshot,
                          change: OperationalChange,
                          before_commitments: tuple[Commitment, ...],
                          after_commitments: tuple[Commitment, ...], key: ResourceKey) -> bool:
    kind, resource_id = key.kind, key.resource_id
    if kind in (ResourceKind.SUPPLIER_DELIVERY, ResourceKind.INVENTORY_LOT, ResourceKind.SKU):
        left = _snapshot_rows(before.operational, kind, resource_id)
        right = _snapshot_rows(after.operational, kind, resource_id)
        if left == right:
            return False
        if kind is ResourceKind.SUPPLIER_DELIVERY:
            old = next((row for row in before.operational.incoming_deliveries if row.delivery_id == resource_id), None)
            new = next((row for row in after.operational.incoming_deliveries if row.delivery_id == resource_id), None)
            if old is None or new is None or _utc(old.expected_at) == _utc(new.expected_at):
                return False
        return True
    if kind in (ResourceKind.PRODUCTION_RESOURCE, ResourceKind.PRODUCTION_JOB):
        production_changed = (_production_rows(before.production, kind, resource_id)
                              != _production_rows(after.production, kind, resource_id))
        if kind is ResourceKind.PRODUCTION_RESOURCE:
            calendar_changed = (_snapshot_rows(before.operational, kind, resource_id)
                                != _snapshot_rows(after.operational, kind, resource_id))
            return production_changed or calendar_changed
        return production_changed
    if kind in (ResourceKind.ORDER, ResourceKind.COMMITMENT):
        return _core_rows(before_commitments, kind, resource_id) != _core_rows(after_commitments, kind, resource_id)
    return False


def _after_key_evidence(snapshot: EvaluationSnapshot, commitments: tuple[Commitment, ...],
                        key: ResourceKey) -> set[str]:
    op, production = snapshot.operational, snapshot.production
    refs: set[str] = set()
    if key.kind is ResourceKind.SUPPLIER_DELIVERY:
        rows = [row for row in op.incoming_deliveries if row.delivery_id == key.resource_id]
        refs.update(ref for row in rows for ref in _expanded_operational_evidence(op, row.source_refs))
        for source in op.sources:
            for claim in source.supplier_delivery_evidence:
                if claim.delivery_id == key.resource_id:
                    refs.update((claim.evidence_id, claim.evidence_ref))
    elif key.kind is ResourceKind.INVENTORY_LOT:
        refs.update(ref for row in op.inventory_lots if row.lot_id == key.resource_id
                    for ref in _expanded_operational_evidence(op, row.source_refs))
    elif key.kind is ResourceKind.SKU:
        rows_refs = []
        rows_refs.extend(row.source_refs for row in op.sku_catalog if row.sku_id == key.resource_id)
        rows_refs.extend(row.source_refs for row in op.inventory_lots if row.sku_id == key.resource_id)
        rows_refs.extend(row.source_refs for row in op.incoming_deliveries if row.sku_id == key.resource_id)
        rows_refs.extend(row.source_refs for row in op.bom_components
                         if row.parent_sku_id == key.resource_id or row.component_sku_id == key.resource_id)
        refs.update(ref for row_refs in rows_refs for ref in _expanded_operational_evidence(op, row_refs))
    elif key.kind in (ResourceKind.PRODUCTION_RESOURCE, ResourceKind.PRODUCTION_JOB):
        if production:
            if key.kind is ResourceKind.PRODUCTION_JOB:
                refs.update(ref for row in production.jobs or () if row.job_id == key.resource_id
                            for ref in _expanded_production_evidence(production, row.source_refs))
            else:
                row_refs = []
                row_refs.extend(row.source_refs for row in production.resources if row.resource_id == key.resource_id)
                row_refs.extend(row.source_refs for row in production.processes if key.resource_id in row.resource_ids)
                row_refs.extend(row.source_refs for row in production.jobs or () if key.resource_id in row.resource_ids)
                refs.update(ref for refs_row in row_refs for ref in _expanded_production_evidence(production, refs_row))
        refs.update(ref for row in op.capacity_calendars if row.resource_id == key.resource_id
                    for ref in _expanded_operational_evidence(op, row.source_refs))
    elif key.kind in (ResourceKind.ORDER, ResourceKind.COMMITMENT):
        refs.update(ref for row in commitments
                    if ((key.kind is ResourceKind.ORDER and row.order_id == key.resource_id)
                        or (key.kind is ResourceKind.COMMITMENT and row.commitment_id == key.resource_id))
                    for ref in row.evidence_refs)
        op_ids = {row.commitment_id for row in commitments
                  if ((key.kind is ResourceKind.ORDER and row.order_id == key.resource_id)
                      or (key.kind is ResourceKind.COMMITMENT and row.commitment_id == key.resource_id))}
        refs.update(ref for row in op.confirmed_commitments if row.commitment_id in op_ids
                    for ref in _expanded_operational_evidence(op, row.source_refs))
    return refs


def _validate_change(before: EvaluationSnapshot, after: EvaluationSnapshot,
                     change: OperationalChange, before_commitments: tuple[Commitment, ...],
                     after_commitments: tuple[Commitment, ...]) -> None:
    if before.operational.tenant_id != after.operational.tenant_id or change.tenant_id != after.operational.tenant_id:
        raise ValueError("impact tenant scope mismatch")
    if change.before_snapshot_version != before.operational.snapshot_version:
        raise ValueError("before snapshot version does not match change event")
    if change.after_snapshot_version != after.operational.snapshot_version:
        raise ValueError("after snapshot version does not match change event")
    if change.after_snapshot_version <= change.before_snapshot_version:
        raise ValueError("after snapshot version must be newer than before snapshot version")
    if _utc(change.occurred_at) < _utc(before.operational.captured_at) or _utc(change.occurred_at) > _utc(after.operational.captured_at):
        raise ValueError("change event time must fall between snapshot captures")
    for rows in (before_commitments, after_commitments):
        if any(row.tenant_id != change.tenant_id for row in rows):
            raise ValueError("Core commitment tenant scope mismatch")
        if len({row.commitment_id for row in rows}) != len(rows):
            raise ValueError("duplicate Core commitment")
    if any(not _actual_change_exists(before, after, change, before_commitments,
                                     after_commitments, key) for key in change.resource_keys):
        raise ValueError("changed resource key has no before/after data change")
    for key in change.resource_keys:
        if not set(change.evidence_refs).issubset(_after_key_evidence(after, after_commitments, key)):
            raise ValueError("change evidence is not linked to the changed resource in the after snapshot")
        if key.kind is ResourceKind.SUPPLIER_DELIVERY:
            delivery = next(row for row in after.operational.incoming_deliveries
                            if row.delivery_id == key.resource_id)
            claims = [claim for source in after.operational.sources
                      for claim in source.supplier_delivery_evidence
                      if claim.evidence_id in delivery.eta_change_evidence_ids
                      and claim.evidence_type is SupplierDeliveryEvidenceType.ETA_CHANGE]
            if not any(claim.evidence_ref in change.evidence_refs for claim in claims):
                raise ValueError("supplier ETA change requires its linked ETA-change evidence")


def _material_deltas(before: EvaluationResult | None, after: EvaluationResult | None,
                     commitment_id: str) -> tuple[ImpactDelta, ...]:
    if before is None or after is None:
        return ()
    def rows(result):
        return {(row.commitment_id, row.line_id, row.sku_id, row.unit): row
                for row in result.materials.materials if row.commitment_id == commitment_id}
    old, new = rows(before), rows(after)
    deltas = []
    for key in sorted(set(old) | set(new)):
        left, right = old.get(key), new.get(key)
        left_shortage = left.shortage if left else Decimal(0)
        right_shortage = right.shortage if right else Decimal(0)
        delta = subtract(right_shortage, left_shortage)
        if delta == 0:
            continue
        deltas.append(ImpactDelta(kind="MATERIAL_SHORTAGE", resource_id=key[2], line_id=key[1],
            before_shortage=left_shortage, after_shortage=right_shortage, delta=delta, unit=key[3],
            deadline=(right or left).needed_by,
            evidence_refs=tuple(sorted({*(left.evidence_refs if left else ()), *(right.evidence_refs if right else ())}))))
    return tuple(deltas)


def _constraint_deltas(before: EvaluationResult | None, after: EvaluationResult | None) -> tuple[ImpactDelta, ...]:
    if before is None or after is None:
        return ()
    def rows(result):
        output = {}
        for constraint in result.constraints:
            if constraint.severity != "HARD":
                continue
            key = (constraint.code, constraint.resource_id, constraint.unit, constraint.deadline)
            output[key] = constraint
        return output
    old, new = rows(before), rows(after)
    deltas = []
    for key in sorted(set(old) | set(new), key=lambda row: (row[0], row[1], row[2] or "", str(row[3]))):
        left, right = old.get(key), new.get(key)
        left_shortage = left.shortage if left else Decimal(0)
        right_shortage = right.shortage if right else Decimal(0)
        is_new = left is None and right is not None
        delta = subtract(right_shortage, left_shortage) if left_shortage is not None and right_shortage is not None else None
        if not is_new and (delta is None or delta == 0):
            continue
        deltas.append(ImpactDelta(kind="HARD_CONSTRAINT", code=key[0], resource_id=key[1],
            before_shortage=left_shortage, after_shortage=right_shortage, delta=delta,
            unit=key[2], deadline=key[3], is_new=is_new,
            evidence_refs=tuple(sorted({*(left.evidence_refs if left else ()), *(right.evidence_refs if right else ())}))))
    return tuple(deltas)


def _is_known(result: EvaluationResult | None) -> bool:
    return result is not None and result.status is not FeasibilityState.UNKNOWN


def _buffers(snapshot: EvaluationSnapshot, change: OperationalChange,
             result: EvaluationResult | None, commitment_id: str) -> tuple[ImpactBuffer, ...]:
    if result is None or result.status is FeasibilityState.UNKNOWN:
        return ()
    buffers: list[ImpactBuffer] = []
    for operation in result.capacity.operations:
        if operation.commitment_id != commitment_id or operation.available_minutes is None:
            continue
        margin = subtract(operation.available_minutes, operation.required_minutes)
        if margin > 0:
            buffers.append(ImpactBuffer(resource_id=",".join(operation.resource_ids), kind="CAPACITY",
                value=margin, unit="minutes", evidence_refs=operation.evidence_refs))
    for key in change.resource_keys:
        if key.kind is not ResourceKind.SUPPLIER_DELIVERY:
            continue
        delivery = next((row for row in snapshot.operational.incoming_deliveries
                         if row.delivery_id == key.resource_id), None)
        if delivery is None or delivery.confirmation_status is not DeliveryConfirmationStatus.CONFIRMED:
            continue
        for row in result.materials.materials:
            if row.commitment_id != commitment_id or row.sku_id != delivery.sku_id or row.shortage > 0:
                continue
            delta = _utc(row.needed_by) - _utc(delivery.expected_at)
            slack = (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds
            if slack > 0:
                buffers.append(ImpactBuffer(resource_id=delivery.delivery_id, kind="TIME",
                    value=Decimal(slack), unit="microseconds",
                    evidence_refs=tuple(sorted({*row.evidence_refs,
                        *_expanded_operational_evidence(snapshot.operational, delivery.source_refs)}))))
    return tuple(sorted(buffers, key=lambda row: (row.kind, row.resource_id, row.unit, row.value)))


def _classify(before: EvaluationResult | None, after: EvaluationResult | None,
              material_deltas: tuple[ImpactDelta, ...], hard_deltas: tuple[ImpactDelta, ...],
              buffers: tuple[ImpactBuffer, ...], discovery_complete: bool) -> tuple[ImpactClassification, tuple[str, ...]]:
    if not discovery_complete:
        return ImpactClassification.UNKNOWN, ("DEPENDENCY_GRAPH_INCOMPLETE",)
    adverse_hard = any(row.is_new or (row.delta is not None and row.delta > 0) for row in hard_deltas)
    if (adverse_hard and before is not None and after is not None
            and before.evidence_complete and after.evidence_complete):
        return ImpactClassification.CONFIRMED_IMPACT, ("EVIDENCED_NEW_OR_WORSENED_HARD_CONSTRAINT",)
    if not _is_known(before):
        return ImpactClassification.UNKNOWN, ("BEFORE_EVIDENCE_INSUFFICIENT",)
    if not _is_known(after):
        return ImpactClassification.UNKNOWN, ("AFTER_EVIDENCE_INSUFFICIENT",)
    adverse_material = any(row.delta is not None and row.delta > 0 for row in material_deltas)
    if adverse_material or adverse_hard:
        return ImpactClassification.CONFIRMED_IMPACT, ("EVIDENCED_ADVERSE_BEFORE_AFTER_DELTA",)
    if (before.status is FeasibilityState.INFEASIBLE
            and after.status is FeasibilityState.INFEASIBLE):
        return ImpactClassification.PRE_EXISTING_UNCHANGED, ("PRE_EXISTING_HARD_FAILURE_UNCHANGED",)
    if before.status is FeasibilityState.FEASIBLE and after.status is FeasibilityState.FEASIBLE:
        if any(row.value > 0 for row in buffers):
            return ImpactClassification.VERIFIED_UNAFFECTED, ("FEASIBLE_WITH_EVIDENCED_BUFFER",)
        return ImpactClassification.NO_NEW_ADVERSE_DELTA, ("NO_ADVERSE_DELTA_BUT_NO_POSITIVE_BUFFER_PROOF",)
    return ImpactClassification.NO_NEW_ADVERSE_DELTA, ("NO_NEW_ADVERSE_DELTA",)


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(encoded.encode("utf-8")).hexdigest()


def _intent(event_type: str, change: OperationalChange, row: CommitmentImpact,
            impact_id: str, actual_impact_ids: tuple[str, ...]) -> ImpactEventIntent:
    after = row.after_assessment
    version = row.after_commitment_version
    status = after.status.value if after is not None else "UNKNOWN"
    fingerprint = {
        "tenant": row.tenant_id,
        "commitment": row.commitment_id,
        "commitment_version": version,
        "snapshot_id": row.after_snapshot_id,
        "snapshot_version": row.after_snapshot_version,
        "classification": row.classification.value,
        "status": status,
        "material_deltas": [(d.resource_id, d.line_id, str(d.before_shortage),
                             str(d.after_shortage), str(d.delta), d.unit)
                            for d in row.material_deltas],
        "hard_deltas": [(d.code, d.resource_id, str(d.before_shortage),
                          str(d.after_shortage), str(d.delta), d.is_new)
                         for d in row.hard_constraint_deltas],
    }
    detection = _digest(fingerprint)
    deduplication_key = f"{event_type}:{detection}"
    event_id = "p2-impact-" + _digest({"cause": change.event_id,
                                        "deduplication_key": deduplication_key})[:32]
    payload = {
        "impact_id": impact_id,
        "assessment_id": after.assessment_id if after else None,
        "snapshot_version": row.after_snapshot_version,
        "classification": row.classification.value,
        "affected_commitment_ids": list(actual_impact_ids),
        "material_deltas": [{"resource_id": delta.resource_id, "line_id": delta.line_id,
            "before_shortage": str(delta.before_shortage), "after_shortage": str(delta.after_shortage),
            "delta": str(delta.delta), "unit": delta.unit, "evidence_refs": list(delta.evidence_refs)}
            for delta in row.material_deltas],
        "hard_constraint_codes": sorted({delta.code for delta in row.hard_constraint_deltas if delta.code}),
        "reasons": list(row.reasons),
        "evidence_refs": list(row.evidence_refs),
    }
    event = DomainEvent(event_id=event_id, schema_version=1, event_type=event_type,
        tenant_id=row.tenant_id, commitment_id=row.commitment_id, commitment_version=version,
        correlation_id=change.correlation_id, causation_id=change.event_id,
        occurred_at=change.occurred_at, payload=payload)
    return ImpactEventIntent(deduplication_key=deduplication_key, event=event)


def _evaluate_candidate(snapshot: EvaluationSnapshot, commitment: Commitment | None,
                        commitment_id: str) -> EvaluationResult | None:
    if not _core_matches(snapshot, commitment, commitment_id):
        return None
    try:
        return evaluate(snapshot, None, commitment)
    except (ValueError, ValidationError):
        # A stale or unresolvable Core/snapshot mapping is not a calculation
        # failure that can be called safe; the caller reports UNKNOWN.
        return None


def assess_impact(before: EvaluationSnapshot, after: EvaluationSnapshot,
                  change: OperationalChange, *,
                  before_commitments: tuple[Commitment, ...],
                  after_commitments: tuple[Commitment, ...]) -> ImpactAssessment:
    """Discover candidates and compare actual before/after P2 evaluator outputs."""
    before = EvaluationSnapshot.model_validate(before.model_dump(exclude_computed_fields=True))
    after = EvaluationSnapshot.model_validate(after.model_dump(exclude_computed_fields=True))
    before_core = tuple(Commitment.model_validate(row.model_dump()) for row in before_commitments)
    after_core = tuple(Commitment.model_validate(row.model_dump()) for row in after_commitments)
    _validate_change(before, after, change, before_core, after_core)

    before_graph = build_dependency_graph(before, before_core)
    after_graph = build_dependency_graph(after, after_core)
    path_by_commitment: dict[str, list[DependencyPath]] = defaultdict(list)
    for graph in (before_graph, after_graph):
        for path in graph.paths_from(change.resource_keys):
            path_by_commitment[path.nodes[-1].resource_id].append(path)

    relevant_complete = True
    for key in change.resource_keys:
        if key.kind in (ResourceKind.SUPPLIER_DELIVERY, ResourceKind.INVENTORY_LOT, ResourceKind.SKU):
            relevant_complete &= before_graph.material_dependencies_complete and after_graph.material_dependencies_complete
        elif key.kind in (ResourceKind.PRODUCTION_RESOURCE, ResourceKind.PRODUCTION_JOB):
            relevant_complete &= before_graph.capacity_dependencies_complete and after_graph.capacity_dependencies_complete
        elif key.kind in (ResourceKind.ORDER, ResourceKind.COMMITMENT):
            relevant_complete &= before_graph.order_dependencies_complete and after_graph.order_dependencies_complete

    candidates = set(path_by_commitment)
    fallback_ids: set[str] = set()
    if not relevant_complete:
        fallback_ids = set(before_graph.commitment_ids) | set(after_graph.commitment_ids)
        candidates.update(fallback_ids)
    candidate_ids = tuple(sorted(candidates))
    before_by_id = {row.commitment_id: row for row in before_core}
    after_by_id = {row.commitment_id: row for row in after_core}
    after_snapshot_by_id = {row.commitment_id: row for row in after.operational.confirmed_commitments}
    provisional: list[CommitmentImpact] = []
    for commitment_id in candidate_ids:
        before_result = _evaluate_candidate(before, before_by_id.get(commitment_id), commitment_id)
        after_result = _evaluate_candidate(after, after_by_id.get(commitment_id), commitment_id)
        material_deltas = _material_deltas(before_result, after_result, commitment_id)
        hard_deltas = _constraint_deltas(before_result, after_result)
        buffers = _buffers(after, change, after_result, commitment_id)
        paths = tuple(sorted({path.model_dump_json(): path for path in path_by_commitment.get(commitment_id, ())}.values(),
                             key=lambda row: ( _resource_sort_key(row.resource_key), row.nodes, row.relationships)))
        classification, reasons = _classify(before_result, after_result, material_deltas,
                                             hard_deltas, buffers,
                                             relevant_complete and commitment_id not in fallback_ids)
        before_version = before_result.commitment_version if before_result else next(
            (row.commitment_version for row in before.operational.confirmed_commitments
             if row.commitment_id == commitment_id), None)
        after_version = after_result.commitment_version if after_result else next(
            (row.commitment_version for row in after_snapshot_by_id.values()
             if row.commitment_id == commitment_id), None)
        evidence = set(change.evidence_refs)
        evidence.update(ref for path in paths for ref in path.evidence_refs)
        if before_result:
            evidence.update(before_result.evidence_refs)
        if after_result:
            evidence.update(after_result.evidence_refs)
        evidence.update(ref for delta in (*material_deltas, *hard_deltas) for ref in delta.evidence_refs)
        provisional.append(CommitmentImpact(
            tenant_id=change.tenant_id, commitment_id=commitment_id,
            before_commitment_version=before_version, after_commitment_version=after_version,
            before_snapshot_id=before.operational.snapshot_id,
            before_snapshot_version=before.operational.snapshot_version,
            after_snapshot_id=after.operational.snapshot_id,
            after_snapshot_version=after.operational.snapshot_version,
            classification=classification,
            verified_material_deterioration=any(delta.delta is not None and delta.delta > 0
                                                for delta in material_deltas),
            before_assessment=before_result,
            after_assessment=after_result, material_deltas=material_deltas,
            hard_constraint_deltas=hard_deltas, buffers=buffers,
            dependency_paths=paths, evidence_refs=tuple(sorted(evidence)), reasons=reasons))

    actual_impact_ids = tuple(sorted(row.commitment_id for row in provisional
                                     if row.classification is ImpactClassification.CONFIRMED_IMPACT))
    impact_identity = {
        "change": change.model_dump(mode="json"),
        "before": (before.operational.snapshot_id, before.operational.snapshot_version),
        "after": (after.operational.snapshot_id, after.operational.snapshot_version),
        "candidates": candidate_ids,
    }
    impact_id = "p2-impact-" + _digest(impact_identity)[:32]
    completed: list[CommitmentImpact] = []
    all_intents: list[ImpactEventIntent] = []
    for row in provisional:
        intents = []
        if row.after_assessment is not None:
            intents.append(_intent("commitment.feasibility_assessed", change, row, impact_id, actual_impact_ids))
        intents.append(_intent("operational.impact_updated", change, row, impact_id, actual_impact_ids))
        if (row.classification is ImpactClassification.CONFIRMED_IMPACT
                and row.before_assessment is not None and row.after_assessment is not None
                and row.before_assessment.status is not FeasibilityState.INFEASIBLE
                and row.after_assessment.status is FeasibilityState.INFEASIBLE):
            intents.append(_intent("commitment.at_risk", change, row, impact_id, actual_impact_ids))
        if row.classification is ImpactClassification.UNKNOWN:
            intents.append(_intent("operational.insufficient_data", change, row, impact_id, actual_impact_ids))
        row = row.model_copy(update={"event_intents": tuple(intents)})
        completed.append(row)
        all_intents.extend(intents)

    return ImpactAssessment(impact_id=impact_id, tenant_id=change.tenant_id,
        event_id=change.event_id, correlation_id=change.correlation_id, event_type=change.event_type,
        before_snapshot_id=before.operational.snapshot_id,
        before_snapshot_version=before.operational.snapshot_version,
        after_snapshot_id=after.operational.snapshot_id,
        after_snapshot_version=after.operational.snapshot_version,
        discovery_complete=relevant_complete, candidate_commitment_ids=candidate_ids,
        impacts=tuple(completed), event_intents=tuple(all_intents))
