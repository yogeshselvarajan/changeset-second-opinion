import type { PanelView } from "../../api/types.gen";
import { t } from "../../i18n";
import {
  compositionText,
  CROSS_CHECK_GLYPH,
  CROSS_CHECK_LABEL,
  formatProbability,
  TRI_GLYPH,
  TRI_LABEL,
  USE_LABEL,
} from "./caseModel";
import { ScrollRegion } from "./ScrollRegion";
import { Section } from "./Section";

/**
 * Every yes/no question the model was asked, with what it read and how that reading counted. Nothing
 * is left out: probes that only cross-check the parsed evidence, or that are stored for audit, are
 * listed with the rest and say so.
 */
export function FactPanelBlock({ panel }: { panel: PanelView }) {
  const labelOf = new Map(panel.probes.map((probe) => [probe.id, probe.label]));
  const crossChecks = panel.cross_checks ?? {};
  const strayChecks = Object.entries(crossChecks).filter(([id]) => !labelOf.has(id));
  const composition = panel.composition;
  const named = (ids: readonly string[] | undefined) =>
    (ids ?? []).map((id) => labelOf.get(id) ?? id).join("; ");

  return (
    <Section id="panel" title={t("case.panel.title")} testId="panel">
      <p className="text-sm text-text-muted">
        {t("case.panel.thresholds", {
          low: formatProbability(panel.low),
          high: formatProbability(panel.high),
        })}
      </p>
      <ScrollRegion label={t("case.panel.caption")} className="mt-2">
        <table
          className="w-full min-w-[30rem] border-collapse text-left text-sm"
          data-testid="panel-probes"
        >
          <caption className="sr-only">{t("case.panel.caption")}</caption>
          <thead>
            <tr className="border-b border-border">
              <th scope="col" className="px-2 py-1 font-semibold">
                {t("case.panel.colProbe")}
              </th>
              <th scope="col" className="px-2 py-1 font-semibold">
                {t("case.panel.colReading")}
              </th>
              <th scope="col" className="px-2 py-1 font-semibold">
                {t("case.panel.colProbability")}
              </th>
              <th scope="col" className="px-2 py-1 font-semibold">
                {t("case.panel.colUse")}
              </th>
              <th scope="col" className="px-2 py-1 font-semibold">
                {t("case.panel.colCrossCheck")}
              </th>
            </tr>
          </thead>
          <tbody>
            {panel.probes.map((probe) => {
              const check = crossChecks[probe.id];
              return (
                <tr
                  key={probe.id}
                  className="border-t border-border"
                  data-probe={probe.id}
                  data-reading={probe.reading}
                >
                  <th scope="row" className="px-2 py-1 font-normal">
                    {probe.label}
                  </th>
                  <td className="whitespace-nowrap px-2 py-1">
                    <span aria-hidden="true" className="mr-1 font-mono">
                      {TRI_GLYPH[probe.reading]}
                    </span>
                    {t(TRI_LABEL[probe.reading])}
                  </td>
                  <td className="px-2 py-1 font-mono tabular-nums">
                    {formatProbability(probe.probability)}
                  </td>
                  <td className="px-2 py-1 text-xs">
                    {t(USE_LABEL[probe.use])}
                    {probe.use === "composed" ? (
                      <span className="block text-text-muted">
                        {t(
                          probe.yes_means === "concern"
                            ? "case.panel.yesConcern"
                            : "case.panel.yesReassurance",
                        )}
                      </span>
                    ) : null}
                  </td>
                  <td className="px-2 py-1 text-xs">
                    {check ? (
                      <>
                        <span aria-hidden="true" className="mr-1 font-mono">
                          {CROSS_CHECK_GLYPH[check] ?? "?"}
                        </span>
                        {CROSS_CHECK_LABEL[check] ? t(CROSS_CHECK_LABEL[check]) : check}
                      </>
                    ) : (
                      <span className="text-text-muted">{t("case.crossCheck.none")}</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </ScrollRegion>

      {strayChecks.length > 0 ? (
        <ul className="mt-2 list-disc pl-5 text-xs" data-testid="panel-stray-checks">
          {strayChecks.map(([id, value]) => (
            <li key={id}>
              {id}: {CROSS_CHECK_LABEL[value] ? t(CROSS_CHECK_LABEL[value]) : value}
            </li>
          ))}
        </ul>
      ) : null}

      {composition ? (
        <div className="mt-4" data-testid="composition">
          <h4 className="text-sm font-semibold">{t("case.composition.title")}</h4>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-sm">
            <li data-row={composition.response_row}>
              <strong>{composition.response_row}</strong> ·{" "}
              {compositionText(composition.response_row)}
            </li>
            <li data-row={composition.nature_row}>
              <strong>{composition.nature_row}</strong> · {compositionText(composition.nature_row)}
            </li>
          </ul>
          {(composition.yes ?? []).length > 0 ? (
            <p className="mt-1 text-sm">
              {t("case.composition.yes", { list: named(composition.yes) })}
            </p>
          ) : null}
          {(composition.unknown ?? []).length > 0 ? (
            <p className="mt-1 text-sm">
              {t("case.composition.unknown", { list: named(composition.unknown) })}
            </p>
          ) : null}
        </div>
      ) : null}
    </Section>
  );
}
