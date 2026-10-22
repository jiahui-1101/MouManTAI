import pytest
from fastapi.testclient import TestClient

from app.context.dependencies import development_context, local_repository
from app.context.dev_app import app
from app.context.ingestion_schemas import DevelopmentContext
from app.context.postgres_repository import PostgresMessageRepository
from app.context.repository import PersistenceUnavailable
from app.context.tests.test_postgres_repository import NOW, envelope


@pytest.fixture
def api(pg_engine):
    repository = PostgresMessageRepository(pg_engine)
    app.dependency_overrides[local_repository] = lambda: repository
    app.dependency_overrides[development_context] = lambda: DevelopmentContext(tenant_id="tenant_a")
    try:
        with TestClient(app) as client:
            yield client, repository
    finally:
        app.dependency_overrides.clear()


def test_ingest_list_detail_and_duplicate_responses(api):
    client, repo = api
    payload = envelope().model_dump(mode="json")
    response = client.post("/v1/messages/ingest", json=payload)
    assert response.status_code == 201
    first = response.json()
    assert first["duplicate"] is False
    assert first["message"]["processing_status"] == "RECEIVED"
    assert "fields" not in first["message"] and "context" not in first["message"]
    message_id = first["message"]["message_id"]
    assert client.get(f"/v1/messages/{message_id}").json() == first["message"]
    assert client.get("/v1/messages").json()["items"] == [first["message"]]
    duplicate = client.post("/v1/messages/ingest", json=payload)
    assert duplicate.status_code == 200
    assert duplicate.json() == {**first, "duplicate": True}
    conflict = client.post("/v1/messages/ingest", json=payload | {"text": "changed"})
    assert conflict.status_code == 409
    assert client.get(f"/v1/messages/{message_id}").json()["raw"]["text"] == payload["text"]
    assert repo.list("tenant_a").total == 1


@pytest.mark.parametrize("changes", [{"received_at": "2026-10-20T10:00:00"}, {"channel": "SMS"},
    {"channel": "FAX"}, {"adapter_mode": "LIVE"}, {"text": ""}, {"text": " "},
    {"text": "NUL\u0000not valid"}, {"actor_role": "admin"}])
def test_invalid_and_unimplemented_inputs_do_not_persist(api, changes):
    client, repo = api
    response = client.post("/v1/messages/ingest", json=envelope().model_dump(mode="json") | changes)
    assert response.status_code == 422
    assert repo.list("tenant_a").total == 0


@pytest.mark.parametrize("channel,expected_provider", [
    ("WHATSAPP", "SYNTHETIC_WHATSAPP"),
    ("EMAIL", "SYNTHETIC_EMAIL"),
    ("TELEGRAM", "SYNTHETIC_TELEGRAM"),
])
def test_multi_channel_ingestion_supported(api, channel, expected_provider):
    client, repo = api
    payload = envelope(channel=channel, provider_message_id=f"prov_{channel.lower()}").model_dump(mode="json")
    response = client.post("/v1/messages/ingest", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["message"]["raw"]["channel"] == channel
    assert data["message"]["synthetic_provider"] == expected_provider
    assert not data["duplicate"]
    stored_msg = client.get(f"/v1/messages/{data['message']['message_id']}").json()
    assert stored_msg["raw"]["channel"] == channel
    assert stored_msg["synthetic_provider"] == expected_provider


def test_effective_tenant_is_not_client_controlled(api):
    client, repo = api
    foreign = repo.ingest(envelope(tenant_id="tenant_b"), NOW).message
    mismatch = client.post("/v1/messages/ingest", json=envelope(tenant_id="tenant_b").model_dump(mode="json"), headers={"X-Tenant-ID": "tenant_b"})
    assert mismatch.status_code == 403
    assert client.get("/v1/messages", headers={"X-Tenant-ID": "tenant_b"}).json()["total"] == 0
    inaccessible = client.get(f"/v1/messages/{foreign.message_id}", headers={"X-Tenant-ID": "tenant_b"})
    assert inaccessible.status_code == 404
    assert inaccessible.json() == client.get("/v1/messages/unknown").json()
    assert client.get("/dev/p1/config").json()["tenant_id"] == "tenant_a"


def test_filter_search_and_bounded_query_parameters(api):
    client, repo = api
    repo.ingest(envelope(), NOW)
    assert client.get("/v1/messages", params={"channel": "EMAIL"}).json()["total"] == 0
    page = client.get("/v1/messages", params={"search": "burgers", "limit": 1, "offset": 0}).json()
    assert page["total"] == 1 and page["limit"] == 1
    assert client.get("/v1/messages", params={"search": "absent"}).json()["items"] == []
    for params in [{"limit": 101}, {"limit": 0}, {"offset": -1}, {"offset": 10001}, {"search": "a" * 201}, {"channel": "SMS"}, {"processing_status": "READY"}]:
        assert client.get("/v1/messages", params=params).status_code == 422


@pytest.mark.parametrize("operation", ["ingest", "list", "detail"])
def test_repository_failures_never_return_success(operation):
    class FailingRepository:
        def ingest(self, *args, **kwargs): raise PersistenceUnavailable("private internal connection data")
        def list(self, *args, **kwargs): raise PersistenceUnavailable("private internal connection data")
        def get(self, *args, **kwargs): raise PersistenceUnavailable("private internal connection data")
    app.dependency_overrides[local_repository] = lambda: FailingRepository()
    app.dependency_overrides[development_context] = lambda: DevelopmentContext(tenant_id="tenant_a")
    try:
        with TestClient(app) as client:
            if operation == "ingest":
                response = client.post("/v1/messages/ingest", json=envelope().model_dump(mode="json"))
            else:
                response = client.get("/v1/messages" + ("/unknown" if operation == "detail" else ""))
            assert response.status_code == 503
            assert "private" not in response.text
    finally:
        app.dependency_overrides.clear()


def test_development_context_ignores_request_auth_claims(monkeypatch):
    monkeypatch.setenv("P1_DEV_TENANT_ID", "server_chosen_tenant")
    assert development_context().tenant_id == "server_chosen_tenant"
    monkeypatch.setenv("P1_DEV_TENANT_ID", " ")
    with pytest.raises(PersistenceUnavailable):
        development_context()
