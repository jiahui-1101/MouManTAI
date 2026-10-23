"""Tests for bounded, traceable machine-readable PDF extraction using PyMuPDF."""

import io
from typing import Sequence
import pytest

pymupdf = pytest.importorskip("pymupdf", reason="pymupdf is required for PDF extraction tests")
from fastapi.testclient import TestClient

from app.context.dependencies import development_context, local_repository
from app.context.dev_app import app
from app.context.document_extractor import (
    MAX_PDF_PAGES,
    PDF_EXTRACTOR_VERSION,
    extract_pdf_document,
)
from app.context.document_schemas import AttachmentRecord
from app.context.ingestion_schemas import DevelopmentContext
from app.context.postgres_repository import PostgresMessageRepository


import os
from app.context.dev_database import create_p1_engine, initialize_p1_schema


@pytest.fixture(scope="module")
def shared_repo():
    url = os.environ.get("P1_DATABASE_URL")
    if not url:
        pytest.skip("P1_DATABASE_URL not set")
    try:
        engine = create_p1_engine(url)
        initialize_p1_schema(engine)
        return PostgresMessageRepository(engine)
    except Exception as exc:
        pytest.skip(f"P1 database unavailable: {exc}")


def create_synthetic_pdf(pages_text: Sequence[str]) -> bytes:
    """Create in-memory PDF with real text blocks using PyMuPDF."""
    doc = pymupdf.open()
    for text in pages_text:
        page = doc.new_page()
        page.insert_text((50, 72), text, fontsize=12)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def test_pdf_machine_readable_order_extraction():
    pdf_text = (
        "Purchase Order PO-2026-901\n"
        "Delivery Date: 2026-11-15\n"
        "Please deliver 50 pcs burgers to Main Store\n"
    )
    pdf_bytes = create_synthetic_pdf([pdf_text])

    att = AttachmentRecord(
        attachment_id="att_pdf_01",
        tenant_id="synthetic_tenant_a",
        evidence_ref="ev_att_pdf_01",
        filename="order_po.pdf",
        media_type="application/pdf",
        size_bytes=len(pdf_bytes),
        content_sha256="0" * 64,
    )

    result = extract_pdf_document(att, pdf_bytes)

    assert result.status == "SUCCESS"
    assert result.document_type == "PDF"
    assert result.page_count == 1
    assert "PO-2026-901" in result.text_content
    assert not result.is_payment_notice
    assert result.diagnostic is None

    # Check evidence items
    assert len(result.evidence_items) >= 1
    ev = result.evidence_items[0]
    assert ev.page_number == 1
    assert ev.method == "PDF_TEXT"
    assert ev.method_version == PDF_EXTRACTOR_VERSION
    assert ev.confidence == 1.0
    assert not ev.is_payment_evidence
    assert ev.bounding_box is not None
    assert ev.bounding_box.x0 >= 0

    # Check extracted fields
    order_fields = [f for f in result.extracted_fields if f["field_name"] == "order_id"]
    assert len(order_fields) == 1
    assert order_fields[0]["value"] == "PO-2026-901"
    assert order_fields[0]["page_number"] == 1

    date_fields = [f for f in result.extracted_fields if f["field_name"] == "requested_delivery_at"]
    assert len(date_fields) == 1
    assert date_fields[0]["value"] == "2026-11-15"

    item_fields = [f for f in result.extracted_fields if f["field_name"] == "item"]
    assert len(item_fields) == 1
    assert item_fields[0]["quantity"] == 50
    assert item_fields[0]["sku"] == "BURGER"


def test_pdf_payment_notice_flagging():
    pdf_text = (
        "Maybank DuitNow Transfer Successful\n"
        "Amount RM 350.00\n"
        "Recipient: Supplier Sdn Bhd\n"
        "Reference: DUITNOW-892183\n"
        "Date: 2026-10-21\n"
    )
    pdf_bytes = create_synthetic_pdf([pdf_text])

    att = AttachmentRecord(
        attachment_id="att_bank_slip",
        tenant_id="synthetic_tenant_a",
        evidence_ref="ev_att_bank_slip",
        filename="bank_slip.pdf",
        media_type="application/pdf",
        size_bytes=len(pdf_bytes),
        content_sha256="0" * 64,
    )

    result = extract_pdf_document(att, pdf_bytes)

    assert result.status == "SUCCESS"
    assert result.is_payment_notice is True

    # All evidence must be flagged as payment evidence
    for ev in result.evidence_items:
        assert ev.is_payment_evidence is True

    # Payment field must have UNVERIFIED_EVIDENCE and explicit disclaimer
    pmt_fields = [f for f in result.extracted_fields if f["field_name"] == "payment_notice"]
    assert len(pmt_fields) == 1
    assert pmt_fields[0]["validation_status"] == "UNVERIFIED_EVIDENCE"
    assert "strictly unverified" in pmt_fields[0]["disclaimer"].lower()


def test_pdf_page_count_bounding():
    # Create 12 pages (> MAX_PDF_PAGES = 10)
    pages = [f"Page {i+1} content with ORD-{1000+i}" for i in range(12)]
    pdf_bytes = create_synthetic_pdf(pages)

    att = AttachmentRecord(
        attachment_id="att_long_pdf",
        tenant_id="synthetic_tenant_a",
        evidence_ref="ev_att_long_pdf",
        filename="long_catalog.pdf",
        media_type="application/pdf",
        size_bytes=len(pdf_bytes),
        content_sha256="0" * 64,
    )

    result = extract_pdf_document(att, pdf_bytes, max_pages=10)

    assert result.page_count == 12
    assert result.status == "PARTIAL"
    assert "bounded processing inspected first 10 pages" in result.diagnostic.lower()

    # Evidence should only contain pages <= 10
    pages_seen = {ev.page_number for ev in result.evidence_items}
    assert max(pages_seen) <= 10


def test_pdf_scanned_or_empty_detection():
    # Blank PDF with no text blocks
    doc = pymupdf.open()
    doc.new_page()  # empty page
    pdf_bytes = doc.tobytes()
    doc.close()

    att = AttachmentRecord(
        attachment_id="att_blank_pdf",
        tenant_id="synthetic_tenant_a",
        evidence_ref="ev_att_blank_pdf",
        filename="scanned.pdf",
        media_type="application/pdf",
        size_bytes=len(pdf_bytes),
        content_sha256="0" * 64,
    )

    result = extract_pdf_document(att, pdf_bytes)

    assert result.status == "SUCCESS"
    assert "scanned or image-only" in result.diagnostic.lower()
    assert result.evidence_items == []


def test_pdf_extraction_api_and_persistence(shared_repo):
    tenant = DevelopmentContext(
        tenant_id="tenant_pdf_api_test",
        mode="LOCAL_SYNTHETIC_ONLY",
        implemented_channel="WHATSAPP",
        authentication="NOT_IMPLEMENTED",
    )
    app.dependency_overrides[development_context] = lambda: tenant
    app.dependency_overrides[local_repository] = lambda: shared_repo

    client = TestClient(app)

    # 1. Upload PDF
    pdf_bytes = create_synthetic_pdf(["Purchase Order ORD-5544\n20 burgers\n2026-12-01"])
    upload_res = client.post(
        "/v1/attachments/upload",
        files={"file": ("po_5544.pdf", pdf_bytes, "application/pdf")},
    )
    assert upload_res.status_code == 201
    ev_ref = upload_res.json()["evidence_ref"]

    # 2. Extract Document
    extract_res = client.post(f"/v1/attachments/{ev_ref}/extract")
    assert extract_res.status_code == 200
    data = extract_res.json()
    assert data["status"] == "SUCCESS"
    assert data["document_type"] == "PDF"
    assert len(data["extracted_fields"]) >= 2
    assert any(f["value"] == "ORD-5544" for f in data["extracted_fields"])

    # 3. Retrieve Persisted Extraction
    get_res = client.get(f"/v1/attachments/{ev_ref}/extraction")
    assert get_res.status_code == 200
    assert get_res.json()["evidence_ref"] == ev_ref
    assert get_res.json()["status"] == "SUCCESS"

    # 4. Tenant isolation: different tenant cannot access extraction
    other_tenant = DevelopmentContext(
        tenant_id="tenant_stranger",
        mode="LOCAL_SYNTHETIC_ONLY",
        implemented_channel="WHATSAPP",
        authentication="NOT_IMPLEMENTED",
    )
    app.dependency_overrides[development_context] = lambda: other_tenant
    stranger_res = client.get(f"/v1/attachments/{ev_ref}/extraction")
    assert stranger_res.status_code == 404


def test_scanned_purchase_order_pdf_ocr_fallback():
    pdf_path = os.path.join("output", "pdf", "promiseflow_p1_synthetic_scanned_purchase_order.pdf")
    if not os.path.exists(pdf_path):
        pytest.skip(f"Scanned fixture {pdf_path} not found")

    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    att = AttachmentRecord(
        attachment_id="att_scanned_po_01",
        tenant_id="synthetic_tenant_a",
        evidence_ref="ev_att_scanned_po_01",
        filename="promiseflow_p1_synthetic_scanned_purchase_order.pdf",
        media_type="application/pdf",
        size_bytes=len(pdf_bytes),
        content_sha256="0" * 64,
    )

    result = extract_pdf_document(att, pdf_bytes)

    assert result.status == "SUCCESS"
    assert "ocr" in result.diagnostic.lower() or "image-only" in result.diagnostic.lower()
    assert len(result.evidence_items) > 0
    assert any(ev.method == "OCR" for ev in result.evidence_items)

    field_map = {f["field_name"]: f.get("value") for f in result.extracted_fields}
    assert "order_id" in field_map
    assert "PO-DEMO-2026-1042" in field_map["order_id"]
    assert "requested_delivery_at" in field_map
    assert field_map["requested_delivery_at"] == "2026-10-26"

    item_fields = [f for f in result.extracted_fields if f.get("field_name") == "item"]
    assert len(item_fields) >= 1
    assert item_fields[0]["sku"] == "BURGER"
    assert item_fields[0]["quantity"] == 100

    assert "rescheduling_clause" in field_map
