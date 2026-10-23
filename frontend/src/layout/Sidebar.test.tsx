import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { AuthProvider } from "../shared/auth";
import { Sidebar } from "./Sidebar";

function mount(path = "/overview") {
  return render(<MemoryRouter initialEntries={[path]}><AuthProvider initialTenantId="tenant_sidebar_test"><Sidebar /></AuthProvider></MemoryRouter>);
}

describe("shared sidebar navigation", () => {
  beforeEach(() => window.localStorage.clear());
  afterEach(() => { cleanup(); window.localStorage.clear(); });

  it("expands the active parent and keeps unavailable destinations disabled", () => {
    mount("/activity");
    expect(screen.getByRole("button", { name: "Insights" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: "Activity" })).toHaveClass("is-active");
    expect(screen.getByRole("button", { name: "Insights" })).toHaveClass("is-active");
    expect(screen.queryByRole("link", { name: "Forecasts" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Planning" }));
    expect(screen.getByText("Forecasts").closest(".sidebar-item")).toHaveAttribute("aria-disabled", "true");
  });

  it("filters actual menu entries without creating routes for unavailable pages", () => {
    mount();
    fireEvent.change(screen.getByRole("searchbox", { name: "Search menu" }), { target: { value: "offer" } });
    expect(screen.getByRole("button", { name: "Suppliers" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Offer Comparison").closest(".sidebar-item")).toHaveAttribute("aria-disabled", "true");
    expect(screen.queryByRole("link", { name: "Overview" })).not.toBeInTheDocument();
  });

  it("persists collapse preference and keeps the active route", () => {
    const view = mount("/communications");
    fireEvent.click(screen.getByRole("button", { name: "Collapse sidebar" }));
    expect(screen.getByRole("navigation", { name: "Primary navigation" })).toHaveClass("is-collapsed");
    expect(screen.getByRole("link", { name: "Communications" })).toHaveClass("is-active");
    expect(window.localStorage.getItem("moumantai.sidebar.collapsed")).toBe("true");
    view.unmount();
    mount("/communications");
    expect(screen.getByRole("button", { name: "Expand sidebar" })).toBeInTheDocument();
  });

  it("shows only the current tenant and dismisses the organization menu", () => {
    mount();
    const trigger = screen.getByRole("button", { name: "Current organization: tenant_sidebar_test" });
    fireEvent.click(trigger);
    const list = screen.getByRole("listbox", { name: "Available organizations" });
    expect(within(list).getAllByRole("option")).toHaveLength(1);
    expect(within(list).getByRole("option")).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(list, { key: "Escape" });
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    fireEvent.click(trigger);
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("option", { name: /tenant_sidebar_test/ }));
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(screen.getByTestId("shell-tenant-badge")).toHaveTextContent("tenant_sidebar_test");
  });

  it("keeps development role switching in the account area", () => {
    mount();
    const select = screen.getByRole("combobox", { name: "Demo role selector" });
    fireEvent.change(select, { target: { value: "user_manager_01" } });
    expect(screen.getByTestId("shell-tenant-badge")).toHaveTextContent("tenant_sidebar_test · MANAGER");
  });
});
