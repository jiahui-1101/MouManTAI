import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

describe("shared shell", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the MouManTAI overview and reads backend health", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ status: "ok", service: "moumantai-api", version: "0.1.0" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    render(<App />);

    expect(screen.getByRole("heading", { name: "MouManTAI" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Commitment overview" })).toBeInTheDocument();
    expect(await screen.findByText("Connected")).toBeInTheDocument();
  });
});
