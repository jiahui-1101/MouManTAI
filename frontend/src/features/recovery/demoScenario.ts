/**
 * Deterministic, display-only P3 walkthrough. These values are illustrative
 * synthetic inputs and are deliberately not presented as an API assessment,
 * approval, customer response, or execution record.
 */
export const syntheticSupplierDelayScenario = {
  scenarioId: "p3-supplier-delay-v1",
  label: "SYNTHETIC WALKTHROUGH · READ ONLY",
  commitmentId: "com_001",
  orderId: "ord_001",
  item: "BURGER",
  quantity: 100,
  unit: "pcs",
  originalDeadline: "2026-10-24T15:00:00+08:00",
  resource: "PACKAGING",
  usableOnHand: 80,
  neededQuantity: 100,
  inboundQuantity: 20,
  originalSupplierEta: "2026-10-23T10:00:00+08:00",
  revisedSupplierEta: "2026-10-24T16:00:00+08:00",
  requiredBy: "2026-10-24T12:00:00+08:00",
  supplierEventId: "evt_supplier_delay_001",
  evidenceRefs: ["ev_stock_001", "ev_supplier_003"],
  affectedCommitmentIds: ["com_001", "com_002"],
  options: [
    {
      id: "alternative-supply",
      name: "Request 20 units from an alternative supplier",
      strategy: "ALTERNATIVE_SUPPLY",
      cost: "MYR 80.00 estimated",
      delay: "0 minutes expected if supply arrives before production cutoff",
      customerImpact: "Could protect the original deadline; availability is unconfirmed.",
      status: "CONDITIONAL",
      assumptions: [
        "An alternative supplier can provide 20 packaging units before the production cutoff.",
        "The MYR 80 estimate covers the stated extra supply cost only.",
      ],
      limitations: [
        "No quote or confirmed availability is included in this walkthrough.",
        "A current P2 evaluation and supplier confirmation are required before this can be treated as actionable.",
      ],
      decisionPrompt: "Would an authorized manager accept the estimated MYR 80 premium to protect the original deadline, subject to fresh validation and supplier confirmation?",
    },
    {
      id: "reschedule-delivery",
      name: "Propose delivery one day later",
      strategy: "RESCHEDULE_PARTIAL_FULFILMENT",
      cost: "MYR 0.00 estimated extra cost",
      delay: "24 hours · proposed deadline 25 Oct 2026, 15:00",
      customerImpact: "Changes the customer promise; acceptance is required before terms change.",
      status: "CUSTOMER DECISION REQUIRED",
      assumptions: [
        "The customer is willing to consider a revised delivery date.",
        "The later schedule remains feasible after P2 checks affected commitments and capacity.",
      ],
      limitations: [
        "No customer response is present in this walkthrough.",
        "The scenario does not establish feasibility for other affected commitments.",
      ],
      decisionPrompt: "Would the manager prefer to avoid the extra supply cost and ask the customer to consider a one-day delay, knowing the current promise stays unchanged until explicit acceptance?",
    },
  ],
} as const;

export type SyntheticRecoveryOption = (typeof syntheticSupplierDelayScenario.options)[number];
