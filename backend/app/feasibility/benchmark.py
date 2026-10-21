"""Reproducible independent synthetic metrics, not production accuracy.

Run from backend: python -B -m app.feasibility.benchmark --iterations 10
Labels are authored from scenario facts in benchmark_labels.json, never copied
from predictions. Repetitions measure latency, not independent dataset size.
"""

import argparse
import json
import math
from pathlib import Path
from statistics import median
from time import perf_counter_ns

from app.core.errors import DomainError

from .pipeline_fixtures import build_pipeline_example
from .currentness import require_current_snapshot
from .production import EvaluationSnapshot
from .production_fixtures import build_production_example
from .service import evaluate
from .supplier_pipeline import recalculate_supplier_delay


def rate(numerator: int, denominator: int) -> dict:
    return dict(numerator=numerator, denominator=denominator,
                rate=None if denominator == 0 else numerator / denominator)


def score_labels(*, feasibility, impact, stale_predictions) -> dict:
    infeasible = [(truth, prediction) for truth, prediction in feasibility if truth == 'INFEASIBLE']
    affected = [(truth, prediction) for truth, prediction in impact if truth is True]
    unaffected = [(truth, prediction) for truth, prediction in impact if truth is False]
    return dict(
        false_feasible=rate(sum(p == 'FEASIBLE' for _, p in infeasible), len(infeasible)),
        impacted_recall=rate(sum(p for _, p in affected), len(affected)),
        false_alert=rate(sum(p for _, p in unaffected), len(unaffected)),
        stale_result=rate(sum(p == 'FEASIBLE' for p in stale_predictions), len(stale_predictions)),
        unknown_feasibility_count=sum(p == 'UNKNOWN' for _, p in feasibility),
        unlabelled_impact_count=sum(t is None for t, _ in impact))


def _latency(samples):
    return dict(sample_count=len(samples), median=median(samples),
                p95=sorted(samples)[math.ceil(len(samples) * .95) - 1],
                unit='milliseconds', includes='calculation and boundary validation; excludes fixture construction, I/O and persistence')


def run_benchmark(*, iterations: int = 10) -> dict:
    if iterations < 1:
        raise ValueError('positive benchmark iteration count required')
    labels = json.loads(Path(__file__).with_name('benchmark_labels.json').read_text(encoding='utf-8'))
    baseline, commitment = build_production_example()
    cases = {}
    for name in labels['feasibility']:
        data = baseline.model_dump(exclude_computed_fields=True)
        if name in {'shortage', 'empty_stock'}:
            for lot in data['operational']['inventory_lots']:
                if lot['sku_id'] == 'PATTY':
                    lot['quantity'] = '70'
            if name == 'empty_stock':
                # The domain forbids zero-quantity lots; absence in an evidenced
                # complete inventory ledger represents no stock.
                data['operational']['inventory_lots'] = tuple(
                    lot for lot in data['operational']['inventory_lots'] if lot['sku_id'] != 'PATTY')
        if name == 'missing_production':
            data['production'] = None
        if name == 'stale_version':
            data['current_snapshot_version'] = 2
        if name == 'missing_current_version':
            data['current_snapshot_version'] = None
        cases[name] = EvaluationSnapshot.model_validate(data)
    impact_inputs = {name: build_pipeline_example(two_affected=name == 'two_affected',
                                                 mode='complete' if name == 'two_affected' else name)
                     for name in labels['impact']}
    # Untimed warmup; no prediction is ever used to generate a label.
    evaluate(baseline, None, commitment)
    recalculate_supplier_delay(impact_inputs['complete'], tenant_id=commitment.tenant_id)
    feas_results, impact_results, feas_times, impact_times = {}, {}, [], []
    for _ in range(iterations):
        for name, snapshot in cases.items():
            start = perf_counter_ns()
            result = evaluate(snapshot, None, commitment)
            feas_times.append((perf_counter_ns() - start) / 1_000_000)
            feas_results[name] = result
        for name, inputs in impact_inputs.items():
            start = perf_counter_ns()
            result = recalculate_supplier_delay(inputs, tenant_id=commitment.tenant_id)
            impact_times.append((perf_counter_ns() - start) / 1_000_000)
            impact_results[name] = result
    # The pure historical evaluator deliberately permits absent current authority.
    # The current-result acceptance boundary must reject it; benchmark separately.
    current_predictions = []
    current_guard_errors = {}
    for name in ('stale_version', 'missing_current_version'):
        try:
            require_current_snapshot(cases[name])
        except DomainError as error:
            current_predictions.append('UNKNOWN')
            current_guard_errors[name] = dict(status=error.status_code, code=error.code)
        else:
            current_predictions.append(feas_results[name].status.value)
    feasible_labels = [(labels['feasibility'][name]['status'], result.status.value)
                       for name, result in feas_results.items() if name != 'missing_current_version']
    impact_labels = [(expected, cid in impact_results[name].confirmed_impacted_commitment_ids)
                     for name, expected_rows in labels['impact'].items()
                     for cid, expected in expected_rows.items() if cid != 'reason']
    return dict(scope='SYNTHETIC_P2_BENCHMARK',
                dataset=dict(feasibility_cases=len(cases), impact_scenarios=len(impact_inputs),
                             impact_commitment_observations=len(impact_labels),
                             labelled_impact_observations=sum(t is not None for t, _ in impact_labels),
                             latency_repetitions=iterations, label_file='benchmark_labels.json'),
                metrics=score_labels(feasibility=feasible_labels, impact=impact_labels,
                                     stale_predictions=current_predictions),
                latency_ms=dict(feasibility=_latency(feas_times), impact=_latency(impact_times)),
                feasibility_outputs={name: r.status.value for name, r in feas_results.items()},
                impact_outputs={name: {r.commitment_id: r.classification.value for r in result.impacts}
                                for name, result in impact_results.items()},
                observed_impact_unknown_count=sum(r.classification == 'UNKNOWN' for impact in impact_results.values()
                                                  for r in impact.impacts),
                stale_current_acceptance=current_predictions,
                current_guard_errors=current_guard_errors,
                limitations=['Small manually labelled synthetic dataset, not live SME accuracy.',
                             'Null impact labels excluded from recall/false-alert denominators; UNKNOWN outputs retained.',
                             'UNKNOWN on a labelled true impact counts as missed recall; it is never a false FEASIBLE.',
                             'Stale rate exercises the public assessment current-version guard, not DB races or durable writes.',
                             'Pure historical evaluation can be FEASIBLE without current authority; it must not be accepted as current.',
                             'Production auth, source trust, transaction, network and persistence latency not measured.'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iterations', type=int, default=10)
    print(json.dumps(run_benchmark(iterations=parser.parse_args().iterations), indent=2))
