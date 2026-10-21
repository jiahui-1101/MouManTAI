from __future__ import annotations

from typing import Any


class DomainError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        self.correlation_id = correlation_id


class InsufficientResourceError(DomainError):
    """Raised when requested reservation exceeds available resource stock (HTTP 409 Conflict)."""

    def __init__(
        self,
        message: str = "Insufficient available resource stock for reservation",
        *,
        details: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> None:
        super().__init__(
            "INSUFFICIENT_RESOURCE",
            message,
            status_code=409,
            details=details,
            correlation_id=correlation_id,
        )
