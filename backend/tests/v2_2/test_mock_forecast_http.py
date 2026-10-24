"""Registered Mock demand source to real forecast, backtest and risk APIs."""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select

from app.core.models import OutboxEventRecord
from app.forecasting.mock_models import MockForecastAuditRecord, MockForecastDatasetRecord

KEY = "synthetic-test-key-" + "a" * 32
HEADERS = {"X-Tenant-ID": "tenant_001", "X-Actor-ID": "manager_v22",
           "X-Isolated-E2E-Key": KEY}
BASE = "/v1/backend-v2/mock-forecasts/datasets"


def isolated(monkeypatch):
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E", "1")
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E_KEY", KEY)
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E_MANAGER_ID", "manager_v22")
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E_TENANT_ID", "tenant_001")


def dataset(*, dataset_id="demand_batch_1", stale=False, complete=True):
    now = datetime.now(UTC)
    start = (now - timedelta(days=30 if stale else 21)).date()
    end = start + timedelta(days=20)
    watermark = now - timedelta(days=8 if stale else 0, minutes=1)
    observations = []
    for i in range(21):
        period = start + timedelta(days=i)
        observations.append({
            "tenant_id": "tenant_001", "sku_id": "SKU-A",
            "observation_id": f"mock-day-{i}", "observation_version": 1,
            "period": period.isoformat(), "quantity": str(i % 7 + 1),
            "unit": "pcs", "kind": "ACCEPTED",
            "source_event_ref": f"synthetic://order/{i}",
            "acceptance_ref": f"synthetic://acceptance/{i}",
            "evidence_ref": f"synthetic://history/{i}",
            "source_version": "v1",
            "recorded_at": (datetime.combine(period, datetime.min.time(), UTC)
                            + timedelta(hours=12)).isoformat(),
            "business_timezone": "Asia/Singapore",
            "evidence_tier": "DEMO-ONLY", "integration_mode": "MOCK",
        })
    return {
        "dataset_id": dataset_id, "sku_id": "SKU-A", "unit": "pcs",
        "manifest": {
            "tenant_id": "tenant_001", "source_dataset_id": dataset_id,
            "source_snapshot_id": "mock-snapshot-1", "source_snapshot_version": "v1",
            "source_system": "MOCK_ORBYTE", "integration_mode": "MOCK",
            "evidence_tier": "DEMO-ONLY", "captured_at": now.isoformat(),
            "complete_through": end.isoformat(),
            "historical_window_start": start.isoformat(),
            "historical_window_end": end.isoformat(),
            "source_watermark": watermark.isoformat(),
            "pagination_complete": complete, "source_population_complete": True,
            "input_version": "v1", "missing_source_ids": [],
            "evidence_refs": ["synthetic://demand-history"],
            "reader_attestation": "untrusted-client-claim",
        },
        "observations": observations,
    }


def test_mock_forecast_baseline_backtest_risk_and_persistence(client, session, monkeypatch):
    isolated(monkeypatch)
    source = dataset()
    seeded = client.post(BASE, headers=HEADERS, json=source)
    assert seeded.status_code == 201, seeded.text
    assert seeded.json()["manifest"]["reader_attestation"] == "synthetic://persisted/demand_batch_1"
    assert seeded.json()["evidence_tier"] == "DEMO-ONLY"
    assert client.get(BASE, headers=HEADERS).json()[0]["dataset_id"] == "demand_batch_1"
    assert client.get(BASE + "/demand_batch_1", headers=HEADERS).status_code == 200
    assert client.post(BASE, headers=HEADERS, json=source).status_code == 201
    baseline = client.get(BASE + "/demand_batch_1/baseline?horizon=3", headers=HEADERS)
    assert baseline.status_code == 200, baseline.text
    body = baseline.json()
    assert body["run"]["status"] == "FORECAST_AVAILABLE"
    assert body["run"]["model_name"] == "MOVING_AVERAGE"
    assert len(body["run"]["points"]) == 3
    assert body["operational_action_authorized"] is False
    assert len(body["alerts"]) == 4
    assert all(not alert["operational_action_authorized"] for alert in body["alerts"])
    assert body["alerts"][1]["status"] == "UNKNOWN"
    train_cutoff = (datetime.now(UTC) - timedelta(days=8)).date().isoformat()
    backtest = client.get(BASE + f"/demand_batch_1/backtest?train_cutoff={train_cutoff}",
                          headers=HEADERS)
    assert backtest.status_code == 200, backtest.text
    reports = backtest.json()["reports"]
    assert len(reports) == 3
    assert all(report["evidence_tier"] == "DEMO-ONLY" for report in reports)
    assert backtest.json()["real_world_skill_established"] is False
    session.expire_all()
    assert session.scalar(select(func.count()).select_from(MockForecastDatasetRecord)) == 1
    assert session.scalar(select(func.count()).select_from(MockForecastAuditRecord)) == 1
    assert session.scalar(select(func.count()).select_from(OutboxEventRecord)) == 1


def test_mock_forecast_source_gaps_are_not_forecast_claims(client, monkeypatch):
    isolated(monkeypatch)
    source = dataset(stale=True, complete=False)
    assert client.post(BASE, headers=HEADERS, json=source).status_code == 201
    baseline = client.get(BASE + "/demand_batch_1/baseline", headers=HEADERS)
    assert baseline.status_code == 200, baseline.text
    assert baseline.json()["run"]["points"] == []
    assert baseline.json()["run"]["status"] == "SOURCE_INCOMPLETE"
    train_cutoff = (date.fromisoformat(source["manifest"]["complete_through"])
                    - timedelta(days=7)).isoformat()
    backtest = client.get(BASE + f"/demand_batch_1/backtest?train_cutoff={train_cutoff}",
                          headers=HEADERS)
    assert backtest.status_code == 200
    assert backtest.json()["reports"] == []
    assert "SOURCE_INCOMPLETE" in backtest.json()["diagnostics"]


def test_mock_forecast_identity_and_synthetic_boundary(client, monkeypatch):
    isolated(monkeypatch)
    assert client.get(BASE, headers=HEADERS | {"X-Actor-ID": "staff_01"}).status_code == 403
    assert client.get(BASE, headers=HEADERS | {"X-Tenant-ID": "other"}).status_code == 403
    bad = dataset()
    bad["observations"][0]["acceptance_ref"] = "https://real-order.test/receipt"
    assert client.post(BASE, headers=HEADERS, json=bad).status_code == 422
    bad = dataset()
    bad["manifest"]["evidence_tier"] = "LIVE"
    assert client.post(BASE, headers=HEADERS, json=bad).status_code == 422
    assert client.get(BASE + "/missing/baseline", headers=HEADERS).status_code == 404
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert client.get(BASE, headers=HEADERS).status_code == 503


def test_mock_forecast_registered_openapi(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "post" in paths[BASE]
    assert "get" in paths[BASE + "/{dataset_id}/baseline"]
    assert "get" in paths[BASE + "/{dataset_id}/backtest"]
