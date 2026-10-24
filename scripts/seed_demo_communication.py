"""Deterministic synthetic communication seed script for MouManTAI (P4 Communication Center).

Seeds demo communication requests for tenant_demo_01 linking to canonical commitments
com_delay_01 and com_001, allowing the Communication Center UI to display live requests,
metrics, and drafting controls.
"""
from datetime import datetime, timezone, timedelta
import os
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
env_path = repo_root / ".env"
if env_path.is_file():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))

backend_dir = repo_root / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from app.db.session import SessionLocal
from app.communication.models import CommunicationRequestRecord
from app.communication.schemas import CommunicationRequestView, RecoveryCommunicationReference, RequestStatus
from app.core.schemas import CommitmentTerms


def seed_communication():
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        tenant = "tenant_demo_01"

        # 1. Supplier delay recovery communication (WhatsApp)
        terms1 = CommitmentTerms(sku="BURGER_DELUXE", quantity="200", unit="pcs", deadline=now + timedelta(days=2))
        ref1 = RecoveryCommunicationReference(
            tenant_id=tenant,
            commitment_id="com_delay_01",
            plan_id="plan_delay_01",
            plan_version=1,
            proposal_id="prop_delay_alt1",
            proposal_version=1,
            source_event_id="evt_rec_comm_01",
            commitment_version=4,
            correlation_id="corr_delay_rec_01",
            occurred_at=now,
        )
        view1 = CommunicationRequestView(
            communication_id="comm_delay_01",
            reference=ref1,
            request_status=RequestStatus.READY_FOR_DRAFTING,
            blocking_reasons=[],
            proposed_terms=terms1,
            approval_evidence_refs=["ev_supplier_delay_slip_01"],
            approval_expires_at=now + timedelta(days=3),
            proposal_evidence_refs=["ev_delay_recovery_plan"],
            recipient_identity_id="identity_cust_delay",
            recipient_evidence_refs=["ev_contact_whatsapp"],
            channel="MOCK_WHATSAPP",
            channel_evidence_refs=["ev_consent_wa_01"],
            expires_at=now + timedelta(days=3),
            created_by="user_manager_01",
            created_at=now,
            outbound_status=None,
        )
        rec1 = CommunicationRequestRecord(
            tenant_id=tenant,
            communication_id="comm_delay_01",
            commitment_id="com_delay_01",
            proposal_id="prop_delay_alt1",
            proposal_version=1,
            request_status="READY_FOR_DRAFTING",
            snapshot=view1.model_dump(mode="json"),
            created_at=now,
        )

        # 2. Material shortage recovery communication (Email)
        terms2 = CommitmentTerms(sku="BURGER_PREMIUM", quantity="100", unit="pcs", deadline=now + timedelta(days=1))
        ref2 = RecoveryCommunicationReference(
            tenant_id=tenant,
            commitment_id="com_001",
            plan_id="plan_hero_01",
            plan_version=2,
            proposal_id="prop_hero_substitute",
            proposal_version=1,
            source_event_id="evt_rec_comm_02",
            commitment_version=5,
            correlation_id="corr_hero_rec_02",
            occurred_at=now,
        )
        view2 = CommunicationRequestView(
            communication_id="comm_hero_001",
            reference=ref2,
            request_status=RequestStatus.READY_FOR_DRAFTING,
            blocking_reasons=[],
            proposed_terms=terms2,
            approval_evidence_refs=["ev_stock_shortage_01"],
            approval_expires_at=now + timedelta(days=2),
            proposal_evidence_refs=["ev_plan_substitute_supplier"],
            recipient_identity_id="identity_cust_hero",
            recipient_evidence_refs=["ev_contact_email"],
            channel="MOCK_EMAIL",
            channel_evidence_refs=["ev_consent_email_01"],
            expires_at=now + timedelta(days=2),
            created_by="user_manager_01",
            created_at=now - timedelta(hours=2),
            outbound_status=None,
        )
        rec2 = CommunicationRequestRecord(
            tenant_id=tenant,
            communication_id="comm_hero_001",
            commitment_id="com_001",
            proposal_id="prop_hero_substitute",
            proposal_version=1,
            request_status="READY_FOR_DRAFTING",
            snapshot=view2.model_dump(mode="json"),
            created_at=now - timedelta(hours=2),
        )

        db.merge(rec1)
        db.merge(rec2)
        db.commit()
        print(f"[seed_demo_communication] Successfully seeded demo communication requests for {tenant}.")
    finally:
        db.close()


if __name__ == "__main__":
    seed_communication()
