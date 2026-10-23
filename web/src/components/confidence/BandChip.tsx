import type { Band } from "../../api/types.gen";
import { t } from "../../i18n";
import { bandMeta } from "../case/caseModel";

/**
 * The band exactly as the backend gave it, with a glyph and its words. It is deliberately neutral
 * (not lane-coloured) and carries no number: a band says how decisive the output was, not how
 * likely anything is.
 */
export function BandChip({
  band,
  describedBy,
}: {
  band: Band | null | undefined;
  describedBy?: string;
}) {
  if (!band) {
    return (
      <span
        className="inline-flex min-h-6 items-center gap-1 rounded border border-border px-2 py-0.5 text-xs text-text-muted"
        data-band="none"
      >
        {t("confidence.band.none")}
      </span>
    );
  }
  const meta = bandMeta(band);
  return (
    <span
      className="inline-flex min-h-6 items-center gap-1 rounded border border-control-border px-2 py-0.5 text-xs"
      data-band={band}
      aria-describedby={describedBy}
    >
      <span aria-hidden="true">{meta.glyph}</span>
      <span>{t(meta.label)}</span>
    </span>
  );
}
