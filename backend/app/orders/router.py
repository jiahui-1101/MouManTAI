"""Explicitly isolated, read-only v2.2 validation/diagnostic previews.

No accept, reserve, approve, send or issue-transition endpoint is exposed.
Legacy static actor headers alone do not authorize these routes.
"""

import os
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header
from pydantic import Field
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext, get_db, get_request_context
from app.core.errors import DomainError
from app.core.manager_approval import trusted_isolated_manager
from app.orders.status import CommitmentStatusPreview, read_status_preview
from app.orders.terms import ImmutableContract, OrderTerms, TermsComparison, compare_terms, require_exact_terms


def isolated_preview_context(
    context: Annotated[RequestContext, Depends(get_request_context)],
    x_isolated_e2e_key: str | None = Header(default=None),
) -> RequestContext:
    if os.getenv("ENVIRONMENT", "").lower() == "production":
        raise DomainError("PREVIEW_DISABLED", "Synthetic previews are disabled in production", status_code=503)
    trusted_isolated_manager(context, x_isolated_e2e_key)
    return context


router = APIRouter(prefix="/v1/backend-v2", tags=["v2.2 synthetic read-only previews"])
Context = Annotated[RequestContext, Depends(isolated_preview_context)]


class TermsCheckRequest(ImmutableContract):
    original: OrderTerms
    proposed: OrderTerms
    expected_revision: int = Field(ge=1)
    expected_terms_hash: str


class TermsCheckResponse(ImmutableContract):
    comparison: TermsComparison
    source_verified: Literal[False] = False
    acceptance_enabled: Literal[False] = False
    integration_mode: Literal["SYNTHETIC"] = "SYNTHETIC"
    evidence_tier: Literal["DEMO-ONLY"] = "DEMO-ONLY"


@router.post("/terms/check", response_model=TermsCheckResponse)
def check_terms(command: TermsCheckRequest, context: Context) -> TermsCheckResponse:
    """Input consistency only: supplied original is NOT authenticated customer assent."""
    require_exact_terms(command.original, command.proposed, tenant_id=context.tenant_id,
                        expected_revision=command.expected_revision, expected_terms_hash=command.expected_terms_hash)
    return TermsCheckResponse(comparison=compare_terms(command.original, command.proposed))


@router.get("/commitments/{commitment_id}/status-preview", response_model=CommitmentStatusPreview)
def status_preview(commitment_id: str, context: Context,
                   db: Annotated[Session, Depends(get_db)]) -> CommitmentStatusPreview:
    return read_status_preview(db, context, commitment_id)
