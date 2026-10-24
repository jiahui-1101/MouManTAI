"""Durable, inert C3 review queue over current P1 source evidence.

Approval confirms only a human classification decision. It grants no Orders,
P2, Recovery or Communication command authority.
"""

from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256
from typing import Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext

from .adapters import CurrentP1MessageReader
from .contracts import HumanReviewCandidate, Intent, SourceMessageReference
from .review_models import C3ReviewRecord
from .service import MessageIntelligenceService, SourceContractError


class ReviewGrant(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    tenant_id: str
    actor_id: str
    action: Literal["READ", "APPROVE", "REJECT", "CORRECT"]
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    expires_at: datetime


class C3ReviewAuthority(Protocol):
    def authorize(self, db: Session, context: RequestContext, *,
                  review_id: str, action: str) -> ReviewGrant | None: ...


class ReviewDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["APPROVE", "REJECT", "CORRECT"]
    expected_revision: int = Field(ge=1)
    request_key: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=1000)
    corrected_intent: Intent | None = None

    def model_post_init(self, __context, /):
        if (self.action == "CORRECT") != (self.corrected_intent is not None):
            raise ValueError("only CORRECT requires a corrected intent")


class C3ReviewService:
    def __init__(self, db: Session, reader: CurrentP1MessageReader,
                 authority: C3ReviewAuthority | None = None):
        self.db, self.reader, self.authority = db, reader, authority

    def enqueue(self, message_id: str, classifier: MessageIntelligenceService,
                *, now: datetime) -> C3ReviewRecord | None:
        """Recompute from current P1 records; callers cannot submit model provenance."""
        outcome = self.reader.analyze(message_id, classifier, now=now)
        candidate = outcome.human_review_candidate
        if candidate is None:
            return None
        self.reader.assert_current(candidate.source, evidence=tuple(candidate.evidence))
        if candidate.tenant_id != self.reader.scope.current_verified_tenant_id():
            raise SourceContractError("review tenant does not match verified scope")
        snapshot = candidate.model_dump(mode="json")
        digest = sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        existing = self.db.scalar(select(C3ReviewRecord).where(
            C3ReviewRecord.tenant_id == candidate.tenant_id,
            C3ReviewRecord.message_id == message_id,
            C3ReviewRecord.candidate_hash == digest,
        ))
        if existing:
            return existing
        row = C3ReviewRecord(
            tenant_id=candidate.tenant_id, review_id=f"c3review_{uuid4().hex}",
            message_id=message_id, candidate_hash=digest,
            source_sha256=candidate.source.content_sha256,
            source_snapshot=candidate.source.model_dump(mode="json"),
            candidate_snapshot=snapshot,
            provider_attempts=[item.model_dump(mode="json") for item in outcome.provider_attempts],
            reason_codes=candidate.review_reasons, state="PENDING", revision=1,
            created_at=now,
        )
        self.db.add(row)
        self.db.commit()
        return row

    def decide(self, context: RequestContext, review_id: str,
               command: ReviewDecision, *, now: datetime) -> C3ReviewRecord:
        if now.tzinfo is None or now.utcoffset() is None:
            raise SourceContractError("review time must be offset-aware")
        if self.authority is None:
            raise SourceContractError("trusted C3 review authority is unavailable")
        row = self.db.scalar(select(C3ReviewRecord).where(
            C3ReviewRecord.tenant_id == context.tenant_id,
            C3ReviewRecord.review_id == review_id,
        ).with_for_update())
        if row is None:
            raise SourceContractError("review is unavailable in this tenant")
        grant = self.authority.authorize(
            self.db, context, review_id=review_id, action=command.action,
        )
        if (not isinstance(grant, ReviewGrant)
            or grant.tenant_id != context.tenant_id
            or grant.actor_id != context.actor_id
            or grant.action != command.action
            or grant.expires_at.tzinfo is None
            or grant.expires_at <= now):
            raise SourceContractError("review authorization is absent or out of scope")
        if row.state != "PENDING" or row.revision != command.expected_revision:
            raise SourceContractError("review decision or version is stale")
        if self.db.scalar(select(C3ReviewRecord.review_id).where(
            C3ReviewRecord.tenant_id == context.tenant_id,
            C3ReviewRecord.request_key == command.request_key,
        )) is not None:
            raise SourceContractError("review request key has already been used")
        digest = sha256(json.dumps(row.candidate_snapshot, sort_keys=True,
                                   separators=(",", ":")).encode()).hexdigest()
        if digest != row.candidate_hash:
            raise SourceContractError("stored review candidate integrity is invalid")
        source = SourceMessageReference.model_validate_json(json.dumps(row.source_snapshot))
        candidate = HumanReviewCandidate.model_validate_json(json.dumps(row.candidate_snapshot))
        if candidate.source != source or source.tenant_id != context.tenant_id:
            raise SourceContractError("review source binding is invalid")
        self.reader.assert_current(source, evidence=tuple(candidate.evidence))
        row.state = "DECIDED"
        row.revision += 1
        row.decision = command.action
        row.corrected_intent = command.corrected_intent
        row.decision_reason = command.reason
        row.reviewer_id = context.actor_id
        row.reviewer_role = context.actor_role
        row.authorization_evidence_refs = list(grant.evidence_refs)
        row.request_key = command.request_key
        row.decided_at = now
        self.db.commit()
        return row
