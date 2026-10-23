/**
 * WCAG contrast for the accent colour, mirroring `cso.domain.workspace` on the server so the
 * settings form can show the same numbers while someone types. The server checks again on save.
 */

export const LIGHT_CANVAS = "#F6F5F2";
export const DARK_CANVAS = "#0F1012";
export const MIN_CONTRAST = 4.5;
export const DEFAULT_ACCENT = "#4E5BD8";

const HEX = /^#[0-9a-fA-F]{6}$/;

export function isHexColour(value: string): boolean {
  return HEX.test(value);
}

function channel(value: number): number {
  const c = value / 255;
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

function rgb(color: string): [number, number, number] {
  return [1, 3, 5].map((i) => parseInt(color.slice(i, i + 2), 16)) as [number, number, number];
}

export function relativeLuminance(color: string): number {
  const [r, g, b] = rgb(color);
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

export function contrastRatio(a: string, b: string): number {
  const la = relativeLuminance(a);
  const lb = relativeLuminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

function hex2(value: number): string {
  return value.toString(16).toUpperCase().padStart(2, "0");
}

/** The accent lightened until it reads at 4.5:1 on the dark canvas (the server derives the same). */
export function deriveDarkAccent(accent: string): string {
  const base = rgb(accent);
  for (let step = 0; step <= 100; step += 2) {
    const mix = step / 100;
    const candidate = `#${base.map((c) => hex2(Math.round(c + (255 - c) * mix))).join("")}`;
    if (contrastRatio(candidate, DARK_CANVAS) >= MIN_CONTRAST) return candidate;
  }
  return "#FFFFFF";
}

export interface AccentReadout {
  light: number;
  dark: number;
  darkHex: string;
  /** The rule the server applies: 4.5:1 on the light canvas. The dark copy is derived. */
  passes: boolean;
}

/** Numbers for the live readout, or null while the text is not yet a full `#rrggbb`. */
export function accentReadout(value: string): AccentReadout | null {
  if (!isHexColour(value)) return null;
  const darkHex = deriveDarkAccent(value);
  const light = contrastRatio(value, LIGHT_CANVAS);
  return {
    light,
    dark: contrastRatio(darkHex, DARK_CANVAS),
    darkHex,
    passes: light >= MIN_CONTRAST,
  };
}
