import type {
  AnalysisRun,
  CaseDetail,
  CommunityConfig,
  Job,
  RunSummary,
} from "../../api/types.gen";
import { t } from "../../i18n";
import type { Failure } from "../../lib/problem";
import { BandChip } from "../confidence/BandChip";
import { ConfidenceBlock } from "../confidence/ConfidenceBlock";
import { confidenceRows } from "../confidence/confidenceRows";
import { humanize } from "./caseModel";
import { FactPanelBlock } from "./FactPanelBlock";
import { RulesBlock } from "./RulesBlock";
import { RunHistory } from "./RunHistory";
import { Section, SectionSkeleton } from "./Section";
import { Untrusted } from "./Untrusted";
import { optionLookup } from "./useCaseData";

const STEP_LABEL = {
  fetch_evidence: "case.job.step.fetch_evidence",
  snapshot: "case.job.step.snapshot",
  decide: "case.job.step.decide",
  persist: "case.job.step.persist",
  draft: "case.job.step.draft",
} as const;

/** The right pane: what the checks suggest, how decisive they were, the rules, and the history. */
export function RecommendationPane({
  detail,
  runDetail,
  config,
  runs,
  runsFailure,
  job,
  reveal = false,
}: {
  /** True only right after the case went from analyzing to analyzed: the band and rules rise in. */
  reveal?: boolean;
  detail: CaseDetail;
  runDetail: AnalysisRun | undefined;
  config: CommunityConfig | undefined;
  runs: readonly RunSummary[] | undefined;
  runsFailure: Failure | null;
  job: Job | undefined;
}) {
  const run = detail.latest_run;
  const natureOptions = optionLookup(config?.option_sets.nature);
  const responseOptions = optionLookup(config?.option_sets.response);
  const natureOrder = (config?.option_sets.nature ?? []).map((option) => option.code);
  const responseOrder = (config?.option_sets.response ?? []).map((option) => option.code);
  const analysing = detail.status === "analyzing" || (job !== undefined && !isDone(job));

  return (
    <section aria-labelledby="pane-recommendation-title" data-testid="pane-recommendation">
      <h2 id="pane-recommendation-title" className="text-lg font-semibold">
        {t("case.pane.recommendation")}
      </h2>
      <div className="mt-3">
        {analysing ? (
          <div
            role="status"
            aria-busy="true"
            className="mb-4 rounded border border-control-border p-3 text-sm"
            data-testid="analysis-progress"
          >
            <p className="font-semibold">{t("case.job.running")}</p>
            {job?.step ? (
              <p className="mt-1">{t("case.job.step", { step: t(STEP_LABEL[job.step]) })}</p>
            ) : null}
          </div>
        ) : null}

        {!run ? (
          <Section id="recommendation" title={t("case.rec.title")} testId="recommendation">
            <p className="text-sm text-text-muted" data-testid="no-run">
              {analysing ? t("case.rec.waiting") : t("case.rec.noRun")}
            </p>
          </Section>
        ) : run.status === "failed" ? (
          <Section id="recommendation" title={t("case.rec.title")} testId="recommendation">
            <div
              role="status"
              className="rounded border border-control-border p-3"
              data-testid="failed-run"
            >
              <p className="text-sm font-semibold">{t("case.rec.failed")}</p>
              <p className="mt-1 text-sm">
                {t("case.rec.failedCode")}{" "}
                <code className="font-mono">
                  <Untrusted value={run.failure_code ?? t("case.unknown")} />
                </code>
              </p>
              <p className="mt-1 text-xs text-text-muted">{t("case.rec.failedNote")}</p>
            </div>
          </Section>
        ) : (
          <>
            <Section id="recommendation" title={t("case.rec.title")} testId="recommendation">
              <dl className="space-y-1">
                <div>
                  <dt className="text-sm text-text-muted">{t("case.rec.response")}</dt>
                  <dd className="text-base font-semibold" data-testid="recommendation-response">
                    {run.response
                      ? (responseOptions.get(run.response)?.label ?? humanize(run.response))
                      : t("case.rec.noResponse")}
                  </dd>
                </div>
                <div>
                  <dt className="text-sm text-text-muted">{t("case.rec.nature")}</dt>
                  <dd className="text-sm" data-testid="recommendation-nature">
                    {run.nature
                      ? (natureOptions.get(run.nature)?.label ?? humanize(run.nature))
                      : t("case.rec.noNature")}
                  </dd>
                </div>
              </dl>
              {runDetail?.receipt.reconciliation?.applied ? (
                <p className="mt-2 text-sm" data-testid="reconciliation">
                  {t("case.rec.reconciled", {
                    from: runDetail.receipt.reconciliation.from
                      ? (responseOptions.get(runDetail.receipt.reconciliation.from)?.label ??
                        humanize(runDetail.receipt.reconciliation.from))
                      : t("case.unknown"),
                  })}
                </p>
              ) : null}
              <div
                className={`mt-2 flex flex-wrap items-center gap-2 ${reveal ? "cso-pop" : ""}`}
                data-testid="band-reveal"
              >
                <BandChip band={run.band} describedBy="rec-band-note" />
              </div>
              <p id="rec-band-note" className="mt-1 text-xs text-text-muted">
                {run.panel ? t("confidence.bandPanel") : t("confidence.formula")}
              </p>
              <p className="mt-2 text-sm">{t("case.rec.humanDecides")}</p>
            </Section>

            {run.panel ? <FactPanelBlock panel={run.panel} /> : null}

            <Section id="confidence" title={t("case.conf.title")} testId="confidence">
              {run.panel ? (
                <ConfidenceBlock
                  id="nature"
                  title={t("case.conf.natureAdvisory")}
                  rows={confidenceRows(
                    run.panel.advisory_nature.probabilities,
                    natureOptions,
                    natureOrder,
                  )}
                  advisory
                  markCode={run.panel.advisory_nature.choice}
                  markText={t("case.conf.advisoryTop")}
                  explanation={t("confidence.advisoryNote")}
                />
              ) : (
                <>
                  <ConfidenceBlock
                    id="nature"
                    title={t("case.conf.nature")}
                    rows={confidenceRows(run.nature_probabilities, natureOptions, natureOrder)}
                    band={run.band}
                    showBand
                    markCode={run.nature}
                    markText={t("case.conf.chosen")}
                    orderSensitivity={run.order_sensitivity}
                  />
                  <ConfidenceBlock
                    id="response"
                    title={t("case.conf.response")}
                    rows={confidenceRows(
                      run.response_probabilities,
                      responseOptions,
                      responseOrder,
                    )}
                    markCode={run.response}
                    markText={t("case.conf.chosen")}
                  />
                </>
              )}
            </Section>
          </>
        )}

        <RulesBlock rules={run?.rules_fired ?? []} reveal={reveal} />

        {runs ? (
          <RunHistory runs={runs} latestId={run?.id} responseOptions={responseOptions} />
        ) : runsFailure ? (
          <Section id="runs" title={t("case.runs.title", { n: 0 })} testId="runs">
            <p role="alert" className="text-sm">
              {runsFailure.message}
            </p>
          </Section>
        ) : (
          <Section id="runs" title={t("case.runs.title", { n: 0 })} testId="runs">
            <SectionSkeleton label={t("case.loading.runs")} />
          </Section>
        )}
      </div>
    </section>
  );
}

function isDone(job: Job): boolean {
  return job.status === "succeeded" || job.status === "failed" || job.status === "cancelled";
}
