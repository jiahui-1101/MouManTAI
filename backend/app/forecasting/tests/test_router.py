"""Unit tests for the forecasting HTTP endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_get_forecasts_synthetic_default():
    response = client.get("/v1/forecasts")
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "FORECAST_AVAILABLE"
    assert data["evidence_tier"] == "DEMO-ONLY"
    assert data["integration_mode"] == "SYNTHETIC"
    assert data["is_synthetic"] is True
    assert data["demo_badge"] is True
    assert len(data["historical_points"]) == 21
    assert len(data["forecast_points"]) == 7
    assert data["horizon"] == 7
    assert "DEMO-ONLY" in data["disclaimer"]

    # Verify 4 risk families are represented in advisories
    families = {adv["family"] for adv in data["advisories"]}
    assert "DEMAND" in families
    assert "STOCKOUT_OR_EXPIRY" in families
    assert "SUPPLIER_DELAY" in families
    assert "CAPACITY_OR_DEADLINE" in families

    # Verify each advisory is non-operational
    for adv in data["advisories"]:
        assert adv["operational_action_authorized"] is False
        assert adv["required_human_review"] is True


def test_get_forecasts_model_selection():
    for model in ["moving_average", "seasonal_naive", "naive"]:
        response = client.get(f"/v1/forecasts?model={model}&horizon=14")
        assert response.status_code == 200
        data = response.json()
        assert len(data["forecast_points"]) == 14
        assert data["horizon"] == 14


def test_get_forecasts_db_mode_insufficient():
    # In pure DB mode without seeded history, returns typed INSUFFICIENT_HISTORY
    response = client.get("/v1/forecasts?mode=db&sku_id=SKU-NONEXISTENT")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "INSUFFICIENT_HISTORY"
    assert len(data["forecast_points"]) == 0
    assert data["advisories"][0]["status"] == "INSUFFICIENT_HISTORY"


def test_list_skus():
    response = client.get("/v1/forecasts/skus")
    assert response.status_code == 200
    skus = response.json()
    assert len(skus) >= 1
    assert any(s["sku_id"] == "SKU-PROD-A" for s in skus)
