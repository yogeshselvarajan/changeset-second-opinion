import type { Lane } from "../api/types.gen";
import type { MessageKey } from "../i18n";

export interface LaneMeta {
  lane: Lane;
  glyph: string;
  label: MessageKey;
  /** Tailwind colour token names (see tokens.css): background and foreground. */
  bg: string;
  fg: string;
}

/** Queue order. Every lane has a glyph and a text label, so colour is never the only signal. */
export const LANES: readonly LaneMeta[] = [
  {
    lane: "looks_consistent",
    glyph: "✓",
    label: "lane.looks_consistent",
    bg: "var(--color-lane-consistent-bg)",
    fg: "var(--color-lane-consistent-fg)",
  },
  {
    lane: "review_suggested",
    glyph: "◐",
    label: "lane.review_suggested",
    bg: "var(--color-lane-review-bg)",
    fg: "var(--color-lane-review-fg)",
  },
  {
    lane: "needs_local_knowledge",
    glyph: "⌖",
    label: "lane.needs_local_knowledge",
    bg: "var(--color-lane-local-bg)",
    fg: "var(--color-lane-local-fg)",
  },
  {
    lane: "insufficient_evidence",
    glyph: "◌",
    label: "lane.insufficient_evidence",
    bg: "var(--color-lane-insufficient-bg)",
    fg: "var(--color-lane-insufficient-fg)",
  },
  {
    lane: "rules_only",
    glyph: "≡",
    label: "lane.rules_only",
    bg: "var(--color-lane-rules-only-bg)",
    fg: "var(--color-lane-rules-only-fg)",
  },
];

export function laneMeta(lane: Lane): LaneMeta {
  const found = LANES.find((entry) => entry.lane === lane);
  if (!found) throw new Error(`Unknown lane: ${lane}`);
  return found;
}
