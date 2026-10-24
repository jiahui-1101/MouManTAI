"""Evidence policy for synthetic fulfilment demonstrations.

The demo has no trusted warehouse/POD connector. Its only accepted fulfilment
reference is the exact tenant- and commitment-scoped form
``ev_synthetic_delivery|<tenant_id>|<commitment_id>|<evidence_id>``.
The ``|`` delimiter is reserved and each field must be non-empty and contain
no whitespace. This is a format check, not proof of a real-world delivery.
"""

from __future__ import annotations

import re


_SYNTHETIC_DELIVERY_REF = re.compile(
    r"^ev_synthetic_delivery\|(?P<tenant_id>[^|\s]+)\|"
    r"(?P<commitment_id>[^|\s]+)\|(?P<evidence_id>[^|\s]+)$"
)


def is_trusted_synthetic_delivery_ref(ref: str, *, tenant_id: str, commitment_id: str) -> bool:
    """Match the complete documented reference and its exact business scope."""
    match = _SYNTHETIC_DELIVERY_REF.fullmatch(ref)
    return bool(
        match
        and match.group("tenant_id") == tenant_id
        and match.group("commitment_id") == commitment_id
    )


def are_trusted_synthetic_delivery_refs(
    refs: list[str], *, tenant_id: str, commitment_id: str
) -> bool:
    """Require at least one valid reference and reject unrelated/forged extras."""
    return bool(refs) and all(
        is_trusted_synthetic_delivery_ref(ref, tenant_id=tenant_id, commitment_id=commitment_id)
        for ref in refs
    )
