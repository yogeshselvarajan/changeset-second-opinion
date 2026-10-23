import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ResizablePanes } from "./ResizablePanes";

/** The test environment's own localStorage is not a full one, so use a small stand-in. */
function stubStorage(): Map<string, string> {
  const store = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => void store.set(key, value),
    removeItem: (key: string) => void store.delete(key),
    clear: () => store.clear(),
  });
  return store;
}

function setup() {
  render(<ResizablePanes start={<p>evidence</p>} end={<p>verdict</p>} />);
  return screen.getByRole("separator");
}

describe("ResizablePanes", () => {
  beforeEach(() => {
    stubStorage();
  });

  it("starts at 60 / 40 and shows both panes", () => {
    const divider = setup();
    expect(divider).toHaveAttribute("aria-valuenow", "60");
    expect(screen.getByText("evidence")).toBeInTheDocument();
    expect(screen.getByText("verdict")).toBeInTheDocument();
  });

  it("moves with the arrow keys, stops at the limits and remembers the split", () => {
    const divider = setup();
    fireEvent.keyDown(divider, { key: "ArrowRight" });
    expect(divider).toHaveAttribute("aria-valuenow", "62");
    fireEvent.keyDown(divider, { key: "ArrowLeft" });
    fireEvent.keyDown(divider, { key: "ArrowLeft" });
    expect(divider).toHaveAttribute("aria-valuenow", "58");
    fireEvent.keyDown(divider, { key: "End" });
    expect(divider).toHaveAttribute("aria-valuenow", "75");
    fireEvent.keyDown(divider, { key: "ArrowRight" });
    expect(divider).toHaveAttribute("aria-valuenow", "75");
    fireEvent.keyDown(divider, { key: "Home" });
    expect(divider).toHaveAttribute("aria-valuenow", "30");
    expect(localStorage.getItem("cso.panes")).toBe("30");
  });

  it("restores the remembered split", () => {
    localStorage.setItem("cso.panes", "45");
    expect(setup()).toHaveAttribute("aria-valuenow", "45");
  });

  it("ignores a stored value that is not a number", () => {
    localStorage.setItem("cso.panes", "wide");
    expect(setup()).toHaveAttribute("aria-valuenow", "60");
  });
});
