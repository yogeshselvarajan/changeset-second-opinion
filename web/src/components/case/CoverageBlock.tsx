import type { Coverage, FetchStatus } from "../../api/types.gen";
import { t } from "../../i18n";
import { barFraction, formatProbability, GAP_REASON_LABEL, gapCounts } from "./caseModel";
import { Section } from "./Section";

const FETCH_LABEL: Record<
  FetchStatus,
  "case.fetch.fetched" | "case.fetch.failed" | "case.fetch.skipped"
> = {
  fetched: "case.fetch.fetched",
  failed: "case.fetch.failed",
  skipped: "case.fetch.skipped",
};

/**
 * How much of the changeset the evidence really covers. It comes first because a recommendation is
 * only as good as what was looked at: skipped elements, history gaps and a truncated snapshot are all
 * stated in words, never summarised away.
 */
export function CoverageBlock({
  coverage,
  provisional,
}: {
  coverage: Coverage;
  provisional?: boolean;
}) {
  const total = coverage.elements_in_changeset;
  const detailed = coverage.elements_detailed;
  const skipped = coverage.elements_skipped_budget ?? 0;
  const gaps = coverage.history_gaps ?? [];
  const counts = gapCounts(gaps);
  const score = coverage.score ?? 0;
  const notDetailed = Math.max(0, total - detailed);
  return (
    <Section id="coverage" title={t("case.coverage.title")} testId="coverage">
      <div
        role="meter"
        aria-label={t("case.coverage.meterLabel")}
        aria-valuemin={0}
        aria-valuemax={1}
        aria-valuenow={barFraction(score)}
        aria-valuetext={t("case.coverage.meterText", {
          score: formatProbability(score),
          detailed,
          total,
        })}
        className="h-3 w-full max-w-md overflow-hidden rounded bg-border"
      >
        <div className="h-full bg-text-muted" style={{ width: `${barFraction(score) * 100}%` }} />
      </div>
      <p className="mt-2 text-sm" data-testid="coverage-summary">
        {t("case.coverage.summary", { score: formatProbability(score), detailed, total })}
      </p>
      <dl className="mt-2 space-y-1 text-sm">
        <div className="flex flex-wrap gap-x-2">
          <dt className="text-text-muted">{t("case.coverage.inChangeset")}</dt>
          <dd data-testid="coverage-total">{total}</dd>
        </div>
        <div className="flex flex-wrap gap-x-2">
          <dt className="text-text-muted">{t("case.coverage.detailed")}</dt>
          <dd data-testid="coverage-detailed">{detailed}</dd>
        </div>
        <div className="flex flex-wrap gap-x-2">
          <dt className="text-text-muted">{t("case.coverage.skipped")}</dt>
          <dd data-testid="coverage-skipped">{skipped}</dd>
        </div>
        <div className="flex flex-wrap gap-x-2">
          <dt className="text-text-muted">{t("case.coverage.userProfile")}</dt>
          <dd>
            {coverage.user_profile ? t(FETCH_LABEL[coverage.user_profile]) : t("case.unknown")}
          </dd>
        </div>
        <div className="flex flex-wrap gap-x-2">
          <dt className="text-text-muted">{t("case.coverage.discussion")}</dt>
          <dd>{coverage.discussion ? t(FETCH_LABEL[coverage.discussion]) : t("case.unknown")}</dd>
        </div>
      </dl>

      {coverage.snapshot_truncated ? (
        <p role="note" className="mt-2 rounded border border-control-border p-2 text-sm">
          {t("case.coverage.truncated")}
        </p>
      ) : null}
      {provisional ? (
        <p role="note" className="mt-2 rounded border border-control-border p-2 text-sm">
          {t("case.coverage.provisional")}
        </p>
      ) : null}

      {skipped > 0 || gaps.length > 0 ? (
        <div className="mt-3" data-testid="coverage-gaps">
          <h4 className="text-sm font-semibold">{t("case.coverage.notFetched")}</h4>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-sm">
            {skipped > 0 ? <li>{t("case.coverage.skippedBudget", { n: skipped })}</li> : null}
            {[...counts.entries()].map(([reason, n]) => (
              <li key={reason}>
                {t("case.coverage.gapCount", { n, reason: t(GAP_REASON_LABEL[reason]) })}
              </li>
            ))}
          </ul>
          {gaps.length > 0 ? (
            <details className="mt-2 text-sm">
              <summary className="cursor-pointer">
                {t("case.coverage.gapList", { n: gaps.length })}
              </summary>
              <ul className="mt-1 space-y-0.5 font-mono text-xs">
                {gaps.map((gap) => (
                  <li key={`${gap.osm_type}/${gap.osm_id}/${gap.reason}`}>
                    {gap.osm_type}/{gap.osm_id} · {t(GAP_REASON_LABEL[gap.reason])}
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
          {notDetailed > 0 ? (
            <p className="mt-2 text-xs text-text-muted">
              {t("case.coverage.diffUnavailable", { n: notDetailed })}
            </p>
          ) : null}
        </div>
      ) : (
        <p className="mt-2 text-sm text-text-muted">{t("case.coverage.noGaps")}</p>
      )}
    </Section>
  );
}
