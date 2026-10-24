"""Advisory SME quote selection preview; never persists a decision."""

from typing import Literal

from pydantic import Field

from app.orders.terms import ImmutableContract, Text
from app.sourcing.dossier import DossierEntry


class SelectionRequest(ImmutableContract):
    tenant_id: Text
    sourcing_case_id: Text
    requirement_id: Text
    requirement_version: int = Field(ge=1, strict=True)
    supplier_id: Text
    quote_id: Text
    quote_version: int = Field(ge=1, strict=True)
    spec_version: int = Field(ge=1, strict=True)
    reason_draft: Text
    source_context_version: Text
    current_source_context_version: Text


class SelectionPreview(ImmutableContract):
    tenant_id: Text
    sourcing_case_id: Text
    requirement_id: Text
    requirement_version: int = Field(ge=1, strict=True)
    supplier_id: Text
    quote_id: Text
    quote_version: int = Field(ge=1, strict=True)
    spec_version: int = Field(ge=1, strict=True)
    canonical_status: Text
    evidence_refs: tuple[Text, ...]
    historical_on_time_rate: str | None
    reason_draft: Text
    source_context_version: Text
    current_source_context_version: Text
    outstanding_risks: tuple[Text, ...]
    required_authorization: tuple[Text, ...]
    advisory_status: Literal["PREVIEW_ONLY"] = "PREVIEW_ONLY"


def preview_selection(request: SelectionRequest, entry: DossierEntry) -> SelectionPreview:
    if (
        request.tenant_id,
        request.supplier_id,
        request.quote_id,
        request.quote_version,
        request.spec_version,
    ) != (
        entry.tenant_id,
        entry.supplier_id,
        entry.quote_id,
        entry.quote_version,
        entry.spec_version,
    ):
        raise ValueError("Selected quote or specification version mismatch")
    risks = set(entry.reason_codes) | set(entry.missing_information) | set(entry.source_limitations)
    if request.source_context_version != request.current_source_context_version:
        risks.add("STALE_SOURCE_CONTEXT")
    if entry.canonical_status != "MATCHES":
        risks.add("QUOTE_NOT_VERIFIED_MATCH")
    return SelectionPreview(
        tenant_id=request.tenant_id,
        sourcing_case_id=request.sourcing_case_id,
        requirement_id=request.requirement_id,
        requirement_version=request.requirement_version,
        supplier_id=entry.supplier_id,
        quote_id=entry.quote_id,
        quote_version=entry.quote_version,
        spec_version=entry.spec_version,
        canonical_status=entry.canonical_status,
        evidence_refs=entry.evidence_refs,
        historical_on_time_rate=str(entry.historical_on_time_rate)
        if entry.historical_on_time_rate is not None
        else None,
        reason_draft=request.reason_draft,
        source_context_version=request.source_context_version,
        current_source_context_version=request.current_source_context_version,
        outstanding_risks=tuple(sorted(risks)),
        required_authorization=(
            "AUTHENTICATED_SME_SELECTION",
            "CURRENT_VERSION_CHECK",
            "OWNER_APPROVED_SELECTION_WRITE_PORT",
            "PURCHASE_AUTHORIZATION_SEPARATE",
        ),
    )
