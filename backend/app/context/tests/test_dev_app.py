from fastapi.testclient import TestClient

from app.context.dev_app import app


def test_development_health_is_explicit():
    response = TestClient(app).get("/dev/p1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "mode": "synthetic-development"}
