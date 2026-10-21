"""Provider-independent plain text. No SDK, HTML/Markdown mode or sending permission."""

import json
from hashlib import sha256

from app.core.errors import DomainError
from app.core.schemas import CommitmentTerms, CommunicationChannel

TEMPLATE_KEY = "delivery_change"
TEMPLATE_VERSION = 1  # Change version whenever wording/representation changes.

_TEXT = {
    "en": {
        "greeting": "Dear Customer,",
        "intro": "Please review the following proposed revised terms. Your acceptance is pending.",
        "order": "Order", "commitment": "Commitment", "proposal": "Proposal",
        "version": "Version", "communication": "Communication reference",
        "sku": "Product / SKU", "quantity": "Quantity", "deadline": "Delivery deadline (UTC offset included)",
        "instructions": "Special instructions (exact approved text)",
        "reply": "Please explicitly accept, reject, or request a change, quoting the communication and proposal references.",
        "closing": "Thank you.", "subject": "Proposed delivery terms for order",
    },
    "ms": {
        "greeting": "Pelanggan yang dihormati,",
        "intro": "Sila semak cadangan syarat baharu berikut. Persetujuan anda masih diperlukan.",
        "order": "Pesanan", "commitment": "Komitmen", "proposal": "Cadangan",
        "version": "Versi", "communication": "Rujukan komunikasi",
        "sku": "Produk / SKU", "quantity": "Kuantiti", "deadline": "Tarikh akhir penghantaran (termasuk ofset UTC)",
        "instructions": "Arahan khas (teks tepat yang diluluskan)",
        "reply": "Sila nyatakan persetujuan, penolakan atau permintaan perubahan dengan menyertakan rujukan komunikasi dan cadangan.",
        "closing": "Terima kasih.", "subject": "Cadangan syarat penghantaran untuk pesanan",
    },
    "zh": {
        "greeting": "尊敬的客户：",
        "intro": "请查看以下拟议的新条款，尚待您确认是否接受。",
        "order": "订单", "commitment": "承诺", "proposal": "提案",
        "version": "版本", "communication": "沟通编号",
        "sku": "产品 / SKU", "quantity": "数量", "deadline": "交付截止时间（含 UTC 时差）",
        "instructions": "特别要求（获批原文）",
        "reply": "请明确回复接受、拒绝或提出修改，并注明沟通编号和提案编号。",
        "closing": "谢谢。", "subject": "订单交付条款提案",
    },
}


def fingerprint(data: dict) -> str:
    serialized = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return sha256(serialized.encode("utf-8")).hexdigest()


def _one_line(value: str) -> str:
    # Do not permit injected lines, invisible bidi markers, or ambiguous blank references.
    if not value.strip() or any(not char.isprintable() for char in value):
        raise DomainError("UNSAFE_TEMPLATE_VALUE", "Template references must be nonblank plain text", status_code=422)
    return value


def render_message(
    *, language: str, template_key: str, channel: CommunicationChannel,
    order_id: str, commitment_id: str, proposal_id: str, proposal_version: int,
    communication_id: str, terms: CommitmentTerms,
) -> tuple[str | None, str]:
    if language not in _TEXT:
        raise DomainError("LANGUAGE_UNSUPPORTED", "Unsupported draft language", status_code=422)
    if template_key != TEMPLATE_KEY:
        raise DomainError("TEMPLATE_UNSUPPORTED", "Unsupported draft template", status_code=422)
    if channel == CommunicationChannel.UNKNOWN:
        raise DomainError("AUTHORIZED_CHANNEL_REQUIRED", "Resolved channel required", status_code=409)
    fields = set(terms.model_dump(exclude_none=True))
    supported = {"sku", "quantity", "unit", "deadline", "special_instructions"}
    if fields - supported:
        raise DomainError("UNSUPPORTED_MATERIAL_TERMS", "Template cannot represent all approved fields", status_code=422)
    if not {"sku", "quantity", "unit", "deadline"}.issubset(fields):
        raise DomainError("REQUIRED_DRAFT_TERMS_MISSING", "This template requires product, quantity, unit and deadline", status_code=422)
    text = _TEXT[language]
    order_id, commitment_id, proposal_id, communication_id, sku, unit = map(
        _one_line, (order_id, commitment_id, proposal_id, communication_id, terms.sku, terms.unit),
    )
    lines = [
        text["greeting"], "", text["intro"], "",
        f"{text['order']}: {order_id}", f"{text['commitment']}: {commitment_id}",
        f"{text['proposal']}: {proposal_id} ({text['version']}: {proposal_version})",
        f"{text['communication']}: {communication_id}",
        f"{text['sku']}: {sku}",
        f"{text['quantity']}: {format(terms.quantity, 'f')} {unit}",
        f"{text['deadline']}: {terms.deadline.isoformat()}",
    ]
    if terms.special_instructions is not None:
        # Preserve ALL approved text, including line breaks, as a labelled JSON string.
        # This is data, never executable instructions or newly translated business terms.
        lines.append(f"{text['instructions']}: {json.dumps(terms.special_instructions, ensure_ascii=False)}")
    lines.extend(["", text["reply"], "", text["closing"]])
    subject = f"{text['subject']} {order_id}" if channel.value.endswith("_EMAIL") else None
    return subject, "\n".join(lines)
