import json

import pytest

from app.context.product_catalog import load_product_catalog
from app.context.repository import PersistenceUnavailable
from app.context.review_catalog import approved_review_products


def test_trusted_configuration_is_tenant_scoped_and_not_a_stock_conversion(tmp_path, monkeypatch):
    path = tmp_path / 'catalog.json'
    path.write_text(json.dumps([
        dict(tenant_id='a', sku='A-COOKIE', aliases=['cookies'], unit='box', source_ref='master:approved:a:1'),
        dict(tenant_id='b', sku='B-BREAD', aliases=['bread'], unit='pcs', source_ref='master:approved:b:1'),
    ]))
    monkeypatch.setenv('P1_PRODUCT_CATALOG_PATH', str(path))
    products = load_product_catalog()
    assert approved_review_products('a', products) == [{'sku': 'A-COOKIE', 'unit': 'box'}]
    assert approved_review_products('other', products) == []


@pytest.mark.parametrize('value', [[], {}, [{'tenant_id': 'a', 'sku': 'COOKIE', 'unit': 'box', 'aliases': ['cookies']}],
                                  [{'tenant_id': 'a', 'sku': 'COOKIE', 'unit': 'box', 'aliases': [''], 'source_ref': 'master:1'}]])
def test_invalid_catalog_never_silently_falls_back(tmp_path, monkeypatch, value):
    path = tmp_path / 'catalog.json'
    path.write_text(json.dumps(value))
    monkeypatch.setenv('P1_PRODUCT_CATALOG_PATH', str(path))
    with pytest.raises(PersistenceUnavailable):
        load_product_catalog()


def test_production_without_catalog_fails_closed(monkeypatch):
    monkeypatch.delenv('P1_PRODUCT_CATALOG_PATH', raising=False)
    monkeypatch.setenv('ENVIRONMENT', 'production')
    with pytest.raises(PersistenceUnavailable):
        load_product_catalog()
