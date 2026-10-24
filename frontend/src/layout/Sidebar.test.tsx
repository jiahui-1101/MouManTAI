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

  it("expands the active parent and keeps all destinations accessible as active links", () => {
    mount("/activity");
    expect(screen.getByRole("button", { name: "Insights" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: "Activity" })).toHaveClass("is-active");
    expect(screen.getByRole("button", { name: "Insights" })).toHaveClass("is-active");
    expect(screen.queryByRole("link", { name: "Forecasts" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Planning" }));
    expect(screen.getByRole("link", { name: "Forecasts" })).toHaveAttribute("href", "/planning/forecasts");
  });

  it("filters menu entries and opens matching submenus with clickable links", () => {
    mount();
    fireEvent.change(screen.getByRole("searchbox", { name: "Search menu" }), { target: { value: "offer" } });
    expect(screen.getByRole("button", { name: "Suppliers" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: "Offer Comparison" })).toHaveAttribute("href", "/suppliers/compare");
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

  it("toggles downward navigation menus on click", () => {
    mount("/overview");
    const ordersBtn = screen.getByRole("button", { name: "Orders" });
    const ordersSubmenu = document.getElementById("sidebar-group-orders");

    // Initially closed
    expect(ordersBtn).toHaveAttribute("aria-expanded", "false");
    expect(ordersSubmenu).toHaveAttribute("hidden");

    // Click to open
    fireEvent.click(ordersBtn);
    expect(ordersBtn).toHaveAttribute("aria-expanded", "true");
    expect(ordersSubmenu).not.toHaveAttribute("hidden");

    // Click to close
    fireEvent.click(ordersBtn);
    expect(ordersBtn).toHaveAttribute("aria-expanded", "false");
    expect(ordersSubmenu).toHaveAttribute("hidden");
  });

  it("renders clean user identity bar and switches role by clicking anywhere on the bar", () => {
    mount("/overview");

    // Clean user identity bar (Image 2 style)
    const accountBtn = screen.getByRole("button", { name: /Current user: SDC_Demo/i });
    expect(accountBtn).toBeInTheDocument();
    expect(accountBtn).toHaveAttribute("aria-expanded", "false");
    expect(within(accountBtn).getByText("SDC_Demo")).toBeInTheDocument();
    expect(within(accountBtn).getByText("momentnetid@gmail.com")).toBeInTheDocument();
    expect(accountBtn.querySelector("img")).toHaveAttribute("src", "/images/avatar.png");
    expect(accountBtn.querySelector(".sidebar-status-dot")).toBeInTheDocument();
    expect(accountBtn.querySelector(".sidebar-user-chevrons")).toBeInTheDocument();

    // Clicking anywhere on the bar opens role selection popover
    fireEvent.click(accountBtn);
    expect(accountBtn).toHaveAttribute("aria-expanded", "true");

    const roleDropdown = screen.getByRole("listbox", { name: "Select development user role" });
    expect(roleDropdown).toBeInTheDocument();
    // Header displays clean single line without tenant badge clutter
    expect(within(roleDropdown).getByText("Switch role")).toBeInTheDocument();
    expect(within(roleDropdown).queryByText(/tenant_sidebar_test · OWNER/)).not.toBeInTheDocument();

    const options = within(roleDropdown).getAllByRole("option");
    expect(options).toHaveLength(3);
    expect(options[0]).toHaveAttribute("aria-selected", "true"); // Owner is selected

    // Select Manager
    fireEvent.click(screen.getByRole("option", { name: /SDC_Manager/i }));
    expect(screen.queryByRole("listbox", { name: "Select development user role" })).not.toBeInTheDocument();

    // Bar updates cleanly to Manager
    expect(screen.getByText("SDC_Manager")).toBeInTheDocument();
    expect(screen.getByText("manager@sdc.demo")).toBeInTheDocument();
    expect(screen.getByTestId("shell-tenant-badge")).toHaveTextContent("tenant_sidebar_test · MANAGER");

    // Open and close with Escape
    const updatedAccountBtn = screen.getByRole("button", { name: /Current user: SDC_Manager/i });
    fireEvent.click(updatedAccountBtn);
    expect(screen.getByRole("listbox", { name: "Select development user role" })).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("listbox", { name: "Select development user role" }), { key: "Escape" });
    expect(screen.queryByRole("listbox", { name: "Select development user role" })).not.toBeInTheDocument();
  });

  it("only highlights the active navigation item and parent instead of fixing dashboard permanently", () => {
    mount("/inbox");
    // Dashboard should NOT be active when on /inbox
    expect(screen.getByRole("button", { name: "Dashboard" })).not.toHaveClass("is-active");
    expect(screen.getByRole("button", { name: "Inbox" })).toHaveClass("is-active");
    expect(screen.getByRole("link", { name: "Customer Messages" })).toHaveClass("is-active");
  });
});
