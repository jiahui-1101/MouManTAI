import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { OriginBadge, DeliveryModeBadge, getCaseOrigin, getDeliveryMode } from "../presentation";
import type { CommunicationRequestView } from "../types";

function mockRequest(overrides: Partial<CommunicationRequestView> = {}): CommunicationRequestView {
  return {
    communication_id: "comm_test_001",
    reference: {
      tenant_id: "synthetic_tenant_a",
      commitment_id: "com_001",
      plan_id: "plan_01",
      plan_version: 1,
      proposal_id: "prop_01",
      proposal_version: 1,
      source_event_id: "evt_01",
      commitment_version: 1,
      correlation_id: "corr_01",
      causation_id: null,
      occurred_at: "2026-10-24T12:00:00Z",
    },
    request_status: "READY_FOR_DRAFTING",
    blocking_reasons: [],
    proposed_terms: {
      sku: "BURGER_PREMIUM",
      quantity: "100",
      unit: "pcs",
      deadline: "2026-10-25T12:00:00Z",
    },
    message_status: "DRAFT",
    approval_evidence_refs: ["ev_app_01"],
    approval_expires_at: "2026-10-26T12:00:00Z",
    proposal_evidence_refs: ["ev_prop_01"],
    recipient_identity_id: "identity_cust_01",
    recipient_evidence_refs: ["ev_rec_01"],
    channel: "MOCK_EMAIL",
    channel_evidence_refs: ["ev_chan_01"],
    expires_at: "2026-10-26T12:00:00Z",
    created_by: "user_manager_01",
    created_at: "2026-10-24T12:00:00Z",
    outbound_status: null,
    source_origin: "SYNTHETIC",
    delivery_mode: "SIMULATED",
    ...overrides,
  };
}

describe("Source Origin and Delivery Mode Badges", () => {
  describe("getCaseOrigin and OriginBadge", () => {
    it("renders 'Synthetic' for synthetic/mock cases, NOT 'Mock EMAIL' or 'Mock WHATSAPP'", () => {
      const req = mockRequest({ channel: "MOCK_EMAIL", source_origin: "SYNTHETIC" });
      const origin = getCaseOrigin(req);
      expect(origin.label).toBe("Synthetic");
      expect(origin.type).toBe("synthetic");

      render(<OriginBadge request={req} />);
      const badge = screen.getByTestId("origin-badge");
      expect(badge).toHaveTextContent("Synthetic");
      expect(badge).not.toHaveTextContent("Mock EMAIL");
      expect(badge).toHaveClass("cc-source-synthetic");
    });

    it("renders 'Gmail' for real Gmail cases", () => {
      const req = mockRequest({ channel: "GMAIL", source_origin: "GMAIL" });
      const origin = getCaseOrigin(req);
      expect(origin.label).toBe("Gmail");
      expect(origin.type).toBe("gmail");

      render(<OriginBadge request={req} />);
      const badge = screen.getByTestId("origin-badge");
      expect(badge).toHaveTextContent("Gmail");
      expect(badge).toHaveClass("cc-source-gmail");
    });

    it("renders 'Telegram' for real Telegram cases", () => {
      const req = mockRequest({ channel: "TELEGRAM", source_origin: "TELEGRAM" });
      const origin = getCaseOrigin(req);
      expect(origin.label).toBe("Telegram");
      expect(origin.type).toBe("telegram");

      render(<OriginBadge request={req} />);
      const badge = screen.getByTestId("origin-badge");
      expect(badge).toHaveTextContent("Telegram");
      expect(badge).toHaveClass("cc-source-telegram");
    });

    it("renders 'WhatsApp' for real WhatsApp cases", () => {
      const req = mockRequest({ channel: "WHATSAPP", source_origin: "WHATSAPP" });
      const origin = getCaseOrigin(req);
      expect(origin.label).toBe("WhatsApp");
      expect(origin.type).toBe("whatsapp");

      render(<OriginBadge request={req} />);
      const badge = screen.getByTestId("origin-badge");
      expect(badge).toHaveTextContent("WhatsApp");
      expect(badge).toHaveClass("cc-source-whatsapp");
    });
  });

  describe("Separation of Case Origin and Delivery Mode", () => {
    it("handles a real Gmail case using simulated sending", () => {
      const req = mockRequest({
        channel: "GMAIL",
        source_origin: "GMAIL",
        delivery_mode: "SIMULATED",
      });

      expect(getCaseOrigin(req).label).toBe("Gmail");
      expect(getDeliveryMode(req).label).toBe("Simulated");
      expect(getDeliveryMode(req).isSimulated).toBe(true);

      render(
        <div>
          <OriginBadge request={req} />
          <DeliveryModeBadge request={requestWith(req)} />
        </div>
      );
      function requestWith(r: CommunicationRequestView) { return r; }

      expect(screen.getByTestId("origin-badge")).toHaveTextContent("Gmail");
      expect(screen.getByTestId("delivery-badge")).toHaveTextContent("Simulated");
      expect(screen.getByTestId("delivery-badge")).toHaveClass("cc-delivery-simulated");
    });

    it("handles a real Gmail case using real delivery", () => {
      const req = mockRequest({
        channel: "GMAIL",
        source_origin: "GMAIL",
        delivery_mode: "REAL",
      });

      expect(getCaseOrigin(req).label).toBe("Gmail");
      expect(getDeliveryMode(req).label).toBe("Real");
      expect(getDeliveryMode(req).isSimulated).toBe(false);

      render(
        <div>
          <OriginBadge request={req} />
          <DeliveryModeBadge request={req} />
        </div>
      );

      expect(screen.getByTestId("origin-badge")).toHaveTextContent("Gmail");
      expect(screen.getByTestId("delivery-badge")).toHaveTextContent("Real");
      expect(screen.getByTestId("delivery-badge")).toHaveClass("cc-delivery-real");
    });
  });
});
