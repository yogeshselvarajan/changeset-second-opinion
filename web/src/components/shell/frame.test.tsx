import { readFileSync } from "node:fs";
import { join } from "node:path";

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const reduced = vi.hoisted(() => ({ value: false }));

vi.mock("motion/react", async (original) => {
  const actual = await original<typeof import("motion/react")>();
  return { ...actual, useReducedMotion: () => reduced.value };
});

import { RollingCount } from "../motion/RollingCount";

describe("RollingCount", () => {
  it("rolls digits that the screen reader hears once", () => {
    reduced.value = false;
    const { rerender } = render(<RollingCount value={27} />);
    expect(screen.getByRole("img", { name: "27" })).toBeInTheDocument();
    rerender(<RollingCount value={28} />);
    expect(screen.getByRole("img", { name: "28" })).toBeInTheDocument();
  });

  it("is plain text under reduced motion", () => {
    reduced.value = true;
    render(<RollingCount value={44} />);
    expect(screen.queryByTestId("rolling-count")).toBeNull();
    expect(screen.getByText("44")).toBeInTheDocument();
  });
});

describe("tokens", () => {
  const css = readFileSync(join(__dirname, "..", "..", "tokens.css"), "utf8");

  function block(selector: string, from = 0): Record<string, string> {
    const start = css.indexOf(selector, from);
    const open = css.indexOf("{", start);
    let depth = 0;
    for (let i = open; i < css.length; i++) {
      if (css[i] === "{") depth++;
      if (css[i] === "}" && --depth === 0) {
        const out: Record<string, string> = {};
        for (const m of css.slice(open + 1, i).matchAll(/--color-([\w-]+):\s*(#[0-9a-f]{6})/gi)) {
          out[m[1] as string] = (m[2] as string).toLowerCase();
        }
        return out;
      }
    }
    throw new Error("unbalanced");
  }

  function luminance(hex: string): number {
    const channel = (offset: number) => {
      const value = parseInt(hex.slice(offset, offset + 2), 16) / 255;
      return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
    };
    return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5);
  }
  function ratio(a: string, b: string): number {
    const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
    return (hi + 0.05) / (lo + 0.05);
  }

  const themes = {
    light: block("@theme {"),
    dark: block(':root[data-theme="dark"]'),
  };

  it.each(Object.entries(themes))("%s: the brief's names equal the original names", (_n, theme) => {
    expect(theme.canvas).toBe(theme.bg);
    expect(theme.line).toBe(theme.border);
    expect(theme.ink).toBe(theme.text);
    expect(theme["ink-2"]).toBe(theme["text-muted"]);
    expect(theme.accent).toBe(theme.focus);
    expect(theme["surface-2"]).toBeDefined();
  });

  it.each(Object.entries(themes))("%s: the new surfaces keep text readable", (_n, theme) => {
    expect(ratio(theme.ink as string, theme["surface-2"] as string)).toBeGreaterThanOrEqual(4.5);
    expect(ratio(theme["ink-2"] as string, theme["surface-2"] as string)).toBeGreaterThanOrEqual(
      4.5,
    );
    expect(ratio(theme["accent-fg"] as string, theme.accent as string)).toBeGreaterThanOrEqual(4.5);
    expect(ratio(theme.accent as string, theme.canvas as string)).toBeGreaterThanOrEqual(3);
  });
});
