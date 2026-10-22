"""P1 protocol injection only: no eager app.context/OCR imports or identity store."""
from typing import TYPE_CHECKING

from .demo_policy import deny
from .providers import MOCK_CHANNELS

if TYPE_CHECKING:
    from app.context.customer_directory import CustomerDirectory
    from app.context.association_schemas import PlatformIdentity


class DirectoryContactAdapter:
    def __init__(self, directory: "CustomerDirectory | None"):
        self.directory = directory

    @property
    def connected(self):
        return callable(getattr(self.directory, "get_customer", None)) and callable(
            getattr(self.directory, "get_contact_for_channel", None))

    def resolve(self, tenant, customer_id, channel) -> "PlatformIdentity":
        if channel not in MOCK_CHANNELS:
            deny("CONTACT_CHANNEL_UNSUPPORTED", "Only explicit mock channels are permitted")
        if not self.connected:
            deny("P1_CONTACT_CONTRACT_UNAVAILABLE", "Injected P1 Directory lacks typed channel contact resolution", 503)
        customer = self.directory.get_customer(tenant, customer_id)
        if customer is None or customer.tenant_id != tenant or customer.customer_id != customer_id:
            deny("CONTACT_CUSTOMER_NOT_FOUND", "Customer is not in the current tenant", 404)
        if customer.active is not True:
            deny("CONTACT_CUSTOMER_INACTIVE", "Customer is inactive")
        contact = self.directory.get_contact_for_channel(tenant, customer_id, channel)
        if (contact is None or getattr(contact, "channel", None) != channel or
            not isinstance(getattr(contact, "sender_identity_id", None), str) or not contact.sender_identity_id.strip()):
            deny("CONTACT_UNVERIFIED", "A verified contact for this channel is required")
        # verified_channels currently contains untyped phone strings. It cannot
        # establish a channel binding. Require P1's typed contact membership.
        verified = getattr(customer, "verified_contacts", None)
        if not verified or not any(
            getattr(item, "channel", None) == channel and
            getattr(item, "sender_identity_id", None) == contact.sender_identity_id
            for item in verified
        ):
            deny("CONTACT_UNVERIFIED", "Contact is absent from P1 typed verified contacts")
        return contact


def get_customer_directory() -> "CustomerDirectory | None":
    # Current P1 protocol has no get_contact_for_channel and importing its package
    # eagerly initializes OCR. No dynamic file-loader or copied model workaround.
    # P1/P5 can inject a real lightweight directory through this dependency once
    # its contract and import boundary exist. No fixture is installed by default.
    return None
