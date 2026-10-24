"""Pure P2 evidence for the projected-target owner review.

These are *confirmed-demand test fixtures*, not a pending-order adapter.
"""

from app.feasibility.inventory import calculate_atp
from app.feasibility.models import OperationalSnapshot
from app.feasibility.tests.test_service import fixture


def test_individually_covered_demands_can_contend_in_one_p2_batch():
    snapshot, _ = fixture()
    data = snapshot.operational.model_dump(exclude_computed_fields=True)
    first = data["confirmed_commitments"][0]
    first["lines"][0]["quantity"] = "60"
    second = {
        **first,
        "commitment_id": "synthetic-second-confirmed",
        "lines": ({**first["lines"][0], "line_id": "synthetic-second-line"},),
    }

    def evaluate_rows(rows):
        local = OperationalSnapshot.model_validate({**data, "confirmed_commitments": rows})
        before = local.model_dump_json()
        result = calculate_atp(local, tenant_id=local.tenant_id, as_of=snapshot.as_of)
        assert local.model_dump_json() == before
        return result

    assert evaluate_rows((first,)).status == "COVERED"
    assert evaluate_rows((second,)).status == "COVERED"
    together = evaluate_rows((first, second))
    assert together.status == "SHORTAGE"
    assert any(row.shortage > 0 for row in together.materials)
    assert snapshot.operational.confirmed_commitments[0].lines[0].quantity == 100
