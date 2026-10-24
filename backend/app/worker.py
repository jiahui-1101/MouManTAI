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
    from app.communication.core_confirmation_bridge import build_core_confirmation_consumer
    from app.core.confirmation import P5RecoveryOutboxBoundary, P5VerifiedCoreConfirmationPort
    from app.core.confirmed_event_source import PersistedConfirmedEventSourceProvider
    from app.core.feasibility_adapters import AuthoritativeAssessmentWriter
    from app.feasibility.consumer import create_p2_confirmed_evaluator
    from app.orchestration.service import consume_verified_recovery_task
    from app.recovery.confirmation_responses import register_p3_confirmation_response_consumer
    from app.recovery.eventing import P5OutboxPublisherAdapter
    from app.recovery.trigger_persistence import (
        PersistedCoreAssessmentLookup,
        SessionScopedRecoveryTriggerAdapter,
    )

    dispatcher.register_subscriber(
        "commitment.confirmed",
        "p2_confirmed_evaluator",
        create_p2_confirmed_evaluator(
            PersistedConfirmedEventSourceProvider(),
            AuthoritativeAssessmentWriter(),
        ),
    )

    adapter = SessionScopedRecoveryTriggerAdapter(
        authoritative_assessment_lookup=PersistedCoreAssessmentLookup(),
    )
    dispatcher.register_subscriber("commitment.at_risk", "p3.recovery_trigger.v1", adapter.persist)
    dispatcher.register_subscriber(
        "recovery.internal_task_created",
        "p5.recovery_notification_intent.v1",
        consume_verified_recovery_task,
    )

    confirmation_consumer = build_core_confirmation_consumer(P5VerifiedCoreConfirmationPort())
    for event_type in (
        "confirmation.accepted",
        "confirmation.rejected",
        "confirmation.counteroffer_received",
    ):
        dispatcher.register_subscriber(event_type, "p5.confirmation.required", confirmation_consumer)

    register_p3_confirmation_response_consumer(
        dispatcher,
        P5OutboxPublisherAdapter(P5RecoveryOutboxBoundary()),
    )


def main() -> None:
    configure_isolated_subscribers(default_dispatcher)
    run_worker(SessionLocal, poll_interval=1.0, dispatcher=default_dispatcher)


if __name__ == "__main__":
    main()
