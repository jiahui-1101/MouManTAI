"""B1 read-only boundary checks using the existing P2 fixture and evaluator."""

from datetime import timedelta

import pytest
from app.feasibility.readiness import assess_operational_readiness
from app.feasibility.tests.test_service import changed, competing_snapshot, fixture


def assess(snapshot=None, commitment=None, *, at=None, tenant_id=None):
    original, target = fixture()
    snapshot = original if snapshot is None else snapshot
    commitment = target if commitment is None else commitment
    return assess_operational_readiness(
        tenant_id=target.tenant_id if tenant_id is None else tenant_id,
        commitment=commitment,
        snapshot=snapshot,
        checked_at=snapshot.as_of if at is None else at,
    )


def test_current_snapshot_is_only_ready_for_review_and_deterministic():
    snapshot, commitment = fixture()
    before = (snapshot.model_dump_json(), commitment.model_dump_json())
    result = assess(snapshot, commitment)
    assert result.status == "READY_FOR_REVIEW"
    assert result.feasibility_status == "FEASIBLE"
    assert result.assessment_id and result.evidence_refs
    assert result.snapshot_id == snapshot.operational.snapshot_id
    assert result.snapshot_version == snapshot.operational.snapshot_version
    assert result.reservation_authorized is False
    assert assess(snapshot, commitment) == result
    assert before == (snapshot.model_dump_json(), commitment.model_dump_json())


@pytest.mark.parametrize(
    "case,code",
    [
        ("missing", "SNAPSHOT_UNAVAILABLE"),
        ("no_current_token", "CURRENT_VERSION_UNAVAILABLE"),
        ("version_conflict", "SNAPSHOT_VERSION_CONFLICT"),
        ("tenant", "TENANT_MISMATCH"),
        ("future", "SNAPSHOT_FROM_FUTURE"),
        ("provenance", "SOURCE_PROVENANCE_INCOMPLETE"),
    ],
)
def test_snapshot_authority_fails_closed(case, code):
    snapshot, commitment = fixture()
    if case == "missing":
        result = assess_operational_readiness(
            tenant_id=commitment.tenant_id,
            commitment=commitment,
            snapshot=None,
            checked_at=snapshot.as_of,
        )
    else:
        if case == "no_current_token":
            snapshot = changed(snapshot, lambda d: d.update(current_snapshot_version=None))
        elif case == "version_conflict":
            snapshot = changed(snapshot, lambda d: d.update(current_snapshot_version=2))
        elif case == "provenance":
            snapshot = changed(
                snapshot, lambda d: d["operational"]["sources"][0].update(evidence_refs=())
            )
        result = assess(
            snapshot,
            commitment,
            tenant_id="another-tenant" if case == "tenant" else None,
            at=snapshot.operational.captured_at - timedelta(seconds=1)
            if case == "future"
            else None,
        )
    assert result.status == "UNKNOWN"
    assert result.reason_codes == (code,)
    assert result.assessment_id is None
    assert result.reservation_authorized is False


def test_stale_sources_and_unknown_capacity_never_become_ready():
    snapshot, commitment = fixture()
    stale = assess(snapshot, commitment, at=snapshot.as_of + timedelta(days=5))
    assert stale.status == "UNKNOWN"
    assert stale.feasibility_status == "UNKNOWN"
    missing_jobs = changed(snapshot, lambda d: d["production"].update(jobs=None))
    assert assess(missing_jobs, commitment).status == "UNKNOWN"
    assert (
        assess(changed(snapshot, lambda d: d.update(production=None)), commitment).status
        == "UNKNOWN"
    )


def test_shortage_and_competition_reuse_p2_outcomes():
    snapshot, commitment = fixture()
    shortage = changed(
        snapshot, lambda d: d["operational"]["inventory_lots"][0].update(quantity="70")
    )
    result = assess(shortage, commitment)
    assert result.status == "BLOCKED"
    assert "MATERIAL_SHORTAGE" in result.reason_codes
    competing, target = competing_snapshot()
    contested = assess(competing, target)
    assert contested.status == "UNKNOWN"
    assert "ALLOCATION_DEPENDENT_MATERIAL_SHORTAGE" in contested.reason_codes


def test_unsupported_multiline_and_missing_target_fail_closed():
    snapshot, commitment = fixture()

    def add_line(data):
        target = data["operational"]["confirmed_commitments"][0]
        target["lines"] = (*target["lines"], {**target["lines"][0], "line_id": "second"})

    multi = changed(snapshot, add_line)
    assert assess(multi, commitment).reason_codes == ("UNSUPPORTED_OR_INCONSISTENT_INPUT",)
    absent = changed(snapshot, lambda d: d["operational"].update(confirmed_commitments=()))
    assert assess(absent, commitment).status == "UNKNOWN"


def test_receipt_or_client_claim_is_not_an_input_or_reservation_authority():
    snapshot, commitment = fixture()
    with pytest.raises(TypeError):
        assess_operational_readiness(
            tenant_id=commitment.tenant_id,
            commitment=commitment,
            snapshot=snapshot,
            checked_at=snapshot.as_of,
            reservation_receipt={"status": "CONFIRMED"},
        )
    assert assess(snapshot, commitment).reservation_authorized is False


def test_naive_clock_rejected():
    snapshot, commitment = fixture()
    with pytest.raises(ValueError, match="offset-aware"):
        assess(snapshot, commitment, at=snapshot.as_of.replace(tzinfo=None))
