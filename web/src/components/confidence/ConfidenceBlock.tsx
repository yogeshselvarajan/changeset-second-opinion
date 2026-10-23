import type { Band } from "../../api/types.gen";
import { t } from "../../i18n";
import { barFraction, formatProbability } from "../case/caseModel";
import { BandChip } from "./BandChip";

export interface ConfidenceRow {
  code: string;
  label: string;
  description?: string;
  probability: number;
}

interface ConfidenceBlockProps {
  /** Unique within the page: ids for labels and descriptions are derived from it. */
  id: string;
  title: string;
  /** Every option, in the order the API (or the option set) gave. Nothing is filtered out. */
  rows: readonly ConfidenceRow[];
  band?: Band | null;
  showBand?: boolean;
  orderSensitivity?: number | null;
  /** True when this answer is stored for audit but never used to place a case in a lane. */
  advisory?: boolean;
  /** The option the system picked, marked with words as well as position. */
  markCode?: string | null;
  markText?: string;
  /** What the band and numbers mean for this kind of answer; defaults to the choice-confidence note. */
  explanation?: string;
}

/**
 * Every option with its own number, a neutral bar, and the backend band. There is no single
 * headline figure: a lone percentage would read as the chance that an edit is harmful, and the
 * numbers here are not that.
 */
export function ConfidenceBlock({
  id,
  title,
  rows,
  band,
  showBand = false,
  orderSensitivity,
  advisory = false,
  markCode,
  markText,
  explanation,
}: ConfidenceBlockProps) {
  const headingId = `${id}-heading`;
  const formulaId = `${id}-formula`;
  return (
    <section aria-labelledby={headingId} className="mt-3" data-testid={`confidence-${id}`}>
      <div className="flex flex-wrap items-center gap-2">
        <h4 id={headingId} className="text-sm font-semibold">
          {title}
        </h4>
        {advisory ? (
          <span
            className="rounded border border-control-border px-2 py-0.5 text-xs"
            data-testid={`${id}-advisory`}
          >
            {t("confidence.advisory")}
          </span>
        ) : null}
        {showBand ? <BandChip band={band} describedBy={formulaId} /> : null}
      </div>

      {rows.length === 0 ? (
        <p className="mt-1 text-sm text-text-muted">{t("confidence.noProbabilities")}</p>
      ) : (
        <ul className="mt-2 space-y-2">
          {rows.map((row) => {
            const labelId = `${id}-${row.code}-label`;
            const text = formatProbability(row.probability);
            return (
              <li
                key={row.code}
                className="grid grid-cols-1 items-center gap-1 sm:grid-cols-[minmax(9rem,13rem)_1fr_3rem] sm:gap-3"
                data-option={row.code}
              >
                <span id={labelId} className="text-sm" title={row.description}>
                  {row.label}
                  {markCode === row.code && markText ? (
                    <span className="ml-1 text-xs text-text-muted">({markText})</span>
                  ) : null}
                </span>
                <div
                  role="meter"
                  aria-labelledby={labelId}
                  aria-valuemin={0}
                  aria-valuemax={1}
                  aria-valuenow={barFraction(row.probability)}
                  aria-valuetext={t("confidence.meterText", { label: row.label, value: text })}
                  className="h-3 w-full overflow-hidden rounded bg-border"
                >
                  <div
                    className="h-full bg-text-muted"
                    style={{ width: `${barFraction(row.probability) * 100}%` }}
                  />
                </div>
                <span className="font-mono text-sm tabular-nums" data-testid="option-value">
                  {text}
                </span>
              </li>
            );
          })}
        </ul>
      )}

      {orderSensitivity !== null && orderSensitivity !== undefined ? (
        <p className="mt-2 text-sm">
          {t("confidence.orderSensitivity", { value: formatProbability(orderSensitivity) })}
        </p>
      ) : null}
      {/* The advisory sentence is the explanation below when the caller passes it; saying it twice
          read as two separate caveats. */}
      {advisory && explanation === undefined ? (
        <p className="mt-1 text-xs text-text-muted">{t("confidence.advisoryNote")}</p>
      ) : null}
      <p id={formulaId} className="mt-2 text-xs text-text-muted">
        {explanation ?? t("confidence.formula")}
      </p>
    </section>
  );
}
