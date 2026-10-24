"""Read-only C3 evidence for the isolated, synthetic operator session.

Decision commands remain in C3ReviewService until P5 supplies a trusted
operator identity and C3ReviewAuthority. Browser headers grant no authority.
"""

from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.errors import DomainError
from app.feasibility.api_dependencies import require_isolated_e2e_key

from .review_models import C3ReviewRecord

router = APIRouter(prefix="/v1/c3/reviews", tags=["C3 review"])


def _tenant(_: None = Depends(require_isolated_e2e_key)) -> str:
    if (os.getenv("MOUMANTAI_ISOLATED_E2E") != "1"
        or os.getenv("MOUMANTAI_SYNTHETIC_MODE") != "1"
        or os.getenv("ENVIRONMENT", "").lower() in {"production", "prod"}):
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
        "decision_authority_available": False,
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
