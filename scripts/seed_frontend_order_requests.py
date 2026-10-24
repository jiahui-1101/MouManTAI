"""Seed controlled synthetic OrderRequests through existing HTTP admin routes.

Run only against a disposable isolated demo tenant/database. Never used by the browser.
"""
from __future__ import annotations

import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

backend_path = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(backend_path))
sys.path.insert(0, str(backend_path / "tests" / "v2_2"))
from mock_order_fixtures import mock_terms  # noqa: E402


def main() -> None:
    base = os.environ.get("MOUMANTAI_LOCAL_API_BASE", "http://127.0.0.1:18000")
    tenant = os.environ["MOUMANTAI_ISOLATED_E2E_TENANT_ID"]
    prefix = os.environ.get("MOUMANTAI_E2E_REQUEST_PREFIX", "fe_bff")
    outcome = os.environ.get("MOUMANTAI_E2E_RESERVATION_OUTCOME", "NORMAL")
    if outcome not in {"NORMAL", "UNKNOWN"}:
        raise ValueError("Only NORMAL or UNKNOWN synthetic outcomes are supported")
    headers = {
        "X-Tenant-ID": tenant,
        "X-Actor-ID": os.environ["MOUMANTAI_ISOLATED_E2E_MANAGER_ID"],
        "X-Isolated-E2E-Key": os.environ["MOUMANTAI_ISOLATED_E2E_KEY"],
    }
    now = datetime.now(UTC)
    with httpx.Client(base_url=base, timeout=15) as client:
        resources = client.post("/v1/backend-v2/mock-orbyte/resources", headers=headers,
                                json={"stock_quantity": "150", "next_reservation_outcome": outcome})
        if resources.status_code != 409 or resources.json().get("code") != "MOCK_RESOURCE_ALREADY_CONFIGURED":
            resources.raise_for_status()
        for request_id in (f"{prefix}_accept", f"{prefix}_reject"):
            terms = mock_terms(tenant, request_id=request_id)
            source_id = f"source_{request_id}"
            inquiry = client.post("/v1/backend-v2/mock-orbyte/inquiries", headers=headers, json={
                "source_id": source_id, "source_version": 1, "terms": terms.model_dump(mode="json"),
                "customer_request_ref": "evidence_order", "price_disclosure_ref": "evidence_disclosure",
                "observed_at": (now - timedelta(minutes=1)).isoformat(),
                "valid_through": (now + timedelta(hours=1)).isoformat(),
            })
            inquiry.raise_for_status()
            imported = client.post("/v1/backend-v2/order-requests/import-mock", headers=headers,
                                   json={"source_id": source_id, "expected_source_version": 1})
            imported.raise_for_status()
            print(f"{request_id}: {imported.json()['decision_status']}")


if __name__ == "__main__":
    main()
