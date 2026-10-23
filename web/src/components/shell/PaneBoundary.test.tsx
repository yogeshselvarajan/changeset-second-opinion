import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PaneBoundary } from "./PaneBoundary";

let shouldThrow = true;

function Flaky() {
  if (shouldThrow) throw new Error("boom with <private> text");
  return <p>recovered</p>;
}

afterEach(() => vi.restoreAllMocks());

describe("PaneBoundary", () => {
  it("lets the other pane carry on when one throws", () => {
    shouldThrow = true;
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <>
        <PaneBoundary name="evidence">
          <Flaky />
        </PaneBoundary>
        <PaneBoundary name="verdict">
          <p>verdict is fine</p>
        </PaneBoundary>
      </>,
    );
    expect(screen.getByTestId("pane-failed-evidence")).toHaveTextContent(
      "This part of the page could not be shown",
    );
    expect(screen.getByText("verdict is fine")).toBeInTheDocument();
    expect(screen.queryByTestId("pane-failed-verdict")).toBeNull();
  });

  it("tries again when the button is pressed", () => {
    shouldThrow = true;
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <PaneBoundary name="evidence">
        <Flaky />
      </PaneBoundary>,
    );
    shouldThrow = false;
    fireEvent.click(screen.getByRole("button", { name: "Reload this pane" }));
    expect(screen.getByText("recovered")).toBeInTheDocument();
  });

  it("logs the message and leaves the component stack out", () => {
    shouldThrow = true;
    const log = vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <PaneBoundary name="verdict">
        <Flaky />
      </PaneBoundary>,
    );
    const ours = log.mock.calls.find((call) => String(call[0]).startsWith("pane error (verdict)"));
    expect(ours).toBeDefined();
    expect(ours?.join(" ")).toContain("(stack omitted)");
  });
});
