import { afterEach, describe, expect, it, vi } from "vitest";

import { openPendingTab } from "./pendingTab";

afterEach(() => vi.restoreAllMocks());

function fakeTab() {
  return { closed: false, opener: {}, location: { href: "" }, close: vi.fn() };
}

describe("openPendingTab", () => {
  it("opens the tab immediately, detached, and navigates it later", () => {
    const tab = fakeTab();
    const open = vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
    const pending = openPendingTab();
    expect(open).toHaveBeenCalledOnce();
    expect(tab.opener).toBeNull();
    expect(tab.location.href).toBe("");
    pending.go("https://www.openstreetmap.org/changeset/1");
    expect(tab.location.href).toBe("https://www.openstreetmap.org/changeset/1");
  });

  it("closes an unused tab", () => {
    const tab = fakeTab();
    vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
    openPendingTab().close();
    expect(tab.close).toHaveBeenCalledOnce();
  });

  it("does nothing when the popup was blocked", () => {
    vi.spyOn(window, "open").mockReturnValue(null);
    const pending = openPendingTab();
    expect(() => {
      pending.go("https://www.openstreetmap.org/changeset/1");
      pending.close();
    }).not.toThrow();
  });
});
