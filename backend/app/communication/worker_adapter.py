"""P4 worker-facing entry point. P5 may register ticks using a separate UoW.

No mutation of the shared worker or its outbox consumer transaction occurs here.
"""
from .trusted_runtime import (IsolatedPrincipal, PersistedCommunicationAuthority,
    IsolatedPreferenceScope, IsolatedReminderAuthority)
from .confirmation_authority import ExistingP4ConfirmationAuthority
from .confirmations import ConfirmationService
from .followup import FollowUpService
from .outbound import OutboundService
from .preferences import PreferenceService
from .providers import LocalMockProvider
from .challenge_delivery import BoundChallengeDelivery, isolated_delivery_sink


def run_isolated_reminder_tick(session_factory, context, worker_key, directory, *, now=None, limit=50):
    with session_factory() as db:
        principal = IsolatedPrincipal(db, worker_key=worker_key)
        principal.require(context, "DISPATCH_REMINDER")
        authority = PersistedCommunicationAuthority(principal, directory)
        basis = ExistingP4ConfirmationAuthority(authority, authority)
        outbound = OutboundService(db, authority, authority, authority, LocalMockProvider(receipt_sink=isolated_delivery_sink()),
            challenge_delivery=BoundChallengeDelivery(basis))
        confirmations = ConfirmationService(db, None, basis, None)
        preferences = PreferenceService(db, IsolatedPreferenceScope(principal), directory)
        return FollowUpService(db, IsolatedReminderAuthority(principal), confirmations, outbound, preferences).run_due(
            context, now=now, limit=limit)
