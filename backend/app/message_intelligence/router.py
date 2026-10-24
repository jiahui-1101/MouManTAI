"""C3 evidence and classification-only decisions for the isolated demo admin."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.context.postgres_repository import PostgresMessageRepository
from app.core.dependencies import RequestContext, get_db, get_request_context
from app.core.errors import DomainError
from app.core.manager_approval import trusted_isolated_manager
from app.feasibility.api_dependencies import require_isolated_e2e_key

from .adapters import CurrentP1MessageReader
from .review import C3ReviewService, ReviewDecision, ReviewGrant
from .review_models import C3ReviewRecord
from .service import SourceContractError

router = APIRouter(prefix="/v1/c3/reviews", tags=["C3 review"])


def _tenant(_: None = Depends(require_isolated_e2e_key)) -> str:
    if (os.getenv("MOUMANTAI_ISOLATED_E2E") != "1"
        or os.getenv("MOUMANTAI_SYNTHETIC_MODE") != "1"
        or os.getenv("ENVIRONMENT", "").lower() in {"production", "prod"}
        or os.getenv("APP_ENV", "").lower() in {"production", "prod"}):
        raise DomainError("C3_REVIEW_UNAVAILABLE", "Trusted review identity is unavailable", status_code=503)
    tenant_id = os.getenv("MOUMANTAI_ISOLATED_E2E_TENANT_ID", "")
    if not tenant_id:
        raise DomainError("C3_REVIEW_UNAVAILABLE", "Isolated review tenant is not configured", status_code=503)
    return tenant_id


def _view(row: C3ReviewRecord) -> dict:
    return {
        "review_id": row.review_id,
        "message_id": row.message_id,
        "state": row.state,
        "revision": row.revision,
        "created_at": row.created_at,
        "reason_codes": row.reason_codes,
        "source": row.source_snapshot,
        "candidate": row.candidate_snapshot,
        "provider_attempts": row.provider_attempts,
        "decision": row.decision,
        "corrected_intent": row.corrected_intent,
        "decision_reason": row.decision_reason,
        "reviewer_id": row.reviewer_id,
        "decided_at": row.decided_at,
        "authorization_evidence_refs": row.authorization_evidence_refs,
        "decision_authority_available": os.getenv("MOUMANTAI_DEMO_ADMIN_AUTH") == "1",
    }


@router.get("")
def list_c3_reviews(
    tenant_id: Annotated[str, Depends(_tenant)],
    db: Annotated[Session, Depends(get_db)],
    state: Annotated[str, Query(pattern="^(PENDING|DECIDED)$")] = "PENDING",
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    condition = (C3ReviewRecord.tenant_id == tenant_id) & (C3ReviewRecord.state == state)
    total = db.scalar(select(func.count()).select_from(C3ReviewRecord).where(condition)) or 0
    rows = db.scalars(select(C3ReviewRecord).where(condition)
                      .order_by(C3ReviewRecord.created_at.desc(), C3ReviewRecord.review_id)
                      .limit(limit).offset(offset)).all()
    return {"items": [_view(row) for row in rows], "total": total, "mode": "SYNTHETIC_READ_ONLY"}


@router.get("/{review_id}")
def get_c3_review(review_id: str, tenant_id: Annotated[str, Depends(_tenant)],
                  db: Annotated[Session, Depends(get_db)]) -> dict:
    row = db.scalar(select(C3ReviewRecord).where(
        C3ReviewRecord.tenant_id == tenant_id, C3ReviewRecord.review_id == review_id))
    if row is None:
        raise HTTPException(status_code=404, detail="C3 review unavailable")
    return _view(row)


class _TenantScope:
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id

    def current_verified_tenant_id(self) -> str:
        return self.tenant_id


class _DemoReviewAuthority:
    def __init__(self, key: str):
        self.key = key

    def authorize(self, db: Session, context: RequestContext, *,
                  review_id: str, action: str) -> ReviewGrant | None:
        manager_id = trusted_isolated_manager(context, self.key)
        return ReviewGrant(
            tenant_id=context.tenant_id, actor_id=manager_id, action=action,
            evidence_refs=(f"demo_admin:{manager_id}:c3_classification_v1",),
            expires_at=datetime.now(UTC) + timedelta(minutes=1),
        )


@router.post("/{review_id}/decide")
def decide_c3_review(
    review_id: str, command: ReviewDecision,
    tenant_id: Annotated[str, Depends(_tenant)],
    context: Annotated[RequestContext, Depends(get_request_context)],
    db: Annotated[Session, Depends(get_db)],
    x_isolated_e2e_key: Annotated[str | None, Header()] = None,
) -> dict:
    if os.getenv("MOUMANTAI_DEMO_ADMIN_AUTH") != "1":
        raise DomainError("C3_DECISION_UNAVAILABLE", "Demo Admin decision authority is disabled", status_code=503)
    if context.tenant_id != tenant_id:
        raise DomainError("TENANT_SCOPE_MISMATCH", "Review tenant is outside this demo", status_code=403)
    trusted_isolated_manager(context, x_isolated_e2e_key)
    trusted_context = RequestContext(tenant_id, context.actor_id, "MANAGER", context.correlation_id)
    reader = CurrentP1MessageReader(PostgresMessageRepository(db.get_bind()), _TenantScope(tenant_id))
    try:
        row = C3ReviewService(db, reader, _DemoReviewAuthority(x_isolated_e2e_key or "")).decide(
            trusted_context, review_id, command, now=datetime.now(UTC))
    except SourceContractError as exc:
        db.rollback()
        raise DomainError("C3_REVIEW_CONFLICT", str(exc), status_code=409) from exc
    return _view(row)
