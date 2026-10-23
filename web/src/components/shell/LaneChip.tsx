import type { Lane } from "../../api/types.gen";
import { t } from "../../i18n";
import { laneMeta } from "../../lib/lanes";

/** A lane label with its glyph; the count (when known) is part of the text, not a colour. */
export function LaneChip({ lane, count }: { lane: Lane; count?: number | null }) {
  const meta = laneMeta(lane);
  return (
    <span
      className="inline-flex min-h-6 items-center gap-1 rounded px-2 py-0.5 text-xs"
      style={{ background: meta.bg, color: meta.fg }}
      data-lane={lane}
    >
      <span aria-hidden="true">{meta.glyph}</span>
      <span>{t(meta.label)}</span>
      {count !== undefined && count !== null ? <span>{count}</span> : null}
    </span>
  );
}
