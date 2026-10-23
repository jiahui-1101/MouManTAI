"""Read-only composition around owner-controlled identity, status and P4 readers.

No route binds this service until a real customer identity resolver and the
authoritative order-status reader are available. Transfer values from callers
are never accepted as authentication or source evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from typing import Protocol
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.models import CommitmentRecord

from .models import (
    EvidenceTier,
    Milestone,
    OperationalEvent,
    OrderFacts,
    RecipientPolicy,
    ReportingSource,
    SendHistory,
    StatusProjection,
    Template,
    status_matches,
)
from .planning import Eligibility, NotificationPlan, feedback_readiness, plan_milestone
from .reporting import DailyReport, aggregate_daily
from .validation import validate_events


@dataclass(frozen=True)
class VerifiedCaller:
    """Result of a server-owned authentication and customer-link resolver."""

    tenant_id: str
    actor_id: str
    customer_id: str | None
    may_read_reports: bool = False


class IdentityResolver(Protocol):
    def verify(self, context: RequestContext) -> VerifiedCaller | None: ...


@dataclass(frozen=True)
class CommitmentIdentity:
    tenant_id: str
    commitment_id: str
    order_id: str
    customer_id: str
    version: int
    updated_at: datetime


class CoreCommitmentLookup:
    """Existing Core identity only; never projects a lifecycle state."""

    def __init__(self, db: Session):
        self.db = db

    def find(self, caller: VerifiedCaller, commitment_id: str) -> CommitmentIdentity | None:
        if not caller.tenant_id or not caller.customer_id or not commitment_id:
            return None
        with self.db.no_autoflush:
            row = self.db.execute(
                select(
                    CommitmentRecord.tenant_id,
                    CommitmentRecord.commitment_id,
                    CommitmentRecord.order_id,
                    CommitmentRecord.customer_id,
                    CommitmentRecord.commitment_version,
                    CommitmentRecord.updated_at,
                ).where(
                    CommitmentRecord.tenant_id == caller.tenant_id,
                    CommitmentRecord.commitment_id == commitment_id,
                    CommitmentRecord.customer_id == caller.customer_id,
                )
            ).one_or_none()
        if row is None:
            return None
        return CommitmentIdentity(*row)


class CommitmentLookup(Protocol):
    def find(self, caller: VerifiedCaller, commitment_id: str) -> CommitmentIdentity | None: ...


class AuthoritativeOrderReader(Protocol):
    """To be implemented by the single status owner after PR #48 integration."""

    def read(self, identity: CommitmentIdentity) -> tuple[OrderFacts, StatusProjection] | None: ...


@dataclass(frozen=True)
class PurposePolicy:
    purpose: str
    recipient: RecipientPolicy
    complete: bool


@dataclass(frozen=True)
class ApprovedTemplate:
    template: Template
    approved: bool


@dataclass(frozen=True)
class HistoryResult:
    history: SendHistory
    unresolved_keys: frozenset[str] = frozenset()


class CommunicationReader(Protocol):
    def policy(self, identity: CommitmentIdentity, purpose: str) -> PurposePolicy | None: ...

    def template(self, milestone: Milestone) -> ApprovedTemplate | None: ...

    def history(self, identity: CommitmentIdentity, purpose: str) -> HistoryResult | None: ...


class ReadCode(StrEnum):
    VERIFIED_STATUS_AVAILABLE = "VERIFIED_STATUS_AVAILABLE"
    STATUS_UNKNOWN = "STATUS_UNKNOWN"
    NOT_FOUND = "NOT_FOUND"
    AUTHORIZATION_DENIED = "AUTHORIZATION_DENIED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    SOURCE_STALE = "SOURCE_STALE"
    EVIDENCE_MISSING = "EVIDENCE_MISSING"


@dataclass(frozen=True)
class OrderRead:
    code: ReadCode
    facts: OrderFacts | None = None
    status: StatusProjection | None = None


class OperationalReadService:
    def __init__(
        self,
        identity_resolver: IdentityResolver | None,
        commitments: CommitmentLookup,
        orders: AuthoritativeOrderReader | None = None,
        communication: CommunicationReader | None = None,
    ):
        self.identity_resolver = identity_resolver
        self.commitments = commitments
        self.orders = orders
        self.communication = communication

    def _identity(
        self, context: RequestContext, commitment_id: str
    ) -> tuple[ReadCode | None, CommitmentIdentity | None]:
        if self.identity_resolver is None:
            return ReadCode.AUTHORIZATION_DENIED, None
        caller = self.identity_resolver.verify(context)
        if (
            caller is None
            or caller.tenant_id != context.tenant_id
            or caller.actor_id != context.actor_id
            or not caller.customer_id
        ):
            return ReadCode.AUTHORIZATION_DENIED, None
        identity = self.commitments.find(caller, commitment_id)
        return (None, identity) if identity else (ReadCode.NOT_FOUND, None)

    def read_order(
        self, context: RequestContext, commitment_id: str, *, as_of: datetime
    ) -> OrderRead:
        code, identity = self._identity(context, commitment_id)
        if code is not None:
            return OrderRead(code)
        if self.orders is None:
            return OrderRead(ReadCode.SOURCE_UNAVAILABLE)
        assert identity is not None
        pair = self.orders.read(identity)
        if pair is None:
            return OrderRead(ReadCode.SOURCE_UNAVAILABLE)
        facts, status = pair
        if (
            (facts.tenant_id, facts.commitment_id, facts.order_id, facts.customer_id)
            != (identity.tenant_id, identity.commitment_id, identity.order_id, identity.customer_id)
            or facts.aggregate_version != identity.version
            or not status_matches(facts, status, as_of=as_of)
        ):
            return OrderRead(ReadCode.SOURCE_STALE)
        # A second Core read catches concurrent writes when the caller's session
        # does not provide repeatable-read isolation.
        _, latest = self._identity(context, commitment_id)
        if latest != identity:
            return OrderRead(ReadCode.SOURCE_STALE)
        if status.milestone == Milestone.NOT_AVAILABLE:
            return OrderRead(ReadCode.STATUS_UNKNOWN, facts, status)
        if not validate_events(facts, status, as_of=as_of).usable:
            return OrderRead(ReadCode.EVIDENCE_MISSING)
        if status.evidence_tier != EvidenceTier.VERIFIED:
            return OrderRead(ReadCode.STATUS_UNKNOWN, facts, status)
        return OrderRead(ReadCode.VERIFIED_STATUS_AVAILABLE, facts, status)

    def plan(
        self,
        context: RequestContext,
        commitment_id: str,
        event_id: str,
        *,
        as_of: datetime,
        feedback: bool = False,
    ) -> NotificationPlan:
        read = self.read_order(context, commitment_id, as_of=as_of)
        if read.code != ReadCode.VERIFIED_STATUS_AVAILABLE:
            return NotificationPlan(Eligibility.UNKNOWN, read.code.value)
        assert read.facts is not None and read.status is not None
        facts, status = read.facts, read.status
        if self.communication is None:
            return NotificationPlan(Eligibility.UNKNOWN, "P4_UNAVAILABLE")
        identity = CommitmentIdentity(
            facts.tenant_id,
            facts.commitment_id,
            facts.order_id,
            facts.customer_id,
            facts.aggregate_version,
            facts.updated_at,
        )
        purpose = "FEEDBACK" if feedback else "MILESTONE"
        policy = self.communication.policy(identity, purpose)
        if policy is None or not policy.complete or policy.purpose != purpose:
            return NotificationPlan(Eligibility.UNKNOWN, "PURPOSE_POLICY_UNAVAILABLE")
        history = self.communication.history(identity, purpose)
        if history is None or not history.history.complete:
            return NotificationPlan(Eligibility.UNKNOWN, "SEND_HISTORY_UNKNOWN")
        if feedback:
            result = feedback_readiness(
                facts, status, policy.recipient, history.history, as_of=as_of
            )
        else:
            event: OperationalEvent | None = next(
                (item for item in facts.events if item.event_id == event_id), None
            )
            if event is None:
                return NotificationPlan(Eligibility.UNKNOWN, "EVENT_SOURCE_MISSING")
            template = self.communication.template(status.milestone)
            if template is None or not template.approved:
                return NotificationPlan(Eligibility.UNKNOWN, "APPROVED_TEMPLATE_UNAVAILABLE")
            result = plan_milestone(
                facts,
                status,
                event,
                policy.recipient,
                template.template,
                history.history,
                as_of=as_of,
            )
        if result.dedup_key in history.unresolved_keys:
            return NotificationPlan(Eligibility.UNKNOWN, "PROVIDER_OUTCOME_UNKNOWN")
        return result


@dataclass(frozen=True)
class ReportPage:
    orders: tuple[tuple[OrderFacts, StatusProjection], ...]
    next_cursor: str | None
    watermark_at: datetime
    complete: bool
    missing_sources: tuple[str, ...] = ()


class DailyOrderReader(Protocol):
    def page(
        self, tenant_id: str, start: datetime, end: datetime, cursor: str | None
    ) -> ReportPage | None: ...


def read_daily(
    context: RequestContext,
    resolver: IdentityResolver | None,
    reader: DailyOrderReader | None,
    day: date,
    timezone: str,
    *,
    as_of: datetime,
    max_pages: int = 100,
) -> DailyReport | None:
    """Staff-only bounded page composition; None means authorization denied."""
    caller = resolver.verify(context) if resolver else None
    if (
        caller is None
        or caller.tenant_id != context.tenant_id
        or caller.actor_id != context.actor_id
        or not caller.may_read_reports
    ):
        return None
    zone = ZoneInfo(timezone)
    start = datetime.combine(day, time.min, zone)
    end = datetime.combine(day + timedelta(days=1), time.min, zone)
    orders: list[tuple[OrderFacts, StatusProjection]] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()
    watermark: datetime | None = None
    complete = reader is not None
    missing: set[str] = set()
    for _ in range(max_pages if reader else 0):
        page = reader.page(caller.tenant_id, start, end, cursor)
        if page is None:
            complete = False
            missing.add("ORDER_SOURCE_UNAVAILABLE")
            break
        if (
            page.watermark_at.tzinfo is None
            or page.watermark_at.utcoffset() is None
            or page.watermark_at.astimezone(UTC) > as_of.astimezone(UTC)
            or (watermark is not None and page.watermark_at != watermark)
        ):
            complete = False
            missing.add("SOURCE_WATERMARK_MISMATCH")
            break
        watermark = page.watermark_at
        orders.extend(page.orders)
        missing.update(page.missing_sources)
        complete &= page.complete
        if page.next_cursor is None:
            break
        if page.next_cursor in seen_cursors:
            complete = False
            missing.add("PAGINATION_CYCLE")
            break
        seen_cursors.add(page.next_cursor)
        cursor = page.next_cursor
    else:
        complete = False
        missing.add("PAGINATION_INCOMPLETE")
    if reader is None:
        missing.add("ORDER_SOURCE_UNAVAILABLE")
    watermark = watermark or min(as_of, end)
    source = ReportingSource(
        caller.tenant_id,
        start,
        end,
        watermark,
        complete and watermark.astimezone(UTC) >= end.astimezone(UTC),
        complete,
        tuple(sorted(missing)),
    )
    return aggregate_daily(
        caller.tenant_id, day, timezone, tuple(orders), as_of=as_of, source=source
    )
