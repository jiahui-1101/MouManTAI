# Backend E supplier sourcing boundary

The module consumes `app.suppliers.comparison.compare_offers` from stacked PR #49. It does not persist quotes, source messages, inventory, selections, plans, or approvals. All outputs are immutable, read-only decision material. The synthetic fixture in `backend/tests/v2_2/test_sourcing.py` demonstrates computation only.

## Owner interfaces needed for production

1. **P1 / mavisbong41:** Supply authenticated supplier identity and source evidence lookup satisfying `SupplierIdentityReader`, `SupplierEvidenceReader`, and versioned `SupplierQuoteReader`. The normalized reply must bind exact RFQ case/version, supplier, message and quote revision. A `supplier_identity_verified` field passed by a client is never an authentication mechanism; the owning P1 adapter must construct it.
2. **P5 / Gan0117 and business data owner:** Supply a tenant-scoped, repeatable `SupplierHistoryReader` with complete pagination, source watermark, approved promise baseline, immutable correction chain, purchase order and operational goods receipt refs. `load_authenticated_history` verifies the returned scope and all asserted verified refs through the owner adapter, but cannot prove real-world authenticity by itself. No official Orbyte endpoint or purchase data contract is present.
3. **P2 / meishuet16:** Treat `AlternativeSupplyHandoff` as quoted supply only; reevaluate with the authoritative P2 snapshot. Preserve PR #49's category/spec comparison semantics.
4. **P3 / jiahui-1101:** If useful, map `AlternativeSupplyHandoff` to a P3 `ALTERNATIVE_SUPPLY` candidate after binding current commitment, case and assessment versions. It is always `CONDITIONAL`. P3 owns plan approval and execution.
5. **P4 / Sheng554:** Accept `RFQDraft` only through a P4 approved sender path with recipient identity, consent, channel policy, dispatch idempotency and provider receipt. `NOT_SENT` is intentional.
6. **P5 / Gan0117:** Durable selection requires an authenticated SME command with current source/quote/spec version checks, actor/reason/audit and separate procurement authority. `SelectionPreview` has no write port.

## Requirement status

| Requirement | Backend E result | Remaining dependency |
|---|---|---|
| BE-SUP-01 | Canonical quote/evidence consumed; pure boundary | P1 extraction, storage, authenticated adapter |
| BE-SUP-02 | Canonical hard-spec comparator reused | PR #49 and approved tenant specs |
| BE-SUP-03 | History transfer, validation and metrics implemented and tested | Authoritative purchase/receipt reader and baseline policy |
| BE-SUP-04 | Dossier, RFQ, replies and selection preview implemented and tested | Owner-approved RFQ/send and SME selection/purchase command |
| BE-EM-02 | Conditional P3 handoff implemented and tested | P2 reevaluation and P3 mapping |
| BE-CTA-01/02 | No execution/send/purchase; approval prerequisites explicit | P3/P4/P5 authority |
| BE-ORB-01/02 | Typed read ports and adapter validation | Official business data contracts and live authenticated implementation |

These are **pure boundaries**, not live integration. `SYNTHETIC` history is disclosed in results; synthetic evidence refs do not establish Orbyte authority. A quote never establishes receipt, inventory, purchase permission, commitment safety or Recovery execution.
