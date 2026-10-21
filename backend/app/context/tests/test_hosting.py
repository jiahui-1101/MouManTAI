from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.context.hosting import mount_p1_ingestion
from app.context.ingestion_schemas import DevelopmentContext
from app.context.postgres_repository import PostgresMessageRepository
from app.context.tests.test_postgres_repository import envelope


def test_external_host_can_reuse_its_database_session_without_the_dev_app(pg_engine):
    host = FastAPI()

    def host_db():
        with Session(pg_engine) as session:
            yield session

    def host_repository(session: Session = Depends(host_db)):
        return PostgresMessageRepository(session.get_bind())

    def host_tenant():
        return DevelopmentContext(tenant_id="tenant_a")

    mount_p1_ingestion(host, repository_provider=host_repository, tenant_provider=host_tenant)
    with TestClient(host) as client:
        payload = envelope().model_dump(mode="json")
        created = client.post("/v1/messages/ingest", json=payload)
        assert created.status_code == 201
        assert client.get("/v1/messages").json()["total"] == 1
        assert client.post("/v1/messages/ingest", json=payload).status_code == 200
        assert client.post("/v1/messages/ingest", json=payload | {"text": "conflict"}).status_code == 409
        assert client.post("/v1/messages/ingest", json=payload | {"tenant_id": "tenant_b"}).status_code == 403
        assert client.get("/dev/p1/inbox").status_code == 404  # Fixture routes are not mounted.
        assert client.get("/dev/p1/health").status_code == 404
    assert not host.dependency_overrides.get(host_db)  # The host's DB dependency is not replaced.
