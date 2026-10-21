"""SQLAlchemy repository only; never creates tables or substitutes a memory dictionary."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import CommunicationRequestRecord, CommunicationSourceEventRecord
from .schemas import CommunicationRequestView, RecoveryCommunicationReference, RequestStatus


class CommunicationRequestRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, tenant_id: str, communication_id: str) -> CommunicationRequestRecord | None:
        return self.db.get(CommunicationRequestRecord, (tenant_id, communication_id))

    def by_event(self, tenant_id: str, event_id: str) -> CommunicationRequestRecord | None:
        source = self.db.get(CommunicationSourceEventRecord, (tenant_id, event_id))
        return self.get(tenant_id, source.communication_id) if source else None

    def by_proposal(self, ref: RecoveryCommunicationReference) -> CommunicationRequestRecord | None:
        return self.db.scalar(select(CommunicationRequestRecord).where(
            CommunicationRequestRecord.tenant_id == ref.tenant_id,
            CommunicationRequestRecord.commitment_id == ref.commitment_id,
            CommunicationRequestRecord.proposal_id == ref.proposal_id,
            CommunicationRequestRecord.proposal_version == ref.proposal_version,
        ))

    def list(
        self, tenant_id: str, commitment_id: str | None, request_status: RequestStatus | None,
    ) -> list[CommunicationRequestRecord]:
        query = select(CommunicationRequestRecord).where(
            CommunicationRequestRecord.tenant_id == tenant_id,
        )
        if commitment_id is not None:
            query = query.where(CommunicationRequestRecord.commitment_id == commitment_id)
        if request_status is not None:
            query = query.where(CommunicationRequestRecord.request_status == request_status.value)
        return list(self.db.scalars(query.order_by(
            CommunicationRequestRecord.created_at, CommunicationRequestRecord.communication_id,
        )))

    def add(self, view: CommunicationRequestView) -> CommunicationRequestRecord:
        record = CommunicationRequestRecord(
            tenant_id=view.reference.tenant_id, communication_id=view.communication_id,
            commitment_id=view.reference.commitment_id, proposal_id=view.reference.proposal_id,
            proposal_version=view.reference.proposal_version, request_status=view.request_status.value,
            snapshot=view.model_dump(mode="json"), created_at=view.created_at,
        )
        self.db.add(record)
        self.db.flush()
        return record

    def add_source(self, communication_id: str, ref: RecoveryCommunicationReference) -> None:
        self.db.add(CommunicationSourceEventRecord(
            tenant_id=ref.tenant_id, source_event_id=ref.source_event_id,
            communication_id=communication_id, correlation_id=ref.correlation_id,
            reference=ref.model_dump(mode="json"),
        ))
        self.db.flush()

    @staticmethod
    def view(record: CommunicationRequestRecord) -> CommunicationRequestView:
        return CommunicationRequestView.model_validate(record.snapshot)
