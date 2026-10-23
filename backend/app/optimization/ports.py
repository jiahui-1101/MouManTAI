"""Owner boundaries. Implementations must authenticate/read and verify through P2."""

from typing import Protocol

from .models import JointVerificationResult, P2ConstraintSpec, PortfolioRequest, ProjectedPortfolio


class ConstraintSpecProvider(Protocol):
    def build_for_portfolio(self, request: PortfolioRequest) -> P2ConstraintSpec: ...


class JointPortfolioVerifier(Protocol):
    def verify(
        self, request: PortfolioRequest, candidate: ProjectedPortfolio
    ) -> JointVerificationResult: ...
