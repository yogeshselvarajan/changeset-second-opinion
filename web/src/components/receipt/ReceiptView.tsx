import type { PublicReceipt } from "../../api/types.gen";
import { t } from "../../i18n";
import {
  barFraction,
  formatProbability,
  osmChangesetUrl,
  TRI_GLYPH,
  TRI_LABEL,
} from "../case/caseModel";
import { OsmAttribution } from "../case/OsmAttribution";
import { RulesBlock } from "../case/RulesBlock";
import { Section } from "../case/Section";
import { BandChip } from "../confidence/BandChip";
import { LaneChip } from "../shell/LaneChip";

/**
 * A decision receipt for anyone: the lane, the fact panel, the rules that fired and how much of the
 * changeset the evidence covered. It is read only and built from a public, allow-listed payload, so
 * it carries no reviewer, no decision and no evidence text.
 */
export function ReceiptView({
  receipt,
  headingLevel = 1,
  embedded = false,
}: {
  receipt: PublicReceipt;
  /** 3 when the receipt sits under a section of another page (the home page's example). */
  headingLevel?: 1 | 3;
  /** Leaves out the link into the tool, for a receipt shown as an example. */
  embedded?: boolean;
}) {
  const Heading = headingLevel === 1 ? "h1" : "h3";
  const url = embedded ? null : osmChangesetUrl(receipt.changeset_id);
  const coverage = receipt.coverage;
  const score = coverage.score ?? 0;
  // The API omits empty lists and zero counts from the typed shape; read them as empty and zero.
  const probes = receipt.probes ?? [];
  const rules = receipt.rules_fired ?? [];
  const detailed = coverage.elements_detailed ?? 0;
  const total = coverage.elements_in_changeset ?? 0;
  const gaps = coverage.history_gaps_count ?? 0;
  return (
    <article aria-labelledby="receipt-title" data-testid="receipt">
      <Heading id="receipt-title" className="text-xl font-semibold">
        {t("receipt.title", { id: receipt.changeset_id })}
      </Heading>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <LaneChip lane={receipt.lane} />
        <BandChip band={receipt.band} />
      </div>
      <p className="mt-2 text-sm text-ink-2">
        {t("receipt.meta", {
          date: receipt.created_at.slice(0, 10),
          model: receipt.decider?.model ?? t("case.unknown"),
        })}
      </p>
      {url ? (
        <p className="mt-2">
          <a href={url} rel="noreferrer noopener" target="_blank" className="underline">
            {t("receipt.openChangeset")}
          </a>
        </p>
      ) : null}

      <Section id="receipt-facts" title={t("receipt.facts")} testId="receipt-facts">
        {probes.length === 0 ? (
          <p className="text-sm text-ink-2">{t("receipt.noFacts")}</p>
        ) : (
          <ul className="space-y-1.5 text-sm">
            {probes.map((probe) => (
              <li
                key={probe.code}
                className="flex flex-wrap items-baseline gap-x-3"
                data-probe={probe.code}
                data-reading={probe.reading}
              >
                <span aria-hidden="true" className="w-4 font-mono text-ink-2">
                  {TRI_GLYPH[probe.reading]}
                </span>
                <span className="min-w-0 flex-1">{probe.label}</span>
                <span className="text-ink-2">{t(TRI_LABEL[probe.reading])}</span>
                <span className="font-mono tabular-nums">
                  {formatProbability(probe.probability)}
                </span>
              </li>
            ))}
          </ul>
        )}
        <p className="mt-2 text-xs text-ink-2">{t("receipt.factsNote")}</p>
      </Section>

      <RulesBlock rules={rules.map((rule) => ({ ...rule, triggered_by: {} }))} />

      <Section id="receipt-coverage" title={t("receipt.coverage")} testId="receipt-coverage">
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
          className="h-3 w-full max-w-md overflow-hidden rounded bg-line"
        >
          <div className="h-full bg-ink-2" style={{ width: `${barFraction(score) * 100}%` }} />
        </div>
        <p className="mt-2 text-sm">
          {t("case.coverage.summary", {
            score: formatProbability(score),
            detailed,
            total,
          })}
        </p>
        {gaps > 0 ? (
          <p className="mt-1 text-sm text-ink-2">{t("receipt.gaps", { n: gaps })}</p>
        ) : null}
      </Section>

      <p className="mt-4 text-xs text-ink-2" data-testid="receipt-versions">
        {t("receipt.versions", { config: receipt.config_version.slice(0, 15) })}
      </p>
      <OsmAttribution attribution={receipt.attribution} />
      {embedded ? null : (
        <p className="mt-4 text-sm">
          {/* A plain link: a receipt is a public page, and the tool is a separate bundle. */}
          <a href="/queue" className="underline">
            {t("receipt.toTool")}
          </a>
        </p>
      )}
    </article>
  );
}
