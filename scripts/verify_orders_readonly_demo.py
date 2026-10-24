"""Read-only runtime smoke: no credentials, seeds, mutations or channel sends."""
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BASE = "http://127.0.0.1:8001"


def read(path, *, actor="user_owner_01", tenant="tenant_demo_01", expected=200):
    request = Request(BASE + path, headers={"X-Tenant-ID": tenant, "X-Actor-ID": actor})
    try:
        with urlopen(request, timeout=15) as response:
            assert response.status == expected
            return json.load(response)
    except HTTPError as exc:
        assert exc.code == expected, (path, exc.code)
        return json.load(exc)


def main():
    assert read("/health")["status"] == "ok"
    queue = read("/v1/demo/orders")
    assert queue["coverage"] == "partial" and len(queue["orders"]) == 5
    statuses = {}
    for order in queue["orders"]:
        detail = read("/v1/demo/orders/" + order["order_id"])
        assert detail["order"] == order
        assert detail["related_commitment"]["commitment_id"] == order["commitment_id"]
        assert detail["order"]["lifecycle_status"] == "UNKNOWN"
        statuses[order["order_id"]] = detail["assessment_availability"]
    calendar = read("/v1/demo/orders/planning/calendar?from_date=2026-10-01&to_exclusive=2026-11-01&time_zone=Asia%2FKuala_Lumpur")
    assert calendar["orders"] == queue["orders"]
    for actor in ("user_manager_01", "user_staff_01"):
        assert read("/v1/demo/orders", actor=actor)["actor_id"] == actor
    for path in ("/v1/demo/orders", "/v1/demo/orders/ord_hero_001",
                 "/v1/demo/orders/planning/calendar?from_date=2026-10-01&to_exclusive=2026-11-01"):
        assert "ord_hero_001" not in str(read(path, tenant="other", expected=403))
        assert "ord_hero_001" not in str(read(path, actor="unknown", expected=403))
    print(json.dumps({"runtime": BASE, "result": "PASSED", "orders": 5,
                      "coverage": queue["coverage"], "assessment_availability": statuses,
                      "calendar_matches_queue": True, "roles_and_tenant_isolation": "PASSED",
                      "database_writes": False, "integration_mode": "SYNTHETIC"}, indent=2))


if __name__ == "__main__":
    main()
