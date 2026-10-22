"""SQLAlchemy repository only; never creates tables or substitutes a memory dictionary."""

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from .models import CommunicationRequestRecord, CommunicationSourceEventRecord, DraftReviewRecord, MessageDraftRecord
from .schemas import CommunicationRequestView, DraftReviewDecision, MessageDraftView, RecoveryCommunicationReference, RequestStatus


class CommunicationRequestRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, tenant_id: str, communication_id: str) -> CommunicationRequestRecord | None:
        return self.db.get(CommunicationRequestRecord, (tenant_id, communication_id))

    def summary_counts(self, tenant_id: str) -> tuple[int, int]:
        # One row per request: languages/drafts never inflate these counts.
        total, blocked = self.db.execute(select(
            func.count(),
            func.coalesce(func.sum(case(
                (CommunicationRequestRecord.request_status == RequestStatus.BLOCKED.value, 1),
                else_=0,
            )), 0),
        ).select_from(CommunicationRequestRecord).where(
            CommunicationRequestRecord.tenant_id == tenant_id,
        )).one()
        return int(total), int(blocked)

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


class MessageDraftRepository:
    def __init__(self, db: Session):
        self.db = db

    def for_tenant(self, tenant_id: str) -> list[MessageDraftRecord]:
        return list(self.db.scalars(select(MessageDraftRecord).where(
            MessageDraftRecord.tenant_id == tenant_id,
        ).order_by(MessageDraftRecord.communication_id, MessageDraftRecord.draft_id)))

    def get(self, tenant_id: str, communication_id: str, draft_id: str, *, lock=False) -> MessageDraftRecord | None:
        query = select(MessageDraftRecord).where(
            MessageDraftRecord.tenant_id == tenant_id,
            MessageDraftRecord.communication_id == communication_id,
            MessageDraftRecord.draft_id == draft_id,
        )
        return self.db.scalar(query.with_for_update() if lock else query)

    def by_variant(self, tenant_id: str, communication_id: str, validation_hash: str):
        return self.db.scalar(select(MessageDraftRecord).where(
            MessageDraftRecord.tenant_id == tenant_id,
            MessageDraftRecord.communication_id == communication_id,
            MessageDraftRecord.validation_hash == validation_hash,
        ))

    def add(self, draft: MessageDraftView) -> None:
        self.db.add(MessageDraftRecord(
            tenant_id=draft.tenant_id, draft_id=draft.draft_id,
            communication_id=draft.communication_id, validation_hash=draft.validation_hash,
            snapshot=draft.model_dump(mode="json"), created_at=draft.created_at,
        ))
        self.db.flush()

    @staticmethod
    def view(record: MessageDraftRecord) -> MessageDraftView:
        return MessageDraftView.model_validate(record.snapshot)


class DraftReviewRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, tenant_id: str, communication_id: str, draft_id: str) -> DraftReviewRecord | None:
        return self.db.scalar(select(DraftReviewRecord).where(
            DraftReviewRecord.tenant_id == tenant_id,
            DraftReviewRecord.communication_id == communication_id,
            DraftReviewRecord.draft_id == draft_id,
        ).with_for_update())

    def by_key(self, tenant_id: str, request_key: str) -> DraftReviewRecord | None:
        return self.db.scalar(select(DraftReviewRecord).where(
            DraftReviewRecord.tenant_id == tenant_id, DraftReviewRecord.request_key == request_key,
        ))

    def add(self, decision: DraftReviewDecision) -> DraftReviewRecord:
        row = DraftReviewRecord(
            tenant_id=decision.tenant_id, review_id=decision.review_id,
            communication_id=decision.communication_id, draft_id=decision.draft_id,
            request_key=decision.request_key, snapshot=decision.model_dump(mode="json"),
            reviewed_at=decision.reviewed_at,
        )
        self.db.add(row)
        self.db.flush()
        return row

    @staticmethod
    def view(row: DraftReviewRecord) -> DraftReviewDecision:
        decision = DraftReviewDecision.model_validate(row.snapshot)
        if (decision.tenant_id, decision.review_id, decision.communication_id, decision.draft_id, decision.request_key) != (
            row.tenant_id, row.review_id, row.communication_id, row.draft_id, row.request_key,
        ):
            from app.core.errors import DomainError
            raise DomainError("REVIEW_INTEGRITY_ERROR", "Stored review target is inconsistent", status_code=409)
        return decision
