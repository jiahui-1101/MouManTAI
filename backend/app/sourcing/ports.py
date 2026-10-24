"""Owner-supplied authenticated, tenant-scoped, repeatable read interfaces."""

from typing import Protocol

from app.sourcing.history import HistorySnapshot
from app.suppliers.comparison import SupplierOffer


class SupplierHistoryReader(Protocol):
    def read_history(
        self, *, tenant_id: str, supplier_id: str, source_watermark: str | None = None
    ) -> HistorySnapshot: ...


class SupplierQuoteReader(Protocol):
    def read_quote(
        self,
        *,
        tenant_id: str,
        supplier_id: str,
        quote_id: str,
        quote_version: int,
        source_watermark: str | None = None,
    ) -> SupplierOffer: ...


class SupplierEvidenceReader(Protocol):
    def authenticated_refs(
        self, *, tenant_id: str, refs: tuple[str, ...], source_watermark: str
    ) -> frozenset[str]: ...


class SupplierIdentityReader(Protocol):
    def verified_supplier(
        self, *, tenant_id: str, supplier_id: str, source_watermark: str
    ) -> bool: ...


def load_authenticated_history(
    *,
    tenant_id: str,
    supplier_id: str,
    expected_source_watermark: str | None = None,
    history_reader: SupplierHistoryReader,
    evidence_reader: SupplierEvidenceReader,
    identity_reader: SupplierIdentityReader,
) -> HistorySnapshot:
    """Bind a reader snapshot and every purported verified ref to its owning adapters."""
    snapshot = history_reader.read_history(
        tenant_id=tenant_id, supplier_id=supplier_id, source_watermark=expected_source_watermark
    )
    if (
        snapshot.tenant_id != tenant_id
        or snapshot.supplier_id != supplier_id
        or (
            expected_source_watermark is not None
            and snapshot.source_watermark != expected_source_watermark
        )
        or not snapshot.consistent_read
    ):
        raise ValueError("History reader returned an unbound snapshot")
    if not identity_reader.verified_supplier(
        tenant_id=tenant_id, supplier_id=supplier_id, source_watermark=snapshot.source_watermark
    ):
        raise ValueError("Supplier identity not authenticated")
    refs = tuple(
        sorted(
            {
                ref
                for fact in snapshot.facts
                if fact.trust_tier == "VERIFIED"
                for ref in (
                    *fact.original_evidence_refs,
                    *fact.receipt_evidence_refs,
                    *((fact.promise_baseline_ref,) if fact.promise_baseline_ref else ()),
                )
            }
        )
    )
    authenticated = evidence_reader.authenticated_refs(
        tenant_id=tenant_id, refs=refs, source_watermark=snapshot.source_watermark
    )
    if not set(refs) <= authenticated:
        raise ValueError("Verified evidence refs not authenticated")
    return snapshot


def load_authenticated_quote(
    *,
    tenant_id: str,
    supplier_id: str,
    quote_id: str,
    quote_version: int,
    source_watermark: str,
    quote_reader: SupplierQuoteReader,
    evidence_reader: SupplierEvidenceReader,
    identity_reader: SupplierIdentityReader,
) -> SupplierOffer:
    if not identity_reader.verified_supplier(
        tenant_id=tenant_id, supplier_id=supplier_id, source_watermark=source_watermark
    ):
        raise ValueError("Supplier identity not authenticated")
    offer = quote_reader.read_quote(
        tenant_id=tenant_id,
        supplier_id=supplier_id,
        quote_id=quote_id,
        quote_version=quote_version,
        source_watermark=source_watermark,
    )
    if (offer.tenant_id, offer.supplier_id, offer.quote_id, offer.quote_version) != (
        tenant_id,
        supplier_id,
        quote_id,
        quote_version,
    ):
        raise ValueError("Quote reader returned wrong identity or version")
    refs = tuple(
        sorted(
            {
                *offer.evidence_refs,
                *offer.pack_evidence_refs,
                *offer.availability_evidence_refs,
                *offer.verification_evidence_refs,
                *offer.arrival_evidence_refs,
                *(ref for prop in offer.properties for ref in prop.evidence_refs),
            }
        )
    )
    authenticated = evidence_reader.authenticated_refs(
        tenant_id=tenant_id, refs=refs, source_watermark=source_watermark
    )
    if not refs or not set(refs) <= authenticated:
        raise ValueError("Quote evidence not authenticated")
    return offer
