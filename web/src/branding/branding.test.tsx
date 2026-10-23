import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { PublicBranding } from "../api/types.gen";
import {
  BRANDING_URL,
  accentCss,
  isBranding,
  loadBranding,
  resetBranding,
  setBranding,
  useBranding,
} from "./branding";

const lyon: PublicBranding = {
  name: "Second Opinion Lyon",
  tagline: "Local eyes on flagged edits.",
  accent_hex: "#3A46B0",
  accent_dark_hex: "#6D76C5",
  community_paragraph: "We review for the Lyon mapping community.",
  has_logo: false,
  osm_signin_enabled: true,
};

function respond(body: unknown, ok = true) {
  return vi.fn(async () => ({ ok, json: async () => body }) as Response);
}

beforeEach(() => resetBranding());
afterEach(() => vi.unstubAllGlobals());

describe("branding store", () => {
  it("accepts only a well-formed answer", () => {
    expect(isBranding(lyon)).toBe(true);
    expect(isBranding({ ...lyon, accent_hex: "red" })).toBe(false);
    expect(isBranding({ ...lyon, accent_dark_hex: "url(x)" })).toBe(false);
    expect(isBranding({ ...lyon, has_logo: "yes" })).toBe(false);
    expect(isBranding(null)).toBe(false);
  });

  it("writes no CSS for the built-in accent, and both themes for a new one", () => {
    expect(accentCss({ ...lyon, accent_hex: "#4e5bd8" })).toBeNull();
    const css = accentCss(lyon) ?? "";
    expect(css).toContain("--color-accent:#3A46B0");
    expect(css).toContain('[data-theme="dark"]');
    expect(css).toContain("--color-accent:#6D76C5");
  });

  it("applies a fetched accent to the page and removes it when it is the default again", async () => {
    vi.stubGlobal("fetch", respond(lyon));
    await loadBranding();
    expect(document.getElementById("cso-branding")?.textContent).toContain("#3A46B0");
    setBranding({ ...lyon, accent_hex: "#4E5BD8", accent_dark_hex: "#6772DD" });
    expect(document.getElementById("cso-branding")).toBeNull();
  });

  it("asks without credentials and not again while the copy is fresh", async () => {
    const fetcher = respond(lyon);
    vi.stubGlobal("fetch", fetcher);
    await loadBranding();
    await loadBranding();
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher).toHaveBeenCalledWith(
      BRANDING_URL,
      expect.objectContaining({ credentials: "omit" }),
    );
    await loadBranding(true);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("keeps the built-in wording when the call fails or the answer is odd", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Promise.reject(new TypeError("offline"))),
    );
    await loadBranding();
    vi.stubGlobal("fetch", respond({ name: 1 }));
    await loadBranding();
    vi.stubGlobal("fetch", respond(lyon, false));
    await loadBranding();
    const { result } = renderHook(() => useBranding());
    expect(result.current).toBeNull();
  });

  it("hands a reader the value once it arrives", async () => {
    vi.stubGlobal("fetch", respond(lyon));
    const { result } = renderHook(() => useBranding());
    expect(result.current).toBeNull();
    await waitFor(() => expect(result.current?.name).toBe("Second Opinion Lyon"));
    act(() => setBranding({ ...lyon, name: "Renamed" }));
    expect(result.current?.name).toBe("Renamed");
  });
});
