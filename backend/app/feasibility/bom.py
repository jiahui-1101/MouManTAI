"""Deterministic recursive BOM expansion over immutable snapshot inputs."""

from decimal import Decimal, DecimalException

from backend.app.feasibility.materials import BomExpansion, MaterialRequirement
from backend.app.feasibility.models import (
    FreshnessStatus, IssueSeverity, OperationalSnapshot, SkuSupplyType,
    SnapshotIssue, SourceKind, _utc,
)
from backend.app.feasibility.quantities import add, multiply


def evidence_for(snapshot: OperationalSnapshot, refs: tuple[str, ...]) -> tuple[str, ...]:
    """Keep both source-row IDs and raw evidence references for inspection."""
    sources = {s.source_id: s for s in snapshot.sources}
    return tuple(sorted({*refs, *(ref for key in refs for ref in sources[key].evidence_refs)}))


def source_issues(snapshot, kinds, instant):
    issues = []
    for kind in kinds:
        sources = [s for s in snapshot.sources if s.kind == kind]
        if not sources:
            issues.append(SnapshotIssue(code='MISSING_SOURCE', severity=IssueSeverity.INCOMPLETE,
                                        message=f'Missing {kind.value} source.', resource_id=kind.value))
        for source in sources:
            status = source.freshness_at(instant)
            if status != FreshnessStatus.CURRENT:
                issues.append(SnapshotIssue(code=f'{status.value}_SOURCE', severity=IssueSeverity.INCOMPLETE,
                                            message=f'{source.source_id} is {status.value} at calculation time.',
                                            resource_id=source.source_id, evidence_refs=source.evidence_refs))
    return tuple(issues)


def explode_bom(snapshot: OperationalSnapshot, *, tenant_id: str) -> BomExpansion:
    if tenant_id != snapshot.tenant_id:
        raise ValueError('tenant scope mismatch')
    snapshot = OperationalSnapshot.model_validate(snapshot.model_dump(exclude_computed_fields=True))
    issues = list(source_issues(snapshot, (SourceKind.SKU_CATALOG, SourceKind.BOM,
                                         SourceKind.CONFIRMED_COMMITMENTS), snapshot.captured_at))
    requirements = []
    assumptions = set()
    skus = {s.sku_id: s for s in snapshot.sku_catalog}
    children = {}
    for component in sorted(snapshot.bom_components, key=lambda c: c.component_id):
        children.setdefault(component.parent_sku_id, []).append(component)

    def visit(sku_id, quantity, path, component_path, refs, leaves):
        if sku_id in path:
            issues.append(SnapshotIssue(code='BOM_CYCLE', severity=IssueSeverity.INCOMPLETE,
                                        message=' -> '.join((*path, sku_id)), resource_id=sku_id,
                                        evidence_refs=evidence_for(snapshot, refs)))
            return
        sku = skus[sku_id]
        refs = tuple(sorted(set((*refs, *sku.source_refs))))
        path = (*path, sku_id)
        if sku.supply_type == SkuSupplyType.PURCHASED:
            leaves.append((sku_id, quantity, path, component_path, refs))
            return
        if not children.get(sku_id):
            issues.append(SnapshotIssue(code='MISSING_BOM', severity=IssueSeverity.INCOMPLETE,
                                        message=f'No BOM for {sku_id}.', resource_id=sku_id,
                                        evidence_refs=evidence_for(snapshot, refs)))
            return
        for component in children[sku_id]:
            assumptions.add(f'{component.component_id}: consumption multiplier {component.waste_multiplier} '
                            '(1 = no known loss; markup, not yield division); per one parent base unit.')
            needed = multiply(quantity, multiply(component.quantity, component.waste_multiplier))
            needed = snapshot.quantity_in_base(component.component_sku_id, needed, component.unit)
            visit(component.component_sku_id, needed, path, (*component_path, component.component_id),
                  tuple(sorted(set((*refs, *component.source_refs)))), leaves)

    for conversion in snapshot.unit_conversions:
        assumptions.add(f'{conversion.conversion_id}: {conversion.sku_id} {conversion.from_unit} '
                        f'* {conversion.factor} = {conversion.to_unit}; explicit direct mapping.')
    conversion_refs = tuple(sorted({r for c in snapshot.unit_conversions for r in c.source_refs}))
    try:
        for commitment in sorted(snapshot.confirmed_commitments, key=lambda c: c.commitment_id):
            for line in sorted(commitment.lines, key=lambda line: line.line_id):
                leaves = []
                visit(line.sku_id, snapshot.quantity_in_base(line.sku_id, line.quantity, line.unit),
                      (), (), (*commitment.source_refs, *conversion_refs), leaves)
                for sku_id in sorted({leaf[0] for leaf in leaves}):
                    matching = [leaf for leaf in leaves if leaf[0] == sku_id]
                    quantity = Decimal(0)
                    for leaf in matching:
                        quantity = add(quantity, leaf[1])
                    refs = tuple(sorted({r for leaf in matching for r in leaf[4]}))
                    requirements.append(MaterialRequirement(
                        commitment_id=commitment.commitment_id, commitment_version=commitment.commitment_version,
                        line_id=line.line_id, sku_id=sku_id, quantity=quantity, unit=skus[sku_id].base_unit,
                        needed_by=line.material_use_at, warehouse_id=line.warehouse_id,
                        paths=tuple(leaf[2] for leaf in matching), component_paths=tuple(leaf[3] for leaf in matching),
                        evidence_refs=evidence_for(snapshot, refs)))
    except (DecimalException, RecursionError):
        issues.append(SnapshotIssue(code='CALCULATION_LIMIT', severity=IssueSeverity.INCOMPLETE,
                                    message='BOM exceeds supported exact arithmetic or recursion limits.'))
    ordered = tuple(sorted(requirements, key=lambda r: (_utc(r.needed_by), r.commitment_id,
                           r.commitment_version, r.line_id, r.sku_id)))
    return BomExpansion(tenant_id=snapshot.tenant_id, snapshot_id=snapshot.snapshot_id,
                        snapshot_version=snapshot.snapshot_version, status='UNKNOWN' if issues else 'COMPLETE',
                        requirements=() if issues else ordered, assumptions=tuple(sorted(assumptions)),
                        issues=tuple(issues), evidence_refs=tuple(sorted({e for r in ordered for e in r.evidence_refs})))
