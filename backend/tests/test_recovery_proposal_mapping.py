from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.errors import DomainError
from app.recovery.integrations import IntegrationSource, VersionedSnapshot
from app.recovery.models import RecoveryStrategy
from app.recovery.orchestrator import P2PlanRevalidatorAdapter
from app.recovery.proposal_mapping import (
    ProposalMappingStatus,
    RecoveryPlanProposedChangesBuilder,
)
from app.recovery.service import RecoveryPlanner


@dataclass(frozen=True)
class ProposedChangesContractDouble:
    """Construction spy matching P2's fields; not a replacement P2 model."""

    tenant_id: str
    commitment_id: str
    expected_commitment_version: int
    expected_snapshot_version: int
    evidence_refs: tuple[str, ...]
    quantity: Decimal | None = None
    deadline: datetime | None = None
    production_start_at: datetime | None = None


_MATCH_CURRENT_VERSION = object()


def _context(strategy: RecoveryStrategy | None = None, current_snapshot_version=_MATCH_CURRENT_VERSION):
    planner = RecoveryPlanner()
    inputs = planner.inputs
    case = planner.generate(
        inputs.commitment.tenant_id,
        inputs.commitment.commitment_id,
        expected_commitment_version=inputs.commitment.commitment_version,
    )
    plan = next(item for item in case.plans if item.strategy == (strategy or RecoveryStrategy.RESCHEDULE_PARTIAL_FULFILMENT))
    snapshot_id = "p2_snapshot_1"
    p2_snapshot = SimpleNamespace(
        operational=SimpleNamespace(
            tenant_id=inputs.commitment.tenant_id,
            snapshot_id=snapshot_id,
            snapshot_version=plan.snapshot_version,
            confirmed_commitments=(SimpleNamespace(
                commitment_id=inputs.commitment.commitment_id,
                commitment_version=inputs.commitment.commitment_version,
            ),),
        ),
        current_snapshot_version=(
            plan.snapshot_version if current_snapshot_version is _MATCH_CURRENT_VERSION
            else plan.snapshot_version + 1 if current_snapshot_version == "STALE"
            else current_snapshot_version
        ),
        as_of=datetime(2026, 10, 21, 8, 0, tzinfo=UTC),
    )
    snapshot = VersionedSnapshot(
        snapshot=p2_snapshot,
        tenant_id=inputs.commitment.tenant_id,
        commitment_id=inputs.commitment.commitment_id,
        commitment_version=inputs.commitment.commitment_version,
        snapshot_id=snapshot_id,
        snapshot_version=plan.snapshot_version,
        captured_at=p2_snapshot.as_of,
        source=IntegrationSource.SYNTHETIC_TEST_DOUBLE,
    )
    return plan, snapshot, inputs.commitment


def _builder(calls: list[dict] | None = None):
    def construct(**fields):
        if calls is not None:
            calls.append(fields)
        return ProposedChangesContractDouble(**fields)

    return RecoveryPlanProposedChangesBuilder(model_factory=construct)


def test_reschedule_maps_to_typed_p2_fields_and_retains_assessment_evidence():
    plan, snapshot, commitment = _context()
    result = _builder().build(plan, snapshot, commitment)

    assert result.status == ProposalMappingStatus.MAPPED
    proposal = result.proposed_changes
    assert isinstance(proposal, ProposedChangesContractDouble)
    assert proposal.tenant_id == commitment.tenant_id
    assert proposal.commitment_id == commitment.commitment_id
    assert proposal.expected_commitment_version == commitment.commitment_version
    assert proposal.expected_snapshot_version == snapshot.snapshot_version
    assert proposal.quantity == Decimal(80)
    assert proposal.deadline == datetime.fromisoformat("2026-10-25T15:00:00+08:00")
    assert f"assessment:{plan.based_on_assessment_id}" in proposal.evidence_refs
    assert result.source_assessment_id == plan.based_on_assessment_id
    assert any("not an executed partial shipment" in item for item in result.assumptions)


def test_actual_p2_fixture_reschedule_calls_evaluate_without_mutation():
    p2_production = pytest.importorskip(
        "app.feasibility.production",
        reason="P2 Phase 7B-1 is not yet present in the P3 feature worktree",
    )
    p2_fixtures = pytest.importorskip("app.feasibility.production_fixtures")
    p2_service = pytest.importorskip("app.feasibility.service")
    p2_snapshot, commitment = p2_fixtures.build_production_example()
    assert isinstance(p2_snapshot, p2_production.EvaluationSnapshot)
    p3_inputs = RecoveryPlanner().inputs
    p3_assessment = p3_inputs.assessment.model_copy(update={
        "tenant_id": commitment.tenant_id,
        "commitment_id": commitment.commitment_id,
        "commitment_version": commitment.commitment_version,
    })
    p3_snapshot_ref = p3_inputs.snapshot.model_copy(update={
        "snapshot_id": p2_snapshot.operational.snapshot_id,
        "snapshot_version": p2_snapshot.operational.snapshot_version,
        "captured_at": p2_snapshot.operational.captured_at,
    })
    planner = RecoveryPlanner(
        inputs=replace(
            p3_inputs,
            commitment=commitment,
            assessment=p3_assessment,
            snapshot=p3_snapshot_ref,
        ),
    )
    case = planner.generate(
        commitment.tenant_id,
        commitment.commitment_id,
        expected_commitment_version=commitment.commitment_version,
    )
    plan = next(item for item in case.plans if item.strategy == RecoveryStrategy.RESCHEDULE_PARTIAL_FULFILMENT)
    snapshot = VersionedSnapshot(
        snapshot=p2_snapshot,
        tenant_id=commitment.tenant_id,
        commitment_id=commitment.commitment_id,
        commitment_version=commitment.commitment_version,
        snapshot_id=p2_snapshot.operational.snapshot_id,
        snapshot_version=p2_snapshot.operational.snapshot_version,
        captured_at=p2_snapshot.as_of,
        source=IntegrationSource.SYNTHETIC_FIXTURE,
    )
    builder = RecoveryPlanProposedChangesBuilder()
    mapping = builder.build(plan, snapshot, commitment)
    assert isinstance(mapping.proposed_changes, p2_production.ProposedChanges)
    assert mapping.proposed_changes.quantity == Decimal(80)
    assert mapping.proposed_changes.deadline == datetime.fromisoformat("2026-10-25T15:00:00+08:00")
    assert mapping.proposed_changes.expected_commitment_version == commitment.commitment_version
    assert mapping.proposed_changes.expected_snapshot_version == snapshot.snapshot_version
    assert "not an executed partial shipment" in " ".join(mapping.assumptions)

    snapshot_before = p2_snapshot.model_dump(mode="json")
    commitment_before = commitment.model_dump(mode="json")
    evaluate_calls = []
    p2_results = []

    def real_p2_evaluate(actual_snapshot, proposed_changes, actual_commitment):
        evaluate_calls.append((actual_snapshot, proposed_changes, actual_commitment))
        result = p2_service.evaluate(actual_snapshot, proposed_changes, actual_commitment)
        p2_results.append(result)
        return result

    adapter = P2PlanRevalidatorAdapter(real_p2_evaluate, builder)
    result = adapter.evaluate_plan(snapshot, plan, commitment)

    assert len(evaluate_calls) == 1
    actual_snapshot, actual_proposal, actual_commitment = evaluate_calls[0]
    assert actual_snapshot is p2_snapshot
    assert isinstance(actual_proposal, p2_production.ProposedChanges)
    assert actual_commitment is commitment
    assert result.evaluation_origin == "P2"
    assert result.source is IntegrationSource.SYNTHETIC_FIXTURE
    assert result.source is not IntegrationSource.AUTHORITATIVE
    assert result.tenant_id == commitment.tenant_id
    assert result.commitment_id == commitment.commitment_id
    assert result.commitment_version == commitment.commitment_version
    assert result.snapshot_id == snapshot.snapshot_id
    assert result.snapshot_version == snapshot.snapshot_version
    assert result.evaluation_id == p2_results[0].assessment_id
    assert result.status == p2_results[0].status
    assert result.solver_status
    assert result.solver_status == p2_results[0].solver_status.value
    assert result.constraints == tuple(
        item.model_dump(mode="json") for item in p2_results[0].constraints
    )
    assert result.evidence_refs == p2_results[0].evidence_refs
    assert result.assumptions[:len(p2_results[0].assumptions)] == p2_results[0].assumptions
    assert p2_snapshot.model_dump(mode="json") == snapshot_before
    assert commitment.model_dump(mode="json") == commitment_before
    assert commitment.terms.quantity == Decimal(100)

    alternative = next(item for item in case.plans if item.strategy == RecoveryStrategy.ALTERNATIVE_SUPPLY)
    unsupported = adapter.evaluate_plan(snapshot, alternative, commitment)
    assert unsupported.status.value == "CONDITIONAL"
    assert unsupported.evaluation_origin == "P3_UNSUPPORTED_MAPPING"
    assert unsupported.unsupported_reason_code == "P2_ALTERNATIVE_SUPPLY_UNSUPPORTED"
    assert len(evaluate_calls) == 1


def test_reschedule_maps_optional_production_start_and_deadline_only():
    plan, snapshot, commitment = _context()
    plan.actions[0] = plan.actions[0].model_copy(update={
        "parameters": {
            "new_deadline": "2026-10-25T15:00:00+08:00",
            "production_start_at": "2026-10-22T09:30:00+08:00",
        },
    })
    result = _builder().build(plan, snapshot, commitment)
    assert result.proposed_changes.quantity is None
    assert result.proposed_changes.production_start_at == datetime.fromisoformat("2026-10-22T09:30:00+08:00")


def test_alternative_supply_is_explicitly_unsupported_without_inserting_supply():
    plan, snapshot, commitment = _context(RecoveryStrategy.ALTERNATIVE_SUPPLY)
    calls: list[dict] = []
    result = _builder(calls).build(plan, snapshot, commitment)
    assert result.status == ProposalMappingStatus.UNSUPPORTED
    assert result.proposed_changes is None
    assert result.reason_code == "P2_ALTERNATIVE_SUPPLY_UNSUPPORTED"
    assert not calls
    assert any("not treated as inventory" in item for item in result.assumptions)


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("new_deadline", "2026-10-25T15:00:00", "P2_PROPOSAL_DATE_INVALID"),
        ("new_deadline", "not-a-date", "P2_PROPOSAL_DATE_INVALID"),
        ("production_start_at", "2026-10-22T09:30:00", "P2_PROPOSAL_DATE_INVALID"),
        ("partial_quantity", "NaN", "P2_PROPOSAL_QUANTITY_INVALID"),
        ("partial_quantity", "0", "P2_PROPOSAL_QUANTITY_INVALID"),
        ("partial_quantity", 80.0, "P2_PROPOSAL_QUANTITY_INVALID"),
    ],
)
def test_invalid_dates_and_quantities_are_rejected(field, value, code):
    plan, snapshot, commitment = _context()
    params = dict(plan.actions[0].parameters)
    params[field] = value
    plan.actions[0] = plan.actions[0].model_copy(update={"parameters": params})
    with pytest.raises(DomainError) as exc:
        _builder().build(plan, snapshot, commitment)
    assert exc.value.code == code


def test_unknown_strategy_fields_and_nonpartial_quantity_are_rejected():
    plan, snapshot, commitment = _context()
    params = dict(plan.actions[0].parameters)
    params["supplier_id"] = "supplier_unapproved"
    plan.actions[0] = plan.actions[0].model_copy(update={"parameters": params})
    with pytest.raises(DomainError, match="unsupported strategy fields"):
        _builder().build(plan, snapshot, commitment)

    plan, snapshot, commitment = _context()
    params = dict(plan.actions[0].parameters)
    params["partial_quantity"] = str(commitment.terms.quantity)
    plan.actions[0] = plan.actions[0].model_copy(update={"parameters": params})
    with pytest.raises(DomainError, match="less than the confirmed commitment quantity"):
        _builder().build(plan, snapshot, commitment)


def test_scope_and_current_snapshot_binding_are_mandatory():
    plan, snapshot, commitment = _context()
    wrong_tenant = commitment.model_copy(update={"tenant_id": "tenant_other"})
    with pytest.raises(DomainError) as exc:
        _builder().build(plan, snapshot, wrong_tenant)
    assert exc.value.code == "P2_PROPOSAL_SCOPE_MISMATCH"

    plan, stale_snapshot, commitment = _context(current_snapshot_version="STALE")
    with pytest.raises(DomainError) as exc:
        _builder().build(plan, stale_snapshot, commitment)
    assert exc.value.code == "SNAPSHOT_VERSION_CONFLICT"

    plan, missing_snapshot, commitment = _context(current_snapshot_version=None)
    with pytest.raises(DomainError) as exc:
        _builder().build(plan, missing_snapshot, commitment)
    assert exc.value.code == "CURRENT_SNAPSHOT_VERSION_REQUIRED"


def test_commitment_and_snapshot_version_mismatches_are_rejected():
    plan, snapshot, commitment = _context()
    wrong_commitment = commitment.model_copy(update={"commitment_id": "com_other"})
    with pytest.raises(DomainError) as exc:
        _builder().build(plan, snapshot, wrong_commitment)
    assert exc.value.code == "P2_PROPOSAL_SCOPE_MISMATCH"

    stale_commitment_snapshot = replace(snapshot, commitment_version=commitment.commitment_version + 1)
    with pytest.raises(DomainError) as exc:
        _builder().build(plan, stale_commitment_snapshot, commitment)
    assert exc.value.code == "COMMITMENT_VERSION_CONFLICT"

    stale_plan = plan.model_copy(update={
        "evaluation": plan.evaluation.model_copy(update={
            "commitment_version": commitment.commitment_version + 1,
        }),
    })
    with pytest.raises(DomainError) as exc:
        _builder().build(stale_plan, snapshot, commitment)
    assert exc.value.code == "COMMITMENT_VERSION_CONFLICT"


def test_unsupported_mapping_is_conditional_and_never_calls_p2():
    plan, snapshot, commitment = _context(RecoveryStrategy.ALTERNATIVE_SUPPLY)

    class Evaluator:
        called = False

        def evaluate(self, *_args):
            self.called = True
            raise AssertionError("unsupported proposals must not reach P2")

    evaluator = Evaluator()
    adapter = P2PlanRevalidatorAdapter(evaluator, _builder(), allow_test_double=True)
    result = adapter.evaluate_plan(snapshot, plan, commitment)
    assert result.status.value == "CONDITIONAL"
    assert result.evaluation_origin == "P3_UNSUPPORTED_MAPPING"
    assert result.unsupported_reason_code == "P2_ALTERNATIVE_SUPPLY_UNSUPPORTED"
    assert result.source_assessment_id == plan.based_on_assessment_id
    assert not evaluator.called


def test_mapped_proposal_uses_p2_evaluate_shape_and_preserves_result_binding():
    plan, snapshot, commitment = _context()
    proposal_builder = _builder()

    class Evaluator:
        def evaluate(self, actual_snapshot, proposed_changes, actual_commitment):
            assert actual_snapshot is snapshot.snapshot
            assert isinstance(proposed_changes, ProposedChangesContractDouble)
            assert actual_commitment is commitment
            return SimpleNamespace(
                assessment_id="p2-assessment-new",
                tenant_id=commitment.tenant_id,
                commitment_id=commitment.commitment_id,
                commitment_version=commitment.commitment_version,
                snapshot_id=snapshot.snapshot_id,
                snapshot_version=snapshot.snapshot_version,
                status="CONDITIONAL",
                evidence_refs=("p2-evidence",),
                assumptions=("P2 hypothetical result",),
                assessed_at=datetime.now(UTC),
            )

    result = P2PlanRevalidatorAdapter(
        Evaluator(), proposal_builder, allow_test_double=True
    ).evaluate_plan(snapshot, plan, commitment)
    assert result.evaluation_id == "p2-assessment-new"
    assert result.source_assessment_id == plan.based_on_assessment_id
    assert result.evidence_refs[0] == "p2-evidence"
    assert f"assessment:{plan.based_on_assessment_id}" in result.evidence_refs
    assert any("not an executed partial shipment" in item for item in result.assumptions)
