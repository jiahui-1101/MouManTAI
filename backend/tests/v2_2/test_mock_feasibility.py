from datetime import UTC, datetime

import pytest
from mock_order_fixtures import mock_snapshot, mock_terms

from app.core.errors import DomainError
from app.orders.mock_feasibility import project_pending_order


def test_pending_projection_reuses_p2_without_persisted_confirmation():
    snapshot = mock_snapshot()
    terms = mock_terms(snapshot.operational.tenant_id)
    projected, result = project_pending_order(
        snapshot, terms, commitment_id="com_order_test", checked_at=datetime.now(UTC)
    )
    assert result.status == "FEASIBLE"
    assert result.evidence_complete
    assert len(snapshot.operational.confirmed_commitments) == 1
    assert len(projected.operational.confirmed_commitments) == 2
    target_rows = [row for row in result.materials.materials if row.commitment_id == "com_order_test"]
    assert target_rows
    assert all(row.shortage == 0 for row in target_rows)


def test_pending_projection_insufficient_stock_fails_closed():
    snapshot = mock_snapshot(stock="100")
    terms = mock_terms(snapshot.operational.tenant_id)
    with pytest.raises(DomainError) as error:
        project_pending_order(snapshot, terms, commitment_id="com_order_test", checked_at=datetime.now(UTC))
    assert error.value.code == "P2_NOT_FEASIBLE"
