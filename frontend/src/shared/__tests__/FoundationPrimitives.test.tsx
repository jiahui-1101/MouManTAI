import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api";
import { ConfirmationDialog } from "../ConfirmationDialog";
import { EmptyState } from "../EmptyState";
import { ErrorState } from "../ErrorState";
import { EvidenceTierBadge } from "../EvidenceTierBadge";
import { LastUpdated } from "../LastUpdated";
import { MutationStateView } from "../mutationState";
import { StateTimeline } from "../StateTimeline";
import { UncertaintyNote } from "../UncertaintyNote";
import { VersionConflictBanner } from "../VersionConflictBanner";

afterEach(cleanup);

describe("shared frontend foundation", () => {
  it("keeps evidence maturity and integration mode separate", () => {
    const { rerender } = render(<EvidenceTierBadge evidenceTier="DEMO-ONLY" integrationMode="SYNTHETIC" />);
    const badge = screen.getByLabelText("Evidence: DEMO-ONLY; Integration mode: SYNTHETIC");
    expect(badge).toHaveTextContent("DEMO-ONLY");
    expect(badge).toHaveTextContent("SYNTHETIC");
    expect(badge).not.toHaveTextContent("LIVE CONNECTION");
    rerender(<EvidenceTierBadge integrationMode="MOCK_ORBYTE" />);
    expect(screen.getByText("MOCK_ORBYTE")).toBeInTheDocument();
    rerender(<EvidenceTierBadge integrationMode="LIVE" />);
    expect(screen.getByLabelText("Integration mode: LIVE")).toHaveTextContent("LIVE");
  });

  it("shows missing and offset-aware update times without inventing one", () => {
    const { rerender } = render(<LastUpdated value={null} />);
    expect(screen.getByText("Last updated: unknown")).toBeInTheDocument();
    rerender(<LastUpdated value="2026-10-23T10:15:00+08:00" />);
    const time = screen.getByText(/23 Oct 2026/).closest("time");
    expect(time).toHaveAttribute("datetime", "2026-10-23T10:15:00+08:00");
    rerender(<LastUpdated value="2026-10-23T10:15:00" />);
    expect(screen.getByText("Last updated: unknown")).toBeInTheDocument();
  });

  it("distinguishes a stale version conflict and offers explicit refresh", () => {
    const refresh = vi.fn();
    render(<VersionConflictBanner expectedVersion={2} currentVersion={3} onRefresh={refresh} />);
    expect(screen.getByRole("alert")).toHaveTextContent("may be out of date");
    expect(screen.getByText("Displayed version: 2")).toBeInTheDocument();
    expect(screen.getByText("Latest server version: 3")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Refresh latest version" }));
    expect(refresh).toHaveBeenCalledOnce();
  });

  it("classifies permission failures and only renders safe retry actions", () => {
    const unsafeRetry = vi.fn();
    const { rerender } = render(<ErrorState error={new ApiError(403, "FORBIDDEN", "sensitive backend detail")} onRetry={unsafeRetry} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Access denied");
    expect(screen.queryByText("sensitive backend detail")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
    const safeRetry = vi.fn();
    rerender(<ErrorState error={new TypeError("fetch failed")} onRetry={safeRetry} retrySafe />);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(safeRetry).toHaveBeenCalledOnce();
  });

  it("gives authentication, conflict, validation and domain failures distinct messages", () => {
    const { rerender } = render(<ErrorState error={new ApiError(401, "UNAUTHORIZED", "detail")} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Sign-in required");
    rerender(<ErrorState error={new ApiError(409, "CONFLICT", "detail")} />);
    expect(screen.getByRole("alert")).toHaveTextContent("The record has changed");
    rerender(<ErrorState error={new ApiError(422, "VALIDATION_ERROR", "detail")} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Check the information");
    rerender(<ErrorState error={new ApiError(400, "DOMAIN_REJECTED", "detail")} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Request not accepted");
  });

  it("does not offer retry when a mutation may have reached the server", () => {
    render(<ErrorState error={new TypeError("fetch failed")} operationMayHaveApplied onRetry={vi.fn()} retrySafe />);
    expect(screen.getByRole("alert")).toHaveTextContent("Outcome not confirmed");
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
  });

  it("distinguishes empty, no-result, unavailable and not-measured states", () => {
    const { rerender } = render(<EmptyState kind="empty" title="No records" description="Nothing has been recorded." />);
    expect(screen.getByLabelText("No records")).toBeInTheDocument();
    rerender(<EmptyState kind="no-results" title="No matches" description="Change your filters." />);
    expect(screen.getByLabelText("No matching results")).toBeInTheDocument();
    rerender(<EmptyState kind="unavailable" title="Unavailable" description="The data source is offline." />);
    expect(screen.getByLabelText("Data unavailable")).toBeInTheDocument();
    rerender(<EmptyState kind="not-measured" title="Not measured" description="Coverage is not available." />);
    expect(screen.getByLabelText("Not measured")).toBeInTheDocument();
  });

  it("preserves caller timeline ordering and presents each lifecycle state with evidence", () => {
    render(<StateTimeline stages={[
      { id: "a", label: "Requested", status: "completed", timestamp: "2026-10-23T10:00:00Z", evidenceRefs: ["ev_1"] },
      { id: "b", label: "Review", status: "current", description: "Waiting for an authorized decision." },
      { id: "c", label: "Fulfilment", status: "pending", timestamp: "2026-10-23T10:00:00", },
      { id: "d", label: "Execution", status: "failed" },
    ]} />);
    const timeline = screen.getByRole("list", { name: "State timeline" });
    expect(Array.from(timeline.querySelectorAll(".foundation-timeline-heading strong")).map((node) => node.textContent))
      .toEqual(["Requested", "Review", "Fulfilment", "Execution"]);
    expect(timeline).toHaveTextContent("Completed");
    expect(timeline).toHaveTextContent("Current");
    expect(timeline).toHaveTextContent("Pending");
    expect(timeline).toHaveTextContent("Failed");
    expect(screen.getByText("ev_1")).toBeInTheDocument();
    expect(timeline.querySelectorAll("time")).toHaveLength(1);
  });

  it("labels uncertainty explicitly instead of styling it as success", () => {
    render(<UncertaintyNote kind="unknown">Supplier availability has not been verified.</UncertaintyNote>);
    expect(screen.getByRole("note", { name: "Unknown" })).toHaveTextContent("Supplier availability has not been verified.");
    expect(screen.getByRole("note")).not.toHaveClass("foundation-mutation-success");
  });

  it("requires acknowledgment, traps keyboard focus, and prevents duplicate confirmation", async () => {
    const onConfirm = vi.fn(() => new Promise<void>((resolve) => setTimeout(resolve, 10)));
    const onOpenChange = vi.fn();
    const opener = document.createElement("button");
    document.body.appendChild(opener);
    opener.focus();
    const view = render(
      <ConfirmationDialog
        open
        title="Confirm change"
        description="Review the listed scope before continuing."
        scope={<p>One internal task</p>}
        requiredAcknowledgement="I reviewed this scope"
        onConfirm={onConfirm}
        onOpenChange={onOpenChange}
      />,
    );
    const dialog = screen.getByRole("dialog", { name: "Confirm change" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    const outsideButton = document.createElement("button");
    document.body.appendChild(outsideButton);
    outsideButton.focus();
    expect(dialog.contains(document.activeElement)).toBe(true);
    const confirm = screen.getByRole("button", { name: "Confirm" });
    expect(confirm).toBeDisabled();
    const acknowledgement = screen.getByRole("checkbox", { name: "I reviewed this scope" });
    fireEvent.click(acknowledgement);
    expect(confirm).toBeEnabled();
    acknowledgement.focus();
    fireEvent.keyDown(dialog, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(confirm);
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    expect(onConfirm).toHaveBeenCalledOnce();
    expect(confirm).toBeDisabled();
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    view.rerender(
      <ConfirmationDialog open={false} title="Confirm change" description="Review the listed scope before continuing." onConfirm={onConfirm} onOpenChange={onOpenChange} />,
    );
    expect(opener).toHaveFocus();
    opener.remove();
    outsideButton.remove();
  });

  it("does not dismiss while pending and handles Escape when idle", () => {
    const onOpenChange = vi.fn();
    const { rerender } = render(<ConfirmationDialog open pending title="Pending" description="Working" onConfirm={() => {}} onOpenChange={onOpenChange} />);
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(onOpenChange).not.toHaveBeenCalled();
    rerender(<ConfirmationDialog open title="Ready" description="Ready" onConfirm={() => {}} onOpenChange={onOpenChange} />);
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("does not offer a blind second submission after an unconfirmed result", async () => {
    const onConfirm = vi.fn().mockRejectedValue(new TypeError("fetch failed"));
    const onConfirmError = vi.fn();
    render(<ConfirmationDialog open title="Confirm action" description="Proceed?" onConfirm={onConfirm} onConfirmError={onConfirmError} onOpenChange={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await screen.findByRole("alert");
    expect(screen.getByRole("alert")).toHaveTextContent("Check the current record");
    expect(screen.getByRole("button", { name: "Confirm" })).toBeDisabled();
    expect(onConfirmError).toHaveBeenCalledOnce();
    expect(onConfirm).toHaveBeenCalledOnce();
  });

  it("keeps queued, confirmed and unknown-outcome mutations semantically distinct", () => {
    const { rerender } = render(<MutationStateView state={{ status: "queued" }} />);
    expect(screen.getByRole("status")).toHaveTextContent("Completion is not yet confirmed");
    rerender(<MutationStateView state={{ status: "pending" }} />);
    expect(screen.getByRole("status")).toHaveTextContent("Request in progress");
    rerender(<MutationStateView state={{ status: "success", message: "Approval recorded.", authoritativeState: "APPROVED" }} />);
    expect(screen.getByRole("status")).toHaveTextContent("Server state: APPROVED");
    rerender(<MutationStateView state={{ status: "failure", error: new TypeError("fetch failed"), operationMayHaveApplied: true }} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Outcome not confirmed");
    expect(screen.getByRole("alert")).toHaveTextContent("Check the current record");
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
  });
});
