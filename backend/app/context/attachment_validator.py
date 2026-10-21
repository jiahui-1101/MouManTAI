"""Attachment validation rules: magic bytes, MIME matching, and size bounds."""

from __future__ import annotations

import os
from pathlib import PurePath

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024  # 10 MB per attachment


class AttachmentValidationError(Exception):
    """Base error for attachment validation failures."""


class AttachmentLimitExceeded(AttachmentValidationError):
    """File exceeds the maximum allowable size."""


class InvalidAttachmentPayload(AttachmentValidationError):
    """File content does not match expected magic bytes or declared extension."""


class UnsupportedAttachmentType(AttachmentValidationError):
    """File format is not supported for document extraction or OCR."""


MAGIC_SIGNATURES: list[tuple[bytes, str, set[str]]] = [
    (b"%PDF-", "application/pdf", {".pdf"}),
    (b"\x89PNG\r\n\x1a\n", "image/png", {".png"}),
    (b"\xff\xd8\xff", "image/jpeg", {".jpg", ".jpeg"}),
]


def sanitize_filename(filename: str) -> str:
    """Extract clean basename, disallow path traversal, and enforce length bounds."""
    raw = filename.strip()
    if not raw or "/" in raw or "\\" in raw or ".." in raw:
        raise InvalidAttachmentPayload("Invalid or unsafe attachment filename")
    clean = PurePath(raw).name.strip()
    if not clean or clean in (".", ".."):
        raise InvalidAttachmentPayload("Invalid or unsafe attachment filename")
    if len(clean) > 255:
        raise InvalidAttachmentPayload("Filename exceeds maximum length of 255 characters")
    return clean


def validate_attachment(filename: str, content: bytes, declared_media_type: str | None = None) -> tuple[str, str]:
    """Validate content bytes against declared extension and magic signatures.

    Returns:
        tuple of (detected_media_type, sanitized_filename)

    Raises:
        AttachmentLimitExceeded: if content exceeds 10MB
        InvalidAttachmentPayload: if magic bytes mismatch, empty content, or path traversal detected
        UnsupportedAttachmentType: if file extension or magic bytes are not in allowed list
    """
    clean_filename = sanitize_filename(filename)

    if len(content) > MAX_ATTACHMENT_BYTES:
        raise AttachmentLimitExceeded(
            f"Attachment size {len(content)} bytes exceeds maximum allowed limit of {MAX_ATTACHMENT_BYTES} bytes"
        )
    if len(content) < 4:
        raise InvalidAttachmentPayload("Attachment payload is empty or too small to inspect")
    ext = os.path.splitext(clean_filename)[1].lower()
    all_supported_exts = {e for _, _, exts in MAGIC_SIGNATURES for e in exts}
    if ext not in all_supported_exts:
        raise UnsupportedAttachmentType(
            f"Unsupported attachment format or file extension '{ext}' for '{clean_filename}'. Supported: {', '.join(sorted(all_supported_exts))}"
        )

    # Identify matching signature
    detected_media_type: str | None = None
    for magic, media_type, valid_exts in MAGIC_SIGNATURES:
        if content.startswith(magic):
            detected_media_type = media_type
            if ext not in valid_exts:
                raise InvalidAttachmentPayload(
                    f"Misleading file extension '{ext}' does not match detected magic bytes '{media_type}'"
                )
            break

    if detected_media_type is None:
        raise InvalidAttachmentPayload(
            f"Misleading file extension '{ext}' or corrupted magic bytes for '{clean_filename}'"
        )

    if declared_media_type:
        declared_norm = declared_media_type.split(";")[0].strip().lower()
        if declared_norm != detected_media_type:
            raise InvalidAttachmentPayload(
                f"Declared media_type '{declared_media_type}' does not match detected content '{detected_media_type}'"
            )

    return detected_media_type, clean_filename
