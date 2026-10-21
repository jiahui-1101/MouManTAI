"""Unit tests for attachment storage, magic bytes validation, and tenant isolation."""

import hashlib
import os
import pytest
from fastapi.testclient import TestClient

from app.context.attachment_validator import (
    MAX_ATTACHMENT_BYTES,
    AttachmentLimitExceeded,
    InvalidAttachmentPayload,
    UnsupportedAttachmentType,
    validate_attachment,
)
from app.context.dependencies import development_context, local_repository
from app.context.dev_app import app
from app.context.dev_database import create_p1_engine, initialize_p1_schema
from app.context.document_schemas import AttachmentRecord
from app.context.ingestion_schemas import DevelopmentContext
from app.context.postgres_repository import PostgresMessageRepository

# Minimal valid magic bytes payloads
VALID_PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"
VALID_PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
VALID_JPG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb"


@pytest.fixture(scope="module")
def shared_repo():
    url = os.environ.get("P1_DATABASE_URL")
    if not url:
        pytest.skip("P1_DATABASE_URL not set")
    engine = create_p1_engine(url)
    initialize_p1_schema(engine)
    return PostgresMessageRepository(engine)


def test_validator_magic_bytes():
    # Valid PDF
    media, fn = validate_attachment("order.pdf", VALID_PDF_BYTES, "application/pdf")
    assert media == "application/pdf"
    assert fn == "order.pdf"

    # Valid PNG
    media, fn = validate_attachment("invoice.png", VALID_PNG_BYTES, "image/png")
    assert media == "image/png"
    assert fn == "invoice.png"

    # Valid JPG
    media, fn = validate_attachment("receipt.jpg", VALID_JPG_BYTES, "image/jpeg")
    assert media == "image/jpeg"
    assert fn == "receipt.jpg"

    # Misleading extension: text file named .pdf
    with pytest.raises(InvalidAttachmentPayload, match="Misleading file extension"):
        validate_attachment("invoice.pdf", b"Hello plain text")

    # Misleading extension: PNG bytes named .jpg
    with pytest.raises(InvalidAttachmentPayload, match="Misleading file extension"):
        validate_attachment("photo.jpg", VALID_PNG_BYTES)

    # Unsupported format
    with pytest.raises(UnsupportedAttachmentType, match="Unsupported attachment format"):
        validate_attachment("script.exe", b"MZ\x90\x00")

    # Oversized payload
    with pytest.raises(AttachmentLimitExceeded, match="exceeds maximum allowed limit"):
        validate_attachment("huge.pdf", b"%PDF-" + b"0" * (MAX_ATTACHMENT_BYTES + 10))

    # Path traversal attack in filename
    with pytest.raises(InvalidAttachmentPayload, match="Invalid or unsafe attachment filename"):
        validate_attachment("../../../etc/passwd.pdf", VALID_PDF_BYTES)


def test_attachment_upload_and_download_api(shared_repo):
    tenant = DevelopmentContext(
        tenant_id="tenant_attach_test",
        mode="LOCAL_SYNTHETIC_ONLY",
        implemented_channel="WHATSAPP",
        authentication="NOT_IMPLEMENTED",
    )
    app.dependency_overrides[development_context] = lambda: tenant
    app.dependency_overrides[local_repository] = lambda: shared_repo

    client = TestClient(app)

    # 1. Upload valid PDF
    upload_res = client.post(
        "/v1/attachments/upload",
        files={"file": ("po_document.pdf", VALID_PDF_BYTES, "application/pdf")},
    )
    assert upload_res.status_code == 201, upload_res.text
    data = upload_res.json()
    assert data["filename"] == "po_document.pdf"
    assert data["media_type"] == "application/pdf"
    assert data["size_bytes"] == len(VALID_PDF_BYTES)
    assert data["content_sha256"] == hashlib.sha256(VALID_PDF_BYTES).hexdigest()
    evidence_ref = data["evidence_ref"]
    assert evidence_ref.startswith("ev_att_")

    # 2. Retrieve metadata
    meta_res = client.get(f"/v1/attachments/{evidence_ref}/metadata")
    assert meta_res.status_code == 200
    assert meta_res.json()["evidence_ref"] == evidence_ref
    assert meta_res.json()["tenant_id"] == "tenant_attach_test"

    # 3. Download content
    dl_res = client.get(f"/v1/attachments/{evidence_ref}/content")
    assert dl_res.status_code == 200
    assert dl_res.content == VALID_PDF_BYTES
    assert dl_res.headers["content-type"].startswith("application/pdf")
    assert 'filename="po_document.pdf"' in dl_res.headers["content-disposition"]


def test_attachment_tenant_isolation(shared_repo):
    # Upload as tenant A
    tenant_a = DevelopmentContext(
        tenant_id="tenant_alpha",
        mode="LOCAL_SYNTHETIC_ONLY",
        implemented_channel="WHATSAPP",
        authentication="NOT_IMPLEMENTED",
    )
    app.dependency_overrides[development_context] = lambda: tenant_a
    app.dependency_overrides[local_repository] = lambda: shared_repo

    client = TestClient(app)

    upload_res = client.post(
        "/v1/attachments/upload",
        files={"file": ("alpha_receipt.png", VALID_PNG_BYTES, "image/png")},
    )
    assert upload_res.status_code == 201
    evidence_ref = upload_res.json()["evidence_ref"]

    # Switch to tenant B
    tenant_b = DevelopmentContext(
        tenant_id="tenant_beta",
        mode="LOCAL_SYNTHETIC_ONLY",
        implemented_channel="WHATSAPP",
        authentication="NOT_IMPLEMENTED",
    )
    app.dependency_overrides[development_context] = lambda: tenant_b

    # Tenant B tries to get Tenant A's attachment -> 404
    meta_res = client.get(f"/v1/attachments/{evidence_ref}/metadata")
    assert meta_res.status_code == 404

    content_res = client.get(f"/v1/attachments/{evidence_ref}/content")
    assert content_res.status_code == 404


def test_attachment_upload_rejections(shared_repo):
    tenant = DevelopmentContext(
        tenant_id="tenant_attach_test",
        mode="LOCAL_SYNTHETIC_ONLY",
        implemented_channel="WHATSAPP",
        authentication="NOT_IMPLEMENTED",
    )
    app.dependency_overrides[development_context] = lambda: tenant
    app.dependency_overrides[local_repository] = lambda: shared_repo

    client = TestClient(app)

    # 1. Plain text masquerading as PDF -> 400
    res = client.post(
        "/v1/attachments/upload",
        files={"file": ("fake.pdf", b"This is not a PDF at all", "application/pdf")},
    )
    assert res.status_code == 400
    assert "Misleading file extension" in res.json()["detail"]

    # 2. Unsupported format (.exe) -> 415
    res = client.post(
        "/v1/attachments/upload",
        files={"file": ("danger.exe", b"MZ\x00\x00", "application/octet-stream")},
    )
    assert res.status_code == 415

    # 3. Non-existent evidence_ref -> 404
    res = client.get("/v1/attachments/ev_att_nonexistent999/metadata")
    assert res.status_code == 404
