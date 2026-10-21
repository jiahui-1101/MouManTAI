import pytest

from app.feasibility.benchmark import rate, run_benchmark, score_labels
from app.feasibility import benchmark


def test_metric_arithmetic_counts_errors_unknowns_and_zero_denominators():
    # Deliberately wrong predictions prove the scorer does not manufacture 100%.
    scored = score_labels(
        feasibility=[('INFEASIBLE', 'FEASIBLE'), ('INFEASIBLE', 'UNKNOWN'), ('FEASIBLE', 'FEASIBLE')],
        impact=[(True, True), (True, False), (False, True), (None, False)],
        stale_predictions=['UNKNOWN', 'FEASIBLE'])
    assert scored['false_feasible'] == rate(1, 2)
    assert scored['impacted_recall'] == rate(1, 2)
    assert scored['false_alert'] == rate(1, 1)
    assert scored['stale_result'] == rate(1, 2)
    assert rate(0, 0)['rate'] is None
    assert scored['unknown_feasibility_count'] == 1
    assert scored['unlabelled_impact_count'] == 1


def test_benchmark_executes_real_calculations_and_preserves_labelled_unknowns():
    report = run_benchmark(iterations=1)
    assert report['scope'] == 'SYNTHETIC_P2_BENCHMARK'
    assert report['metrics']['false_feasible']['numerator'] == 0
    assert report['metrics']['impacted_recall'] == rate(3, 3)
    assert report['metrics']['false_alert']['numerator'] == 0
    assert report['metrics']['stale_result'] == rate(0, 2)
    assert report['latency_ms']['feasibility']['sample_count'] > 0
    assert report['latency_ms']['impact']['sample_count'] == 8
    assert report['observed_impact_unknown_count'] >= 8
    with pytest.raises(ValueError):
        run_benchmark(iterations=0)


def test_stale_metric_detects_a_broken_real_acceptance_guard(monkeypatch):
    monkeypatch.setattr(benchmark, 'require_current_snapshot', lambda *args, **kwargs: None)
    report = run_benchmark(iterations=1)
    # Missing current version is historically FEASIBLE; a broken guard exposes it.
    assert report['metrics']['stale_result'] == rate(1, 2)
