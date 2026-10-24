"""Owner-provided authenticated, read-only access boundaries."""

from typing import Protocol

from .models import CaseInput, CurrentSituation, RetrievalPolicy, SourceManifest


class AuthenticatedScope(Protocol):
    def identity(self) -> tuple[str, str]:
        """Return server-resolved tenant and actor, or raise on failure."""


class DecisionHistoryReader(Protocol):
    def read(
        self, tenant_id: str, domain: str, as_of: str, limit: int
    ) -> tuple[SourceManifest, tuple[CaseInput, ...]]:
        """Return one authenticated, complete, consistent owner snapshot."""


class DecisionPolicyReader(Protocol):
    def approved_policy(self, tenant_id: str, domain: str) -> RetrievalPolicy | None:
        """Return owner-authorized live policy; a caller object is insufficient."""


class SourceAuthenticityVerifier(Protocol):
    def verify(self, manifest: SourceManifest, cases: tuple[CaseInput, ...]) -> bool:
        """Authenticate the source and each underlying evidence binding."""

    def verify_current(self, current: CurrentSituation, actor_id: str) -> bool:
        """Authenticate the current context, evidence, and actor access."""


class ReadOnlyCaseConsumer(Protocol):
    def consume(self, case_ref: str, outcome_ref: str | None) -> None:
        """Optional P2/P3/Reporting/Forecasting/Supplier reader contract."""
