"""Outcome reconciliation requires independent operational evidence."""

from itertools import pairwise

from .models import Event, Evidence, OutcomeClass

OPERATIONAL_KINDS = {
    "RECOVERY": {"BUSINESS_RESOLUTION", "FULFILMENT_VERIFIED"},
    "SUPPLIER": {"GOODS_RECEIPT", "QUALITY_ACCEPTANCE"},
    "CAPACITY": {"CAPACITY_ACTUAL", "DEADLINE_ACTUAL"},
    "ORDER": {"FULFILMENT_VERIFIED"},
}


def reconcile_outcome(
    domain: str,
    outcomes: tuple[Event, ...],
    evidence: tuple[Evidence, ...],
) -> tuple[OutcomeClass, Event | None, tuple[str, ...]]:
    if not outcomes:
        return OutcomeClass.UNKNOWN, None, ()
    by_id = {e.evidence_id: e for e in evidence}
    ordered = sorted(outcomes, key=lambda e: (e.occurred_at, e.event_id))
    latest = ordered[-1]
    # A correction must link to its predecessor; conflicting unlinked claims fail closed.
    for before, after in pairwise(ordered):
        if before.status != after.status and after.corrects_id != before.event_id:
            return OutcomeClass.CONFLICTING_EVIDENCE, latest, ()
        if before.status != after.status:
            prior = {by_id[i].evidence_id: by_id[i] for i in before.evidence_ids if i in by_id}
            corrected = [by_id[i] for i in after.evidence_ids if i in by_id]
            if (
                not prior
                or not corrected
                or any(
                    p.corrects_id not in prior
                    or p.source_version <= prior[p.corrects_id].source_version
                    for p in corrected
                )
            ):
                return OutcomeClass.CONFLICTING_EVIDENCE, latest, ()
    proofs = tuple(by_id[i] for i in latest.evidence_ids if i in by_id)
    if len(proofs) != len(latest.evidence_ids) or not proofs:
        return OutcomeClass.REPORTED_ONLY, latest, ()
    kinds = {p.kind for p in proofs if p.authenticated and p.subject_id == latest.subject_id}
    if not kinds.intersection(OPERATIONAL_KINDS[domain]):
        return OutcomeClass.REPORTED_ONLY, latest, ()
    if latest.status == "SUCCESS":
        state = OutcomeClass.VERIFIED_SUCCESS
    elif latest.status == "FAILURE":
        state = OutcomeClass.VERIFIED_FAILURE
    elif latest.status == "PARTIAL":
        state = OutcomeClass.PARTIALLY_VERIFIED
    else:
        state = OutcomeClass.UNKNOWN
    return state, latest, tuple(p.evidence_id for p in proofs)
