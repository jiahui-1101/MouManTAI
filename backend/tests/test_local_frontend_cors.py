"""The default Vite origin must be able to call the shared API."""

from fastapi.testclient import TestClient

from app.main import app


def test_default_local_frontend_origins_pass_api_preflight() -> None:
    with TestClient(app) as client:
        for origin in ("http://localhost:5173", "http://127.0.0.1:5173"):
            response = client.options(
                "/v1/communications",
                headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "GET",
                    "Access-Control-Request-Headers": "x-tenant-id,x-actor-id",
                },
            )
            assert response.status_code == 200
            assert response.headers["access-control-allow-origin"] == origin
