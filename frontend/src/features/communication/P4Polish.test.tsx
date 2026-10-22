import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../../App";
import { ApiError } from "../../shared/api";
import { ErrorNotice, DisplayBadge } from "./presentation";
import { ConfirmationBadge, ConfirmationError } from "./confirmationPresentation";
import { P4Loading } from "./P4Feedback";
import { ManagerReview } from "./ManagerReview";
import { OutboundPanel } from "./OutboundPanel";
import { DraftPreview } from "./DraftPreview";
import { createPolishFixtures, createPolishTransport, QA_AUTH, QA_CONFIRMATION_ID, QA_DRAFT_ID, QA_LONG_EVIDENCE, QA_LONG_ID } from "./__tests__/polishFixtures";
import type { ConfirmationView } from "./confirmationTypes";

const clients: QueryClient[] = [];
const fetchMock = vi.fn<typeof fetch>();
beforeEach(() => { fetchMock.mockReset(); fetchMock.mockImplementation(createPolishTransport()); vi.stubGlobal("fetch", fetchMock); });
afterEach(() => { cleanup(); clients.splice(0).forEach(client => client.clear()); vi.unstubAllGlobals(); window.history.replaceState({}, "", "/"); });
function client() {
  const value = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0, refetchOnWindowFocus: false }, mutations: { retry: false } } });
  clients.push(value); return value;
}
function app(path: string) {
  window.history.replaceState({}, "", path);
  render(<App queryClient={client()} initialTenantId={QA_AUTH.tenantId} initialActorId={QA_AUTH.actorId} />);
}
const mutations = () => fetchMock.mock.calls.filter(([, init]) => init?.method && init.method !== "GET");

describe("P4 polish and demo regression", () => {
  it("keeps the complete read-only Center -> Confirmation -> Queue -> Details journey on the actual App", async () => {
    app("/communications"); fireEvent.click(await screen.findByRole("button", { name: /com_demo_order_42/ }));
    const linked = await screen.findByRole("region", { name: "Linked confirmations" });
    fireEvent.click(await within(linked).findByRole("link", { name: `Open confirmation ${QA_CONFIRMATION_ID}` }));
    await screen.findByRole("region", { name: "Proposal and version details" });
    expect(screen.getByText("Version 3")).toBeInTheDocument();
    expect(await screen.findByText(QA_LONG_EVIDENCE)).toBeInTheDocument();
    const queueLink = screen.getByRole("link", { name: "Follow-Up Queue" }); queueLink.focus(); expect(queueLink).toHaveFocus();
    fireEvent.click(queueLink); const queue = await screen.findByRole("list", { name: "Confirmation follow-ups" });
    const record = within(queue).getByRole("article", { name: `Confirmation ${QA_CONFIRMATION_ID}` });
    fireEvent.click(within(record).getByRole("link", { name: "View Confirmation" }));
    expect(await screen.findByRole("region", { name: "Confirmation overview" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Primary navigation" })).toBeInTheDocument();
    expect(mutations()).toHaveLength(0);
    expect(screen.queryByRole("button", { name: /^Accept$|^Reject$|Send reminder|Escalate/i })).not.toBeInTheDocument();
  });
  it("preserves long exact IDs, terms version and focusable scrollable draft content", () => {
    const data = createPolishFixtures(); render(<DraftPreview draft={data.draft} onReload={() => {}} />);
    const preview = screen.getByRole("article", { name: "Message draft preview" });
    expect(preview).toHaveTextContent(data.draft.reference.proposal_id); expect(preview).toHaveTextContent("v3");
    expect(preview).toHaveTextContent(QA_LONG_EVIDENCE); expect(preview).toHaveTextContent(QA_DRAFT_ID);
    const body = screen.getByLabelText("Draft message body"); body.focus(); expect(body).toHaveFocus();
    expect(body).toHaveAttribute("tabindex", "0"); expect(body.textContent).toBe(data.draft.body);
  });
  it("moves approval focus into the existing fieldset and restores it on Escape/cancel without submitting", async () => {
    const data = createPolishFixtures(); render(<QueryClientProvider client={client()}><ManagerReview draft={data.draft} auth={QA_AUTH} now={Date.now()} /></QueryClientProvider>);
    const trigger = await screen.findByRole("button", { name: "Approve Draft" }); trigger.focus(); fireEvent.click(trigger);
    const confirm = screen.getByRole("button", { name: "Confirm Approve Draft" }); expect(confirm).toHaveFocus();
    fireEvent.keyDown(confirm, { key: "Escape" }); expect(screen.getByRole("button", { name: "Approve Draft" })).toHaveFocus();
    fireEvent.click(screen.getByRole("button", { name: "Approve Draft" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel approval" }));
    expect(screen.getByRole("button", { name: "Approve Draft" })).toHaveFocus(); expect(mutations()).toHaveLength(0);
  });
  it("moves mock-send focus without changing eligibility or sending from a keyboard cancel", async () => {
    fetchMock.mockImplementation(createPolishTransport("send")); const data = createPolishFixtures();
    render(<QueryClientProvider client={client()}><OutboundPanel communicationId={QA_LONG_ID} draft={data.draft} auth={QA_AUTH} now={Date.now()} /></QueryClientProvider>);
    const trigger = screen.getByRole("button", { name: "Send Message" }); await waitFor(() => expect(trigger).toBeEnabled());
    trigger.focus(); fireEvent.click(trigger); const confirm = screen.getByRole("button", { name: "Confirm Send Message" }); expect(confirm).toHaveFocus();
    fireEvent.keyDown(confirm, { key: "Escape" }); expect(trigger).toHaveFocus(); expect(screen.queryByRole("group", { name: "Confirm mock send" })).not.toBeInTheDocument();
    expect(mutations()).toHaveLength(0);
  });
  it("keeps backend-denied sending disabled and explains the reason", async () => {
    const data = createPolishFixtures(); render(<QueryClientProvider client={client()}><OutboundPanel communicationId={QA_LONG_ID} draft={data.draft} auth={QA_AUTH} now={Date.now()} /></QueryClientProvider>);
    expect(await screen.findByText(/SEND_AUTHORITY_UNAVAILABLE/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send Message" })).toBeDisabled(); expect(mutations()).toHaveLength(0);
  });
  it("groups queue rules under an accessible disclosure without changing classification or hiding scope", async () => {
    app("/communications/follow-ups"); await screen.findByRole("list", { name: "Confirmation follow-ups" });
    const summary = screen.getByText("How attention labels work"); expect(summary.tagName).toBe("SUMMARY");
    expect(summary.closest("details")).not.toHaveAttribute("open");
    expect(screen.getByText(/P4 Evidence Only/)).toBeInTheDocument();
    expect(screen.getByText(/Attention labels are browser display hints/)).toBeInTheDocument();
    expect(screen.getByLabelText("Follow-up filters")).toBeInTheDocument();
  });
  it.each(["AWAITING_RESPONSE", "UNRESOLVED", "CLARIFICATION_REQUIRED", "EXPIRED", "SUPERSEDED", "ACCEPTED"] as const)("styles %s without implying Core confirmation or green success", state => {
    render(<ConfirmationBadge value={{ ...createPolishFixtures().confirmation, state }} />);
    const badge = document.querySelector(".cw-badge"); expect(badge).not.toHaveClass("badge-success");
    expect(badge).toHaveClass(`p4-confirmation-${state === "EXPIRED" ? "danger" : state === "ACCEPTED" ? "evidence" : state === "AWAITING_RESPONSE" ? "neutral" : "warning"}`);
    expect(badge?.textContent?.trim()).not.toBe("");
  });
  it.each(["Sent", "Sending", "Pending"])("does not give delivery %s a green success badge", label => {
    render(<DisplayBadge label={label} />); expect(document.querySelector(".status-badge")).not.toHaveClass("badge-success");
  });
  it.each([
    [400, "BAD_REQUEST"], [403, "FORBIDDEN"], [404, "NOT_FOUND"], [409, "STALE_PROPOSAL_VERSION"],
    [409, "PROPOSAL_ID_MISMATCH"], [503, "CONFIRMATION_PROCESSOR_AUTH_UNAVAILABLE"], [502, "UNEXPECTED_BACKEND_FAILURE"],
  ])("retains %s %s and correlation without leaking diagnostics", (status, code) => {
    const retry = vi.fn(); render(<ConfirmationError error={new ApiError(Number(status), String(code), "PRIVATE SERVER TOKEN", "corr-" + "x".repeat(150))} retry={retry} />);
    const alert = screen.getByRole("alert"); expect(alert).toHaveTextContent(String(code)); expect(alert).not.toHaveTextContent("PRIVATE SERVER TOKEN");
    const button = within(alert).getByRole("button", { name: "Retry" }); button.focus(); expect(button).toHaveFocus(); fireEvent.click(button); expect(retry).toHaveBeenCalledOnce();
    expect(mutations()).toHaveLength(0);
  });
  it("exposes Communication API codes consistently and safe network messages", () => {
    const view = render(<ErrorNotice error={new ApiError(409, "PROPOSAL_ID_MISMATCH", "PRIVATE TOKEN")} resource="detail" onRetry={() => {}} />);
    expect(screen.getByRole("alert")).toHaveTextContent("PROPOSAL_ID_MISMATCH"); expect(screen.getByRole("alert")).toHaveTextContent("exact proposal ID and version");
    view.rerender(<ErrorNotice error={new TypeError("PRIVATE NETWORK DIAGNOSTIC")} resource="detail" onRetry={() => {}} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Cannot reach the server"); expect(screen.getByRole("alert")).not.toHaveTextContent("PRIVATE NETWORK");
  });
  it("announces a stable loading region without fake records or an enabled operation", () => {
    render(<P4Loading>Loading confirmation details…</P4Loading>);
    const status = screen.getByRole("status"); expect(status).toHaveAttribute("aria-live", "polite"); expect(status).toHaveClass("p4-loading");
    expect(screen.queryByRole("button")).not.toBeInTheDocument(); expect(screen.queryByText("Acceptance recorded")).not.toBeInTheDocument();
  });
  it("keeps revoked and unverified facts out of successful lifecycle claims", () => {
    const record: ConfirmationView = { ...createPolishFixtures().confirmation, revoked_at: new Date().toISOString(), blocked_reasons: ["CONFIRMATION_REVOKED"] };
    render(<ConfirmationBadge value={record} />); expect(screen.getByText("Revoked")).toHaveClass("p4-confirmation-danger");
    expect(screen.queryByText("FULFILLED")).not.toBeInTheDocument();
  });
});
