import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "../../App";

function response(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

describe("database-backed supplier availability", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.history.replaceState({}, "", "/");
  });

  it("keeps navigation available without displaying hardcoded supplier records", async () => {
    const fetchMock = vi.fn((url: string | URL | Request, _init?: RequestInit) => response(String(url).includes("/v1/overview") ? { integration_mode: "SYNTHETIC", last_updated_at: "2026-10-24T00:00:00Z", counts: {}, attention_queue: [], commitments: [] } : {}));
    vi.stubGlobal("fetch", fetchMock);
    window.history.replaceState({}, "", "/suppliers");
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Supplier directory" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Supplier data unavailable");
    expect(screen.queryByText("Example Packaging Co.")).not.toBeInTheDocument();
    expect(screen.queryByText("Sample General Supply")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: "Offer comparison" }));
    expect(await screen.findByRole("heading", { name: "Offer comparison" })).toBeInTheDocument();
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
    expect(screen.getAllByRole("button", { name: /Select supplier/ })).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: /Select supplier/ }).every((button) => (button as HTMLButtonElement).disabled)).toBe(true);
    expect(fetchMock.mock.calls.every(([, init]) => !init?.method || init.method === "GET")).toBe(true);
  });

  it("does not pretend a directly linked supplier is a connected record", async () => {
    vi.stubGlobal("fetch", vi.fn(() => response({ integration_mode: "SYNTHETIC", counts: {}, attention_queue: [], commitments: [] })));
    window.history.replaceState({}, "", "/suppliers/example-packaging");
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Supplier details unavailable" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("no database-backed supplier directory");
    expect(screen.queryByText("Example Packaging Co.")).not.toBeInTheDocument();
  });

  it("keeps sourcing unavailable from the navigation", async () => {
    vi.stubGlobal("fetch", vi.fn(() => response({ integration_mode: "SYNTHETIC", counts: {}, attention_queue: [], commitments: [] })));
    window.history.replaceState({}, "", "/suppliers");
    render(<App />);
    expect(await screen.findByRole("navigation", { name: "Primary navigation" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Sourcing" })).not.toBeInTheDocument();
  });
});
