import type { CaseSummary } from "../../api/types.gen";
import { countsText } from "../queue/search";

type Counts = CaseSummary["element_counts"];

const CELLS = [
  { key: "create", glyph: "+", tint: "var(--color-diff-added)" },
  { key: "modify", glyph: "~", tint: "var(--color-diff-changed)" },
  { key: "delete", glyph: "−", tint: "var(--color-diff-removed)" },
] as const;

/**
 * Created, modified and deleted element counts as three cells. The bar under each number is scaled
 * to the largest of the three, so a glance shows the shape; the numbers carry the exact values and
 * one sentence carries the same for screen readers.
 */
export function CountMeter({ counts }: { counts: Counts }) {
  const values = CELLS.map((cell) => counts[cell.key] ?? 0);
  const max = Math.max(1, ...values);
  return (
    <span className="inline-grid grid-cols-3 gap-1 font-mono text-[12px]" data-testid="count-meter">
      <span className="sr-only">{countsText(counts)}</span>
      {CELLS.map((cell, index) => (
        <span key={cell.key} aria-hidden="true" className="flex min-w-0 flex-col">
          <span className="truncate text-ink">
            {cell.glyph}
            {values[index]}
          </span>
          <span
            className="h-[3px] rounded-full"
            style={{
              width: `${((values[index] as number) / max) * 100}%`,
              minWidth: (values[index] as number) > 0 ? 3 : 0,
              background: cell.tint,
              boxShadow: "inset 0 0 0 1px var(--color-line)",
            }}
          />
        </span>
      ))}
    </span>
  );
}
