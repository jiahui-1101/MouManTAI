from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.core.schemas import CommitmentTerms, CommunicationChannel
from app.communication.schemas import (
    CommunicationRequestView, RecoveryCommunicationReference, RequestStatus,
)
from app.communication.service import CommunicationRequestService


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'test_origin.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def make_view():
    def _builder(channel=CommunicationChannel.MOCK_EMAIL, commitment_id="com_001", source_origin=None, delivery_mode=None):
        now = datetime.now(timezone.utc)
        return CommunicationRequestView(
            communication_id="comm_test_origin",
            reference=RecoveryCommunicationReference(
                source_event_id="evt_01",
                tenant_id="synthetic_tenant_a",
                correlation_id="corr_01",
                causation_id=None,
                occurred_at=now,
                commitment_id=commitment_id,
                commitment_version=1,
                plan_id="plan_01",
                plan_version=1,
                proposal_id="prop_01",
                proposal_version=1,
            ),
            request_status=RequestStatus.READY_FOR_DRAFTING,
            blocking_reasons=[],
            proposed_terms=CommitmentTerms(sku="BURGER_DELUXE", quantity="10", unit="pcs", deadline=now),
            approval_evidence_refs=["ev_app_01"],
            approval_expires_at=now,
            proposal_evidence_refs=["ev_prop_01"],
            recipient_identity_id="identity_cust_01",
            recipient_evidence_refs=["ev_rec_01"],
            channel=channel,
            channel_evidence_refs=["ev_chan_01"],
            expires_at=now,
            created_by="user_01",
            created_at=now,
            outbound_status=None,
            source_origin=source_origin,
            delivery_mode=delivery_mode,
        )
    return _builder


def test_mock_channels_resolve_to_synthetic_origin(db, make_view):
    service = CommunicationRequestService(db, None)

    view_email = make_view(channel=CommunicationChannel.MOCK_EMAIL)
    projected_email = service._with_outbound(view_email)
    assert projected_email.source_origin == "SYNTHETIC"
    assert projected_email.delivery_mode == "SIMULATED"

    view_wa = make_view(channel=CommunicationChannel.MOCK_WHATSAPP)
    projected_wa = service._with_outbound(view_wa)
    assert projected_wa.source_origin == "SYNTHETIC"
    assert projected_wa.delivery_mode == "SIMULATED"

    view_tg = make_view(channel=CommunicationChannel.MOCK_TELEGRAM)
    projected_tg = service._with_outbound(view_tg)
    assert projected_tg.source_origin == "SYNTHETIC"
    assert projected_tg.delivery_mode == "SIMULATED"


def test_real_channels_resolve_to_exact_origin(db, make_view):
    service = CommunicationRequestService(db, None)

    view_gmail = make_view(channel=CommunicationChannel.GMAIL)
    assert service._with_outbound(view_gmail).source_origin == "GMAIL"

    view_email = make_view(channel=CommunicationChannel.EMAIL)
    assert service._with_outbound(view_email).source_origin == "GMAIL"

    view_tg = make_view(channel=CommunicationChannel.TELEGRAM)
    assert service._with_outbound(view_tg).source_origin == "TELEGRAM"

    view_wa = make_view(channel=CommunicationChannel.WHATSAPP)
    assert service._with_outbound(view_wa).source_origin == "WHATSAPP"


def test_explicit_source_origin_and_delivery_mode_preserved(db, make_view):
    service = CommunicationRequestService(db, None)

    # Real Gmail case using simulated sending
    view = make_view(channel=CommunicationChannel.GMAIL, source_origin="GMAIL", delivery_mode="SIMULATED")
    projected = service._with_outbound(view)
    assert projected.source_origin == "GMAIL"
    assert projected.delivery_mode == "SIMULATED"

    # Real Gmail case using real delivery
    view_real = make_view(channel=CommunicationChannel.GMAIL, source_origin="GMAIL", delivery_mode="REAL")
    projected_real = service._with_outbound(view_real)
    assert projected_real.source_origin == "GMAIL"
    assert projected_real.delivery_mode == "REAL"
