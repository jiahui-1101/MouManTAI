"""Synthetic owner-labelled mathematics tests. These are not live P2 receipts."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import pairwise

import pytest
from pydantic import ValidationError

from app.optimization.cp_sat import ORTOOLS_VERSION, solve
from app.optimization.models import (
    AuthorizedLot,
    AuthorizedResource,
    CandidateBinding,
    CandidateLine,
    FinancialEvidence,
    FixedJob,
    JointVerificationResult,
    MaterialRequirement,
    P2ConstraintSpec,
    PendingOrderCandidate,
    PortfolioRequest,
    ProductionTask,
    ResourceWindow,
    SolverConfig,
    SolverStatus,
    Strategy,
)
from app.optimization.scaling import ScalingError, scaled, unscaled
from app.optimization.service import (
    _verify,
    allocation_digest,
    compare,
    projected_portfolio_digest,
    schedule_digest,
)
from app.optimization.validation import validate_spec

NOW = datetime(2026, 10, 24, 0, 0, tzinfo=UTC)


def fixture_receipt(request, candidate, *, status="FIXTURE_VALIDATED", updates=None):
    receipt = JointVerificationResult(
        status=status,
        tenant_id=request.tenant_id,
        snapshot_id=request.snapshot_id,
        snapshot_version=request.snapshot_version,
        constraint_spec_version=request.constraint_spec_version,
        assessment_watermark=request.assessment_watermark,
        portfolio_run_id=request.portfolio_run_id,
        validated_order_ids=candidate.selected_order_ids,
        validated_order_bindings=candidate.selected_order_bindings,
        allocation_digest=allocation_digest(candidate),
        schedule_digest=schedule_digest(candidate),
        projected_portfolio_digest=projected_portfolio_digest(candidate),
        portfolio_validation_id=f"fixture:{request.portfolio_run_id}",
        evidence_refs=("SYNTHETIC_TEST_FIXTURE",),
        evaluated_at=request.evaluated_at,
        valid_through=request.source_valid_through,
        source_authority="SYNTHETIC_TEST_FIXTURE",
        source_version="fixture-verifier-v1",
    )
    return receipt.model_copy(update=updates or {})


class FixtureProvider:
    def __init__(self, spec):
        self.spec = spec

    def build_for_portfolio(self, request):
        return self.spec


class FixtureVerifier:
    authority = "SYNTHETIC_TEST_FIXTURE"

    def __init__(self, spec, *, disagree=False):
        self.spec = spec
        self.disagree = disagree
        self.receipt_updates = {}
        self.calls = []

    def verify(self, request, candidate):
        self.calls.append(candidate)
        if self.disagree:
            return fixture_receipt(
                request, candidate, status="P2_REJECTED", updates={"portfolio_validation_id": None}
            )
        spec = self.spec
        selected = set(candidate.selected_order_ids)
        assert candidate.snapshot_id == spec.snapshot_id
        assert candidate.snapshot_version == spec.snapshot_version
        assert candidate.spec_version == spec.spec_version
        assert candidate.assessment_watermark == spec.assessment_watermark
        quantities = {}
        for row in candidate.allocations:
            assert row.order_request_id in selected
            quantities[row.lot_id] = quantities.get(row.lot_id, Decimal(0)) + row.quantity
        for lot in spec.lots:
            assert quantities.get(lot.lot_id, 0) <= lot.free_quantity
        scheduled = {task.task_id: task for task in candidate.schedule}
        for requirement in spec.requirements:
            if requirement.order_request_id not in selected:
                continue
            rows = [
                row
                for row in candidate.allocations
                if row.order_request_id == requirement.order_request_id
                and row.line_id == requirement.line_id
            ]
            assert sum((row.quantity for row in rows), Decimal(0)) == requirement.quantity
            assert all(row.lot_id in requirement.compatible_lot_ids for row in rows)
            start = scheduled[requirement.material_use_task_id].start_minute
            for row in rows:
                lot = next(l for l in spec.lots if l.lot_id == row.lot_id)
                assert start >= lot.available_minute
                assert lot.expires_minute is None or start < lot.expires_minute
        occupied = {resource.resource_id: [] for resource in spec.resources}
        for job in spec.fixed_jobs:
            for resource_id in job.resource_ids:
                occupied[resource_id].append((job.start_minute, job.end_minute))
        for task in spec.tasks:
            if task.order_request_id not in selected:
                continue
            scheduled_task = scheduled[task.task_id]
            start, end = scheduled_task.start_minute, scheduled_task.end_minute
            assert end - start == task.duration_minutes
            assert start >= task.earliest_start_minute and end <= task.latest_end_minute
            for resource_id in task.resource_ids:
                resource = next(r for r in spec.resources if r.resource_id == resource_id)
                assert any(
                    w.start_minute <= start and end <= w.end_minute for w in resource.windows
                )
                occupied[resource_id].append((start, end))
        for intervals in occupied.values():
            ordered = sorted(intervals)
            assert all(a[1] <= b[0] for a, b in pairwise(ordered))
        return fixture_receipt(request, candidate, updates=self.receipt_updates)


def fixture(
    *,
    material_capacity=Decimal(7),
    second_lot=Decimal(3),
    shared_resource=True,
    missing_cost=False,
    missing_expiry=False,
):
    candidates = []
    for name, quantity, minutes, revenue in (("A", "6", 0, "90"), ("B", "7", 5, "160")):
        financial = FinancialEvidence(
            order_request_id=name,
            request_version=1,
            terms_hash=f"hash-{name}",
            currency="MYR",
            revenue=Decimal(revenue),
            material_cost=Decimal(30),
            labor_cost=Decimal(10),
            freight_cost=Decimal(5),
            price_revision="catalog-1",
            valid_through=NOW + timedelta(days=1),
            approved_policy_id="fixture-policy",
            evidence_refs=("fixture-price",),
        )
        candidates.append(
            PendingOrderCandidate(
                order_request_id=name,
                tenant_id="fixture-tenant",
                request_version=1,
                terms_revision=1,
                terms_hash=f"hash-{name}",
                lines=(
                    CandidateLine(
                        line_id="line", sku_id="box", quantity=Decimal(quantity), unit="each"
                    ),
                ),
                deadline=NOW + timedelta(hours=3),
                received_at=NOW - timedelta(minutes=30 - minutes),
                received_at_verified=True,
                source_identity=f"fixture-source-{name}",
                evidence_refs=(f"fixture-order-{name}",),
                decision_readiness="READY",
                state="PENDING",
                financial=None if missing_cost and name == "B" else financial,
            )
        )
    request = PortfolioRequest(
        tenant_id="fixture-tenant",
        portfolio_run_id="fixture-run",
        actor_id="fixture-sme",
        actor_scope_verified=True,
        snapshot_id="fixture-snapshot",
        snapshot_version=1,
        constraint_spec_version="fixture-spec-1",
        assessment_watermark="fixture-assessment-1",
        business_timezone="Asia/Kuala_Lumpur",
        evaluated_at=NOW,
        source_valid_through=NOW + timedelta(hours=1),
        evidence_refs=("fixture-source",),
        integration_mode="SYNTHETIC",
        comparison_requested=False,
        solver=SolverConfig(
            max_seconds=Decimal(5),
            random_seed=1,
            workers=1,
            quantity_scale=1000,
            currency_scale=100,
            max_candidates=5,
            max_lots=5,
            max_resources=5,
            max_horizon_minutes=240,
        ),
        candidates=tuple(candidates),
    )
    lots = (
        AuthorizedLot(
            lot_id="old",
            sku_id="leaf",
            warehouse_id="W1",
            free_quantity=material_capacity - second_lot,
            unit="each",
            available_minute=0,
            expires_minute=None if missing_expiry else 120,
            evidence_refs=("fixture-stock-old",),
        ),
        AuthorizedLot(
            lot_id="new",
            sku_id="leaf",
            warehouse_id="W1",
            free_quantity=second_lot,
            unit="each",
            available_minute=0,
            expires_minute=None if missing_expiry else 220,
            evidence_refs=("fixture-stock-new",),
        ),
    )
    requirements = tuple(
        MaterialRequirement(
            order_request_id=name,
            line_id="line",
            sku_id="leaf",
            quantity=Decimal(quantity),
            unit="each",
            compatible_lot_ids=("old", "new"),
            material_use_task_id=f"task-{name}",
            evidence_refs=("fixture-P2-BOM",),
        )
        for name, quantity in (("A", "6"), ("B", "7"))
    )
    resources = (
        AuthorizedResource(
            resource_id="machine",
            windows=(ResourceWindow(start_minute=0, end_minute=240),),
            evidence_refs=("fixture-calendar",),
        ),
    )
    if not shared_resource:
        resources += (
            AuthorizedResource(
                resource_id="machine-B",
                windows=(ResourceWindow(start_minute=0, end_minute=240),),
                evidence_refs=("fixture-calendar-B",),
            ),
        )
    tasks = tuple(
        ProductionTask(
            task_id=f"task-{name}",
            order_request_id=name,
            line_id="line",
            resource_ids=("machine" if shared_resource or name == "A" else "machine-B",),
            duration_minutes=60,
            earliest_start_minute=30,
            latest_end_minute=180,
            evidence_refs=("fixture-process",),
        )
        for name in ("A", "B")
    )
    spec = P2ConstraintSpec(
        owner="SYNTHETIC_TEST_FIXTURE",
        tenant_id="fixture-tenant",
        snapshot_id="fixture-snapshot",
        snapshot_version=1,
        spec_version="fixture-spec-1",
        assessment_watermark="fixture-assessment-1",
        candidate_bindings=tuple(
            CandidateBinding(
                order_request_id=c.order_request_id,
                request_version=c.request_version,
                terms_revision=c.terms_revision,
                terms_hash=c.terms_hash,
                source_identity=c.source_identity,
                evidence_refs=c.evidence_refs,
            )
            for c in candidates
        ),
        horizon_minutes=240,
        lots=lots,
        requirements=requirements,
        resources=resources,
        fixed_jobs=(
            FixedJob(
                job_id="accepted-job",
                resource_ids=("machine",),
                start_minute=0,
                end_minute=30,
                evidence_refs=("fixture-accepted-commitment",),
            ),
        ),
        tasks=tasks,
        accepted_reservations_protected=True,
        source_refs=("SYNTHETIC_TEST_FIXTURE",),
    )
    return request, spec


def test_three_distinct_strategies_and_joint_verification():
    request, spec = fixture()
    verifier = FixtureVerifier(spec)
    result = compare(request, provider=FixtureProvider(spec), verifier=verifier)
    assert result.trigger == "JOINT_CONTENTION"
    fcfs, profit, expiry = result.scenarios
    assert fcfs.selected_order_ids == ("A",)
    assert fcfs.exclusions[0].reason_code == "JOINT_RESOURCE_CONTENTION"
    assert profit.selected_order_ids == ("B",)
    assert profit.objective_value == Decimal(115)
    assert profit.objective_unit == "MYR"
    assert expiry.selected_order_ids == ("B",)
    assert {a.lot_id: a.quantity for a in expiry.allocations} == {
        "old": Decimal(4),
        "new": Decimal(3),
    }
    assert all(s.validation_status == "FIXTURE_VALIDATED" for s in result.scenarios)
    assert all(s.recommendation_only for s in result.scenarios)
    assert len(verifier.calls) == 3  # FCFS inclusion and each CP-SAT scenario.
    assert result.integration_mode == "SYNTHETIC"
    assert ORTOOLS_VERSION != "UNAVAILABLE"


def test_individually_feasible_jointly_infeasible_and_fixed_job():
    request, spec = fixture()
    for oid in ("A", "B"):
        status, _, _, _ = solve(request, spec, Strategy.FCFS, forced_selected=frozenset({oid}))
        assert status == SolverStatus.OPTIMAL
    status, projection, _, _ = solve(
        request, spec, Strategy.FCFS, forced_selected=frozenset({"A", "B"})
    )
    assert status == SolverStatus.INFEASIBLE and projection is None


def test_missing_sources_and_disagreement_fail_closed():
    request, spec = fixture(missing_cost=True)
    result = compare(request, provider=FixtureProvider(spec), verifier=FixtureVerifier(spec))
    assert result.scenarios[0].validation_status == "FIXTURE_VALIDATED"
    assert result.scenarios[1].validation_status == "PROFIT_COMPARISON_UNAVAILABLE"
    request, spec = fixture(missing_expiry=True)
    result = compare(request, provider=FixtureProvider(spec), verifier=FixtureVerifier(spec))
    assert result.scenarios[2].validation_status == "EXPIRY_COMPARISON_UNAVAILABLE"
    request, spec = fixture()
    result = compare(
        request, provider=FixtureProvider(spec), verifier=FixtureVerifier(spec, disagree=True)
    )
    assert "VALIDATION_MISMATCH" in result.limitation_codes
    assert all(not s.selected_order_ids for s in result.scenarios)
    assert compare(request).limitation_codes == ("P2_CONSTRAINT_SPEC_UNAVAILABLE",)
    assert compare(request, provider=FixtureProvider(spec)).limitation_codes == (
        "P2_JOINT_VERIFIER_UNAVAILABLE",
    )


@pytest.mark.parametrize(
    "value,scale,code",
    [
        (Decimal("0.0001"), 1000, "SCALING_PRECISION_UNSUPPORTED"),
        (Decimal("NaN"), 100, "SCALING_PRECISION_UNSUPPORTED"),
        (Decimal("1e30"), 100, "SCALING_OVERFLOW"),
    ],
)
def test_scaling_rejects_unsafe_values(value, scale, code):
    with pytest.raises(ScalingError, match=code):
        scaled(value, scale)


def test_scaling_is_exact_under_low_ambient_precision():
    from decimal import localcontext

    with localcontext() as context:
        context.prec = 3
        assert scaled(Decimal("123456.789"), 1000) == 123456789
        assert unscaled(123456789, 1000) == Decimal("123456.789")


def test_rejects_cross_tenant_and_unprotected_spec():
    request, spec = fixture()
    with pytest.raises(ValueError, match="STALE_OR_CROSS_TENANT_TENANT"):
        validate_spec(request, spec.model_copy(update={"tenant_id": "other"}))
    with pytest.raises(ValueError, match="UNPROTECTED_ACCEPTED_RESERVATIONS"):
        validate_spec(request, spec.model_copy(update={"accepted_reservations_protected": False}))


def test_invalid_candidate_identity_and_time():
    request, _ = fixture()
    with pytest.raises(ValidationError):
        request.model_copy(update={"candidates": request.candidates * 2}).model_validate(
            request.model_copy(update={"candidates": request.candidates * 2}).model_dump()
        )
    invalid = request.candidates[0].model_copy(update={"received_at_verified": False})
    with pytest.raises(ValidationError):
        PortfolioRequest.model_validate(
            request.model_copy(update={"candidates": (invalid, request.candidates[1])}).model_dump()
        )


def test_no_contention_avoids_comparison():
    request, spec = fixture(
        material_capacity=Decimal(13), second_lot=Decimal(7), shared_resource=False
    )
    spec = spec.model_copy(update={"fixed_jobs": ()})
    result = compare(request, provider=FixtureProvider(spec), verifier=FixtureVerifier(spec))
    assert result.trigger == "SINGLE_ORDER_P2"
    assert result.scenarios == ()


def test_explicit_comparison_even_when_resources_are_independent():
    request, spec = fixture(
        material_capacity=Decimal(13), second_lot=Decimal(7), shared_resource=False
    )
    request = request.model_copy(update={"comparison_requested": True})
    spec = spec.model_copy(update={"fixed_jobs": ()})
    result = compare(request, provider=FixtureProvider(spec), verifier=FixtureVerifier(spec))
    assert result.trigger == "EXPLICIT_SME_COMPARISON"
    assert result.scenarios[0].selected_order_ids == ("A", "B")


def test_fixed_job_and_disjoint_calendar_prevent_false_capacity():
    request, spec = fixture(material_capacity=Decimal(13), second_lot=Decimal(7))
    resource = spec.resources[0].model_copy(
        update={
            "windows": (
                ResourceWindow(start_minute=0, end_minute=75),
                ResourceWindow(start_minute=90, end_minute=135),
            )
        }
    )
    task = spec.tasks[0].model_copy(update={"duration_minutes": 90})
    spec = spec.model_copy(update={"resources": (resource,), "tasks": (task, spec.tasks[1])})
    status, projection, _, _ = solve(request, spec, Strategy.FCFS, forced_selected=frozenset({"A"}))
    assert status == SolverStatus.INFEASIBLE and projection is None


def test_capacity_only_joint_contention():
    request, spec = fixture(material_capacity=Decimal(13), second_lot=Decimal(7))
    tasks = tuple(task.model_copy(update={"latest_end_minute": 90}) for task in spec.tasks)
    spec = spec.model_copy(update={"tasks": tasks})
    result = compare(request, provider=FixtureProvider(spec), verifier=FixtureVerifier(spec))
    assert result.trigger == "JOINT_CONTENTION"
    assert result.scenarios[0].selected_order_ids == ("A",)


def test_expiry_at_use_and_confirmed_incoming_boundary():
    request, spec = fixture()
    lots = (
        spec.lots[0].model_copy(update={"expires_minute": 30}),
        spec.lots[1].model_copy(update={"available_minute": 31}),
    )
    spec = spec.model_copy(update={"lots": lots})
    status, projection, _, _ = solve(request, spec, Strategy.FCFS, forced_selected=frozenset({"B"}))
    assert status == SolverStatus.INFEASIBLE and projection is None


def test_negative_contribution_selects_nothing():
    request, spec = fixture()
    candidates = tuple(
        c.model_copy(update={"financial": c.financial.model_copy(update={"revenue": Decimal(1)})})
        for c in request.candidates
    )
    request = request.model_copy(update={"candidates": candidates})
    result = compare(request, provider=FixtureProvider(spec), verifier=FixtureVerifier(spec))
    assert result.scenarios[1].selected_order_ids == ()
    assert result.scenarios[1].objective_value == Decimal(0)


def test_stale_finance_currency_mismatch_and_missing_verifier():
    request, spec = fixture()
    candidate = request.candidates[1]
    old = candidate.financial.model_copy(update={"valid_through": NOW - timedelta(seconds=1)})
    request = request.model_copy(
        update={
            "candidates": (request.candidates[0], candidate.model_copy(update={"financial": old}))
        }
    )
    result = compare(request, provider=FixtureProvider(spec), verifier=FixtureVerifier(spec))
    assert result.scenarios[1].validation_status == "PROFIT_COMPARISON_UNAVAILABLE"
    request, spec = fixture()
    wrong_currency = request.candidates[1].financial.model_copy(update={"currency": "USD"})
    request = request.model_copy(
        update={
            "candidates": (
                request.candidates[0],
                request.candidates[1].model_copy(update={"financial": wrong_currency}),
            )
        }
    )
    result = compare(request, provider=FixtureProvider(spec), verifier=FixtureVerifier(spec))
    assert result.scenarios[1].validation_status == "PROFIT_COMPARISON_UNAVAILABLE"


@pytest.mark.parametrize(
    "change,code",
    [
        ({"snapshot_version": 2}, "STALE_OR_CROSS_TENANT_SNAPSHOT_VERSION"),
        ({"spec_version": "wrong"}, "STALE_OR_CROSS_TENANT_SPEC_VERSION"),
        ({"assessment_watermark": "wrong"}, "STALE_OR_CROSS_TENANT_ASSESSMENT"),
        ({"owner": "P2"}, "SYNTHETIC_SPEC_REQUIRED"),
    ],
)
def test_spec_binding_rejects_stale_or_wrong_authority(change, code):
    request, spec = fixture()
    with pytest.raises(ValueError, match=code):
        validate_spec(request, spec.model_copy(update=change))


def test_spec_must_bind_exact_pending_order_terms_and_source():
    request, spec = fixture()
    stale = spec.candidate_bindings[0].model_copy(update={"terms_hash": "stale"})
    spec = spec.model_copy(update={"candidate_bindings": (stale, spec.candidate_bindings[1])})
    with pytest.raises(ValueError, match="P2_CANDIDATE_BINDING_MISMATCH"):
        validate_spec(request, spec)


def test_live_request_cannot_use_fixture_authority():
    request, spec = fixture()
    request = request.model_copy(update={"integration_mode": "LIVE"})
    result = compare(request, provider=FixtureProvider(spec), verifier=FixtureVerifier(spec))
    assert result.scenarios == ()
    assert result.limitation_codes == ("P2_CONSTRAINT_SPEC_UNAVAILABLE",)


def test_revalidated_boundary_blocks_model_copy_financial_version_bypass():
    request, spec = fixture()
    candidate = request.candidates[1]
    wrong = candidate.financial.model_copy(update={"terms_hash": "wrong"})
    request = request.model_copy(
        update={
            "candidates": (request.candidates[0], candidate.model_copy(update={"financial": wrong}))
        }
    )
    result = compare(request, provider=FixtureProvider(spec), verifier=FixtureVerifier(spec))
    assert result.trigger == "INSUFFICIENT_DATA"
    assert result.scenarios == ()


def test_verifier_timeout_blocks_all_scenarios():
    request, spec = fixture()

    class TimedOutVerifier:
        authority = "SYNTHETIC_TEST_FIXTURE"

        def verify(self, request, candidate):
            raise TimeoutError("fixture unavailable")

    result = compare(request, provider=FixtureProvider(spec), verifier=TimedOutVerifier())
    assert all(s.validation_status == "P2_JOINT_VERIFIER_UNAVAILABLE" for s in result.scenarios)
    assert all(not s.selected_order_ids for s in result.scenarios)


def test_fcfs_timestamp_tie_uses_stable_id():
    request, spec = fixture()
    tied = request.candidates[1].model_copy(
        update={"received_at": request.candidates[0].received_at}
    )
    request = request.model_copy(update={"candidates": (request.candidates[0], tied)})
    result = compare(request, provider=FixtureProvider(spec), verifier=FixtureVerifier(spec))
    assert result.scenarios[0].selected_order_ids == ("A",)


@pytest.mark.parametrize(
    "receipt_updates",
    [
        {"tenant_id": "another-tenant"},
        {"snapshot_id": "another-snapshot"},
        {"snapshot_version": 99},
        {"constraint_spec_version": "old-spec"},
        {"assessment_watermark": "old-watermark"},
        {"portfolio_run_id": "another-run"},
        {"validated_order_ids": ()},
        {"validated_order_bindings": ()},
        {"allocation_digest": "different-allocation"},
        {"schedule_digest": "different-schedule"},
        {"projected_portfolio_digest": "different-projection"},
        {"evaluated_at": NOW - timedelta(seconds=1)},
        {"valid_through": NOW - timedelta(seconds=1)},
        {"evidence_refs": ()},
        {"source_authority": "P2"},
        {"source_version": ""},
        {"status": "P2_VALIDATED"},
    ],
)
def test_wrong_or_replayed_joint_receipt_is_mismatch(receipt_updates):
    request, spec = fixture()
    verifier = FixtureVerifier(spec)
    verifier.receipt_updates = receipt_updates
    result = compare(request, provider=FixtureProvider(spec), verifier=verifier)
    assert all(s.validation_status == "VALIDATION_MISMATCH" for s in result.scenarios)
    assert all(not s.selected_order_ids for s in result.scenarios)


def test_fake_p2_validated_provider_cannot_establish_live_authority():
    request, spec = fixture()
    live_request = request.model_copy(update={"integration_mode": "LIVE"})
    live_spec = spec.model_copy(update={"owner": "P2"})

    class FakeP2Verifier:
        authority = "P2"
        calls = 0

        def verify(self, request, candidate):
            self.calls += 1
            return fixture_receipt(
                request,
                candidate,
                status="P2_VALIDATED",
                updates={"source_authority": "P2"},
            )

    verifier = FakeP2Verifier()
    result = compare(live_request, provider=FixtureProvider(live_spec), verifier=verifier)
    assert all(s.validation_status == "P2_JOINT_VERIFIER_UNAVAILABLE" for s in result.scenarios)
    assert verifier.calls == 0


@pytest.mark.parametrize("field", ["allocations", "schedule"])
def test_replayed_receipt_for_same_orders_but_different_projection_is_rejected(field):
    request, spec = fixture()
    status, projection, _, _ = solve(request, spec, Strategy.FCFS, forced_selected=frozenset({"A"}))
    assert status == SolverStatus.OPTIMAL and projection is not None
    if field == "allocations":
        changed = (
            projection.allocations[0].model_copy(
                update={"quantity": projection.allocations[0].quantity + Decimal(1)}
            ),
            *projection.allocations[1:],
        )
    else:
        changed = tuple(
            task.model_copy(
                update={"start_minute": task.start_minute + 1, "end_minute": task.end_minute + 1}
            )
            for task in projection.schedule
        )
    replayed_projection = projection.model_copy(update={field: changed})
    assert replayed_projection.selected_order_ids == projection.selected_order_ids

    class ReplayVerifier:
        authority = "SYNTHETIC_TEST_FIXTURE"

        def verify(self, request, candidate):
            return fixture_receipt(request, projection)

    with pytest.raises(ValueError, match="VALIDATION_MISMATCH"):
        _verify(request, replayed_projection, ReplayVerifier())


@pytest.mark.parametrize("field", ["revenue", "material_cost", "labor_cost", "freight_cost"])
def test_missing_financial_component_is_invalid(field):
    request, _ = fixture()
    finance = request.candidates[0].financial.model_dump()
    del finance[field]
    with pytest.raises(ValidationError):
        FinancialEvidence.model_validate(finance)


@pytest.mark.parametrize(
    "field,value",
    [
        ("actor_scope_verified", False),
        ("assessment_watermark", ""),
        ("source_valid_through", NOW - timedelta(seconds=1)),
    ],
)
def test_missing_authoritative_request_fields_fail_closed(field, value):
    request, _ = fixture()
    with pytest.raises(ValidationError):
        PortfolioRequest.model_validate(request.model_copy(update={field: value}).model_dump())


def test_model_size_limits_reject_unbounded_spec():
    request, spec = fixture()
    solver = request.solver.model_copy(update={"max_tasks": 1})
    request = request.model_copy(update={"solver": solver})
    with pytest.raises(ValueError, match="MODEL_LIMIT_EXCEEDED"):
        validate_spec(request, spec)


def test_solver_scales_require_exact_decimal_units():
    request, _ = fixture()
    with pytest.raises(ValidationError, match="powers of ten"):
        SolverConfig.model_validate(
            request.solver.model_copy(update={"quantity_scale": 3}).model_dump()
        )
