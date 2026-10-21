import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Breadcrumbs } from "../../layout/AppShell";
import { ErrorBoundary } from "../ErrorBoundary";
import { ToastProvider, useToast } from "../Toast";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Shell Building Blocks (FE-01b, FE-01c)", () => {
  // 1. Breadcrumbs
  describe("Breadcrumbs navigation", () => {
    it("renders Overview crumb when on / or /overview", () => {
      render(
        <MemoryRouter initialEntries={["/overview"]}>
          <Breadcrumbs />
        </MemoryRouter>,
      );
      const nav = screen.getByTestId("shell-breadcrumbs");
      expect(nav).toHaveTextContent("Overview");
    });

    it("renders hierarchy for deep links: Overview > Commitments > com_001", () => {
      render(
        <MemoryRouter initialEntries={["/commitments/com_001"]}>
          <Breadcrumbs />
        </MemoryRouter>,
      );
      const nav = screen.getByTestId("shell-breadcrumbs");
      expect(nav).toHaveTextContent("Overview");
      expect(nav).toHaveTextContent("Commitments");
      expect(nav).toHaveTextContent("com_001");
      const current = screen.getByText("com_001");
      expect(current).toHaveAttribute("aria-current", "page");
    });

    it("renders hierarchy for impact links: Overview > Impact > fa_001", () => {
      render(
        <MemoryRouter initialEntries={["/impact/fa_001"]}>
          <Breadcrumbs />
        </MemoryRouter>,
      );
      const nav = screen.getByTestId("shell-breadcrumbs");
      expect(nav).toHaveTextContent("Overview");
      expect(nav).toHaveTextContent("Impact");
      expect(nav).toHaveTextContent("fa_001");
    });
  });

  // 2. ErrorBoundary
  describe("ErrorBoundary component", () => {
    function BombComponent({ shouldThrow }: { shouldThrow: boolean }) {
      if (shouldThrow) {
        throw new Error("Simulated component explosion in renderer\nAt line 42 stack trace here");
      }
      return <div>Normal Content</div>;
    }

    it("renders children when no error occurs", () => {
      render(
        <ErrorBoundary>
          <div>Child Content</div>
        </ErrorBoundary>,
      );
      expect(screen.getByText("Child Content")).toBeInTheDocument();
    });

    it("catches error, provides retry affordance, and prevents raw stack traces from rendering", () => {
      // Suppress console.error in this test since React logs boundary catches
      const spy = vi.spyOn(console, "error").mockImplementation(() => {});

      const { rerender } = render(
        <ErrorBoundary>
          <BombComponent shouldThrow={true} />
        </ErrorBoundary>,
      );

      // Verify fallback is rendered
      expect(screen.getByTestId("error-boundary-fallback")).toBeInTheDocument();
      expect(screen.getByText("Something went wrong")).toBeInTheDocument();

      // Verify message is sanitized without raw stack trace
      const messageEl = screen.getByTestId("error-boundary-message");
      expect(messageEl).toHaveTextContent("Simulated component explosion in renderer");
      expect(messageEl.textContent).not.toContain("stack trace here");

      // Verify retry affordance
      const retryBtn = screen.getByTestId("error-boundary-retry-button");
      expect(retryBtn).toBeInTheDocument();

      // Reset state on retry
      rerender(
        <ErrorBoundary>
          <BombComponent shouldThrow={false} />
        </ErrorBoundary>,
      );
      fireEvent.click(retryBtn);

      expect(screen.getByText("Normal Content")).toBeInTheDocument();
      spy.mockRestore();
    });
  });

  // 3. Toast Provider & useToast
  describe("Toast system", () => {
    function TestToastConsumer() {
      const toast = useToast();
      return (
        <div>
          <button onClick={() => toast.success("Plan executed successfully")}>Trigger Success</button>
          <button onClick={() => toast.error("Plan execution failed")}>Trigger Error</button>
          <button onClick={() => toast.success("Proposal PENDING approval")}>Trigger Pending Success</button>
          <button onClick={() => toast.success("Awaiting customer confirmation")}>Trigger Awaiting Success</button>
        </div>
      );
    }

    it("renders toast with success and error variants", () => {
      render(
        <ToastProvider>
          <TestToastConsumer />
        </ToastProvider>,
      );

      fireEvent.click(screen.getByText("Trigger Success"));
      const successToast = screen.getByTestId("toast-success");
      expect(successToast).toHaveTextContent("Plan executed successfully");

      fireEvent.click(screen.getByText("Trigger Error"));
      const errorToast = screen.getByTestId("toast-error");
      expect(errorToast).toHaveTextContent("Plan execution failed");
    });

    it("invariant: never shows a success toast for pending or awaiting state (downgrades to info)", () => {
      render(
        <ToastProvider>
          <TestToastConsumer />
        </ToastProvider>,
      );

      fireEvent.click(screen.getByText("Trigger Pending Success"));
      // Should NOT render as toast-success
      expect(screen.queryByTestId("toast-success")).not.toBeInTheDocument();
      // Should be downgraded to info
      const infoToast1 = screen.getByTestId("toast-info");
      expect(infoToast1).toHaveTextContent("Proposal PENDING approval");

      fireEvent.click(screen.getByText("Trigger Awaiting Success"));
      const infoToasts = screen.getAllByTestId("toast-info");
      expect(infoToasts.length).toBe(2);
      expect(infoToasts[1]).toHaveTextContent("Awaiting customer confirmation");
    });
  });
});
