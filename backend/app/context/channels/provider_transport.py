"""Internal C2 provider transport contracts. These are deliberately not wired to P4."""

from __future__ import annotations

import hashlib
import json
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Literal

import httpx


def source_evidence_key(
    tenant_id: str, provider: str, account_id: str | None, source_ids: list[str], content: bytes
) -> str:
    """Stable scoped source bytes; changed bytes cannot overwrite prior evidence."""
    if not tenant_id or not account_id or not source_ids:
        raise ValueError("Attachment source account and native identity are required")
    identity = [tenant_id, provider, account_id, source_ids, hashlib.sha256(content).hexdigest()]
    return hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()[:32]


ProviderErrorClass = Literal["AUTHENTICATION", "RATE_LIMITED", "TRANSIENT", "PERMANENT", "UNKNOWN"]
ProviderSendState = Literal["ACCEPTED", "REJECTED", "UNKNOWN"]


@dataclass(frozen=True)
class ProviderSendResult:
    provider: str
    state: ProviderSendState
    provider_message_id: str | None = None
    provider_status: str | None = None
    error_class: ProviderErrorClass | None = None
    error_code: str | None = None
    idempotency_key: str | None = None
    idempotent_replay: bool = False


@dataclass(frozen=True)
class ProviderStatusReceipt:
    provider: str
    tenant_id: str
    provider_message_id: str
    state: Literal["SENT", "DELIVERED", "READ", "FAILED", "UNKNOWN"]
    occurred_at: str | None = None
    error_code: str | None = None


class ProviderTransportError(RuntimeError):
    """Sanitized, classified provider error; never embeds a request URL or body."""

    def __init__(self, provider: str, error_class: ProviderErrorClass, error_code: str):
        self.provider = provider
        self.error_class = error_class
        self.error_code = error_code
        super().__init__(f"{provider} transport failed ({error_code}; {error_class})")


def classify_http_status(
    status_code: int,
) -> tuple[ProviderSendState, ProviderErrorClass | None, str | None]:
    if 200 <= status_code < 300:
        return "ACCEPTED", None, None
    if status_code in {401, 403}:
        return "REJECTED", "AUTHENTICATION", "PROVIDER_AUTH_REJECTED"
    if status_code == 429:
        return "REJECTED", "RATE_LIMITED", "PROVIDER_RATE_LIMITED"
    if status_code >= 500:
        return "UNKNOWN", "TRANSIENT", "PROVIDER_SERVER_ERROR"
    return "REJECTED", "PERMANENT", "PROVIDER_REQUEST_REJECTED"


def safe_get(client: httpx.Client, url: str, **kwargs) -> httpx.Response:
    """Retry one time only for safe GET reads after network failure or a gateway 5xx."""
    for attempt in range(2):
        try:
            response = client.get(url, **kwargs)
        except httpx.RequestError:
            if attempt:
                raise
            continue
        if response.status_code not in {502, 503, 504} or attempt:
            return response
    raise AssertionError("unreachable")


class ProviderPayloadTooLarge(ValueError):
    """A provider response exceeded the configured in-memory retrieval bound."""


def read_limited_get(client: httpx.Client, url: str, max_bytes: int, **kwargs) -> tuple[int, bytes]:
    """Read a GET response in bounded chunks; retry only safe network/gateway failures once."""
    for attempt in range(2):
        try:
            with client.stream("GET", url, **kwargs) as response:
                if response.status_code in {502, 503, 504} and not attempt:
                    continue
                if not response.is_success:
                    return response.status_code, b""
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > max_bytes:
                    raise ProviderPayloadTooLarge(
                        "provider response exceeded the configured size limit"
                    )
                content = bytearray()
                for chunk in response.iter_bytes():
                    if len(content) + len(chunk) > max_bytes:
                        raise ProviderPayloadTooLarge(
                            "provider response exceeded the configured size limit"
                        )
                    content.extend(chunk)
                return response.status_code, bytes(content)
        except httpx.RequestError:
            if attempt:
                raise
    raise AssertionError("unreachable")


class ProcessIdempotencyGate:
    """Prevent duplicate sends within one adapter process.

    Durable idempotency is owned by P4. The gate intentionally caches UNKNOWN outcomes too:
    a timeout must not cause the same transport side effect to be replayed automatically.
    """

    def __init__(self, max_entries: int = 4096):
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[str, ProviderSendResult]] = {}
        self._max_entries = max_entries

    def execute(
        self, key: str, request_fingerprint: str, operation: Callable[[], ProviderSendResult]
    ) -> ProviderSendResult:
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,200}", key):
            raise ValueError("a bounded, header-safe idempotency key is required")
        with self._lock:
            existing = self._entries.get(key)
            if existing is not None:
                old_fingerprint, old_result = existing
                if old_fingerprint != request_fingerprint:
                    raise ValueError("idempotency key is already bound to a different request")
                return replace(old_result, idempotent_replay=True)
            result = operation()
            self._entries[key] = (request_fingerprint, result)
            if len(self._entries) > self._max_entries:
                self._entries.pop(next(iter(self._entries)))
            return result
