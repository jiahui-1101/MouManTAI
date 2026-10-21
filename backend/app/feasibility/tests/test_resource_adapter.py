from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.models import Base
from app.core.reservations import seed_resource_stock
from app.feasibility.production_fixtures import build_production_example
from app.feasibility.resource_adapter import read_resource_summary


def context(tenant):
    return RequestContext(tenant_id=tenant, actor_id='synthetic-reader', actor_role='STAFF',
                          correlation_id='synthetic-read', causation_id=None)


def test_real_core_query_preserves_decimal_reservations_and_resource_versions():
    _, commitment = build_production_example()
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        seed_resource_stock(db, commitment.tenant_id, 'PATTY', '100.125', 'pcs', '60.025', snapshot_version=7)
        seed_resource_stock(db, 'foreign', 'PATTY', '999', 'pcs')
        result = read_resource_summary(db, context(commitment.tenant_id), commitment,
                                       resource_ids=('PATTY', 'MISSING'))
        assert result.status == 'INCOMPLETE'
        assert result.missing_resource_ids == ('MISSING',)
        assert len(result.resources) == 1
        row = result.resources[0]
        assert (row.total_quantity, row.reserved_quantity, row.available_quantity) == (
            Decimal('100.125'), Decimal('60.025'), Decimal('40.100'))
        assert row.resource_version == 7
        assert row.valid_through is None
        assert row.evidence_refs == ()
        assert result.commitment_version == commitment.commitment_version
        assert 'reservation_ownership' in result.unavailable_fields
        assert not hasattr(result, 'snapshot_version')
        assert not db.new and not db.dirty
        with pytest.raises(ValueError, match='tenant'):
            read_resource_summary(db, context('foreign'), commitment, resource_ids=('PATTY',))
        with pytest.raises(ValueError, match='resource'):
            read_resource_summary(db, context(commitment.tenant_id), commitment, resource_ids=())


def test_empty_stock_query_is_unavailable_not_complete_empty_inventory():
    _, commitment = build_production_example()
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        result = read_resource_summary(db, context(commitment.tenant_id), commitment,
                                       resource_ids=('PATTY',))
        assert result.status == 'UNAVAILABLE'
        assert result.resources == ()
        assert result.missing_resource_ids == ('PATTY',)
