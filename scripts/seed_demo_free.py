"""Idempotent synthetic fixtures for the isolated single-account demo."""
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.context.ingestion import IngestionService
from app.context.postgres_repository import PostgresMessageRepository
from app.context.schemas import RawMessageEnvelope
from app.core.dependencies import RequestContext
from app.db.session import engine
from app.feasibility.production import EvaluationSnapshot
from app.feasibility.production_fixtures import build_production_example
from app.message_intelligence.adapters import CurrentP1MessageReader
from app.message_intelligence.review import C3ReviewService
from app.message_intelligence.review_models import C3ClassificationRecord
from app.message_intelligence.service import MessageIntelligenceService
from app.orders.models import MockOrbyteStateRecord, MockOrderSourceRecord, OrderRequestRecord
from app.orders.service import import_request
from app.orders.terms import OrderTerms


tenant = os.environ["MOUMANTAI_ISOLATED_E2E_TENANT_ID"]
actor = os.environ["MOUMANTAI_ISOLATED_E2E_MANAGER_ID"]
now = datetime.now(UTC)
request_id = "order_demo_001"


def move(value, shift):
    if isinstance(value, datetime):
        return value + shift
    if isinstance(value, dict):
        return {key: tenant if key == "tenant_id" else move(item, shift)
                for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [move(item, shift) for item in value]
    return value


with Session(engine) as db:
    if db.get(MockOrderSourceRecord, (tenant, f"source_{request_id}")) is None:
        terms = OrderTerms.model_validate({
            "tenant_id": tenant, "order_request_id": request_id,
            "customer_id": "customer_synthetic_001", "terms_revision": 1,
            "items": [{"sku": "BURGER", "quantity": "10", "unit": "pcs", "unit_price": "2"}],
            "fulfilment_method": "DELIVERY", "location_ref": "synthetic_address_001",
            "window_start": (now + timedelta(hours=24)).isoformat(),
            "window_end": (now + timedelta(hours=27)).isoformat(),
            "business_timezone": "Asia/Kuala_Lumpur", "currency": "MYR",
            "fees": "5", "tax": "0", "discount": "0", "total": "25",
            "price_source": {"source_type": "APPROVED_CATALOG", "source_id": "synthetic_catalog",
                             "source_version": "1", "policy_ref": "synthetic_policy",
                             "disclosed_at": (now - timedelta(hours=1)).isoformat(),
                             "evidence_refs": ["synthetic_price_disclosure"]},
            "binding_policy_ref": "synthetic_policy", "source_message_ids": ["synthetic_order_message"],
            "evidence_refs": ["synthetic_customer_request", "synthetic_price_disclosure"],
        })
        db.add(MockOrderSourceRecord(
            tenant_id=tenant, source_id=f"source_{request_id}",
            customer_id=terms.customer_id, source_version=1,
            terms=terms.model_dump(mode="json"),
            customer_request_ref="synthetic_customer_request",
            price_disclosure_ref="synthetic_price_disclosure",
            observed_at=now - timedelta(minutes=5),
            valid_through=now + timedelta(days=2), status="CURRENT",
        ))
    if db.get(MockOrbyteStateRecord, tenant) is None:
        original, _ = build_production_example()
        shifted = move(original.model_dump(exclude_computed_fields=True),
                       now - original.as_of - timedelta(minutes=1))
        shifted["operational"]["inventory_lots"][0]["quantity"] = Decimal("150")
        snapshot = EvaluationSnapshot.model_validate(shifted)
        db.add(MockOrbyteStateRecord(
            tenant_id=tenant, snapshot_version=1,
            snapshot_payload=snapshot.model_dump(mode="json", exclude_computed_fields=True),
            next_outcome="NORMAL", updated_at=now,
        ))
    db.commit()
    if db.get(OrderRequestRecord, (tenant, request_id)) is None:
        import_request(db, RequestContext(tenant, actor, "OWNER", "corr_demo_seed"),
                       f"source_{request_id}", 1)


repository = PostgresMessageRepository(engine)
class Scope:
    def current_verified_tenant_id(self):
        return tenant


with Session(engine) as db:
    existing = db.query(C3ClassificationRecord).filter_by(tenant_id=tenant).first()
if existing is None:
    message = RawMessageEnvelope(
        tenant_id=tenant, channel="TELEGRAM", provider_message_id="synthetic_demo_message_001",
        sender_identity_id="synthetic_sender_001", sender_alias="Synthetic customer",
        received_at=now, message_at=now, text="Please advise about my burger order",
        adapter_mode="SYNTHETIC", source_authenticity="SYNTHETIC",
    )
    stored = IngestionService(repository).ingest(message, tenant).message
    repository.process(tenant, stored.message_id)
    reader = CurrentP1MessageReader(repository, Scope())
    classifier = MessageIntelligenceService.from_env()
    outcome = reader.analyze(stored.message_id, classifier, now=now)
    source_hash = hashlib.sha256(json.dumps(outcome.source.model_dump(mode="json"),
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    with Session(engine) as db:
        review = C3ReviewService(db, reader).enqueue(
            stored.message_id, classifier, now=now, outcome=outcome, commit=False)
        db.add(C3ClassificationRecord(
            tenant_id=tenant, message_id=stored.message_id, source_hash=source_hash,
            outcome=outcome.model_dump(mode="json"),
            review_id=review.review_id if review else None, created_at=now,
        ))
        db.commit()
print("Synthetic Demo Admin Orders and C3 fixtures ready")
