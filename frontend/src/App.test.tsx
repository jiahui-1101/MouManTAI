import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

const mockOverview = {
  tenant_id: "tenant_demo_01",
  actor_id: "user_owner_01",
  actor_role: "OWNER",
  integration_mode: "SYNTHETIC",
  last_updated_at: "2026-10-21T02:00:00Z",
  counts: {
    requested: 1,
    confirmed: 2,
    at_risk: 0,
    pending_approval: 0,
    execution_in_progress: 0,
    awaiting_confirmation: 0,
    fulfilled: 1,
  },
  attention_queue: [],
  commitments: [],
};

describe("shared shell", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the MouManTAI shell and loads overview data", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string | URL | Request) => {
        const urlStr = typeof url === "string" ? url : url.toString();
        if (urlStr.includes("/v1/overview")) {
          return Promise.resolve(
            new Response(JSON.stringify(mockOverview), {
              status: 200,
              headers: { "Content-Type": "application/json" },
            }),
          );
        }
        return Promise.resolve(
          new Response(JSON.stringify({ status: "ok", service: "moumantai-api", version: "0.1.0" }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }),
    );

    render(<App />);

    expect(screen.getByRole("heading", { name: "MouManTAI" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: /commitment overview/i })).toBeInTheDocument();
    expect(await screen.findByTestId("synthetic-badge")).toHaveTextContent("SYNTHETIC");
    expect(screen.getByTestId("active-tenant")).toHaveTextContent("tenant_demo_01");
  });

  it("supports additive route registration inside the existing shell", async () => {
    window.history.pushState({}, "", "/future-order-workspace");
    const { unmount } = render(
      <App routeExtensions={[
        { path: "/future-order-workspace", element: <h2>Future order workspace</h2> },
      ]} />,
    );
    expect(await screen.findByRole("heading", { name: "Future order workspace" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Primary navigation" })).toBeInTheDocument();
    unmount();
    window.history.pushState({}, "", "/");
  });
});
