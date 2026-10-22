"""Real P1 HTTP boundary; no model calls or historical data writes."""
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.context.deterministic_extraction import ProductAlias
from app.context.hosting import mount_p1_ingestion
from app.context.ingestion_schemas import DevelopmentContext
from app.context.order_context_schemas import RequestedItem
from app.context.postgres_repository import PostgresMessageRepository
from app.context.tests.test_core_publisher import make_valid_context


CATALOG = (ProductAlias('judge-a', 'BURGER', ('burger',), 'pcs'),
           ProductAlias('judge-b', 'PRIVATE-SKU', ('private',), 'box'))


def client_for(repo, tenant='judge-a'):
    app = FastAPI()
    mount_p1_ingestion(app, repository_provider=lambda: repo,
                      tenant_provider=lambda: DevelopmentContext(tenant_id=tenant))
    return TestClient(app)


def repo_stub():
    repo = Mock()
    repo.catalog = CATALOG
    repo.get_order_context.return_value = make_valid_context('judge-a', 'judge-context')
    return repo


def test_catalog_is_tenant_scoped_and_contains_only_canonical_pairs():
    response = client_for(repo_stub()).get('/v1/contexts/catalog')
    assert response.status_code == 200
    assert response.json() == [{'sku': 'BURGER', 'unit': 'pcs'}]


def test_known_product_mapping_reaches_existing_review_service():
    repo = repo_stub()
    repo.apply_context_review.return_value = repo.get_order_context.return_value
    response = client_for(repo).post('/v1/contexts/judge-context/review', json={
        'expected_context_version': 1, 'action': 'EDIT_FIELD', 'field_edits': {'requested_items': [
            {'sku': 'BURGER', 'quantity': '12', 'unit': 'pcs'}]}})
    assert response.status_code == 200
    repo.apply_context_review.assert_called_once()


@pytest.mark.parametrize('items', [
    [{'sku': 'cookies', 'quantity': '25', 'unit': 'box'}],
    [{'sku': 'BURGER', 'quantity': '12', 'unit': 'box'}],
    [{'sku': 'PRIVATE-SKU', 'quantity': '25', 'unit': 'box'}],
    [{'sku': 'BURGER', 'quantity': '12', 'unit': 'pcs'},
     {'sku': 'cookies', 'quantity': '25', 'unit': 'box'}],
])
def test_edit_unknown_incompatible_or_mixed_items_is_rejected_without_mutation(items):
    repo = repo_stub()
    response = client_for(repo).post('/v1/contexts/judge-context/review', json={
        'expected_context_version': 1, 'action': 'EDIT_FIELD', 'field_edits': {'requested_items': items}})
    assert response.status_code == 422
    repo.apply_context_review.assert_not_called()


def test_accept_unknown_item_and_publish_cannot_bypass_catalog():
    repo = repo_stub()
    repo.get_order_context.return_value.requested_items = [RequestedItem(sku='cookies', quantity='25', unit='box')]
    client = client_for(repo)
    assert client.post('/v1/contexts/judge-context/review', json={
        'expected_context_version': 1, 'action': 'ACCEPT_EXTRACTION'}).status_code == 422
    assert client.post('/v1/contexts/judge-context/publish').status_code == 422
    repo.apply_context_review.assert_not_called()


def test_patch_cannot_bypass_catalog_and_unresolved_remains_available():
    repo = repo_stub()
    repo.apply_context_review.return_value = repo.get_order_context.return_value
    client = client_for(repo)
    assert client.patch('/v1/contexts/judge-context', json={'expected_context_version': 1,
        'requested_items': [{'sku': 'cookies', 'quantity': '25', 'unit': 'box'}]}).status_code == 422
    repo.update_order_context.assert_not_called()
    assert client.post('/v1/contexts/judge-context/review', json={
        'expected_context_version': 1, 'action': 'MARK_UNRESOLVED'}).status_code == 200


def test_mapping_known_product_persists_across_repository_refresh(pg_engine):
    repo = PostgresMessageRepository(pg_engine, catalog=CATALOG)
    ctx = make_valid_context('judge-a', 'judge-context')
    ctx.requested_items = [RequestedItem(sku='cookies', quantity='25', unit='box')]
    ctx.status = 'UNRESOLVED'
    ctx.field_evidence = {'sku': [{'evidence_id': 'cookie-source', 'quote': 'cookies', 'method': 'MODEL',
        'normalization_metadata': {'domain_supported': 'false', 'group_id': 'g1'}}]}
    repo.save_order_context(ctx)
    client = client_for(repo)
    assert client.post('/v1/contexts/judge-context/review', json={
        'expected_context_version': 1, 'action': 'ACCEPT_EXTRACTION'}).status_code == 422
    assert repo.get_order_context('judge-a', ctx.context_id).context_version == 1
    assert repo.list_context_reviews('judge-a', ctx.context_id) == []
    assert client.post('/v1/contexts/judge-context/review', json={'expected_context_version': 1,
        'action': 'EDIT_FIELD', 'field_edits': {'requested_items': [
            {'sku': 'BURGER', 'quantity': '25', 'unit': 'pcs'}]},
        'note': 'Synthetic staff-confirmed replacement and quantity; not a box-to-piece conversion',
    }).status_code == 200
    refreshed = PostgresMessageRepository(pg_engine, catalog=CATALOG).get_order_context('judge-a', ctx.context_id)
    assert refreshed.context_version == 2
    assert refreshed.requested_items[0].sku == 'BURGER'
    assert ctx.requested_items[0].sku == 'cookies'
    assert refreshed.field_evidence['sku'] == ctx.field_evidence['sku']
    assert len(repo.list_context_reviews('judge-a', ctx.context_id)) == 1
