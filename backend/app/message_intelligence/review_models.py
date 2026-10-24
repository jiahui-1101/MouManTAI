"""C3-owned review storage; no foreign business aggregate or send authority."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class C3ReviewRecord(Base):
    __tablename__ = "c3_message_reviews"

    tenant_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    review_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    message_id: Mapped[str] = mapped_column(String(200), nullable=False)
    candidate_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    candidate_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    provider_attempts: Mapped[list] = mapped_column(JSON, nullable=False)
    reason_codes: Mapped[list] = mapped_column(JSON, nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision: Mapped[str | None] = mapped_column(String(24))
    corrected_intent: Mapped[str | None] = mapped_column(String(40))
    decision_reason: Mapped[str | None] = mapped_column(String(1000))
    reviewer_id: Mapped[str | None] = mapped_column(String(128))
    reviewer_role: Mapped[str | None] = mapped_column(String(32))
    authorization_evidence_refs: Mapped[list | None] = mapped_column(JSON)
    request_key: Mapped[str | None] = mapped_column(String(128))

    __table_args__ = (
        UniqueConstraint("tenant_id", "message_id", "candidate_hash", name="uq_c3_review_candidate"),
        UniqueConstraint("tenant_id", "request_key", name="uq_c3_review_request_key"),
        Index("ix_c3_review_queue", "tenant_id", "state", "created_at"),
    )
