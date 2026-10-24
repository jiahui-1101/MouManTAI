"""Internal C1 framing helpers used by authenticated channel adapters and P1 storage.

Inputs must come from an authenticated transport with server-owned tenant/account
configuration. Shape validation does not establish contact identity or consent.
REFERENCE_MATCH means a scoped source reference, never business authorization. The
helpers do not perform persistence, network calls, events, domain transitions or
inferred role decisions.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Iterable
from dataclasses import dataclass
from email import policy
from email.parser import HeaderParser
from typing import Any, Literal


class FramingError(ValueError):
    """Missing, invalid or ambiguous source framing; caller must fail closed."""


def _object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise FramingError("Expected source object")
    return value


def _array(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise FramingError("Expected source array")
    return value


def _identifier(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 998:
        raise FramingError("Missing or invalid source identifier")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise FramingError("Control character in source identifier")
    return value


def _telegram_id(value: Any, *, positive: bool = False) -> str:
    if type(value) is not int or value == 0 or (positive and value < 0):
        raise FramingError("Invalid native Telegram identifier")
    return str(value)


@dataclass(frozen=True)
class ReplyFrame:
    """Local source observation; not an API DTO or verified business relationship."""

    tenant_id: str
    provider: Literal["TELEGRAM", "WHATSAPP", "EMAIL"]
    account_id: str
    native_message_id: str
    sender_id: str
    conversation_id: str | None
    exact_parent_id: str | None
    relationship_source: Literal["PROVIDER_QUOTE", "SENDER_HEADER", "NONE"]
    rfc_message_id: str | None = None
    in_reply_to: tuple[str, ...] = ()
    references: tuple[str, ...] = ()
    attachment_source_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for value in (self.tenant_id, self.account_id, self.native_message_id, self.sender_id):
            _identifier(value)
        for value in (self.conversation_id, self.exact_parent_id, self.rfc_message_id):
            if value is not None:
                _identifier(value)
        if self.provider not in {"TELEGRAM", "WHATSAPP", "EMAIL"}:
            raise FramingError("Unsupported provider")
        own_id = self.rfc_message_id if self.provider == "EMAIL" else self.native_message_id
        if self.exact_parent_id is not None and self.exact_parent_id == own_id:
            raise FramingError("Message cannot be its own parent")


@dataclass(frozen=True)
class ParentResolution:
    state: Literal[
        "NO_EXACT_PARENT",
        "UNRESOLVED",
        "AMBIGUOUS",
        "REFERENCE_MATCH",
        "LEGACY_UNKNOWN",
        "INVALID",
    ]
    parent_native_id: str | None = None


def resolve_parent(reply: ReplyFrame, candidates: Iterable[ReplyFrame]) -> ParentResolution:
    """Resolve only a unique exact reference in the same full source scope.

    Candidate loading, transport authentication and durable pending-reference
    reconciliation belong to the reviewed canonical repository integration.
    Email header matches remain sender assertions, even when uniquely resolved.
    """
    if reply.exact_parent_id is None:
        return ParentResolution("NO_EXACT_PARENT")
    matches = []
    for parent in candidates:
        if (reply.tenant_id, reply.provider, reply.account_id) != (
            parent.tenant_id,
            parent.provider,
            parent.account_id,
        ):
            continue
        if reply.provider != "EMAIL" and reply.conversation_id != parent.conversation_id:
            continue
        target_id = parent.rfc_message_id if reply.provider == "EMAIL" else parent.native_message_id
        if target_id == reply.exact_parent_id:
            matches.append(parent)
    if not matches:
        return ParentResolution("UNRESOLVED")
    if len(matches) != 1:
        return ParentResolution("AMBIGUOUS")
    return ParentResolution("REFERENCE_MATCH", matches[0].native_message_id)


def telegram_frame(update: dict[str, Any], *, tenant_id: str, account_id: str) -> ReplyFrame:
    """Observe one ordinary Telegram message; external replies never imply a local parent."""
    message = _object(update).get("message")
    if not isinstance(message, dict):
        raise FramingError("Expected an ordinary Telegram message")
    chat_id = _telegram_id(_object(message.get("chat")).get("id"))
    native_id = _telegram_id(message.get("message_id"), positive=True)
    sender_id = _telegram_id(_object(message.get("from")).get("id"), positive=True)
    parent_id = None
    if "reply_to_message" in message:
        parent = message["reply_to_message"]
        if not isinstance(parent, dict):
            raise FramingError("Invalid quoted parent")
        parent_id = _telegram_id(parent.get("message_id"), positive=True)
        if "chat" in parent and _telegram_id(_object(parent["chat"]).get("id")) != chat_id:
            raise FramingError("Quoted parent is outside this chat")
    attachments = []
    if any(
        key in message for key in ("audio", "voice", "video", "video_note", "sticker", "animation")
    ):
        raise FramingError("Unsupported Telegram attachment requires review")
    if "document" in message:
        attachments.append(_identifier(_object(message["document"]).get("file_id")))
    if "photo" in message:
        photos = message["photo"]
        if not isinstance(photos, list) or not photos:
            raise FramingError("Missing photo source")
        attachments.append(_identifier(_object(photos[-1]).get("file_id")))
    return ReplyFrame(
        tenant_id,
        "TELEGRAM",
        account_id,
        native_id,
        sender_id,
        chat_id,
        parent_id,
        "PROVIDER_QUOTE" if parent_id else "NONE",
        attachment_source_ids=tuple(attachments),
    )


def whatsapp_frame(
    message: dict[str, Any], *, tenant_id: str, account_id: str, callback_account_id: str
) -> ReplyFrame:
    """Observe one message from a signature-verified callback's messages array."""
    message = _object(message)
    _identifier(account_id)
    if callback_account_id != account_id:
        raise FramingError("Callback account differs from server configuration")
    sender_id = _identifier(message.get("from"))
    native_id = _identifier(message.get("id"))
    parent_id = None
    if "context" in message:
        context = message["context"]
        if not isinstance(context, dict):
            raise FramingError("Invalid WhatsApp context")
        parent_id = _identifier(context.get("id"))
    attachments = []
    kind = message.get("type")
    if kind in {"image", "document", "audio", "video", "sticker"}:
        media = message.get(kind)
        if not isinstance(media, dict):
            raise FramingError("Missing media source")
        attachments.append(_identifier(media.get("id")))
    return ReplyFrame(
        tenant_id,
        "WHATSAPP",
        account_id,
        native_id,
        sender_id,
        sender_id,
        parent_id,
        "PROVIDER_QUOTE" if parent_id else "NONE",
        attachment_source_ids=tuple(attachments),
    )


def _mailbox(value: str) -> str:
    if not isinstance(value, str):
        raise FramingError("Missing mailbox")
    value = _identifier(value.strip())
    header = HeaderParser(policy=policy.default).parsestr("From: " + value + "\n\n")["From"]
    if header.defects or len(header.addresses) != 1:
        raise FramingError("Expected exactly one mailbox")
    address = header.addresses[0].addr_spec
    if address.count("@") != 1:
        raise FramingError("Invalid mailbox")
    local, domain = address.rsplit("@", 1)
    if not local or not domain or any(char.isspace() for char in address):
        raise FramingError("Invalid mailbox")
    # Domain is case-insensitive; local-part equivalence requires provider policy.
    return local + "@" + domain.lower()


_MESSAGE_ID = re.compile(r"<[^<>\s@]+@[^<>\s@]+>")


def _message_ids(value: str) -> tuple[str, ...]:
    if not value:
        return ()
    values = tuple(_MESSAGE_ID.findall(value))
    if not values or _MESSAGE_ID.sub("", value).strip():
        raise FramingError("Unsupported or malformed RFC message identifier")
    return values


def email_frame(message: dict[str, Any], *, tenant_id: str, mailbox: str) -> ReplyFrame:
    """Observe Gmail full-message headers; no subject/From-based authority.

    Conservative RFC subset: angle-bracket IDs and folded whitespace. Unusual,
    obsolete or ambiguous headers require review rather than guessed linkage.
    Mailbox is the authenticated server account, never a To header.
    """
    message = _object(message)
    payload = _object(message.get("payload", {}))
    headers = {}
    for header in _array(payload.get("headers", [])):
        header = _object(header)
        name = _identifier(header.get("name")).lower()
        if name not in {"from", "message-id", "in-reply-to", "references"}:
            continue
        if name in headers:
            raise FramingError("Duplicate relationship/identity header")
        value = header.get("value")
        if not isinstance(value, str):
            raise FramingError("Invalid email header")
        value = re.sub(r"\r\n[ \t]+", " ", value)
        headers[name] = _identifier(value) if value else ""
    own_ids = _message_ids(headers.get("message-id", ""))
    parent_ids = _message_ids(headers.get("in-reply-to", ""))
    references = _message_ids(headers.get("references", ""))
    if len(own_ids) > 1 or len(parent_ids) > 1:
        raise FramingError("Ambiguous exact message/parent header")
    if parent_ids and references and parent_ids[0] != references[-1]:
        raise FramingError("Parent header conflicts with reference chain")
    attachments = []

    def walk(part: dict[str, Any]) -> None:
        part = _object(part)
        body = _object(part.get("body", {}))
        if part.get("filename") or "attachmentId" in body:
            # Inline content has no retrievable attachmentId: explicit review.
            attachments.append(_identifier(body.get("attachmentId")))
        for child in _array(part.get("parts", [])):
            walk(child)

    walk(payload)
    thread = message.get("threadId")
    return ReplyFrame(
        tenant_id,
        "EMAIL",
        _mailbox(mailbox),
        _identifier(message.get("id")),
        _mailbox(headers.get("from", "")),
        _identifier(thread) if thread else None,
        parent_ids[0] if parent_ids else None,
        "SENDER_HEADER" if parent_ids else "NONE",
        own_ids[0] if own_ids else None,
        parent_ids,
        references,
        tuple(attachments),
    )


def verify_telegram_secret(expected: str | None, supplied: str | None) -> None:
    """Fail closed, including when webhook authentication is not configured."""
    if (
        not expected
        or not supplied
        or not hmac.compare_digest(expected.encode(), supplied.encode())
    ):
        raise FramingError("Telegram webhook authentication failed")


def verify_whatsapp_signature(
    raw_body: bytes, signature: str | None, app_secret: str | None
) -> None:
    """Check the exact HTTP bytes before JSON parsing; never persist secrets."""
    if not app_secret or not signature or not re.fullmatch(r"sha256=[a-f0-9]{64}", signature):
        raise FramingError("WhatsApp webhook authentication failed")
    expected = "sha256=" + hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise FramingError("WhatsApp webhook authentication failed")
