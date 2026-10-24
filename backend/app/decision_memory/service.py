"""No public route, database mutation, provider call, or client-authored policy."""

from .assembly import assemble_case
from .governance import ReviewProposal, propose_review
from .lessons import OutcomeInsight, summarize
from .models import CurrentSituation, DecisionMemoryCase, RetrievalResult, SourceMode
from .ports import (
    AuthenticatedScope,
    DecisionHistoryReader,
    DecisionPolicyReader,
    SourceAuthenticityVerifier,
)
from .retrieval import retrieve
from .validation import HistoryValidationError, validate_source


class DecisionMemoryService:
    def __init__(
        self,
        identity: AuthenticatedScope | None = None,
        history: DecisionHistoryReader | None = None,
        policy: DecisionPolicyReader | None = None,
        authenticity: SourceAuthenticityVerifier | None = None,
    ) -> None:
        self.identity = identity
        self.history = history
        self.policy = policy
        self.authenticity = authenticity

    def _read(
        self, current: CurrentSituation, *, live: bool
    ) -> tuple[DecisionMemoryCase, ...] | str:
        if self.identity is None or self.history is None or self.authenticity is None:
            return "SOURCE_UNAVAILABLE"
        try:
            tenant_id, actor_id = self.identity.identity()
            if not actor_id or tenant_id != current.tenant_id:
                return "CONTEXT_UNVERIFIED"
            if not self.authenticity.verify_current(current, actor_id):
                return "CONTEXT_UNVERIFIED"
            manifest, inputs = self.history.read(
                tenant_id, current.domain.value, current.as_of.isoformat(), 1000
            )
            if manifest.as_of > current.as_of:
                return "SOURCE_INCOMPLETE"
            if manifest.tenant_id != tenant_id or not self.authenticity.verify(manifest, inputs):
                return "SOURCE_UNAVAILABLE"
            if live and manifest.integration_mode != SourceMode.LIVE:
                return "SOURCE_UNAVAILABLE"
            checked = validate_source(manifest, inputs)
            return tuple(assemble_case(case, manifest) for case in checked)
        except (HistoryValidationError, ValueError):
            return "SOURCE_INCOMPLETE"
        except (ConnectionError, TimeoutError, LookupError, PermissionError):
            return "SOURCE_UNAVAILABLE"

    def retrieve_similar_cases(
        self, current: CurrentSituation, *, live: bool = True
    ) -> RetrievalResult:
        cases = self._read(current, live=live)
        if isinstance(cases, str):
            return RetrievalResult(status=cases, eligible_count=0)
        if live and self.policy is None:
            return RetrievalResult(status="POLICY_NOT_APPROVED", eligible_count=0)
        try:
            approved = (
                self.policy.approved_policy(current.tenant_id, current.domain.value)
                if self.policy
                else None
            )
        except (ConnectionError, TimeoutError, LookupError, PermissionError):
            return RetrievalResult(status="POLICY_NOT_APPROVED", eligible_count=0)
        return retrieve(current, cases, approved, live=live)

    def summarize_verified_outcomes(self, current: CurrentSituation, *,
                                    live: bool = True) -> OutcomeInsight | str:
        cases = self._read(current, live=live)
        return cases if isinstance(cases, str) else summarize(cases)

    def propose_review_insights(self, current: CurrentSituation, *,
                                live: bool = True) -> ReviewProposal | str:
        insight = self.summarize_verified_outcomes(current, live=live)
        return (
            insight
            if isinstance(insight, str)
            else propose_review(current.tenant_id, current.domain, insight)
        )
