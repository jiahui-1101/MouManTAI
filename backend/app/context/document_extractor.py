"""Bounded, traceable document-content extraction for PDFs and images."""

from __future__ import annotations

import io
import os
import re
import uuid
from typing import Any, Sequence

import numpy as np

from .deterministic_extraction import ORDER_RE, PROVISIONAL_PRODUCTS, ProductAlias
from .document_schemas import AttachmentRecord, BoundingBox, DocumentEvidence, DocumentExtractionResult

PDF_EXTRACTOR_VERSION = "p1-pdf-v1"
OCR_EXTRACTOR_VERSION = "p1-paddleocr-v1"
MAX_PDF_PAGES = 10
MAX_TEXT_LENGTH = 100_000

PAYMENT_KEYWORDS = [
    "duitnow",
    "transfer successful",
    "bank slip",
    "receipt",
    "transaction successful",
    "amount rm",
    "payment received",
    "payment slip",
    "successful transfer",
]

DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
DOC_ORDER_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:ORD-[0-9]+|PO-[0-9A-Z\-]+|INV-[0-9A-Z\-]+|synthetic_order_[a-z0-9]+)(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
QTY_ITEM_RE = re.compile(
    r"\b(\d+)\s*(pcs|pieces|pack|packs|box|boxes|carton|cartons|sets?|kg)?\s+([a-zA-Z0-9_\-\s]+?)(?=\s*(?:\n|,|\.|$|\d|\b(?:at|for|by|on)\b))",
    re.IGNORECASE,
)


def is_payment_document(text: str) -> bool:
    """Check if the text exhibits strong payment receipt / bank slip indicators."""
    lowered = text.lower()
    return any(keyword in lowered for keyword in PAYMENT_KEYWORDS)


MONTH_MAP = {
    "january": "01", "jan": "01", "february": "02", "feb": "02", "march": "03", "mar": "03",
    "april": "04", "apr": "04", "may": "05", "june": "06", "jun": "06", "july": "07", "jul": "07",
    "august": "08", "aug": "08", "september": "09", "sep": "09", "october": "10", "oct": "10",
    "november": "11", "nov": "11", "december": "12", "dec": "12",
}

DATE_ISO_RE = re.compile(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b")
DATE_WRITTEN_RE = re.compile(
    r"\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(20\d{2})\b",
    re.IGNORECASE,
)
CLAUSE_RE = re.compile(
    r"\b(RESCHEDULING\s+CLAUSE[^\n]*|MANUAL\s+CONFIRMATION\s+REQUIRED[^\n]*)\b",
    re.IGNORECASE,
)


def extract_document_fields(
    evidence_items: list[DocumentEvidence],
    *,
    catalog: Sequence[ProductAlias] = PROVISIONAL_PRODUCTS,
    tenant_id: str | None = None,
    is_payment: bool = False,
) -> list[dict]:
    """Extract structured fields (order_id, delivery date, item/quantity, rescheduling clause) from document evidence."""
    extracted_fields: list[dict] = []

    # 1. Order ID references
    seen_pos: set[str] = set()
    for ev in evidence_items:
        for match in DOC_ORDER_RE.finditer(ev.quote):
            po_val = match.group()
            if po_val in seen_pos:
                continue
            seen_pos.add(po_val)
            extracted_fields.append({
                "field_name": "order_id",
                "value": po_val,
                "validation_status": "UNRESOLVED",
                "evidence_id": ev.evidence_id,
                "quote": po_val,
                "page_number": ev.page_number,
                "is_payment_evidence": is_payment,
            })

    # 2. Requested Delivery Dates (both ISO and written formats)
    seen_dates: set[str] = set()
    for i, ev in enumerate(evidence_items):
        quote = ev.quote
        date_val = None
        iso_m = DATE_ISO_RE.search(quote)
        if iso_m:
            y, m, d = iso_m.groups()
            date_val = f"{y}-{int(m):02d}-{int(d):02d}"
        else:
            w_m = DATE_WRITTEN_RE.search(quote)
            if w_m:
                d, m_str, y = w_m.groups()
                date_val = f"{y}-{MONTH_MAP.get(m_str.lower(), '01')}-{int(d):02d}"
            elif "delivery date" in quote.lower() and i + 1 < len(evidence_items):
                next_m = DATE_WRITTEN_RE.search(evidence_items[i + 1].quote) or DATE_ISO_RE.search(evidence_items[i + 1].quote)
                if next_m:
                    if len(next_m.groups()) == 3 and next_m.group(2).isalpha():
                        d, m_str, y = next_m.groups()
                        date_val = f"{y}-{MONTH_MAP.get(m_str.lower(), '01')}-{int(d):02d}"
                    elif len(next_m.groups()) == 3:
                        y, m, d = next_m.groups()
                        date_val = f"{y}-{int(m):02d}-{int(d):02d}"

        if date_val and date_val not in seen_dates:
            seen_dates.add(date_val)
            extracted_fields.append({
                "field_name": "requested_delivery_at",
                "value": date_val,
                "validation_status": "VALID",
                "evidence_id": ev.evidence_id,
                "quote": quote,
                "page_number": ev.page_number,
                "is_payment_evidence": is_payment,
            })

    # 3. Catalog Products / Quantity
    seen_items: set[tuple[str, str]] = set()
    # 3a. Inline quote matching: "50 pcs burgers" or "burger 50 pcs"
    for ev in evidence_items:
        quote_lower = ev.quote.lower()
        for prod in catalog:
            if prod.tenant_id and tenant_id and prod.tenant_id != tenant_id:
                if any(p.tenant_id == tenant_id for p in catalog):
                    continue
            for alias in prod.aliases:
                p1 = rf"\b(\d+)\s*(pcs|pieces|units?|pack|packs|box|boxes|sets?|kg)?\s+{re.escape(alias.lower())}\b"
                m1 = re.search(p1, quote_lower)
                if m1:
                    item_key = (prod.sku, ev.evidence_id)
                    if item_key not in seen_items:
                        seen_items.add(item_key)
                        extracted_fields.append({
                            "field_name": "item",
                            "value": f"{int(m1.group(1))} {m1.group(2) or 'pcs'} {prod.sku}",
                            "sku": prod.sku,
                            "product_name": prod.sku.title(),
                            "quantity": int(m1.group(1)),
                            "unit": m1.group(2) or "pcs",
                            "validation_status": "VALID",
                            "evidence_id": ev.evidence_id,
                            "quote": m1.group(0),
                            "page_number": ev.page_number,
                            "is_payment_evidence": is_payment,
                        })
                        break

    # 3b. Tabular / Multi-line layout matching (e.g. BURGER -> description -> 100 -> pcs)
    if not any(f.get("field_name") == "item" for f in extracted_fields):
        for i, ev in enumerate(evidence_items):
            quote_clean = ev.quote.strip()
            for prod in catalog:
                if prod.tenant_id and tenant_id and prod.tenant_id != tenant_id:
                    if any(p.tenant_id == tenant_id for p in catalog):
                        continue
                if any(alias.lower() == quote_clean.lower() or f" {alias.lower()} " in f" {quote_clean.lower()} " for alias in prod.aliases):
                    for j in range(i + 1, min(i + 6, len(evidence_items))):
                        next_quote = evidence_items[j].quote.strip()
                        qty_m = re.match(r"^(\d+)\s*(pcs|pieces|units?|pack|packs|box|boxes)?$", next_quote, re.IGNORECASE)
                        if qty_m:
                            qty = int(qty_m.group(1))
                            unit = qty_m.group(2) or "pcs"
                            if not qty_m.group(2) and j + 1 < len(evidence_items):
                                u_cand = evidence_items[j + 1].quote.strip().lower()
                                if u_cand in ["pcs", "pieces", "units", "pack", "packs", "box", "boxes", "kg"]:
                                    unit = u_cand
                            extracted_fields.append({
                                "field_name": "item",
                                "value": f"{qty} {unit} {prod.sku}",
                                "sku": prod.sku,
                                "product_name": prod.sku.title(),
                                "quantity": qty,
                                "unit": unit,
                                "validation_status": "VALID",
                                "evidence_id": ev.evidence_id,
                                "quote": f"{quote_clean} ... {qty} {unit}",
                                "page_number": ev.page_number,
                                "is_payment_evidence": is_payment,
                            })
                            break
                    if any(f.get("field_name") == "item" for f in extracted_fields):
                        break

    # 4. Rescheduling clause detection
    for ev in evidence_items:
        c_m = CLAUSE_RE.search(ev.quote)
        if c_m:
            extracted_fields.append({
                "field_name": "rescheduling_clause",
                "value": "MANUAL_CONFIRMATION_REQUIRED",
                "validation_status": "UNRESOLVED",
                "evidence_id": ev.evidence_id,
                "quote": c_m.group(0).strip(),
                "page_number": ev.page_number,
                "is_payment_evidence": is_payment,
            })
            break

    # 5. Payment Evidence Notice
    if is_payment:
        extracted_fields.append({
            "field_name": "payment_notice",
            "value": "UNVERIFIED_EVIDENCE",
            "validation_status": "UNVERIFIED_EVIDENCE",
            "disclaimer": "Payment slips and receipts are strictly unverified evidence. P1 never infers verified payment, identity, or fulfilment.",
            "evidence_id": evidence_items[0].evidence_id if evidence_items else "ev:unverified:payment",
            "page_number": evidence_items[0].page_number if evidence_items else 1,
            "is_payment_evidence": True,
        })

    return extracted_fields


def extract_pdf_document(
    attachment: AttachmentRecord,
    content: bytes,
    *,
    catalog: Sequence[ProductAlias] = PROVISIONAL_PRODUCTS,
    max_pages: int = MAX_PDF_PAGES,
) -> DocumentExtractionResult:
    """Extract text, bounding boxes, and traceable evidence from machine-readable or scanned PDF bytes."""
    try:
        import pymupdf
        doc = pymupdf.open(stream=content, filetype="pdf")
    except Exception as exc:
        return DocumentExtractionResult(
            attachment_id=attachment.attachment_id,
            evidence_ref=attachment.evidence_ref,
            status="FAILED",
            document_type="PDF",
            page_count=0,
            text_content="",
            extracted_fields=[],
            evidence_items=[],
            is_payment_notice=False,
            diagnostic=f"Failed to open PDF document: {exc}",
        )

    if doc.is_encrypted:
        doc.close()
        return DocumentExtractionResult(
            attachment_id=attachment.attachment_id,
            evidence_ref=attachment.evidence_ref,
            status="FAILED",
            document_type="PDF",
            page_count=0,
            text_content="",
            extracted_fields=[],
            evidence_items=[],
            is_payment_notice=False,
            diagnostic="Encrypted or password-protected PDF files are not supported",
        )

    total_pages = len(doc)
    inspect_pages = min(total_pages, max_pages)
    evidence_items: list[DocumentEvidence] = []
    page_texts: list[str] = []

    for page_idx in range(inspect_pages):
        page_num = page_idx + 1
        page = doc[page_idx]
        blocks = page.get_text("blocks")
        # blocks format: (x0, y0, x1, y1, text, block_no, block_type)
        page_block_texts = []
        for b in blocks:
            if len(b) >= 7 and b[6] == 0:  # text block
                text = b[4].strip()
                if not text:
                    continue
                page_block_texts.append(text)
                bbox = BoundingBox(x0=round(b[0], 2), y0=round(b[1], 2), x1=round(b[2], 2), y1=round(b[3], 2))
                evidence_items.append(
                    DocumentEvidence(
                        evidence_id=f"ev:{attachment.attachment_id}:p{page_num}:b{b[5]}",
                        evidence_ref=attachment.evidence_ref,
                        attachment_id=attachment.attachment_id,
                        page_number=page_num,
                        quote=text,
                        bounding_box=bbox,
                        method="PDF_TEXT",
                        method_version=PDF_EXTRACTOR_VERSION,
                        confidence=1.0,
                        is_payment_evidence=False,
                    )
                )
        page_texts.append("\n".join(page_block_texts))

    used_ocr = False
    ocr_error = None
    if not any(t.strip() for t in page_texts):
        # Image-only / Scanned PDF detected: fallback to OCR
        try:
            from PIL import Image
            ocr = get_ocr_engine()
            ocr_evidence: list[DocumentEvidence] = []
            ocr_texts: list[str] = []

            for page_idx in range(inspect_pages):
                page_num = page_idx + 1
                page = doc[page_idx]
                pix = page.get_pixmap(dpi=150)
                img = Image.open(io.BytesIO(pix.tobytes("png")))
                rgb_array = np.array(img.convert("RGB"))
                results = ocr.predict(rgb_array)

                if results and len(results) > 0:
                    first = results[0]
                    rec_texts = first.get("rec_texts", [])
                    rec_scores = first.get("rec_scores", [])
                    raw_boxes = first.get("rec_boxes")
                    rec_boxes = raw_boxes.tolist() if hasattr(raw_boxes, "tolist") else (list(raw_boxes) if raw_boxes is not None else [])

                    for idx, text in enumerate(rec_texts):
                        cleaned = text.strip()
                        if not cleaned:
                            continue
                        ocr_texts.append(cleaned)
                        bbox = None
                        if idx < len(rec_boxes):
                            box = rec_boxes[idx]
                            if len(box) == 4:
                                bbox = BoundingBox(
                                    x0=float(box[0]), y0=float(box[1]), x1=float(box[2]), y1=float(box[3])
                                )
                        score = float(rec_scores[idx]) if idx < len(rec_scores) else None
                        ocr_evidence.append(
                            DocumentEvidence(
                                evidence_id=f"ev:{attachment.attachment_id}:p{page_num}:ocr:{idx}",
                                evidence_ref=attachment.evidence_ref,
                                attachment_id=attachment.attachment_id,
                                page_number=page_num,
                                quote=cleaned,
                                bounding_box=bbox,
                                method="OCR",
                                method_version=OCR_EXTRACTOR_VERSION,
                                confidence=round(score, 4) if score is not None else None,
                                is_payment_evidence=False,
                            )
                        )
            if ocr_texts:
                evidence_items = ocr_evidence
                page_texts = ["\n".join(ocr_texts)]
                used_ocr = True
        except Exception as exc:
            ocr_error = str(exc)

    doc.close()

    full_text = "\n\n".join(filter(None, page_texts))
    if len(full_text) > MAX_TEXT_LENGTH:
        full_text = full_text[:MAX_TEXT_LENGTH]

    # Payment slip guard
    is_payment = is_payment_document(full_text)
    if is_payment:
        for ev in evidence_items:
            ev.is_payment_evidence = True

    extracted_fields = extract_document_fields(
        evidence_items,
        catalog=catalog,
        tenant_id=attachment.tenant_id,
        is_payment=is_payment,
    )

    # Status assessment
    diagnostic = None
    if total_pages > max_pages:
        status = "PARTIAL"
        diagnostic = f"Document has {total_pages} pages; bounded processing inspected first {max_pages} pages."
    elif not full_text.strip():
        status = "SUCCESS"
        diagnostic = "Scanned or image-only PDF detected; 0 machine-readable text blocks found."
        if ocr_error:
            diagnostic += f" (OCR error: {ocr_error})"
    elif used_ocr:
        status = "SUCCESS"
        diagnostic = f"Image-only PDF detected; executed OCR ({len(evidence_items)} text blocks, {len(extracted_fields)} fields extracted)."
    else:
        status = "SUCCESS"

    return DocumentExtractionResult(
        attachment_id=attachment.attachment_id,
        evidence_ref=attachment.evidence_ref,
        status=status,
        document_type="PDF",
        page_count=total_pages,
        text_content=full_text,
        extracted_fields=extracted_fields,
        evidence_items=evidence_items,
        is_payment_notice=is_payment,
        diagnostic=diagnostic,
    )


MAX_IMAGE_DIMENSION = 4096
_ocr_engine: Any = None


def get_ocr_engine() -> Any:
    global _ocr_engine
    if _ocr_engine is None:
        os.environ["PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT"] = "False"
        from paddleocr import PaddleOCR
        _ocr_engine = PaddleOCR(lang="en")
    return _ocr_engine


def extract_image_ocr(
    attachment: AttachmentRecord,
    content: bytes,
    *,
    catalog: Sequence[ProductAlias] = PROVISIONAL_PRODUCTS,
) -> DocumentExtractionResult:
    """Bounded, traceable OCR on synthetic or uploaded images using PaddleOCR."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(content))
        width, height = img.size
    except Exception as exc:
        return DocumentExtractionResult(
            attachment_id=attachment.attachment_id,
            evidence_ref=attachment.evidence_ref,
            status="FAILED",
            document_type="IMAGE",
            page_count=1,
            text_content="",
            extracted_fields=[],
            evidence_items=[],
            is_payment_notice=False,
            diagnostic=f"Failed to decode image payload: {exc}",
        )

    if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
        return DocumentExtractionResult(
            attachment_id=attachment.attachment_id,
            evidence_ref=attachment.evidence_ref,
            status="FAILED",
            document_type="IMAGE",
            page_count=1,
            text_content="",
            extracted_fields=[],
            evidence_items=[],
            is_payment_notice=False,
            diagnostic=f"Image dimensions {width}x{height} exceed maximum allowed {MAX_IMAGE_DIMENSION}x{MAX_IMAGE_DIMENSION} limit",
        )

    try:
        rgb_array = np.array(img.convert("RGB"))
        ocr = get_ocr_engine()
        results = ocr.predict(rgb_array)
    except Exception as exc:
        return DocumentExtractionResult(
            attachment_id=attachment.attachment_id,
            evidence_ref=attachment.evidence_ref,
            status="FAILED",
            document_type="IMAGE",
            page_count=1,
            text_content="",
            extracted_fields=[],
            evidence_items=[],
            is_payment_notice=False,
            diagnostic=f"OCR engine execution failed: {exc}",
        )

    rec_texts: list[str] = []
    rec_scores: list[float] = []
    rec_boxes: list[list[float]] = []

    if results and len(results) > 0:
        first = results[0]
        rec_texts = first.get("rec_texts", [])
        rec_scores = first.get("rec_scores", [])
        raw_boxes = first.get("rec_boxes")
        if raw_boxes is not None:
            rec_boxes = raw_boxes.tolist() if hasattr(raw_boxes, "tolist") else list(raw_boxes)

    full_text = "\n".join(rec_texts)
    is_payment = is_payment_document(full_text)

    evidence_items: list[DocumentEvidence] = []
    for idx, text in enumerate(rec_texts):
        cleaned = text.strip()
        if not cleaned:
            continue
        bbox = None
        if idx < len(rec_boxes):
            box = rec_boxes[idx]
            if len(box) == 4:
                bbox = BoundingBox(
                    x0=float(box[0]), y0=float(box[1]), x1=float(box[2]), y1=float(box[3])
                )
        score = float(rec_scores[idx]) if idx < len(rec_scores) else None
        evidence_items.append(
            DocumentEvidence(
                evidence_id=f"ev:{attachment.attachment_id}:ocr:{idx}",
                evidence_ref=attachment.evidence_ref,
                attachment_id=attachment.attachment_id,
                page_number=1,
                quote=cleaned,
                bounding_box=bbox,
                method="OCR",
                method_version=OCR_EXTRACTOR_VERSION,
                confidence=round(score, 4) if score is not None else None,
                is_payment_evidence=is_payment,
            )
        )

    extracted_fields = extract_document_fields(
        evidence_items,
        catalog=catalog,
        tenant_id=attachment.tenant_id,
        is_payment=is_payment,
    )

    diagnostic = None
    if not rec_texts:
        status = "SUCCESS"
        diagnostic = "0 text lines detected by OCR"
    else:
        status = "SUCCESS"

    return DocumentExtractionResult(
        attachment_id=attachment.attachment_id,
        evidence_ref=attachment.evidence_ref,
        status=status,
        document_type="IMAGE",
        page_count=1,
        text_content=full_text,
        extracted_fields=extracted_fields,
        evidence_items=evidence_items,
        is_payment_notice=is_payment,
        diagnostic=diagnostic,
    )

