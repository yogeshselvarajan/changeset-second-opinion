import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const css = readFileSync(join(__dirname, "..", "tokens.css"), "utf8");

/** Text of the first `{ ... }` block that follows `selector`. */
function blockAfter(selector: string, from = 0): { body: string; end: number } {
  const start = css.indexOf(selector, from);
  if (start === -1) throw new Error(`selector not found: ${selector}`);
  const open = css.indexOf("{", start);
  let depth = 0;
  for (let i = open; i < css.length; i++) {
    if (css[i] === "{") depth++;
    if (css[i] === "}" && --depth === 0) return { body: css.slice(open + 1, i), end: i };
  }
  throw new Error("unbalanced braces");
}

function variables(body: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const match of body.matchAll(/--color-([\w-]+):\s*(#[0-9a-fA-F]{6})\s*;/g)) {
    out[match[1] as string] = (match[2] as string).toLowerCase();
  }
  return out;
}

const light = variables(blockAfter("@theme {").body);
const darkExplicit = variables(blockAfter(':root[data-theme="dark"]').body);
const darkMedia = variables(
  blockAfter(':root:not([data-theme="light"])', css.indexOf("@media (prefers-color-scheme: dark)"))
    .body,
);

function luminance(hex: string): number {
  const channel = (offset: number) => {
    const value = parseInt(hex.slice(offset, offset + 2), 16) / 255;
    return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5);
}

export function ratio(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

const LANES = ["consistent", "review", "local", "insufficient", "rules-only"];
const DIFFS = ["added", "removed", "changed"];

describe.each([
  ["light", light],
  ["dark", darkExplicit],
])("%s theme contrast", (_name, theme) => {
  it("keeps body text at 4.5:1 or better", () => {
    for (const fg of ["text", "text-muted"]) {
      for (const bg of ["bg", "surface"]) {
        expect(
          ratio(theme[fg] as string, theme[bg] as string),
          `${fg} on ${bg}`,
        ).toBeGreaterThanOrEqual(4.5);
      }
    }
  });

  it("keeps the focus ring and control borders at 3:1 or better", () => {
    for (const token of ["focus", "control-border"]) {
      for (const bg of ["bg", "surface"]) {
        expect(
          ratio(theme[token] as string, theme[bg] as string),
          `${token} on ${bg}`,
        ).toBeGreaterThanOrEqual(3);
      }
    }
  });

  it("keeps every lane label readable on its own background", () => {
    for (const lane of LANES) {
      const fg = theme[`lane-${lane}-fg`] as string;
      const bg = theme[`lane-${lane}-bg`] as string;
      expect(ratio(fg, bg), lane).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("keeps text readable on every diff background", () => {
    for (const diff of DIFFS) {
      expect(
        ratio(theme.text as string, theme[`diff-${diff}`] as string),
        diff,
      ).toBeGreaterThanOrEqual(4.5);
    }
  });
});

describe("dark theme blocks", () => {
  it("define the same values for the system setting and the explicit choice", () => {
    expect(darkMedia).toEqual(darkExplicit);
  });

  it("override every light token", () => {
    expect(Object.keys(darkExplicit).sort()).toEqual(Object.keys(light).sort());
  });
});
