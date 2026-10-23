import { useQuery } from "@tanstack/react-query";

import { getCaseOptions, getRunOptions } from "../../api/@tanstack/react-query.gen";
import type { DecisionRow } from "../../api/types.gen";
import { t } from "../../i18n";
import { BandChip } from "../confidence/BandChip";
import { formatDateTime, formatProbability, humanize } from "../case/caseModel";
import { failureFromError, retryTransient } from "../case/failure";
import { SectionSkeleton } from "../case/Section";
import { Untrusted } from "../case/Untrusted";
import { optionLookup, useConfig } from "../case/useCaseData";
import { joinParts } from "../draft/draftChecks";
import { dispositionLabel } from "../draft/draftModel";
import { hasChanges, wordDiff } from "../draft/wordDiff";

function Probabilities({
  title,
  probabilities,
  labels,
  testId,
}: {
  title: string;
  probabilities: Partial<Record<string, number>> | undefined;
  labels: Map<string, { label: string }>;
  testId: string;
}) {
  const entries = Object.entries(probabilities ?? {}).filter(
    (entry): entry is [string, number] => typeof entry[1] === "number",
  );
  if (entries.length === 0) return null;
  return (
    <div data-testid={testId}>
      <h4 className="text-xs font-semibold text-text-muted">{title}</h4>
      <ul className="mt-1 grid gap-x-4 sm:grid-cols-2">
        {entries.map(([code, value]) => (
          <li key={code} className="flex justify-between gap-2 text-sm">
            <span>{labels.get(code)?.label ?? humanize(code)}</span>
            <span className="font-mono" data-testid="probability">
              {formatProbability(value)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * What one recorded decision looked like: the final text next to the generated draft (word-level
 * changes), the reason and note, and the model's probabilities as they were at that run. The
 * decision list does not carry these, so they are read from the case and its run.
 */
export function DecisionDetail({ row }: { row: DecisionRow }) {
  const config = useConfig();
  const caseQuery = useQuery({
    ...getCaseOptions({ path: { id: row.case_id } }),
    retry: retryTransient,
  });
  const detail = caseQuery.data;
  const outcome =
    detail?.latest_outcome_detail && detail.latest_outcome_detail.id === row.outcome_id
      ? detail.latest_outcome_detail
      : null;
  const runQuery = useQuery({
    ...getRunOptions({ path: { id: outcome?.run_id_seen ?? "" } }),
    enabled: Boolean(outcome?.run_id_seen),
    retry: retryTransient,
  });
  const draft =
    detail?.latest_draft &&
    outcome &&
    detail.latest_draft.run_id === outcome.run_id_seen &&
    detail.latest_draft.response_type === outcome.response_type
      ? detail.latest_draft
      : null;
  const generated = draft ? joinParts(draft) : null;
  const diff =
    generated !== null && outcome?.final_text ? wordDiff(generated, outcome.final_text) : [];
  const natureLabels = optionLookup(config.data?.option_sets.nature);
  const responseLabels = optionLookup(config.data?.option_sets.response);

  if (caseQuery.isPending) return <SectionSkeleton label={t("history.detail.loading")} />;
  if (caseQuery.isError) {
    return (
      <p role="alert" data-testid="decision-detail-error">
        {failureFromError(caseQuery.error).message}
      </p>
    );
  }

  return (
    <div className="space-y-3 text-sm" data-testid="decision-detail">
      <dl className="grid gap-x-4 gap-y-1 sm:grid-cols-[10rem_1fr]">
        <dt className="text-text-muted">{t("history.detail.decision")}</dt>
        <dd>{dispositionLabel(row.disposition)}</dd>
        <dt className="text-text-muted">{t("history.detail.when")}</dt>
        <dd>{formatDateTime(row.created_at)}</dd>
        <dt className="text-text-muted">{t("history.detail.band")}</dt>
        <dd>
          <BandChip band={row.band_at_decision} />
        </dd>
        {outcome?.reason_code ? (
          <>
            <dt className="text-text-muted">{t("history.detail.reason")}</dt>
            <dd data-testid="detail-reason">{humanize(outcome.reason_code)}</dd>
          </>
        ) : null}
        {outcome?.note ? (
          <>
            <dt className="text-text-muted">{t("history.detail.note")}</dt>
            <dd>
              <Untrusted block value={outcome.note} />
            </dd>
          </>
        ) : null}
      </dl>

      {!outcome ? (
        <p className="text-text-muted" data-testid="detail-superseded">
          {t("history.detail.superseded")}
        </p>
      ) : null}

      {outcome?.final_text ? (
        <div data-testid="detail-final">
          <h4 className="text-xs font-semibold text-text-muted">{t("history.detail.final")}</h4>
          <Untrusted
            block
            value={outcome.final_text}
            className="mt-1 rounded border border-border p-2"
          />
        </div>
      ) : null}

      {generated !== null && outcome?.final_text ? (
        <div data-testid="detail-diff">
          <h4 className="text-xs font-semibold text-text-muted">{t("history.detail.diff")}</h4>
          {hasChanges(diff) ? (
            <p className="mt-1 whitespace-pre-wrap break-words rounded border border-border p-2">
              {diff.map((run, index) =>
                run.kind === "same" ? (
                  <span key={index}>{run.text}</span>
                ) : run.kind === "ins" ? (
                  <ins key={index} className="bg-diff-added no-underline">
                    <span aria-hidden="true">+</span>
                    <span className="sr-only">{t("draft.diff.added")}</span>
                    {run.text}
                  </ins>
                ) : (
                  <del key={index} className="bg-diff-removed">
                    <span aria-hidden="true">−</span>
                    <span className="sr-only">{t("draft.diff.removed")}</span>
                    {run.text}
                  </del>
                ),
              )}
            </p>
          ) : (
            <p className="mt-1 text-text-muted">{t("history.detail.unchanged")}</p>
          )}
        </div>
      ) : null}

      {runQuery.data ? (
        <div className="space-y-2" data-testid="detail-probabilities">
          <p className="text-xs text-text-muted">{t("history.detail.frozen")}</p>
          <Probabilities
            title={t("history.detail.response")}
            probabilities={runQuery.data.response_probabilities}
            labels={responseLabels}
            testId="probs-response"
          />
          <Probabilities
            title={t("history.detail.nature")}
            probabilities={runQuery.data.nature_probabilities}
            labels={natureLabels}
            testId="probs-nature"
          />
        </div>
      ) : null}
    </div>
  );
}
