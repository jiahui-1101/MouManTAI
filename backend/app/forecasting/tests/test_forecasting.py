from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.forecasting.backtesting import backtest, compare_on_same_holdout
from app.forecasting.baselines import MovingAverage, Naive, SeasonalNaive, forecast
from app.forecasting.models import (
    DemandKind,
    DemandObservation,
    ForecastSourceManifest,
    ForecastStatus,
    Mode,
    RiskFamily,
    Tier,
)
from app.forecasting.ports import CurrentSnapshot, P2ScenarioAttestation
from app.forecasting.scenarios import capacity_or_deadline, stockout_or_expiry
from app.forecasting.service import ForecastService
from app.forecasting.source_validation import validate_series

NOW = datetime(2026, 10, 24, 12, tzinfo=UTC)
START = date(2026, 10, 1)


def fixture(days=21, start=START):
    manifest = ForecastSourceManifest(
        tenant_id="demo",
        source_dataset_id="fixture",
        source_snapshot_id="snapshot-1",
        source_snapshot_version="v1",
        source_system="test fixture",
        integration_mode=Mode.SYNTHETIC,
        evidence_tier=Tier.DEMO_ONLY,
        captured_at=NOW,
        complete_through=start + timedelta(days=days - 1),
        historical_window_start=start,
        historical_window_end=start + timedelta(days=days - 1),
        source_watermark=NOW,
        pagination_complete=True,
        source_population_complete=True,
        input_version="fixture-1",
        evidence_refs=("fixture",),
        reader_attestation="test-only reader",
    )
    observations = tuple(
        DemandObservation(
            tenant_id="demo",
            sku_id="A",
            observation_id=f"row-{i}",
            observation_version=1,
            period=start + timedelta(days=i),
            quantity=Decimal(i % 7 + 1),
            unit="pcs",
            kind=DemandKind.ACCEPTED,
            source_event_ref=f"order-{i}",
            acceptance_ref=f"accept-{i}",
            evidence_ref=f"fixture-{i}",
            source_version="v1",
            recorded_at=datetime.combine(start, datetime.min.time(), UTC)
            + timedelta(days=i, hours=12),
            business_timezone="Asia/Singapore",
            evidence_tier=Tier.DEMO_ONLY,
            integration_mode=Mode.SYNTHETIC,
        )
        for i in range(days)
    )
    return manifest, observations


def series(days=21, start=START):
    manifest, rows = fixture(days, start)
    return validate_series(
        manifest,
        rows,
        tenant_id="demo",
        sku_id="A",
        unit="pcs",
        cutoff=manifest.complete_through,
        now=NOW,
        trusted_reader=True,
    )


@pytest.mark.parametrize("field", ["observation_version", "supersedes_version"])
@pytest.mark.parametrize("invalid", [True, False, 1.0, 1.5, "1", "bad", 0, -1])
def test_observation_versions_reject_coercion_and_nonpositive_values(field, invalid):
    _, rows = fixture()
    payload = rows[0].model_dump()
    payload[field] = invalid
    with pytest.raises(ValueError, match=field):
        DemandObservation.model_validate(payload)


def test_baselines_and_evidence():
    s = series()
    cutoff = s.manifest.complete_through
    moving = forecast(s, MovingAverage(7), cutoff=cutoff, horizon=3, generated_at=NOW)
    seasonal = forecast(s, SeasonalNaive(7), cutoff=cutoff, horizon=3, generated_at=NOW)
    assert moving.status == ForecastStatus.AVAILABLE
    assert [point.quantity for point in moving.points] == [Decimal(4)] * 3
    assert [point.quantity for point in seasonal.points] == [Decimal(1), Decimal(2), Decimal(3)]
    assert moving.evidence_tier == Tier.DEMO_ONLY and moving.integration_mode == Mode.SYNTHETIC
    assert all(point.period > cutoff for point in moving.points)


def test_missing_is_not_zero_and_non_demand_excluded():
    manifest, rows = fixture()
    unknown = rows[-1].model_copy(
        update={"kind": DemandKind.UNKNOWN, "quantity": None, "acceptance_ref": None}
    )
    inquiry = rows[0].model_copy(
        update={"kind": DemandKind.INQUIRY, "quantity": None, "acceptance_ref": None}
    )
    s = validate_series(
        manifest,
        (inquiry,) + rows[1:-1] + (unknown,),
        tenant_id="demo",
        sku_id="A",
        unit="pcs",
        cutoff=manifest.complete_through,
        now=NOW,
        trusted_reader=True,
    )
    assert s.values[unknown.period] is None and inquiry.period not in s.values
    assert (
        forecast(
            s, MovingAverage(7), cutoff=manifest.complete_through, horizon=1, generated_at=NOW
        ).status
        == ForecastStatus.INSUFFICIENT
    )
    assert (
        forecast(
            s, SeasonalNaive(7), cutoff=manifest.complete_through, horizon=1, generated_at=NOW
        ).status
        == ForecastStatus.AVAILABLE
    )


@pytest.mark.parametrize(
    "mutation,code",
    [
        (
            lambda m, r: (m.model_copy(update={"pagination_complete": False}), r),
            "SOURCE_INCOMPLETE",
        ),
        (
            lambda m, r: (m, r + (r[-1].model_copy(update={"quantity": Decimal(99)}),)),
            "CONFLICTING_DUPLICATE_OR_UNVERIFIED_CORRECTION",
        ),
        (
            lambda m, r: (m, r + (r[-1].model_copy(update={"observation_id": "new"}),)),
            "DUPLICATE_PERIOD_BUCKET",
        ),
        (
            lambda m, r: (m, r[:-1] + (r[-1].model_copy(update={"tenant_id": "other"}),)),
            "IDENTITY_OR_UNIT_MISMATCH",
        ),
        (
            lambda m, r: (m, r[:-1] + (r[-1].model_copy(update={"source_version": "v2"}),)),
            "SOURCE_VERSION_MISMATCH",
        ),
    ],
)
def test_source_fail_closed(mutation, code):
    m, r = mutation(*fixture())
    s = validate_series(
        m,
        r,
        tenant_id="demo",
        sku_id="A",
        unit="pcs",
        cutoff=m.complete_through,
        now=NOW,
        trusted_reader=True,
    )
    assert code in s.diagnostics and not s.values


def test_replay_and_verified_correction():
    m, r = fixture()
    replay = validate_series(
        m,
        r + (r[-1],),
        tenant_id="demo",
        sku_id="A",
        unit="pcs",
        cutoff=m.complete_through,
        now=NOW,
        trusted_reader=True,
    )
    assert replay.status == ForecastStatus.AVAILABLE and len(replay.values) == len(r)
    correction = r[-1].model_copy(
        update={"observation_version": 2, "supersedes_version": 1, "quantity": Decimal(8)}
    )
    corrected = validate_series(
        m,
        r + (correction,),
        tenant_id="demo",
        sku_id="A",
        unit="pcs",
        cutoff=m.complete_through,
        now=NOW,
        trusted_reader=True,
    )
    assert corrected.values[r[-1].period] == 8


def test_no_reader_and_disabled_maturity():
    assert (
        ForecastService().readiness("demo", "A", "pcs", START, NOW).status
        == ForecastStatus.UNAVAILABLE
    )
    m, r = fixture()
    m = m.model_copy(update={"evidence_tier": Tier.VALIDATED})
    s = validate_series(
        m,
        r,
        tenant_id="demo",
        sku_id="A",
        unit="pcs",
        cutoff=m.complete_through,
        now=NOW,
        trusted_reader=True,
    )
    assert "PRODUCTION_EVIDENCE_GATE_DISABLED" in s.diagnostics


def test_backtest_chronology_metrics_and_common_holdout():
    s = series()
    cutoff = START + timedelta(days=13)
    report = backtest(
        s, MovingAverage(7), train_cutoff=cutoff, test_end=s.manifest.complete_through
    )
    assert report.eligible_actuals == 7 and report.skipped_unknown_actuals == 0
    assert report.mae.value is not None and report.wape.value is not None
    assert all(row.origin < row.period for row in report.rows)
    reports = compare_on_same_holdout(
        s,
        (MovingAverage(7), SeasonalNaive(7), Naive()),
        train_cutoff=cutoff,
        test_end=s.manifest.complete_through,
    )
    assert len({report.eligible_actuals for report in reports}) == 1
    assert all(report.evidence_tier == Tier.DEMO_ONLY for report in reports)


def test_undefined_metrics_and_late_record_not_leaked():
    m, rows = fixture()
    rows = tuple(row.model_copy(update={"quantity": Decimal(0)}) for row in rows)
    late = rows[14].model_copy(update={"recorded_at": NOW})
    rows = rows[:14] + (late,) + rows[15:]
    s = validate_series(
        m,
        rows,
        tenant_id="demo",
        sku_id="A",
        unit="pcs",
        cutoff=m.complete_through,
        now=NOW,
        trusted_reader=True,
    )
    report = backtest(
        s, Naive(), train_cutoff=START + timedelta(days=13), test_end=m.complete_through
    )
    assert report.wape.value is None and report.mase.value is None
    assert report.rows[1].prediction is None  # late day-14 value hidden at day-15 origin


def test_four_family_advisories_fail_closed_and_matching_p2():
    run = forecast(
        series(), MovingAverage(), cutoff=START + timedelta(days=20), horizon=1, generated_at=NOW
    )
    alerts = ForecastService().advisories(run)
    assert [a.family for a in alerts] == list(RiskFamily)
    assert alerts[1].status == alerts[2].status == alerts[3].status == "UNKNOWN"
    assert all(not a.operational_action_authorized for a in alerts)
    snapshot = CurrentSnapshot(
        tenant_id="demo",
        sku_id="A",
        snapshot_id="op-1",
        snapshot_version="3",
        captured_at=NOW,
        valid_through=NOW + timedelta(days=1),
        business_timezone="Asia/Singapore",
        evidence_refs=("op",),
    )
    attestation = P2ScenarioAttestation(
        tenant_id="demo",
        sku_id="A",
        snapshot_id="op-1",
        snapshot_version="3",
        source_watermark=NOW,
        evaluator_version="p2-1",
        forecast_run_id=run.run_id,
        risk_family=RiskFamily.STOCKOUT_OR_EXPIRY,
        target_period=run.points[0].period,
        coverage_start=run.points[0].period,
        coverage_end=run.points[0].period,
        assessment_status="SUPPORTED",
        exposure="conditional exposure",
        reason_codes=("CONDITIONAL",),
        evidence_refs=("p2",),
        evaluated_at=NOW,
        valid_through=NOW + timedelta(days=1),
    )
    from app.forecasting.scenarios import stockout_or_expiry

    assert (
        stockout_or_expiry(run, snapshot, attestation, as_of=NOW).status == "FUTURE_RISK_ADVISORY"
    )
    assert (
        stockout_or_expiry(
            run,
            snapshot,
            attestation.model_copy(update={"snapshot_version": "old"}),
            as_of=NOW,
        ).status
        == "UNKNOWN"
    )
    assert stockout_or_expiry(
        run,
        snapshot,
        attestation.model_copy(update={"risk_family": RiskFamily.CAPACITY_OR_DEADLINE}),
        as_of=NOW,
    ).explanation_codes == ("P2_RISK_FAMILY_MISMATCH",)
    stock_alert_as_capacity = capacity_or_deadline(run, snapshot, attestation, as_of=NOW)
    assert stock_alert_as_capacity.status == "UNKNOWN"
    assert "P2_RISK_FAMILY_MISMATCH" in stock_alert_as_capacity.explanation_codes
    capacity_attestation = attestation.model_copy(
        update={"risk_family": RiskFamily.CAPACITY_OR_DEADLINE}
    )
    assert capacity_or_deadline(run, snapshot, capacity_attestation, as_of=NOW).status == (
        "FUTURE_RISK_ADVISORY"
    )
    capacity_alert_as_stock = stockout_or_expiry(run, snapshot, capacity_attestation, as_of=NOW)
    assert capacity_alert_as_stock.status == "UNKNOWN"
    assert "P2_RISK_FAMILY_MISMATCH" in capacity_alert_as_stock.explanation_codes


@pytest.mark.parametrize(
    ("updates", "expected"),
    [
        ({"evaluated_at": NOW + timedelta(minutes=1)}, "P2_EVALUATION_IN_FUTURE"),
        ({"valid_through": NOW - timedelta(seconds=1)}, "P2_ATTESTATION_STALE_AT_AS_OF"),
        ({"assessment_status": "INCOMPLETE"}, "P2_ASSESSMENT_NOT_SUPPORTED"),
        ({"evidence_refs": ()}, "P2_EVIDENCE_MISSING"),
        ({"coverage_end": START}, "P2_COVERAGE_MISMATCH"),
        ({"source_watermark": NOW - timedelta(seconds=1)}, "P2_SOURCE_WATERMARK_MISMATCH"),
        ({"tenant_id": "other"}, "P2_TENANT_OR_SKU_MISMATCH"),
        ({"sku_id": "other"}, "P2_TENANT_OR_SKU_MISMATCH"),
        ({"snapshot_id": "other"}, "P2_SNAPSHOT_VERSION_MISMATCH"),
        ({"forecast_run_id": "old-run"}, "P2_FORECAST_RUN_MISMATCH"),
        ({"target_period": START}, "P2_COVERAGE_MISMATCH"),
        ({"risk_family": RiskFamily.CAPACITY_OR_DEADLINE}, "P2_RISK_FAMILY_MISMATCH"),
    ],
)
def test_invalid_p2_attestation_returns_unknown_with_diagnostic(updates, expected):
    run = forecast(
        series(), MovingAverage(), cutoff=START + timedelta(days=20), horizon=1, generated_at=NOW
    )
    snapshot = CurrentSnapshot(
        tenant_id="demo",
        sku_id="A",
        snapshot_id="op-1",
        snapshot_version="3",
        captured_at=NOW,
        valid_through=NOW + timedelta(days=1),
        business_timezone="Asia/Singapore",
        evidence_refs=("op",),
    )
    attestation = P2ScenarioAttestation(
        tenant_id="demo",
        sku_id="A",
        snapshot_id="op-1",
        snapshot_version="3",
        source_watermark=NOW,
        evaluator_version="p2-1",
        forecast_run_id=run.run_id,
        risk_family=RiskFamily.STOCKOUT_OR_EXPIRY,
        target_period=run.points[0].period,
        coverage_start=run.points[0].period,
        coverage_end=run.points[0].period,
        assessment_status="SUPPORTED",
        exposure="conditional exposure",
        reason_codes=(),
        evidence_refs=("p2",),
        evaluated_at=NOW,
        valid_through=NOW + timedelta(days=1),
    ).model_copy(update=updates)
    result = stockout_or_expiry(run, snapshot, attestation, as_of=NOW)
    assert result.status == "UNKNOWN"
    assert expected in result.explanation_codes


def test_future_or_stale_current_snapshot_returns_unknown():
    run = forecast(
        series(), MovingAverage(), cutoff=START + timedelta(days=20), horizon=1, generated_at=NOW
    )
    attestation = P2ScenarioAttestation(
        tenant_id="demo",
        sku_id="A",
        snapshot_id="op-1",
        snapshot_version="3",
        source_watermark=NOW,
        evaluator_version="p2-1",
        forecast_run_id=run.run_id,
        risk_family=RiskFamily.STOCKOUT_OR_EXPIRY,
        target_period=run.points[0].period,
        coverage_start=run.points[0].period,
        coverage_end=run.points[0].period,
        assessment_status="SUPPORTED",
        exposure="conditional exposure",
        reason_codes=(),
        evidence_refs=("p2",),
        evaluated_at=NOW,
        valid_through=NOW + timedelta(days=1),
    )
    stale = CurrentSnapshot(
        tenant_id="demo",
        sku_id="A",
        snapshot_id="op-1",
        snapshot_version="3",
        captured_at=NOW - timedelta(days=1),
        valid_through=NOW - timedelta(seconds=1),
        business_timezone="Asia/Singapore",
        evidence_refs=("op",),
    )
    stale_alert = stockout_or_expiry(run, stale, attestation, as_of=NOW)
    assert stale_alert.status == "UNKNOWN"
    assert "SNAPSHOT_STALE_AT_AS_OF" in stale_alert.explanation_codes

    future = stale.model_copy(update={"captured_at": NOW + timedelta(minutes=1)})
    future_alert = stockout_or_expiry(run, future, attestation, as_of=NOW)
    assert future_alert.status == "UNKNOWN"
    assert "SNAPSHOT_CAPTURED_IN_FUTURE" in future_alert.explanation_codes

    naive_as_of = stockout_or_expiry(run, stale, attestation, as_of=datetime(2026, 10, 24, 12))
    assert naive_as_of.status == "UNKNOWN"
    assert "TRUSTED_AS_OF_REQUIRED" in naive_as_of.explanation_codes


def test_live_forward_attestation_fails_closed_until_p2_ratifies_contract():
    run = forecast(
        series(), MovingAverage(), cutoff=START + timedelta(days=20), horizon=1, generated_at=NOW
    ).model_copy(update={"integration_mode": Mode.LIVE, "evidence_tier": Tier.LIVE})
    snapshot = CurrentSnapshot(
        tenant_id="demo",
        sku_id="A",
        snapshot_id="op-1",
        snapshot_version="3",
        captured_at=NOW,
        valid_through=NOW + timedelta(days=1),
        business_timezone="Asia/Singapore",
        evidence_refs=("op",),
    )
    attestation = P2ScenarioAttestation(
        tenant_id="demo",
        sku_id="A",
        snapshot_id="op-1",
        snapshot_version="3",
        source_watermark=NOW,
        evaluator_version="p2-1",
        forecast_run_id=run.run_id,
        risk_family=RiskFamily.STOCKOUT_OR_EXPIRY,
        target_period=run.points[0].period,
        coverage_start=run.points[0].period,
        coverage_end=run.points[0].period,
        assessment_status="SUPPORTED",
        exposure="conditional exposure",
        reason_codes=(),
        evidence_refs=("p2",),
        evaluated_at=NOW,
        valid_through=NOW + timedelta(days=1),
    )
    result = stockout_or_expiry(run, snapshot, attestation, as_of=NOW)
    assert result.status == "UNKNOWN"
    assert "P2_FORWARD_CONTRACT_NOT_RATIFIED" in result.explanation_codes


def test_service_requests_separate_snapshot_bound_p2_attestations_per_family():
    run = forecast(
        series(), MovingAverage(), cutoff=START + timedelta(days=20), horizon=1, generated_at=NOW
    )
    snapshot = CurrentSnapshot(
        tenant_id="demo",
        sku_id="A",
        snapshot_id="op-1",
        snapshot_version="3",
        captured_at=NOW,
        valid_through=NOW + timedelta(days=1),
        business_timezone="Asia/Singapore",
        evidence_refs=("op",),
    )

    class SnapshotReader:
        def read(self, tenant_id, sku_id):
            assert (tenant_id, sku_id) == ("demo", "A")
            return snapshot

    class P2Reader:
        def __init__(self):
            self.calls = []

        def evaluate(
            self,
            tenant_id,
            sku_id,
            snapshot_id,
            snapshot_version,
            forecast_run_id,
            risk_family,
            target_period,
            as_of,
        ):
            self.calls.append((snapshot_id, snapshot_version, forecast_run_id, risk_family, as_of))
            return P2ScenarioAttestation(
                tenant_id=tenant_id,
                sku_id=sku_id,
                snapshot_id=snapshot_id,
                snapshot_version=snapshot_version,
                source_watermark=snapshot.captured_at,
                evaluator_version="p2-1",
                forecast_run_id=forecast_run_id,
                risk_family=risk_family,
                target_period=target_period,
                coverage_start=target_period,
                coverage_end=target_period,
                assessment_status="SUPPORTED",
                exposure=f"conditional {risk_family.value.lower()} exposure",
                reason_codes=("CONDITIONAL",),
                evidence_refs=(f"p2-{risk_family.value.lower()}",),
                evaluated_at=as_of,
                valid_through=as_of + timedelta(hours=1),
            )

    reader = P2Reader()
    alerts = ForecastService(snapshot_reader=SnapshotReader(), p2_reader=reader).advisories(
        run, as_of=NOW
    )
    assert [call[3] for call in reader.calls] == [
        RiskFamily.STOCKOUT_OR_EXPIRY,
        RiskFamily.CAPACITY_OR_DEADLINE,
    ]
    assert all(call[:3] == ("op-1", "3", run.run_id) for call in reader.calls)
    assert all(call[4] == NOW for call in reader.calls)
    assert alerts[1].status == alerts[3].status == "FUTURE_RISK_ADVISORY"
    assert alerts[1].explanation_codes[-1] == alerts[3].explanation_codes[-1] == "CONDITIONAL"


def test_forecast_run_id_binds_all_material_source_and_model_inputs():
    s = series()
    cutoff = START + timedelta(days=20)

    def run(data=s, model=None, horizon=1):
        return forecast(
            data,
            model or MovingAverage(7),
            cutoff=cutoff,
            horizon=horizon,
            generated_at=NOW,
        )

    original = run()
    assert original.run_id == run().run_id
    assert (
        original.run_id
        != run(
            data=replace(s, manifest=s.manifest.model_copy(update={"tenant_id": "other"}))
        ).run_id
    )
    assert (
        original.run_id
        != run(
            data=replace(
                s, manifest=s.manifest.model_copy(update={"source_snapshot_version": "v2"})
            )
        ).run_id
    )
    assert (
        original.run_id
        != run(
            data=replace(s, manifest=s.manifest.model_copy(update={"input_version": "fixture-2"}))
        ).run_id
    )
    assert (
        original.run_id
        != run(
            data=replace(
                s,
                manifest=s.manifest.model_copy(
                    update={"source_watermark": NOW + timedelta(seconds=1)}
                ),
            )
        ).run_id
    )
    assert original.run_id != run(model=MovingAverage(14)).run_id
    assert original.run_id != run(model=SeasonalNaive(7)).run_id
    assert original.run_id != run(horizon=2).run_id

    class ScaledNaive:
        name = "SCALED_NAIVE"
        version = "1"

        def __init__(self, scale):
            self.scale = scale

        def predict(self, values, cutoff, horizon):
            value = values.get(cutoff)
            return None if value is None else (value * Decimal(str(self.scale)),) * horizon

    assert run(model=ScaledNaive(0.25)).run_id != run(model=ScaledNaive(0.5)).run_id


def test_old_p2_attestation_run_id_cannot_match_changed_forecast():
    s = series()
    cutoff = START + timedelta(days=20)
    old_run = forecast(s, MovingAverage(7), cutoff=cutoff, horizon=1, generated_at=NOW)
    new_run = forecast(s, MovingAverage(14), cutoff=cutoff, horizon=1, generated_at=NOW)
    snapshot = CurrentSnapshot(
        tenant_id="demo",
        sku_id="A",
        snapshot_id="op-1",
        snapshot_version="3",
        captured_at=NOW,
        valid_through=NOW + timedelta(days=1),
        business_timezone="Asia/Singapore",
        evidence_refs=("op",),
    )
    stale = P2ScenarioAttestation(
        tenant_id="demo",
        sku_id="A",
        snapshot_id="op-1",
        snapshot_version="3",
        source_watermark=NOW,
        evaluator_version="p2-1",
        forecast_run_id=old_run.run_id,
        risk_family=RiskFamily.STOCKOUT_OR_EXPIRY,
        target_period=new_run.points[0].period,
        coverage_start=new_run.points[0].period,
        coverage_end=new_run.points[0].period,
        assessment_status="SUPPORTED",
        exposure="conditional exposure",
        reason_codes=(),
        evidence_refs=("p2",),
        evaluated_at=NOW,
        valid_through=NOW + timedelta(days=1),
    )
    result = stockout_or_expiry(new_run, snapshot, stale, as_of=NOW)
    assert result.status == "UNKNOWN"
    assert "P2_FORECAST_RUN_MISMATCH" in result.explanation_codes


def test_large_fixture_linear_mechanics():
    s = series(1000, date(2023, 1, 1))
    assert len(s.values) == 1000
    result = forecast(
        s, MovingAverage(30), cutoff=s.manifest.complete_through, horizon=30, generated_at=NOW
    )
    assert result.status == ForecastStatus.AVAILABLE and len(result.points) == 30


def test_service_end_to_end_synthetic_reader_no_mutation():
    class Reader:
        calls = 0

        def read(self, tenant_id, sku_id, cutoff):
            self.calls += 1
            assert (tenant_id, sku_id) == ("demo", "A")
            return fixture()

    reader = Reader()
    service = ForecastService(demand_reader=reader)
    cutoff = START + timedelta(days=20)
    run = service.baseline("demo", "A", "pcs", cutoff, 3, NOW, MovingAverage(7))
    reports = service.evaluate("demo", "A", "pcs", START + timedelta(days=13), cutoff, NOW)
    alerts = service.advisories(run)
    assert reader.calls == 2
    assert [p.quantity for p in run.points] == [Decimal(4)] * 3
    assert len(reports) == 3 and all(r.evidence_tier == Tier.DEMO_ONLY for r in reports)
    assert [a.status for a in alerts] == ["FUTURE_RISK_ADVISORY", "UNKNOWN", "UNKNOWN", "UNKNOWN"]
    assert all(not a.operational_action_authorized for a in alerts)


def test_invalid_quantity_and_datetime_rejected():
    _, rows = fixture()
    for value in (Decimal("NaN"), Decimal("Infinity"), Decimal(-1)):
        with pytest.raises(ValueError):
            DemandObservation.model_validate({**rows[0].model_dump(), "quantity": value})
    with pytest.raises(ValueError):
        DemandObservation.model_validate(
            {**rows[0].model_dump(), "recorded_at": datetime(2026, 10, 1)}
        )


def test_stale_source_and_future_history_fail_closed():
    manifest, rows = fixture()
    stale = manifest.model_copy(update={"source_watermark": NOW - timedelta(days=8)})
    result = validate_series(
        stale,
        rows,
        tenant_id="demo",
        sku_id="A",
        unit="pcs",
        cutoff=manifest.complete_through,
        now=NOW,
        trusted_reader=True,
    )
    assert result.status == ForecastStatus.STALE and "SOURCE_STALE" in result.diagnostics
    future = rows[-1].model_copy(update={"period": manifest.complete_through + timedelta(days=1)})
    result = validate_series(
        manifest,
        rows[:-1] + (future,),
        tenant_id="demo",
        sku_id="A",
        unit="pcs",
        cutoff=manifest.complete_through,
        now=NOW,
        trusted_reader=True,
    )
    assert (
        result.status == ForecastStatus.INVALID
        and "OBSERVATION_OUTSIDE_CUTOFF" in result.diagnostics
    )


def test_known_zero_is_valid_but_unknown_actual_is_skipped():
    manifest, rows = fixture()
    zero = rows[-1].model_copy(
        update={"kind": DemandKind.KNOWN_ZERO, "quantity": Decimal(0), "acceptance_ref": None}
    )
    unknown = rows[-2].model_copy(
        update={"kind": DemandKind.UNKNOWN, "quantity": None, "acceptance_ref": None}
    )
    validated = validate_series(
        manifest,
        rows[:-2] + (unknown, zero),
        tenant_id="demo",
        sku_id="A",
        unit="pcs",
        cutoff=manifest.complete_through,
        now=NOW,
        trusted_reader=True,
    )
    assert validated.values[zero.period] == 0 and validated.values[unknown.period] is None
    report = backtest(
        validated,
        Naive(),
        train_cutoff=START + timedelta(days=13),
        test_end=manifest.complete_through,
    )
    assert report.skipped_unknown_actuals == 1
