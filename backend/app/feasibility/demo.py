"""Run: python -B -m app.feasibility.demo (from backend/). Synthetic only."""

import json

from .history import SyntheticHistoryRepository
from .pipeline_fixtures import build_pipeline_example
from .supplier_pipeline import recalculate_supplier_delay


def run_demo() -> dict:
    scenarios = {}
    for mode in ('complete', 'material_only', 'missing_supplier', 'stale_inventory',
                 'stale_production', 'confounded', 'preexisting', 'two_affected'):
        inputs = build_pipeline_example(two_affected=mode == 'two_affected',
                                        mode='complete' if mode == 'two_affected' else mode)
        result = recalculate_supplier_delay(inputs, tenant_id=inputs.request.change.tenant_id)
        history = SyntheticHistoryRepository()
        intents = history.append_impact(inputs, result)
        replay = history.append_impact(inputs, recalculate_supplier_delay(
            inputs, tenant_id=inputs.request.change.tenant_id))
        scenarios[mode] = dict(input=inputs.request.model_dump(mode='json'),
                               previous_eta=inputs.previous_eta.isoformat(),
                               updated_eta=inputs.updated_eta.isoformat(),
                               before_snapshot_id=inputs.before_snapshot_id,
                               after_snapshot_id=inputs.after_snapshot_id,
                               candidate_commitment_ids=result.candidate_commitment_ids,
                               confirmed_impacted_commitment_ids=result.confirmed_impacted_commitment_ids,
                               verified_unaffected_commitment_ids=result.verified_unaffected_commitment_ids,
                               impacts=[r.model_dump(mode='json') for r in result.impacts],
                               first_intent_count=len(intents), replay_new_intent_count=len(replay))
    return dict(scope='SYNTHETIC_P2_PIPELINE', persistence='process-local reference only; nothing published',
                scenarios=scenarios)


if __name__ == '__main__':
    print(json.dumps(run_demo(), indent=2))
