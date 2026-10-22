"""Deterministic synthetic seed script for MouManTAI (DEV-1, BE-03f).

Seeds the database with resource stocks and the 5 canonical demo commitments:
1. Normal feasible commitment (`com_normal_01`)
2. Material shortage / AT_RISK commitment (`com_001`)
3. Supplier delay with alternate recovery plans (`com_delay_01`)
4. Ambiguous customer confirmation (`com_ambiguous_01`)
5. Verified operational completion (`com_fulfilled_01`)

Idempotent: safe to run multiple times without duplicating or corrupting state.
Usage:
    python scripts/seed_demo.py [DATABASE_URL]
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
import sys

# Ensure repository root and backend directory are in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

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


def seed_demo(db_url: str | None = None) -> None:
    database_url = db_url or os.getenv("DATABASE_URL", DEFAULT_DB_URL)
    print(f"[seed_demo] Target database: {database_url}")

    engine_kwargs: dict[str, object] = {"pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        engine_kwargs["connect_args"] = {"check_same_thread": False}

    engine = create_engine(database_url, **engine_kwargs)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    now = _now()
    tenant = "tenant_demo_01"

    target_commitment_ids = {
        "com_normal_01",
        "com_001",
        "com_delay_01",
        "com_ambiguous_01",
        "com_fulfilled_01",
    }

    with session_factory() as db:
        # 1. Clean up existing demo commitments for clean idempotency
        existing_commitments = db.scalars(
            select(CommitmentRecord).where(
                CommitmentRecord.tenant_id == tenant,
                CommitmentRecord.commitment_id.in_(target_commitment_ids),
            )
        ).all()
        for c in existing_commitments:
            db.delete(c)

        existing_proposals = db.scalars(
            select(CommitmentProposalRecord).where(
                CommitmentProposalRecord.tenant_id == tenant,
                CommitmentProposalRecord.commitment_id.in_(target_commitment_ids),
            )
        ).all()
        for p in existing_proposals:
            db.delete(p)

        existing_audits = db.scalars(
            select(AuditEventRecord).where(
                AuditEventRecord.tenant_id == tenant,
                AuditEventRecord.commitment_id.in_(target_commitment_ids),
            )
        ).all()
        for a in existing_audits:
            db.delete(a)

        existing_outbox = db.scalars(
            select(OutboxEventRecord).where(
                OutboxEventRecord.tenant_id == tenant,
                OutboxEventRecord.commitment_id.in_(target_commitment_ids),
            )
        ).all()
        for o in existing_outbox:
            db.delete(o)

        db.commit()

        # 2. Seed stock levels
        seed_resource_stock(db, tenant, "BUN", Decimal("1000"), "pcs")
        seed_resource_stock(db, tenant, "PATTY", Decimal("500"), "pcs")
        seed_resource_stock(db, tenant, "BURGER", Decimal("300"), "pcs")
        seed_resource_stock(db, tenant, "GREENS", Decimal("200"), "kg")
        print(" -> Seeded inventory stocks: BUN (1000 pcs), PATTY (500 pcs), BURGER (300 pcs), GREENS (200 kg).")

        # ---------------------------------------------------------------------
        # Commitment 1: Normal feasible commitment (com_normal_01)
        # ---------------------------------------------------------------------
        com_normal = CommitmentRecord(
            tenant_id=tenant,
            commitment_id="com_normal_01",
            order_id="ord_normal_01",
            customer_id="cust_normal_01",
            terms={
                "sku": "BURGER_CLASSIC",
                "quantity": "50",
                "unit": "pcs",
                "deadline": (now + timedelta(days=3)).isoformat(),
            },
            agreement_state="CONFIRMED",
            feasibility_state="FEASIBLE",
            risk_state="NORMAL",
            recovery_state="NONE",
            fulfilment_state="NOT_STARTED",
            commitment_version=2,
            evidence_refs=["ev_order_normal_01", "ev_conf_normal_01"],
            updated_at=now - timedelta(hours=5),
        )

        # ---------------------------------------------------------------------
        # Commitment 2: Material shortage / AT_RISK commitment (com_001)
        # ---------------------------------------------------------------------
        com_at_risk = CommitmentRecord(
            tenant_id=tenant,
            commitment_id="com_001",
            order_id="ord_hero_001",
            customer_id="cust_hero_001",
            terms={
                "sku": "BURGER_PREMIUM",
                "quantity": "100",
                "unit": "pcs",
                "deadline": (now + timedelta(days=2)).isoformat(),
            },
            agreement_state="CONFIRMED",
            feasibility_state="INFEASIBLE",
            risk_state="AT_RISK",
            recovery_state="RECOVERY_REQUIRED",
            fulfilment_state="NOT_STARTED",
            commitment_version=5,
            evidence_refs=["ev_msg_hero_sku", "ev_stock_shortage_01"],
            updated_at=now - timedelta(hours=2),
        )

        # ---------------------------------------------------------------------
        # Commitment 3: Supplier delay with alternate recovery plans (com_delay_01)
        # ---------------------------------------------------------------------
        com_delay = CommitmentRecord(
            tenant_id=tenant,
            commitment_id="com_delay_01",
            order_id="ord_delay_01",
            customer_id="cust_delay_01",
            terms={
                "sku": "BURGER_DELUXE",
                "quantity": "200",
                "unit": "pcs",
                "deadline": (now + timedelta(days=1)).isoformat(),
            },
            agreement_state="CONFIRMED",
            feasibility_state="INFEASIBLE",
            risk_state="AT_RISK",
            recovery_state="PENDING_APPROVAL",
            fulfilment_state="NOT_STARTED",
            commitment_version=4,
            evidence_refs=["ev_supplier_delay_slip_01"],
            updated_at=now - timedelta(hours=1),
        )

        # Alternate recovery proposals for com_delay_01
        prop_delay_alt1 = CommitmentProposalRecord(
            proposal_id="prop_delay_alt1",
            tenant_id=tenant,
            commitment_id="com_delay_01",
            proposal_version=1,
            revised_terms={
                "sku": "BURGER_DELUXE",
                "quantity": "200",
                "unit": "pcs",
                "deadline": (now + timedelta(days=1)).isoformat(),
                "recovery_action": "EXPEDITE_SUPPLIER",
                "estimated_additional_cost": "50.00",
            },
            status="ACTIVE",
            reason="Expedite shipment from secondary local bakery with courier surcharge",
            evidence_refs=["ev_quote_secondary_bakery_01"],
            created_at=now - timedelta(minutes=45),
            updated_at=now - timedelta(minutes=45),
        )
        prop_delay_alt2 = CommitmentProposalRecord(
            proposal_id="prop_delay_alt2",
            tenant_id=tenant,
            commitment_id="com_delay_01",
            proposal_version=2,
            revised_terms={
                "sku": "BURGER_DELUXE",
                "quantity": "200",
                "unit": "pcs",
                "deadline": (now + timedelta(days=3)).isoformat(),
                "recovery_action": "REVISE_SCHEDULE",
                "courtesy_discount_pct": "5",
            },
            status="DRAFT",
            reason="Reschedule delivery +2 days with 5% customer courtesy discount",
            evidence_refs=["ev_delay_notice_01"],
            created_at=now - timedelta(minutes=30),
            updated_at=now - timedelta(minutes=30),
        )

        # ---------------------------------------------------------------------
        # Commitment 4: Ambiguous customer confirmation (com_ambiguous_01)
        # ---------------------------------------------------------------------
        com_ambiguous = CommitmentRecord(
            tenant_id=tenant,
            commitment_id="com_ambiguous_01",
            order_id="ord_ambiguous_01",
            customer_id="cust_ambiguous_01",
            terms={
                "sku": "BURGER_VEGAN",
                "quantity": "75",
                "unit": "pcs",
                "deadline": (now + timedelta(days=4)).isoformat(),
                "requires_manual_review": True,
                "conflicts": ["ambiguous_customer_reply"],
            },
            agreement_state="OFFERED",
            feasibility_state="FEASIBLE",
            risk_state="NORMAL",
            recovery_state="NONE",
            fulfilment_state="NOT_STARTED",
            commitment_version=2,
            evidence_refs=["ev_chat_ambiguous_ok"],
            updated_at=now - timedelta(minutes=20),
        )

        prop_ambiguous = CommitmentProposalRecord(
            proposal_id="prop_ambiguous_01",
            tenant_id=tenant,
            commitment_id="com_ambiguous_01",
            proposal_version=1,
            revised_terms={
                "sku": "BURGER_VEGAN",
                "quantity": "75",
                "unit": "pcs",
                "deadline": (now + timedelta(days=4)).isoformat(),
            },
            status="ACTIVE",
            reason="Customer replied 'sounds ok maybe' in chat; awaiting formal term confirmation",
            evidence_refs=["ev_chat_ambiguous_ok"],
            created_at=now - timedelta(minutes=20),
            updated_at=now - timedelta(minutes=20),
        )

        # ---------------------------------------------------------------------
        # Commitment 5: Verified operational completion (com_fulfilled_01)
        # ---------------------------------------------------------------------
        com_fulfilled = CommitmentRecord(
            tenant_id=tenant,
            commitment_id="com_fulfilled_01",
            order_id="ord_fulfilled_01",
            customer_id="cust_fulfilled_01",
            terms={
                "sku": "BURGER_COMBO",
                "quantity": "120",
                "unit": "pcs",
                "deadline": (now - timedelta(hours=2)).isoformat(),
            },
            agreement_state="CONFIRMED",
            feasibility_state="FEASIBLE",
            risk_state="RESOLVED",
            recovery_state="NONE",
            fulfilment_state="FULFILLED",
            commitment_version=6,
            evidence_refs=["ev_ops_delivery_pod_com_fulfilled"],
            updated_at=now - timedelta(minutes=15),
        )

        db.add_all([
            com_normal,
            com_at_risk,
            com_delay,
            com_ambiguous,
            com_fulfilled,
            prop_delay_alt1,
            prop_delay_alt2,
            prop_ambiguous,
        ])

        # ---------------------------------------------------------------------
        # Seed Audit & Outbox Events
        # ---------------------------------------------------------------------
        audits = [
            AuditEventRecord(
                audit_id="aud_demo_01",
                tenant_id=tenant,
                commitment_id="com_normal_01",
                event_type="commitment.confirmed",
                actor_id="user_manager_01",
                actor_role="MANAGER",
                dimension="agreement",
                previous_state={"agreement_state": "OFFERED", "commitment_version": 1},
                new_state={"agreement_state": "CONFIRMED", "commitment_version": 2},
                evidence_refs=["ev_conf_normal_01"],
                reason="Standard terms signed and confirmed",
                correlation_id="corr_normal_01",
                causation_id=None,
                occurred_at=now - timedelta(hours=5),
            ),
            AuditEventRecord(
                audit_id="aud_demo_02",
                tenant_id=tenant,
                commitment_id="com_001",
                event_type="commitment.at_risk",
                actor_id="service_p2_feasibility",
                actor_role="SERVICE",
                dimension="risk",
                previous_state={"risk_state": "NORMAL", "commitment_version": 4},
                new_state={"risk_state": "AT_RISK", "recovery_state": "RECOVERY_REQUIRED", "commitment_version": 5},
                evidence_refs=["ev_stock_shortage_01"],
                reason="Raw material shortage: BEEF_PATTIES shortage 40 pcs",
                correlation_id="corr_hero_001",
                causation_id="evt_p2_eval_01",
                occurred_at=now - timedelta(hours=2),
            ),
            AuditEventRecord(
                audit_id="aud_demo_03",
                tenant_id=tenant,
                commitment_id="com_delay_01",
                event_type="commitment.at_risk",
                actor_id="service_p2_feasibility",
                actor_role="SERVICE",
                dimension="risk",
                previous_state={"risk_state": "NORMAL", "commitment_version": 3},
                new_state={"risk_state": "AT_RISK", "recovery_state": "PENDING_APPROVAL", "commitment_version": 4},
                evidence_refs=["ev_supplier_delay_slip_01"],
                reason="Supplier delivery delayed by 2 days; recovery alternatives generated",
                correlation_id="corr_delay_01",
                causation_id="evt_supplier_delay_01",
                occurred_at=now - timedelta(hours=1),
            ),
            AuditEventRecord(
                audit_id="aud_demo_04",
                tenant_id=tenant,
                commitment_id="com_fulfilled_01",
                event_type="commitment.fulfilment_verified",
                actor_id="user_owner_01",
                actor_role="OWNER",
                dimension="fulfilment",
                previous_state={"fulfilment_state": "NOT_STARTED", "commitment_version": 5},
                new_state={"fulfilment_state": "FULFILLED", "risk_state": "RESOLVED", "commitment_version": 6},
                evidence_refs=["ev_ops_delivery_pod_com_fulfilled"],
                reason="Courier delivery verified with customer signature on POD",
                correlation_id="corr_fulfilled_01",
                causation_id="evt_pod_delivered_01",
                occurred_at=now - timedelta(minutes=15),
            ),
        ]
        db.add_all(audits)

        outbox_events = [
            OutboxEventRecord(
                event_id="evt_outbox_at_risk_001",
                tenant_id=tenant,
                event_type="commitment.at_risk",
                commitment_id="com_001",
                commitment_version=5,
                correlation_id="corr_hero_001",
                causation_id="evt_p2_eval_01",
                occurred_at=now - timedelta(hours=2),
                payload={
                    "commitment_id": "com_001",
                    "shortage_item": "BEEF_PATTIES",
                    "shortage_quantity": "40",
                    "severity": "HARD",
                },
                published_at=None,
                attempts=0,
                status="PENDING",
            ),
            OutboxEventRecord(
                event_id="evt_outbox_fulfilled_01",
                tenant_id=tenant,
                event_type="commitment.fulfilment_verified",
                commitment_id="com_fulfilled_01",
                commitment_version=6,
                correlation_id="corr_fulfilled_01",
                causation_id="evt_pod_delivered_01",
                occurred_at=now - timedelta(minutes=15),
                payload={"commitment_id": "com_fulfilled_01", "fulfilment_state": "FULFILLED"},
                published_at=now - timedelta(minutes=14),
                attempts=1,
                status="PUBLISHED",
            ),
        ]
        db.add_all(outbox_events)

        db.commit()

    print(f" -> Successfully seeded {len(target_commitment_ids)} canonical demo commitments:")
    print("    1. com_normal_01    (CONFIRMED, FEASIBLE, NORMAL, NOT_STARTED)")
    print("    2. com_001          (CONFIRMED, INFEASIBLE, AT_RISK, RECOVERY_REQUIRED)")
    print("    3. com_delay_01     (CONFIRMED, INFEASIBLE, AT_RISK, PENDING_APPROVAL, with 2 recovery plans)")
    print("    4. com_ambiguous_01 (OFFERED, FEASIBLE, NORMAL, manual review required)")
    print("    5. com_fulfilled_01 (CONFIRMED, FEASIBLE, RESOLVED, FULFILLED, signed POD proof)")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None
    seed_demo(target)
