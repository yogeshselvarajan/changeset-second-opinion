import { describe, expect, it } from "vitest";

import type { WorkspaceSettings } from "../../api/types.gen";
import {
  LOGO_MAX_BYTES,
  buildUpdate,
  classifySave,
  exportJson,
  fieldLabel,
  isDirty,
  readLogoFile,
  settingsIfMatch,
  svgDataUrl,
  usesLabel,
} from "./settingsModel";

const settings: WorkspaceSettings = {
  name: "Changeset Second Opinion",
  tagline: "A second opinion.",
  accent_hex: "#4E5BD8",
  accent_dark_hex: "#6772DD",
  accent_contrast_light: 5.1,
  accent_contrast_dark: 4.6,
  community_paragraph: "Paragraph.",
  logo_svg: null,
  osm_signin_configured: false,
  osm_signin_enabled: true,
  active_pack: "default",
  calibration_version: null,
  updated_at: "2026-10-19T00:00:00Z",
  version: 3,
};

describe("settings model", () => {
  it("writes the If-Match header the server parses", () => {
    expect(settingsIfMatch(3)).toBe('W/"3"');
    expect(settingsIfMatch(-1)).toBe('W/"0"');
  });

  it("builds a full update from the server values and a patch", () => {
    const update = buildUpdate(settings, { name: "Lyon" });
    expect(update).toEqual({
      name: "Lyon",
      tagline: "A second opinion.",
      accent_hex: "#4E5BD8",
      community_paragraph: "Paragraph.",
      logo_svg: null,
      osm_signin_enabled: true,
    });
    expect(Object.keys(update)).not.toContain("version");
  });

  it("sees an edit, ignores colour case, and ignores the sign-in switch", () => {
    expect(isDirty(settings, { ...settings })).toBe(false);
    expect(isDirty(settings, { ...settings, accent_hex: "#4e5bd8" })).toBe(false);
    expect(isDirty(settings, { ...settings, osm_signin_enabled: false })).toBe(false);
    expect(isDirty(settings, { ...settings, name: "x" })).toBe(true);
    expect(isDirty(settings, { ...settings, logo_svg: "<svg/>" })).toBe(true);
  });

  it("sorts failures into conflict, field errors and the rest", () => {
    expect(classifySave({ status: 412 })).toEqual({ kind: "conflict" });
    expect(
      classifySave({
        status: 422,
        errors: [
          { loc: ["body", "name"], msg: "Too long", type: "x" },
          { loc: ["body", "name"], msg: "Empty", type: "x" },
          { loc: ["body", "logo_svg"], msg: "Bad", type: "x" },
        ],
      }),
    ).toEqual({ kind: "invalid", fields: { name: ["Too long", "Empty"], logo_svg: ["Bad"] } });
    expect(classifySave({ status: 500 })).toEqual({ kind: "other", status: 500 });
    expect(classifySave(new TypeError("offline"))).toEqual({ kind: "other", status: null });
  });

  it("names the fields it knows and echoes the rest", () => {
    expect(fieldLabel("accent_hex")).toBe("Accent colour");
    expect(fieldLabel("mystery")).toBe("mystery");
  });

  it("reads a logo only when it looks like an SVG of a fair size", async () => {
    const good = new File(["<svg/>"], "Logo.SVG", { type: "image/svg+xml" });
    expect(await readLogoFile(good)).toEqual({ ok: true, svg: "<svg/>" });
    expect(await readLogoFile(new File(["x"], "logo.png"))).toEqual({
      ok: false,
      reason: "notSvg",
    });
    const big = new File([new Uint8Array(LOGO_MAX_BYTES + 1)], "big.svg");
    expect(await readLogoFile(big)).toEqual({ ok: false, reason: "tooBig" });
  });

  it("shows a logo through a data URL and exports without a secret", () => {
    expect(svgDataUrl("<svg a='b'/>")).toMatch(/^data:image\/svg\+xml;charset=utf-8,%3Csvg/);
    const parsed = JSON.parse(exportJson(settings)) as Record<string, unknown>;
    expect(parsed.name).toBe(settings.name);
    expect(parsed.version).toBe(3);
    expect(Object.keys(parsed).some((key) => /secret|token|code/i.test(key))).toBe(false);
  });

  it("words the use count", () => {
    expect(usesLabel(2, 5)).toBe("2 of 5");
    expect(usesLabel(2, null)).toBe("2");
  });
});
