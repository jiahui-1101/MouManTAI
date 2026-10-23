"""Tests for bounded, traceable image and scanned-document OCR using PaddleOCR."""

import io
import os
os.environ["FLAGS_use_mkldnn"] = "0"
os.environ["PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT"] = "False"
try:
    import paddle
    paddle.set_flags({"FLAGS_use_mkldnn": False})
except Exception:
    pass
import pytest

pytest.importorskip("numpy", reason="numpy is required for image OCR tests")
pytest.importorskip("paddleocr", reason="paddleocr is required for image OCR tests")
from PIL import Image, ImageDraw
from fastapi.testclient import TestClient

from app.context.dependencies import development_context, local_repository
from app.context.dev_app import app
from app.context.dev_database import create_p1_engine, initialize_p1_schema
from app.context.document_extractor import (
    OCR_EXTRACTOR_VERSION,
    extract_image_ocr,
)
from app.context.document_schemas import AttachmentRecord
from app.context.ingestion_schemas import DevelopmentContext
from app.context.postgres_repository import PostgresMessageRepository


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


def create_synthetic_image(text_lines: list[str], *, width: int = 400, height: int = 150) -> bytes:
    """Create in-memory PNG with text using PIL."""
    img = Image.new("RGB", (width, height), color="white")
    draw = ImageDraw.Draw(img)
    y = 20
    for line in text_lines:
        draw.text((20, y), line, fill="black")
        y += 35
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_image_ocr_order_extraction():
    img_bytes = create_synthetic_image([
        "PO-2026-888",
        "25 burgers",
        "Delivery 2026-11-20",
    ])

    att = AttachmentRecord(
        attachment_id="att_img_01",
        tenant_id="synthetic_tenant_a",
        evidence_ref="ev_att_img_01",
        filename="order_scan.png",
        media_type="image/png",
        size_bytes=len(img_bytes),
        content_sha256="0" * 64,
    )

    result = extract_image_ocr(att, img_bytes)

    assert result.status == "SUCCESS", f"Diagnostic: {result.diagnostic}"
    assert result.document_type == "IMAGE"
    assert result.page_count == 1
    assert not result.is_payment_notice
    assert len(result.evidence_items) >= 2

    # Check evidence item structure
    ev = result.evidence_items[0]
    assert ev.method == "OCR"
    assert ev.method_version == OCR_EXTRACTOR_VERSION
    assert ev.confidence is not None and ev.confidence > 0.0
    assert not ev.is_payment_evidence
    assert ev.bounding_box is not None

    # Check extracted fields
    order_fields = [f for f in result.extracted_fields if f["field_name"] == "order_id"]
    assert len(order_fields) == 1
    assert order_fields[0]["value"] == "PO-2026-888"

    item_fields = [f for f in result.extracted_fields if f["field_name"] == "item"]
    assert len(item_fields) == 1
    assert item_fields[0]["sku"] == "BURGER"
    assert item_fields[0]["quantity"] == 25

    date_fields = [f for f in result.extracted_fields if f["field_name"] == "requested_delivery_at"]
    assert len(date_fields) == 1
    assert date_fields[0]["value"] == "2026-11-20"


def test_image_ocr_payment_screenshot_guard():
    img_bytes = create_synthetic_image([
        "DuitNow Transfer Successful",
        "Amount RM 250.00",
        "Ref DUITNOW-77112",
    ])

    att = AttachmentRecord(
        attachment_id="att_receipt_img",
        tenant_id="tenant_ocr_test",
        evidence_ref="ev_att_receipt_img",
        filename="payment_slip.png",
        media_type="image/png",
        size_bytes=len(img_bytes),
        content_sha256="0" * 64,
    )

    result = extract_image_ocr(att, img_bytes)

    assert result.status == "SUCCESS", f"Diagnostic: {result.diagnostic}"
    assert result.is_payment_notice is True

    # Every evidence item must be tagged as payment evidence
    for ev in result.evidence_items:
        assert ev.is_payment_evidence is True

    # Payment notice field must be UNVERIFIED_EVIDENCE with explicit disclaimer
    pmt_fields = [f for f in result.extracted_fields if f["field_name"] == "payment_notice"]
    assert len(pmt_fields) == 1
    assert pmt_fields[0]["validation_status"] == "UNVERIFIED_EVIDENCE"
    assert "strictly unverified evidence" in pmt_fields[0]["disclaimer"].lower()


def test_image_ocr_oversized_dimensions_guard():
    # Construct image header with oversized width 5000 (> 4096 limit)
    img = Image.new("RGB", (5000, 100), color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    huge_bytes = buf.getvalue()

    att = AttachmentRecord(
        attachment_id="att_huge_img",
        tenant_id="tenant_ocr_test",
        evidence_ref="ev_att_huge_img",
        filename="huge_scan.png",
        media_type="image/png",
        size_bytes=len(huge_bytes),
        content_sha256="0" * 64,
    )

    result = extract_image_ocr(att, huge_bytes)

    assert result.status == "FAILED"
    assert "exceed maximum allowed 4096x4096 limit" in result.diagnostic


def test_image_ocr_blank_image():
    # Plain white image without text
    img = Image.new("RGB", (150, 150), color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    blank_bytes = buf.getvalue()

    att = AttachmentRecord(
        attachment_id="att_blank_img",
        tenant_id="tenant_ocr_test",
        evidence_ref="ev_att_blank_img",
        filename="blank.png",
        media_type="image/png",
        size_bytes=len(blank_bytes),
        content_sha256="0" * 64,
    )

    result = extract_image_ocr(att, blank_bytes)

    assert result.status == "SUCCESS", f"Diagnostic: {result.diagnostic}"
    assert result.evidence_items == []
    assert "0 text lines detected by OCR" in result.diagnostic


def test_image_ocr_api_and_persistence(shared_repo):
    tenant = DevelopmentContext(
        tenant_id="tenant_img_api_test",
        mode="LOCAL_SYNTHETIC_ONLY",
        implemented_channel="WHATSAPP",
        authentication="NOT_IMPLEMENTED",
    )
    app.dependency_overrides[development_context] = lambda: tenant
    app.dependency_overrides[local_repository] = lambda: shared_repo

    client = TestClient(app)

    # 1. Upload Image
    img_bytes = create_synthetic_image(["ORD-9021", "10 burgers", "2026-10-30"])
    upload_res = client.post(
        "/v1/attachments/upload",
        files={"file": ("order_slip.png", img_bytes, "image/png")},
    )
    assert upload_res.status_code == 201
    ev_ref = upload_res.json()["evidence_ref"]

    # 2. Extract Document via OCR
    extract_res = client.post(f"/v1/attachments/{ev_ref}/extract")
    assert extract_res.status_code == 200
    data = extract_res.json()
    assert data["status"] == "SUCCESS"
    assert data["document_type"] == "IMAGE"
    assert any(f["value"] == "ORD-9021" for f in data["extracted_fields"])

    # 3. Retrieve Persisted Extraction
    get_res = client.get(f"/v1/attachments/{ev_ref}/extraction")
    assert get_res.status_code == 200
    assert get_res.json()["evidence_ref"] == ev_ref
    assert get_res.json()["document_type"] == "IMAGE"
