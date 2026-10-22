"""Outbox dispatcher worker entrypoint for MouManTAI."""

from __future__ import annotations

import os

from app.core.outbox import OutboxDispatcher, default_dispatcher, run_worker
from app.db.session import SessionLocal


def configure_isolated_subscribers(dispatcher: OutboxDispatcher) -> None:
    """Enable persisted mandatory consumers only in an explicitly keyed E2E worker."""
    if os.getenv("MOUMANTAI_ISOLATED_E2E") != "1":
        return
    if len(os.getenv("MOUMANTAI_ISOLATED_E2E_KEY", "")) < 32:
        raise RuntimeError("Isolated E2E worker requires a server-owned mutation key")
    from app.recovery.trigger_persistence import (
        PersistedCoreAssessmentLookup,
        SessionScopedRecoveryTriggerAdapter,
    )
    from app.feasibility.confirmed_consumer import PersistedConfirmedEvaluator

    dispatcher.register_subscriber(
        "commitment.confirmed", "p2_confirmed_evaluator", PersistedConfirmedEvaluator().persist,
    )

    adapter = SessionScopedRecoveryTriggerAdapter(
        authoritative_assessment_lookup=PersistedCoreAssessmentLookup(),
    )
    dispatcher.register_subscriber("commitment.at_risk", "p3.recovery_trigger.v1", adapter.persist)


def main() -> None:
    configure_isolated_subscribers(default_dispatcher)
    run_worker(SessionLocal, poll_interval=1.0, dispatcher=default_dispatcher)


if __name__ == "__main__":
    main()
