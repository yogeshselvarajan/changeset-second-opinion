import type { RunSummary } from "../../api/types.gen";
import { t } from "../../i18n";
import { LaneChip } from "../shell/LaneChip";
import { BandChip } from "../confidence/BandChip";
import { formatDateTime, humanize } from "./caseModel";
import type { OptionInfo } from "./useCaseData";
import { Section } from "./Section";
import { Untrusted } from "./Untrusted";

/** Every analysis run for the case, newest first, read-only. The latest one drives the screen. */
export function RunHistory({
  runs,
  latestId,
  responseOptions,
}: {
  runs: readonly RunSummary[];
  latestId: string | undefined;
  responseOptions: ReadonlyMap<string, OptionInfo>;
}) {
  return (
    <Section id="runs" title={t("case.runs.title", { n: runs.length })} testId="runs">
      {runs.length === 0 ? (
        <p className="text-sm text-text-muted">{t("case.runs.none")}</p>
      ) : (
        <ol className="space-y-2" data-testid="runs-list">
          {runs.map((run) => (
            <li key={run.id} className="rounded border border-border p-2 text-sm" data-run={run.id}>
              <p className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-xs">{formatDateTime(run.created_at)}</span>
                {run.id === latestId ? (
                  <span className="rounded border border-control-border px-2 text-xs">
                    {t("case.runs.latest")}
                  </span>
                ) : null}
                <LaneChip lane={run.lane} />
                <BandChip band={run.band} />
              </p>
              <p className="mt-1">
                {run.status === "failed"
                  ? t("case.runs.failed", { code: run.failure_code ?? t("case.unknown") })
                  : run.response
                    ? (responseOptions.get(run.response)?.label ?? humanize(run.response))
                    : t("case.runs.noResponse")}
              </p>
              <p className="mt-1 text-xs text-text-muted">
                {run.decider_model ? (
                  <Untrusted value={run.decider_model} />
                ) : (
                  t("case.runs.noModel")
                )}
                {" · "}
                {t("case.runs.config", { version: run.config_version.slice(0, 18) })}
              </p>
            </li>
          ))}
        </ol>
      )}
    </Section>
  );
}
