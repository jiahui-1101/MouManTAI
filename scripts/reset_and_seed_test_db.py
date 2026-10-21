"""Database Reset and Seed Script for Live-API Smoke Testing (UI-06).

Resets the SQLite or PostgreSQL database and seeds a deterministic synthetic dataset
representing all 7 lifecycle states, stock levels, audit trails, and causal chains.

Single documented command:
    python scripts/reset_and_seed_test_db.py
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.models import (
    AuditEventRecord,
    CommitmentProposalRecord,
    CommitmentRecord,
    OutboxEventRecord,
)
from app.core.reservations import seed_resource_stock
from app.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


DEFAULT_DB_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "test_live.db"))
DEFAULT_DB_URL = f"sqlite:///{DEFAULT_DB_FILE.replace(os.sep, '/')}"


def reset_and_seed(db_url: str | None = None) -> None:
    database_url = db_url or os.getenv("DATABASE_URL", DEFAULT_DB_URL)
    print(f"[UI-06] Resetting and seeding database at: {database_url}")

    engine_kwargs: dict[str, object] = {"pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        engine_kwargs["connect_args"] = {"check_same_thread": False}

    engine = create_engine(database_url, **engine_kwargs)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    # 1. Reset: Drop all and Recreate
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    print(" -> All database tables dropped and recreated.")

    now = _now()
    tenant = "tenant_demo_01"

    with Session() as db:
        # 2. Seed stock levels
        seed_resource_stock(db, tenant, "BUN", Decimal("500"), "pcs")
        seed_resource_stock(db, tenant, "PATTY", Decimal("500"), "pcs")
        seed_resource_stock(db, tenant, "BURGER", Decimal("200"), "pcs")
        print(" -> Seeded inventory stocks: BUN (500), PATTY (500), BURGER (200).")

        # 3. Seed 7 deterministic commitments covering all state buckets
        commitments = [
            CommitmentRecord(
                tenant_id=tenant,
                commitment_id="com_001",
                order_id="ord_hero_001",
                customer_id="cust_hero_001",
                terms={"sku": "BURGER", "quantity": "100", "unit": "pcs", "deadline": (now + timedelta(days=2)).isoformat()},
                agreement_state="CONFIRMED",
                feasibility_state="FEASIBLE",
                risk_state="NORMAL",
                recovery_state="COMPLETED",
                fulfilment_state="FULFILLED",
                commitment_version=9,
                evidence_refs=["ev_pod_hero_001"],
                updated_at=now,
            ),
            CommitmentRecord(
                tenant_id=tenant,
                commitment_id="cmt_conf_01",
                order_id="ord_conf_001",
                customer_id="cust_beta",
                terms={"sku": "BURGER", "quantity": "50", "unit": "boxes", "deadline": (now + timedelta(days=3)).isoformat()},
                agreement_state="CONFIRMED",
                feasibility_state="FEASIBLE",
                risk_state="NORMAL",
                recovery_state="NONE",
                fulfilment_state="NOT_STARTED",
                commitment_version=2,
                evidence_refs=["doc_conf_01"],
                updated_at=now - timedelta(hours=3),
            ),
            CommitmentRecord(
                tenant_id=tenant,
                commitment_id="cmt_risk_01",
                order_id="ord_risk_101",
                customer_id="cust_gamma",
                terms={"sku": "BURGER", "quantity": "150", "unit": "pcs", "deadline": (now + timedelta(days=1)).isoformat()},
                agreement_state="CONFIRMED",
                feasibility_state="INFEASIBLE",
                risk_state="AT_RISK",
                recovery_state="PLANNING",
                fulfilment_state="NOT_STARTED",
                commitment_version=3,
                evidence_refs=["doc_risk_01"],
                updated_at=now - timedelta(hours=2),
            ),
            CommitmentRecord(
                tenant_id=tenant,
                commitment_id="cmt_appr_01",
                order_id="ord_appr_102",
                customer_id="cust_delta",
                terms={"sku": "FRIES", "quantity": "80", "unit": "packs", "deadline": (now + timedelta(days=2)).isoformat()},
                agreement_state="CONFIRMED",
                feasibility_state="CONDITIONAL",
                risk_state="AT_RISK",
                recovery_state="PENDING_APPROVAL",
                fulfilment_state="NOT_STARTED",
                commitment_version=2,
                evidence_refs=["doc_appr_01"],
                updated_at=now - timedelta(hours=1),
            ),
            CommitmentRecord(
                tenant_id=tenant,
                commitment_id="cmt_exec_01",
                order_id="ord_exec_103",
                customer_id="cust_epsilon",
                terms={"sku": "DRINK", "quantity": "120", "unit": "cans", "deadline": (now + timedelta(days=4)).isoformat()},
                agreement_state="CONFIRMED",
                feasibility_state="FEASIBLE",
                risk_state="NORMAL",
                recovery_state="EXECUTING",
                fulfilment_state="NOT_STARTED",
                commitment_version=3,
                evidence_refs=["doc_exec_01"],
                updated_at=now - timedelta(minutes=45),
            ),
            CommitmentRecord(
                tenant_id=tenant,
                commitment_id="cmt_offered_01",
                order_id="ord_offered_104",
                customer_id="cust_zeta",
                terms={"sku": "COMBO", "quantity": "60", "unit": "sets", "deadline": (now + timedelta(days=5)).isoformat()},
                agreement_state="OFFERED",
                feasibility_state="FEASIBLE",
                risk_state="NORMAL",
                recovery_state="NONE",
                fulfilment_state="NOT_STARTED",
                commitment_version=2,
                evidence_refs=["doc_prop_01"],
                updated_at=now - timedelta(minutes=30),
            ),
            CommitmentRecord(
                tenant_id=tenant,
                commitment_id="cmt_req_01",
                order_id="ord_req_105",
                customer_id="cust_eta",
                terms={"sku": "SPECIAL", "quantity": "40", "unit": "pcs", "deadline": (now + timedelta(days=6)).isoformat()},
                agreement_state="REQUESTED",
                feasibility_state="NOT_ASSESSED",
                risk_state="NORMAL",
                recovery_state="NONE",
                fulfilment_state="NOT_STARTED",
                commitment_version=1,
                evidence_refs=["doc_req_01"],
                updated_at=now - timedelta(minutes=15),
            ),
        ]
        db.add_all(commitments)
        print(f" -> Seeded {len(commitments)} commitments across all 7 state dimensions.")

        # 4. Seed Proposals
        proposals = [
            CommitmentProposalRecord(
                proposal_id="prop_hero_001",
                tenant_id=tenant,
                commitment_id="com_001",
                proposal_version=1,
                revised_terms={"sku": "BURGER", "quantity": "100", "unit": "pcs"},
                status="ACCEPTED",
                reason="Initial recovery proposal offered",
                evidence_refs=["ev_prop_hero_001"],
                created_at=now - timedelta(hours=4),
                updated_at=now - timedelta(hours=3),
            ),
            CommitmentProposalRecord(
                proposal_id="prop_appr_001",
                tenant_id=tenant,
                commitment_id="cmt_appr_01",
                proposal_version=1,
                revised_terms={"sku": "FRIES", "quantity": "80", "unit": "packs"},
                status="ACTIVE",
                reason="Split shipment proposed",
                evidence_refs=["ev_prop_appr_001"],
                created_at=now - timedelta(hours=1),
                updated_at=now - timedelta(hours=1),
            ),
        ]
        db.add_all(proposals)

        # 5. Seed Unbroken Causal Chain for com_001 (F1 -> F2 -> F3 -> F4 -> Core)
        corr_hero = "corr_hero_001"
        audit_events = [
            AuditEventRecord(
                audit_id="aud_01",
                tenant_id=tenant,
                commitment_id="com_001",
                event_type="context.message_received",
                actor_id="user_staff_01",
                actor_role="STAFF",
                dimension="AGREEMENT",
                previous_state=None,
                new_state={"agreement_state": "REQUESTED", "commitment_version": 1},
                evidence_refs=["msg_hero_001"],
                reason="WhatsApp customer order ingested",
                correlation_id=corr_hero,
                causation_id=None,
                occurred_at=now - timedelta(hours=6),
            ),
            AuditEventRecord(
                audit_id="aud_02",
                tenant_id=tenant,
                commitment_id="com_001",
                event_type="commitment.feasibility_assessed",
                actor_id="system",
                actor_role="SYSTEM",
                dimension="FEASIBILITY",
                previous_state={"feasibility_state": "NOT_ASSESSED", "commitment_version": 1},
                new_state={"feasibility_state": "FEASIBLE", "commitment_version": 2},
                evidence_refs=["eval_log_001"],
                reason="Initial feasibility check passed",
                correlation_id=corr_hero,
                causation_id="aud_01",
                occurred_at=now - timedelta(hours=5),
            ),
            AuditEventRecord(
                audit_id="aud_03",
                tenant_id=tenant,
                commitment_id="com_001",
                event_type="commitment.proposal_offered",
                actor_id="user_manager_01",
                actor_role="MANAGER",
                dimension="AGREEMENT",
                previous_state={"agreement_state": "REQUESTED", "commitment_version": 2},
                new_state={"agreement_state": "OFFERED", "commitment_version": 3},
                evidence_refs=["prop_doc_001"],
                reason="Offered initial terms to customer",
                correlation_id=corr_hero,
                causation_id="aud_02",
                occurred_at=now - timedelta(hours=4),
            ),
            AuditEventRecord(
                audit_id="aud_04",
                tenant_id=tenant,
                commitment_id="com_001",
                event_type="commitment.confirmed",
                actor_id="system",
                actor_role="SYSTEM",
                dimension="AGREEMENT",
                previous_state={"agreement_state": "OFFERED", "commitment_version": 3},
                new_state={"agreement_state": "CONFIRMED", "commitment_version": 4},
                evidence_refs=["cust_accept_001"],
                reason="Customer accepted proposal v1",
                correlation_id=corr_hero,
                causation_id="aud_03",
                occurred_at=now - timedelta(hours=3),
            ),
            AuditEventRecord(
                audit_id="aud_05",
                tenant_id=tenant,
                commitment_id="com_001",
                event_type="commitment.fulfilled",
                actor_id="user_owner_01",
                actor_role="OWNER",
                dimension="FULFILMENT",
                previous_state={"fulfilment_state": "NOT_STARTED", "commitment_version": 8},
                new_state={"fulfilment_state": "FULFILLED", "commitment_version": 9},
                evidence_refs=["ev_pod_hero_001"],
                reason="Verified operational delivery with signed POD",
                correlation_id=corr_hero,
                causation_id="aud_04",
                occurred_at=now - timedelta(minutes=10),
            ),
        ]
        db.add_all(audit_events)

        # 6. Seed Outbox Events
        outbox_events = [
            OutboxEventRecord(
                event_id="evt_01",
                tenant_id=tenant,
                event_type="commitment.fulfilled",
                commitment_id="com_001",
                commitment_version=9,
                correlation_id=corr_hero,
                causation_id="aud_05",
                occurred_at=now - timedelta(minutes=10),
                payload={"commitment_id": "com_001", "fulfilment_state": "FULFILLED"},
                published_at=now - timedelta(minutes=9),
                attempts=1,
                status="PUBLISHED",
            ),
        ]
        db.add_all(outbox_events)

        db.commit()

    print("[UI-06] Database reset and synthetic seed completed successfully.")


if __name__ == "__main__":
    db_target = sys.argv[1] if len(sys.argv) > 1 else None
    reset_and_seed(db_target)
