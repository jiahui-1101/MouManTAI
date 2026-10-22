from app.context.postgres_repository import PostgresMessageRepository
from app.context.tests.test_core_publisher import make_valid_context
from app.context.tests.test_review_catalog_boundary import CATALOG, client_for


def create_context(pg_engine, *, verified=True, groups=1):
    repo = PostgresMessageRepository(pg_engine, catalog=CATALOG)
    ctx = make_valid_context('judge-a', 'mapping-readiness')
    ctx.requested_items = []
    ctx.missing_fields = ['requested_items', 'sku_mapping', 'unit']
    ctx.status = 'INFORMATION_PARTIAL'
    if not verified:
        ctx.customer_id = None
        ctx.customer_identity_status = 'UNVERIFIED'
    ctx.field_evidence = {'sku': [{'message_id': 'msg_001', 'quote': 'cookies',
        'normalization_metadata': {'group_id': f'g{i}'}} for i in range(groups)]}
    repo.save_order_context(ctx)
    return repo, client_for(repo)


def edit(client, count=1, extra=None):
    return client.post('/v1/contexts/mapping-readiness/review', json={
        'expected_context_version': 1, 'action': 'EDIT_FIELD', 'field_edits': {
            'requested_items': [{'sku': 'BURGER', 'quantity': '12', 'unit': 'pcs'} for _ in range(count)],
            **(extra or {}),
        }, 'note': 'Staff verified replacement and quantities; no packaging conversion assumed'})


def test_completed_human_mapping_clears_obsolete_structural_gaps_and_persists(pg_engine):
    repo, client = create_context(pg_engine)
    result = edit(client)
    assert result.status_code == 200
    assert result.json()['missing_fields'] == []
    assert result.json()['status'] == 'INFORMATION_READY'
    assert repo.get_order_context('judge-a', 'mapping-readiness').context_version == 2
    assert repo.list_context_reviews('judge-a', 'mapping-readiness')[0].field_changes['missing_fields']['new'] == []


def test_client_cannot_clear_missing_identity_by_submitting_empty_flags(pg_engine):
    _, client = create_context(pg_engine, verified=False)
    result = edit(client, extra={'missing_fields': []})
    assert result.status_code == 200
    assert 'customer_identity' in result.json()['missing_fields']
    assert result.json()['status'] != 'INFORMATION_READY'


def test_mapping_first_item_does_not_erase_unknown_second_item(pg_engine):
    _, client = create_context(pg_engine, groups=2)
    result = edit(client)
    assert result.status_code == 200
    assert 'sku_mapping' in result.json()['missing_fields']
    assert result.json()['status'] != 'INFORMATION_READY'


def test_mapping_all_items_can_resolve_each_source_group(pg_engine):
    _, client = create_context(pg_engine, groups=2)
    result = edit(client, count=2)
    assert result.status_code == 200
    assert result.json()['status'] == 'INFORMATION_READY'


def test_ready_context_is_downgraded_when_identity_becomes_unverified(pg_engine):
    repo, client = create_context(pg_engine)
    assert edit(client).json()['status'] == 'INFORMATION_READY'
    result = client.post('/v1/contexts/mapping-readiness/review', json={
        'expected_context_version': 2, 'action': 'EDIT_FIELD',
        'field_edits': {'customer_identity_status': 'UNVERIFIED', 'missing_fields': []}})
    assert result.status_code == 200
    assert result.json()['status'] == 'INFORMATION_PARTIAL'
    assert 'customer_identity' in result.json()['missing_fields']
