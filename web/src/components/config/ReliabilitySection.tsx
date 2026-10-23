import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  calibrateConfigMutation,
  getConfigQueryKey,
  getConfigReliabilityOptions,
  getConfigReliabilityQueryKey,
  listConfigPacksQueryKey,
  listConfigVersionsQueryKey,
} from "../../api/@tanstack/react-query.gen";
import type { ProbeReliability } from "../../api/types.gen";
import { t } from "../../i18n";
import { failureFromError } from "../case/failure";
import { ScrollRegion } from "../case/ScrollRegion";
import { SectionSkeleton } from "../case/Section";
import { controlClass, QueueDialog } from "../queue/QueueDialog";
import { useAnnounce } from "../shell/Announcer";

const pair = (low: number, high: number) => `${low.toFixed(2)} / ${high.toFixed(2)}`;
const share = (value: number) => value.toFixed(2);

/** "0.88 (0.74 to 0.95)" for decided readings, or a plain dash when nothing was decided. */
function accuracyText(correct: number, decided: number, lower: number, upper: number): string {
  if (decided === 0) return t("config.reliability.none");
  return t("config.reliability.accuracy", {
    value: share(correct / decided),
    lower: share(lower),
    upper: share(upper),
  });
}

function sentence(probe: ProbeReliability): string {
  if (probe.status === "insufficient_data") {
    return t("config.reliability.sentence.few", {
      label: probe.label,
      n: probe.n,
      floor: 25,
    });
  }
  return t("config.reliability.sentence.rows", {
    label: probe.label,
    n: probe.n,
    correct: probe.correct,
    decided: probe.decided,
  });
}

/**
 * How the fact probes fared against reviewers' decisions, with the cut points a refit would pick.
 * Nothing changes until an admin confirms in the dialog; applying makes a new configuration
 * version and leaves every earlier run on the version it used.
 */
export function ReliabilitySection() {
  const announce = useAnnounce();
  const queryClient = useQueryClient();
  const report = useQuery({ ...getConfigReliabilityOptions(), retry: 1 });
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const apply = useMutation({
    ...calibrateConfigMutation(),
    onSuccess: async (result) => {
      setError(null);
      if (result.applied) {
        setOpen(false);
        announce(t("config.reliability.applied"));
      } else {
        setError(result.reason ?? t("config.reliability.notApplied"));
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: getConfigReliabilityQueryKey() }),
        queryClient.invalidateQueries({ queryKey: getConfigQueryKey() }),
        queryClient.invalidateQueries({ queryKey: listConfigVersionsQueryKey() }),
        queryClient.invalidateQueries({ queryKey: listConfigPacksQueryKey() }),
      ]);
    },
    onError: (failure) => setError(failureFromError(failure).message),
  });

  if (report.isPending) return <SectionSkeleton label={t("config.reliability.loading")} />;
  if (report.isError || !report.data) {
    return (
      <p role="alert" data-testid="reliability-error">
        {failureFromError(report.error).message}
      </p>
    );
  }
  const data = report.data;
  const changes = data.probes.filter(
    (p) => p.status === "fitted" && (p.low !== p.default_low || p.high !== p.default_high),
  );

  return (
    <div data-testid="reliability">
      <p className="text-ink-2" data-testid="reliability-summary">
        {t("config.reliability.summary", {
          decisions: data.n_outcomes,
          labelled: data.n_labelled_outcomes,
        })}
      </p>
      {(data.synthetic_outcomes ?? 0) > 0 ? (
        <p role="note" className="mt-1" data-testid="reliability-synthetic">
          {t("config.reliability.synthetic", { n: data.synthetic_outcomes ?? 0 })}
        </p>
      ) : null}
      <p className="mt-1 text-xs text-ink-2">{t("config.reliability.bias")}</p>

      <ScrollRegion label={t("config.reliability.region")} className="mt-2">
        <table className="w-full min-w-[40rem] border-collapse text-left text-xs">
          <caption className="sr-only">{t("config.reliability.caption")}</caption>
          <thead>
            <tr className="border-b border-line text-ink-2">
              <th scope="col" className="py-1 pr-2 font-medium">
                {t("config.reliability.col.probe")}
              </th>
              <th scope="col" className="py-1 pr-2 font-medium">
                {t("config.reliability.col.n")}
              </th>
              <th scope="col" className="py-1 pr-2 font-medium">
                {t("config.reliability.col.accuracy")}
              </th>
              <th scope="col" className="py-1 pr-2 font-medium">
                {t("config.reliability.col.default")}
              </th>
              <th scope="col" className="py-1 font-medium">
                {t("config.reliability.col.tuned")}
              </th>
            </tr>
          </thead>
          <tbody>
            {data.probes.map((probe) => (
              <tr
                key={probe.probe}
                className="border-b border-line align-top"
                data-probe-row={probe.probe}
                data-status={probe.status}
              >
                <th scope="row" className="py-1 pr-2 font-normal">
                  {probe.label}
                  <span className="block text-ink-2">{sentence(probe)}</span>
                </th>
                <td className="py-1 pr-2 font-mono">{probe.n}</td>
                <td className="py-1 pr-2">
                  {accuracyText(probe.correct, probe.decided, probe.lower, probe.upper)}
                </td>
                <td className="py-1 pr-2 font-mono">
                  {pair(probe.default_low, probe.default_high)}
                </td>
                <td className="py-1 font-mono">
                  {probe.status === "fitted"
                    ? pair(probe.low, probe.high)
                    : t(
                        probe.status === "kept_default"
                          ? "config.reliability.status.kept_default"
                          : "config.reliability.status.insufficient_data",
                      )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </ScrollRegion>

      <button
        type="button"
        className={`${controlClass} mt-3`}
        onClick={() => {
          setError(null);
          setOpen(true);
        }}
        data-testid="refit-open"
      >
        {t("config.reliability.refit")}
      </button>

      {open ? (
        <QueueDialog
          isOpen
          onOpenChange={(next) => (next ? undefined : setOpen(false))}
          title={t("config.reliability.confirm.title")}
        >
          <p className="mt-2 text-sm">{t("config.reliability.confirm.body")}</p>
          {changes.length === 0 ? (
            <p className="mt-2 text-sm" data-testid="refit-none">
              {t("config.reliability.confirm.none")}
            </p>
          ) : (
            <ul className="mt-2 list-disc space-y-1 pl-5 text-sm" data-testid="refit-changes">
              {changes.map((probe) => (
                <li key={probe.probe}>
                  {t("config.reliability.confirm.change", {
                    label: probe.label,
                    from: pair(probe.default_low, probe.default_high),
                    to: pair(probe.low, probe.high),
                  })}
                </li>
              ))}
            </ul>
          )}
          {error ? (
            <p role="alert" className="mt-2 text-sm">
              {error}
            </p>
          ) : null}
          <div className="mt-3 flex flex-wrap justify-end gap-2">
            <button type="button" className={controlClass} onClick={() => setOpen(false)}>
              {t("queue.add.cancel")}
            </button>
            <button
              type="button"
              className={controlClass}
              disabled={apply.isPending || changes.length === 0}
              onClick={() => apply.mutate({ body: { apply: true } })}
              data-testid="refit-confirm"
            >
              {t("config.reliability.confirm.action")}
            </button>
          </div>
        </QueueDialog>
      ) : null}
    </div>
  );
}
