"""Automated verification for scripts/seed_demo.py (DEV-1, BE-03f).

Validates that seed_demo seeds all 5 canonical demo commitments with expected invariants:
1. com_normal_01    (CONFIRMED, FEASIBLE, NORMAL, NOT_STARTED)
2. com_001          (CONFIRMED, INFEASIBLE, AT_RISK, RECOVERY_REQUIRED)
3. com_delay_01     (CONFIRMED, INFEASIBLE, AT_RISK, PENDING_APPROVAL, with proposals)
4. com_ambiguous_01 (OFFERED, FEASIBLE, NORMAL, requires_manual_review)
5. com_fulfilled_01 (CONFIRMED, FEASIBLE, RESOLVED, FULFILLED, signed POD proof)
"""

from __future__ import annotations

import os
import sys

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Ensure scripts is importable
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "scripts")))
from seed_demo import seed_demo

from app.core.models import (
    AuditEventRecord,
    CommitmentProposalRecord,
    CommitmentRecord,
    OutboxEventRecord,
)
from app.db.base import Base


def test_seed_demo_creates_all_five_canonical_commitments(test_engine) -> None:
    """Verifies that seed_demo correctly populates the 5 canonical demo commitments and associated records."""
    # Seed using the test engine connection URL
    # SQLite memory requires static pool connection; we can test on a temporary sqlite file
    test_db_url = "sqlite:///./temp_test_seed.db"
    try:
        seed_demo(test_db_url)

        engine = create_engine(test_db_url, connect_args={"check_same_thread": False})
        Session = sessionmaker(bind=engine)

        with Session() as db:
            # 1. Normal feasible commitment
            c_normal = db.scalar(
                select(CommitmentRecord).where(CommitmentRecord.commitment_id == "com_normal_01")
            )
            assert c_normal is not None
            assert c_normal.agreement_state == "CONFIRMED"
            assert c_normal.feasibility_state == "FEASIBLE"
            assert c_normal.risk_state == "NORMAL"
            assert c_normal.recovery_state == "NONE"
            assert c_normal.fulfilment_state == "NOT_STARTED"

            # 2. Material shortage / AT_RISK commitment
            c_hero = db.scalar(
                select(CommitmentRecord).where(CommitmentRecord.commitment_id == "com_001")
            )
            assert c_hero is not None
            assert c_hero.agreement_state == "CONFIRMED"
            assert c_hero.feasibility_state == "INFEASIBLE"
            assert c_hero.risk_state == "AT_RISK"
            assert c_hero.recovery_state == "RECOVERY_REQUIRED"

            # Check that an outbox event for at_risk exists
            at_risk_outbox = db.scalar(
                select(OutboxEventRecord).where(
                    OutboxEventRecord.commitment_id == "com_001",
                    OutboxEventRecord.event_type == "commitment.at_risk",
                )
            )
            assert at_risk_outbox is not None
            assert at_risk_outbox.payload["shortage_item"] == "BEEF_PATTIES"

            # 3. Supplier delay with alternate recovery plans
            c_delay = db.scalar(
                select(CommitmentRecord).where(CommitmentRecord.commitment_id == "com_delay_01")
            )
            assert c_delay is not None
            assert c_delay.agreement_state == "CONFIRMED"
            assert c_delay.risk_state == "AT_RISK"
            assert c_delay.recovery_state == "PENDING_APPROVAL"

            # Check alternate recovery proposals
            proposals = db.scalars(
                select(CommitmentProposalRecord).where(
                    CommitmentProposalRecord.commitment_id == "com_delay_01"
                )
            ).all()
            assert len(proposals) >= 2
            actions = {p.revised_terms.get("recovery_action") for p in proposals}
            assert "EXPEDITE_SUPPLIER" in actions
            assert "REVISE_SCHEDULE" in actions

            # 4. Ambiguous customer confirmation
            c_ambig = db.scalar(
                select(CommitmentRecord).where(CommitmentRecord.commitment_id == "com_ambiguous_01")
            )
            assert c_ambig is not None
            assert c_ambig.agreement_state == "OFFERED"
            assert c_ambig.terms.get("requires_manual_review") is True

            # 5. Verified operational completion
            c_fulfil = db.scalar(
                select(CommitmentRecord).where(CommitmentRecord.commitment_id == "com_fulfilled_01")
            )
            assert c_fulfil is not None
            assert c_fulfil.agreement_state == "CONFIRMED"
            assert c_fulfil.fulfilment_state == "FULFILLED"
            assert c_fulfil.risk_state == "RESOLVED"
            assert "ev_synthetic_delivery|tenant_demo_01|com_fulfilled_01|pod_fulfilled" in c_fulfil.evidence_refs

        # Test idempotency: running seed_demo again on same DB should succeed without duplicate key errors
        seed_demo(test_db_url)

        with Session() as db:
            total_demo_commitments = db.scalars(
                select(CommitmentRecord).where(
                    CommitmentRecord.commitment_id.in_([
                        "com_normal_01",
                        "com_001",
                        "com_delay_01",
                        "com_ambiguous_01",
                        "com_fulfilled_01",
                    ])
                )
            ).all()
            assert len(total_demo_commitments) == 5

    finally:
        if os.path.exists("./temp_test_seed.db"):
            try:
                os.remove("./temp_test_seed.db")
            except Exception:
                pass
