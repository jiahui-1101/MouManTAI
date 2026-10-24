"""Synthetic framing tests; no sockets, contact authority or business mutations."""

import hashlib
import hmac
from dataclasses import FrozenInstanceError, replace

import pytest

from app.context.channels.reply_framing import (
    FramingError,
    email_frame,
    resolve_parent,
    telegram_frame,
    verify_telegram_secret,
    verify_whatsapp_signature,
    whatsapp_frame,
)


def tg(message_id=2, parent=1, **changes):
    message = {
        "message_id": message_id,
        "chat": {"id": -100},
        "from": {"id": 42},
        "text": "yes, I am the supplier",
    }
    if parent is not None:
        message["reply_to_message"] = {"message_id": parent, "chat": {"id": -100}}
    message.update(changes)
    return telegram_frame({"message": message}, tenant_id="tenant", account_id="bot")


def mail(message_id="native-2", headers=None, **kwargs):
    return email_frame(
        {
            "id": message_id,
            "threadId": "thread",
            "payload": {
                "headers": headers
                or [
                    {"name": "From", "value": "Customer <sender@example.test>"},
                    {"name": "Message-ID", "value": "<two@example.test>"},
                    {"name": "In-Reply-To", "value": "<one@example.test>"},
                    {"name": "References", "value": "<root@example.test> <one@example.test>"},
                ]
            },
        },
        tenant_id="tenant",
        mailbox=" Sales@EXAMPLE.test ",
        **kwargs,
    )


def test_new_message_has_no_parent():
    frame = tg(parent=None)
    assert frame.exact_parent_id is None
    assert resolve_parent(frame, []).state == "NO_EXACT_PARENT"


def test_telegram_native_chat_and_exact_quote_are_separate():
    frame = tg()
    assert (frame.native_message_id, frame.conversation_id) == ("2", "-100")
    assert frame.exact_parent_id == "1"
    assert frame.sender_id == "42"
    result = resolve_parent(frame, [tg(1, None)])
    assert result.state == "REFERENCE_MATCH"
    assert result.parent_native_id == "1"
    assert frame.relationship_source == "PROVIDER_QUOTE"


def test_whatsapp_context_is_exact_parent():
    frame = whatsapp_frame(
        {"id": "wamid.2", "from": "60100000000", "type": "text", "context": {"id": "wamid.1"}},
        tenant_id="tenant",
        account_id="phone-number-id",
        callback_account_id="phone-number-id",
    )
    assert frame.native_message_id == "wamid.2"
    assert frame.exact_parent_id == "wamid.1"
    assert frame.conversation_id == "60100000000"
    assert frame.sender_id == "60100000000"
    assert (
        resolve_parent(
            frame, [replace(frame, native_message_id="wamid.1", exact_parent_id=None)]
        ).state
        == "REFERENCE_MATCH"
    )
    plain = replace(frame, exact_parent_id=None)
    assert resolve_parent(plain, [frame]).state == "NO_EXACT_PARENT"


def test_email_keeps_native_and_rfc_namespaces():
    frame = mail()
    assert frame.account_id == "Sales@example.test"
    assert frame.native_message_id == "native-2"
    assert frame.rfc_message_id == "<two@example.test>"
    assert frame.in_reply_to == ("<one@example.test>",)
    assert frame.references == ("<root@example.test>", "<one@example.test>")
    assert frame.exact_parent_id == "<one@example.test>"
    assert frame.relationship_source == "SENDER_HEADER"
    parent = replace(
        frame,
        native_message_id="native-1",
        rfc_message_id="<one@example.test>",
        exact_parent_id=None,
    )
    assert resolve_parent(frame, [parent]).parent_native_id == "native-1"
    # Native provider IDs are never treated as RFC Message-IDs.
    assert (
        resolve_parent(
            frame, [replace(parent, rfc_message_id=None, native_message_id="<one@example.test>")]
        ).state
        == "UNRESOLVED"
    )


def test_references_only_never_invents_exact_parent():
    headers = [
        {"name": "From", "value": "sender@example.test"},
        {"name": "References", "value": "<root@example.test> <one@example.test>"},
    ]
    frame = mail(headers=headers)
    assert frame.references == ("<root@example.test>", "<one@example.test>")
    assert frame.exact_parent_id is None


def test_same_thread_different_parent_does_not_match():
    assert resolve_parent(tg(), [tg(3, None)]).state == "UNRESOLVED"


def test_out_of_order_reference_can_be_resolved_without_mutating_source():
    reply = tg()
    assert resolve_parent(reply, []).state == "UNRESOLVED"
    assert resolve_parent(reply, [tg(1, None)]).state == "REFERENCE_MATCH"
    assert reply.exact_parent_id == "1"
    with pytest.raises(FrozenInstanceError):
        reply.exact_parent_id = "3"


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", "other"),
        ("provider", "WHATSAPP"),
        ("account_id", "other-bot"),
        ("conversation_id", "other-chat"),
    ],
)
def test_cross_scope_parent_is_not_linked(field, value):
    assert resolve_parent(tg(), [replace(tg(1, None), **{field: value})]).state == "UNRESOLVED"


def test_ambiguous_parent_fails_closed():
    assert resolve_parent(tg(), [tg(1, None), tg(1, None)]).state == "AMBIGUOUS"


def test_self_reply_is_rejected():
    with pytest.raises(FramingError):
        tg(message_id=1, parent=1)


@pytest.mark.parametrize(
    "changes",
    [
        {"from": {}},
        {"chat": {}},
        {"message_id": None},
        {"message_id": True},
        {"reply_to_message": {}},
        {"reply_to_message": {"message_id": 1, "chat": {"id": 999}}},
    ],
)
def test_invalid_telegram_identity_or_parent_fails_closed(changes):
    with pytest.raises(FramingError):
        tg(**changes)


def test_unknown_telegram_external_reply_is_not_same_chat_parent():
    frame = tg(parent=None, external_reply={"message_id": 1, "chat": {"id": 999}})
    assert frame.exact_parent_id is None


@pytest.mark.parametrize(
    "headers",
    [
        [{"name": "From", "value": "one@example.test, two@example.test"}],
        [{"name": "From", "value": "not-an-address"}],
        [
            {"name": "From", "value": "one@example.test"},
            {"name": "In-Reply-To", "value": "<one@example.test> <two@example.test>"},
        ],
        [
            {"name": "From", "value": "one@example.test"},
            {"name": "In-Reply-To", "value": "subject match"},
        ],
        [
            {"name": "From", "value": "one@example.test"},
            {"name": "Message-ID", "value": "<one@example.test>"},
            {"name": "Message-ID", "value": "<two@example.test>"},
        ],
        [{"name": "From", "value": "one@example.test\r\nBcc: other@example.test"}],
    ],
)
def test_ambiguous_or_invalid_email_headers_fail_closed(headers):
    with pytest.raises(FramingError):
        mail(headers=headers)


def test_email_folding_and_mailbox_local_part_are_preserved():
    headers = [
        {"name": "From", "value": "Person <Sender@EXAMPLE.test>"},
        {"name": "References", "value": "<a@example.test>\r\n <b@example.test>"},
    ]
    frame = mail(headers=headers)
    assert frame.sender_id == "Sender@example.test"
    assert frame.references == ("<a@example.test>", "<b@example.test>")
    assert (
        resolve_parent(mail(), [replace(mail(), account_id="sales@example.test")]).state
        == "UNRESOLVED"
    )


def test_whatsapp_callback_account_must_match_server_configuration():
    with pytest.raises(FramingError):
        whatsapp_frame(
            {"id": "wamid.1", "from": "60100000000"},
            tenant_id="tenant",
            account_id="expected",
            callback_account_id="other",
        )


@pytest.mark.parametrize(
    "secret,header", [(None, None), ("", ""), ("secret", None), ("secret", "wrong")]
)
def test_unsigned_or_spoofed_telegram_is_rejected(secret, header):
    with pytest.raises(FramingError):
        verify_telegram_secret(secret, header)


def test_valid_telegram_secret():
    assert verify_telegram_secret("secret", "secret") is None


def test_whatsapp_signature_binds_exact_raw_bytes():
    body = b'{"synthetic":true}'
    signature = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert verify_whatsapp_signature(body, signature, "secret") is None
    for changed_body, header, secret in [
        (body + b" ", signature, "secret"),
        (body, None, "secret"),
        (body, signature, None),
        (body, "sha256=garbage", "secret"),
    ]:
        with pytest.raises(FramingError):
            verify_whatsapp_signature(changed_body, header, secret)


def test_attachment_native_source_reference_preserved():
    frame = tg(document={"file_id": "telegram-file", "file_unique_id": "unique"})
    assert frame.attachment_source_ids == ("telegram-file",)


@pytest.mark.parametrize(
    "changes",
    [
        {"document": {}},
        {"photo": [{}]},
        {"document": {"file_id": ""}},
    ],
)
def test_missing_attachment_reference_fails_closed(changes):
    with pytest.raises(FramingError):
        tg(**changes)


def test_text_or_display_name_never_grants_business_authority():
    frame = tg()
    assert not hasattr(frame, "customer_id")
    assert not hasattr(frame, "supplier_id")
    assert not hasattr(frame, "accepted")
    assert not hasattr(frame, "customer_assent")
    assert not hasattr(frame, "delivery_status")


@pytest.mark.parametrize(
    "changes", [{"from": None}, {"chat": []}, {"document": None}, {"photo": [None]}]
)
def test_malformed_telegram_objects_use_fail_closed_error(changes):
    with pytest.raises(FramingError):
        tg(**changes)


@pytest.mark.parametrize("provider", ["WHATSAPP", "EMAIL"])
def test_missing_native_attachment_reference_on_other_providers(provider):
    with pytest.raises(FramingError):
        if provider == "WHATSAPP":
            whatsapp_frame(
                {
                    "id": "wamid.2",
                    "from": "60100000000",
                    "type": "document",
                    "document": {"filename": "order.pdf"},
                },
                tenant_id="tenant",
                account_id="phone",
                callback_account_id="phone",
            )
        else:
            email_frame(
                {
                    "id": "native",
                    "payload": {
                        "headers": [{"name": "From", "value": "sender@example.test"}],
                        "parts": [{"filename": "order.pdf", "body": {}}],
                    },
                },
                tenant_id="tenant",
                mailbox="sales@example.test",
            )


def test_email_conflicting_parent_and_reference_chain_require_review():
    with pytest.raises(FramingError):
        mail(
            headers=[
                {"name": "From", "value": "sender@example.test"},
                {"name": "In-Reply-To", "value": "<one@example.test>"},
                {"name": "References", "value": "<different@example.test>"},
            ]
        )


def test_unsupported_telegram_attachment_is_not_silently_lost():
    with pytest.raises(FramingError):
        tg(voice={"file_id": "voice-source"})


def test_unnamed_email_attachment_native_reference_is_preserved():
    frame = email_frame(
        {
            "id": "native",
            "payload": {
                "headers": [{"name": "From", "value": "sender@example.test"}],
                "parts": [{"body": {"attachmentId": "unnamed-native-attachment"}}],
            },
        },
        tenant_id="tenant",
        mailbox="sales@example.test",
    )
    assert frame.attachment_source_ids == ("unnamed-native-attachment",)
