import { describe, expect, it } from "vitest";

import {
  DARK_CANVAS,
  DEFAULT_ACCENT,
  LIGHT_CANVAS,
  accentReadout,
  contrastRatio,
  deriveDarkAccent,
  isHexColour,
} from "./contrast";

describe("contrast", () => {
  it("matches the WCAG reference values", () => {
    expect(contrastRatio("#000000", "#FFFFFF")).toBeCloseTo(21, 5);
    expect(contrastRatio("#777777", "#FFFFFF")).toBeCloseTo(4.48, 2);
    expect(contrastRatio("#FFFFFF", "#FFFFFF")).toBe(1);
  });

  it("accepts only #rrggbb", () => {
    expect(isHexColour("#3A46B0")).toBe(true);
    expect(isHexColour("#3a46b0")).toBe(true);
    for (const bad of ["3A46B0", "#3A46B", "#3A46B0FF", "#GGGGGG", "red", ""]) {
      expect(isHexColour(bad)).toBe(false);
    }
  });

  it("derives a dark-canvas accent that reads at 4.5:1", () => {
    for (const accent of [DEFAULT_ACCENT, "#3A46B0", "#1B4D3E", "#000000", "#8E1B1B"]) {
      const dark = deriveDarkAccent(accent);
      expect(contrastRatio(dark, DARK_CANVAS)).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("derives the same colour the server does for the default accent", () => {
    // `derive_dark_accent("#4E5BD8")` in backend/src/cso/domain/workspace.py
    expect(deriveDarkAccent(DEFAULT_ACCENT)).toBe("#6772DD");
    expect(deriveDarkAccent("#3A46B0")).toBe("#6D76C5");
  });

  it("reports whether the light-canvas rule holds", () => {
    expect(accentReadout("#4E5BD8")?.passes).toBe(true);
    expect(accentReadout("#F0F0F0")?.passes).toBe(false);
    expect(accentReadout("#4E5B")).toBeNull();
    expect(contrastRatio(DEFAULT_ACCENT, LIGHT_CANVAS)).toBeGreaterThan(4.5);
  });
});
