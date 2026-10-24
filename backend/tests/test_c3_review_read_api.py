"""Isolated C3 evidence reads never derive authority from browser identity headers."""

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.dependencies import get_db
from app.main import app
from app.message_intelligence.review_models import C3ReviewRecord
from app.message_intelligence.adapters import CurrentP1MessageReader
from app.message_intelligence.review import C3ReviewService
from app.message_intelligence.service import MessageIntelligenceService
from tests.test_message_intelligence import NOW, CurrentSourceFixture, canonical_message


def test_duplicate_review_enqueue_does_not_rerun_classification():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    C3ReviewRecord.__table__.create(engine)
    msg = canonical_message("Please advise")
    source = CurrentSourceFixture(msg)

    class CountingClassifier(MessageIntelligenceService):
        calls = 0

        def analyze(self, *args, **kwargs):
            self.calls += 1
            return super().analyze(*args, **kwargs)

    classifier = CountingClassifier()
    with Session(engine) as db:
        service = C3ReviewService(db, CurrentP1MessageReader(source, source))
        first = service.enqueue(msg.message_id, classifier, now=NOW)
        second = service.enqueue(msg.message_id, classifier, now=NOW)
        assert first is not None and second is not None
        assert first.review_id == second.review_id
        assert classifier.calls == 1
    engine.dispose()


def test_c3_review_reads_are_keyed_tenant_scoped_and_mutations_absent(monkeypatch):
    key = "synthetic-test-server-key-at-least-32-characters"
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E", "1")
    monkeypatch.setenv("MOUMANTAI_SYNTHETIC_MODE", "1")
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E_KEY", key)
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E_TENANT_ID", "tenant_a")
    monkeypatch.setenv("ENVIRONMENT", "test")
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    C3ReviewRecord.__table__.create(engine)
    with Session(engine) as db:
        for tenant in ("tenant_a", "tenant_b"):
            db.add(C3ReviewRecord(
                tenant_id=tenant, review_id=f"review_{tenant}", message_id=f"msg_{tenant}",
                candidate_hash="a" * 64, source_sha256="b" * 64,
                source_snapshot={"tenant_id": tenant, "channel": "TELEGRAM"},
                candidate_snapshot={"intent": "UNKNOWN", "evidence": []},
                provider_attempts=[], reason_codes=["SEMANTIC_PROVIDER_UNAVAILABLE"],
                state="PENDING", revision=1, created_at=datetime.now(UTC)))
        db.commit()

    def session_override():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = session_override
    try:
        client = TestClient(app)
        path = "/v1/c3/reviews"
        assert client.get(path).status_code == 403
        assert client.get(path, headers={"X-Isolated-E2E-Key": "wrong"}).status_code == 403
        headers = {"X-Isolated-E2E-Key": key, "X-Tenant-ID": "tenant_b", "X-Actor-Role": "OWNER"}
        response = client.get(path, headers=headers)
        assert response.status_code == 200
        assert response.json()["total"] == 1
        assert response.json()["items"][0]["review_id"] == "review_tenant_a"
        assert response.json()["items"][0]["decision_authority_available"] is False
        assert client.get(f"{path}/review_tenant_b", headers=headers).status_code == 404
        assert client.post(f"{path}/review_tenant_a/decide", headers=headers, json={}).status_code in {404, 405}
        monkeypatch.setenv("ENVIRONMENT", "production")
        assert client.get(path, headers=headers).status_code == 503
        monkeypatch.setenv("ENVIRONMENT", "test")
        monkeypatch.setenv("APP_ENV", "production")
        assert client.get(path, headers=headers).status_code == 503
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
