"""Route registration against the real main app; no approval adapter is overridden."""

from collections import Counter

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.communication.router import (
    router, get_request_authority, get_draft_authority,
)
from app.communication.authority_adapters import RuntimeDraftAuthority, RuntimeRequestAuthority
from app.communication.tests.test_requests import db, authority, service, create, HEADERS  # noqa: F401
from app.core.dependencies import get_db
from app.core.router import router as core_router
from app.main import app


@pytest.fixture
def main_client(db):  # noqa: F811 - pytest fixture imported for collection
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def exposed_routes(routes):
    # Newer FastAPI retains included routers lazily instead of flattening
    # app.routes. Inspect effective paths, including any accidental prefix.
    for route in routes:
        if hasattr(route, "effective_route_contexts"):
            yield from route.effective_route_contexts()
        else:
            yield route


def route_keys(routes):
    return Counter((method, route.path) for route in exposed_routes(routes) for method in getattr(route, "methods", set()))


def test_main_registers_every_existing_p4_route_once_without_extra_prefix():
    expected = {
        ("GET", "/v1/communications/runtime-capabilities"),
        ("GET", "/v1/communications/recipient-preferences"),
        ("POST", "/v1/communications/recipient-preferences"),
        ("GET", "/v1/communications/{communication_id}/outbound"),
        ("GET", "/v1/communications/{communication_id}/drafts/{draft_id}/send-eligibility"),
        ("POST", "/v1/communications/{communication_id}/drafts/{draft_id}/send"),
        ("GET", "/v1/communications"),
        ("GET", "/v1/communications/summary"),
        ("GET", "/v1/communications/{communication_id}"),
        ("POST", "/v1/communications/requests"),
        ("POST", "/v1/communications/{communication_id}/prepare"),
        ("GET", "/v1/communications/{communication_id}/drafts/{draft_id}"),
        ("GET", "/v1/communications/{communication_id}/drafts/{draft_id}/review"),
        ("POST", "/v1/communications/{communication_id}/drafts/{draft_id}/approve"),
        ("POST", "/v1/communications/{communication_id}/drafts/{draft_id}/reject"),
    }
    actual = route_keys(app.routes)
    assert set(route_keys(router.routes)) == expected
    assert all(actual[key] == 1 for key in expected)
    assert not any("/v1/communications/v1/" in path or path.startswith("/v1/communication/") for _, path in actual)


def test_original_core_routes_still_point_to_original_endpoints():
    for original in exposed_routes(core_router.routes):
        matches = [route for route in exposed_routes(app.routes) if getattr(route, "path", None) == original.path
                   and getattr(route, "methods", None) == original.methods]
        assert len(matches) == 1
        assert matches[0].endpoint is original.endpoint


def test_summary_dispatches_to_static_endpoint_not_communication_id(main_client):
    path = "/v1/communications/summary"
    paths = [route.path for route in exposed_routes(app.routes)]
    assert paths.index(path) < paths.index("/v1/communications/{communication_id}")
    response = main_client.get(path, headers=HEADERS)
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 0
    assert response.json()["drafted"] is None and response.json()["sent"] == 0


def test_registered_openapi_exposes_existing_draft_retrieval_once():
    schema = app.openapi()
    for route in router.routes:
        assert route.path in schema["paths"]
        for method in route.methods:
            assert method.lower() in schema["paths"][route.path]
    operations = [operation["operationId"] for path in schema["paths"].values()
                  for operation in path.values() if isinstance(operation, dict) and "operationId" in operation]
    assert len(operations) == len(set(operations))


def test_startup_health_and_existing_error_handler_without_database_override():
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200 and response.json()["status"] == "ok"
        missing = client.get("/route-integration-unknown", headers={"X-Correlation-ID": "corr_route"})
        assert missing.status_code == 404 and missing.json()["code"] == "NOT_FOUND"
        assert missing.json()["correlation_id"] == "corr_route"


def test_auth_headers_and_known_actor_validation_remain_enforced(main_client):
    assert main_client.get("/v1/communications/summary").status_code == 400
    response = main_client.get("/v1/communications/summary", headers={**HEADERS, "X-Actor-ID": "unknown"})
    assert response.status_code == 403


def test_registration_does_not_configure_fake_authority(main_client):
    assert isinstance(get_request_authority(), RuntimeRequestAuthority)
    assert isinstance(get_draft_authority(), RuntimeDraftAuthority)
    response = main_client.post("/v1/communications/requests", headers=HEADERS, json={"source_event_id": "evt_001"})
    assert response.status_code == 503
    assert response.json()["code"] == "COMMUNICATION_AUTHORITY_UNAVAILABLE"


def test_registered_prepare_still_fails_closed_with_real_default_provider(main_client, service):  # noqa: F811
    # Arrange a persisted request via the existing test-only fixture, without
    # installing that fixture as a production dependency/authority provider.
    request = create(service)
    response = main_client.post(f"/v1/communications/{request.communication_id}/prepare", headers=HEADERS, json={"language": "en"})
    assert response.status_code == 503 and response.json()["code"] == "DRAFT_REVALIDATION_UNAVAILABLE"


@pytest.mark.parametrize("path,code", [
    ("/v1/communications", "COMMUNICATION_PERSISTENCE_UNAVAILABLE"),
    ("/v1/communications/summary", "COMMUNICATION_SUMMARY_UNAVAILABLE"),
])
def test_missing_migration_is_storage_503_not_missing_route(path, code, tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'no-p4-migration.sqlite'}")
    previous = app.dependency_overrides.copy()
    with Session(engine) as session:
        app.dependency_overrides[get_db] = lambda: session
        try:
            with TestClient(app) as client:
                result = client.get(path, headers=HEADERS)
                assert result.status_code == 503 and result.json()["code"] == code
                assert client.get("/health").status_code == 200
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(previous)
    engine.dispose()
