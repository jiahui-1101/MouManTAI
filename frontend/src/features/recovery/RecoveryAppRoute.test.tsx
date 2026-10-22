import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "../../App";

function response(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  }));
}

describe("P3 recovery App route", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.history.replaceState({}, "", "/");
  });

  it("mounts the read-only case page at /recovery/:id without action controls", async () => {
    const fetchMock = vi.fn((_url: string | URL | Request, _init?: RequestInit) =>
      response({ code: "NOT_FOUND", message: "Recovery case was not found" }, 404),
    );
    vi.stubGlobal("fetch", fetchMock);
    window.history.replaceState({}, "", "/recovery/com_100");

    render(<App initialTenantId="tenant_route_test" initialActorId="user_manager_01" />);

    expect(await screen.findByRole("heading", { name: "Recovery case not found" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "MouManTAI" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/v1/recovery/cases/com_100"),
      expect.objectContaining({
        headers: expect.objectContaining({ "X-Tenant-ID": "tenant_route_test", "X-Actor-ID": "user_manager_01" }),
      }),
    );
    expect(fetchMock.mock.calls.every(([, init]) => !init?.method || init.method === "GET")).toBe(true);
    expect(screen.queryByRole("button", { name: /approve|execute/i })).not.toBeInTheDocument();
  });

  it("keeps the recovery planning workspace on an explicit /plans route", async () => {
    const fetchMock = vi.fn((_url: string | URL | Request, _init?: RequestInit) =>
      response({ code: "NOT_FOUND", message: "Recovery case was not found" }, 404),
    );
    vi.stubGlobal("fetch", fetchMock);
    window.history.replaceState({}, "", "/recovery/com_200/plans");

    render(<App initialTenantId="tenant_route_test" initialActorId="user_manager_01" />);

    expect(await screen.findByText(/No plan was approved or executed by this screen/)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/v1/recovery/cases/com_200"),
      expect.objectContaining({ headers: expect.any(Object) }),
    );
    expect(fetchMock.mock.calls.every(([, init]) => !init?.method || init.method === "GET")).toBe(true);
  });});
