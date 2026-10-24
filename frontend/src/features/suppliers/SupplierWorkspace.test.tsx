import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "../../App";

function response(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

describe("synthetic supplier workspace", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.history.replaceState({}, "", "/");
  });

  it("searches directory samples and opens a directly linked detail with unknown availability", async () => {
    const fetchMock = vi.fn((url: string | URL | Request, _init?: RequestInit) => response(String(url).includes("/v1/overview") ? { integration_mode: "SYNTHETIC", last_updated_at: "2026-10-24T00:00:00Z", counts: {}, attention_queue: [], commitments: [] } : {}));
    vi.stubGlobal("fetch", fetchMock);
    window.history.replaceState({}, "", "/suppliers");
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Supplier directory" })).toBeInTheDocument();
    expect(screen.getByText(/Illustrative data only/)).toBeInTheDocument();
    fireEvent.change(screen.getByRole("searchbox", { name: "Search sample suppliers" }), { target: { value: "Packaging" } });
    expect(screen.getByRole("link", { name: "Example Packaging Co." })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Sample General Supply" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: "Example Packaging Co." }));
    expect(await screen.findByText("DEMO-SPEC-v1")).toBeInTheDocument();
    expect(screen.getByText(/Availability/)).toBeInTheDocument();
    expect(fetchMock.mock.calls.every(([, init]) => !init?.method || init.method === "GET")).toBe(true);
  });

  it("shows comparison unknowns and disables selection without sending writes", async () => {
    const fetchMock = vi.fn((url: string | URL | Request, _init?: RequestInit) => response(String(url).includes("/v1/overview") ? { integration_mode: "SYNTHETIC", last_updated_at: "2026-10-24T00:00:00Z", counts: {}, attention_queue: [], commitments: [] } : {}));
    vi.stubGlobal("fetch", fetchMock);
    window.history.replaceState({}, "", "/suppliers/compare");
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Offer comparison" })).toBeInTheDocument();
    expect(screen.getByText(/UNKNOWN — not assessed/)).toBeInTheDocument();
    expect(screen.getByText(/no approved versioned offer-selection command/i)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /Select supplier/ })).toHaveLength(2);
    expect(screen.getAllByRole("button", { name: /Select supplier/ }).every((button) => (button as HTMLButtonElement).disabled)).toBe(true);
    expect(fetchMock.mock.calls.every(([, init]) => !init?.method || init.method === "GET")).toBe(true);
  });

  it("keeps sourcing unavailable from the navigation", async () => {
    vi.stubGlobal("fetch", vi.fn(() => response({ integration_mode: "SYNTHETIC", counts: {}, attention_queue: [], commitments: [] })));
    window.history.replaceState({}, "", "/suppliers");
    render(<App />);
    expect(await screen.findByRole("navigation", { name: "Primary navigation" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Sourcing" })).not.toBeInTheDocument();
  });
});
