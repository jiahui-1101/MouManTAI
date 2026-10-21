"""P1 document and attachment schemas for bounded document extraction and OCR."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Identifier = Annotated[str, StringConstraints(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_\-\.:]+$")]


class P1DocModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)


class BoundingBox(P1DocModel):
    """Bounding box coordinates [x0, y0, x1, y1] normalized or in points/pixels."""
    x0: float
    y0: float
    x1: float
    y1: float


class DocumentEvidence(P1DocModel):
    """Traceable evidence extracted from a document page, distinct from message text spans."""
    evidence_id: Identifier
    evidence_ref: Identifier
    attachment_id: Identifier
    page_number: int = Field(ge=1, description="1-indexed page number where the text appears")
    quote: str = Field(min_length=1, description="Exact text snippet recognized from document or OCR")
    bounding_box: BoundingBox | None = None
    method: Literal["PDF_TEXT", "OCR"]
    method_version: Identifier
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    is_payment_evidence: bool = Field(default=False, description="Whether this evidence comes from a payment screenshot or bank receipt")


class AttachmentRecord(P1DocModel):
    """Metadata record for a stored attachment."""
    attachment_id: Identifier
    tenant_id: Identifier
    evidence_ref: Identifier
    filename: str = Field(min_length=1, max_length=255)
    media_type: str = Field(min_length=1, max_length=100)
    size_bytes: int = Field(ge=0, le=25_000_000)
    content_sha256: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DocumentExtractionResult(P1DocModel):
    """Result of document parsing or OCR on an attachment."""
    attachment_id: Identifier
    evidence_ref: Identifier
    status: Literal["SUCCESS", "PARTIAL", "FAILED", "UNSUPPORTED"]
    document_type: Literal["PDF", "IMAGE", "UNKNOWN"]
    page_count: int = Field(ge=0)
    text_content: str = Field(default="", max_length=100_000)
    extracted_fields: list[dict] = Field(default_factory=list)
    evidence_items: list[DocumentEvidence] = Field(default_factory=list)
    is_payment_notice: bool = Field(default=False)
    diagnostic: str | None = None
    extracted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
