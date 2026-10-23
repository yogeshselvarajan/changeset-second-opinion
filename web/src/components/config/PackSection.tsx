import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  activateConfigPackMutation,
  getConfigDiffOptions,
  getConfigQueryKey,
  listConfigPacksOptions,
  listConfigPacksQueryKey,
  listConfigVersionsQueryKey,
} from "../../api/@tanstack/react-query.gen";
import type { PackSummary } from "../../api/types.gen";
import { t } from "../../i18n";
import { failureFromError } from "../case/failure";
import { ScrollRegion } from "../case/ScrollRegion";
import { SectionSkeleton } from "../case/Section";
import { controlClass, QueueDialog } from "../queue/QueueDialog";
import { useAnnounce } from "../shell/Announcer";

/** What would change if `target` replaced `current`: one row per setting that differs. */
function DiffTable({ current, target }: { current: string; target: string }) {
  const diff = useQuery({
    ...getConfigDiffOptions({ query: { a: current, b: target } }),
    retry: 1,
  });
  if (diff.isPending) return <SectionSkeleton label={t("config.packs.diff.loading")} />;
  if (diff.isError || !diff.data) {
    return (
      <p role="alert" className="mt-2 text-sm">
        {failureFromError(diff.error).message}
      </p>
    );
  }
  const changes = diff.data.changes;
  if (changes.length === 0) return <p className="mt-2 text-sm">{t("config.packs.diff.none")}</p>;
  return (
    <ScrollRegion label={t("config.packs.diff.region")} className="mt-2 max-h-72">
      <table className="w-full border-collapse text-left text-xs" data-testid="pack-diff">
        <caption className="sr-only">
          {t("config.packs.diff.caption", { a: current, b: target })}
        </caption>
        <thead>
          <tr className="border-b border-line text-ink-2">
            <th scope="col" className="py-1 pr-2 font-medium">
              {t("config.packs.diff.setting")}
            </th>
            <th scope="col" className="py-1 pr-2 font-medium">
              {t("config.packs.diff.from")}
            </th>
            <th scope="col" className="py-1 font-medium">
              {t("config.packs.diff.to")}
            </th>
          </tr>
        </thead>
        <tbody>
          {changes.map((change) => (
            <tr key={`${change.area}:${change.key}`} className="border-b border-line align-top">
              <th scope="row" className="py-1 pr-2 font-mono font-normal">
                {change.key}
              </th>
              <td className="py-1 pr-2">{change.a ?? t("config.packs.diff.unset")}</td>
              <td className="py-1">{change.b ?? t("config.packs.diff.unset")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollRegion>
  );
}

/**
 * The community packs the server offers, with the one in use marked. An admin can switch: a dialog
 * lists every setting that would change first. Runs already made keep the version they used.
 */
export function PackSection() {
  const announce = useAnnounce();
  const queryClient = useQueryClient();
  const packs = useQuery({ ...listConfigPacksOptions(), retry: 1 });
  const [target, setTarget] = useState<PackSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  const activate = useMutation({
    ...activateConfigPackMutation(),
    onSuccess: async (result) => {
      setTarget(null);
      setError(null);
      announce(t("config.packs.switched", { title: result.pack.title }));
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: listConfigPacksQueryKey() }),
        queryClient.invalidateQueries({ queryKey: getConfigQueryKey() }),
        queryClient.invalidateQueries({ queryKey: listConfigVersionsQueryKey() }),
      ]);
    },
    onError: (failure) => setError(failureFromError(failure).message),
  });

  if (packs.isPending) return <SectionSkeleton label={t("config.packs.loading")} />;
  if (packs.isError || !packs.data) {
    return (
      <p role="alert" data-testid="packs-error">
        {failureFromError(packs.error).message}
      </p>
    );
  }
  const items = packs.data.items;
  const active = items.find((item) => item.is_active);

  return (
    <>
      <ul className="space-y-2" data-testid="pack-list">
        {items.map((pack) => (
          <li
            key={pack.id}
            className="flex flex-wrap items-start gap-x-3 gap-y-1 rounded-[var(--radius-pane)] border border-line bg-surface p-3"
            data-pack={pack.id}
            data-active={pack.is_active}
          >
            <div className="min-w-0 flex-1">
              <p className="m-0 font-medium">
                {pack.title}{" "}
                <span className="font-normal text-ink-2">
                  {t("config.packs.meta", { author: pack.author, version: pack.version })}
                </span>
              </p>
              <p className="m-0 mt-0.5 text-ink-2">{pack.description}</p>
            </div>
            {pack.is_active ? (
              <span
                className="rounded-[var(--radius-chip)] border border-control-border px-2 py-0.5 text-xs"
                data-testid="pack-active"
              >
                {t("config.packs.active")}
              </span>
            ) : (
              <button
                type="button"
                className={controlClass}
                onClick={() => {
                  setError(null);
                  setTarget(pack);
                }}
                data-testid="pack-switch"
              >
                {t("config.packs.switch")}
                <span className="sr-only"> {pack.title}</span>
              </button>
            )}
          </li>
        ))}
      </ul>

      {target && active ? (
        <QueueDialog
          isOpen
          onOpenChange={(open) => (open ? undefined : setTarget(null))}
          title={t("config.packs.confirm.title", { title: target.title })}
        >
          <p className="mt-2 text-sm">{t("config.packs.confirm.body")}</p>
          <DiffTable current={active.id} target={target.id} />
          {error ? (
            <p role="alert" className="mt-2 text-sm">
              {error}
            </p>
          ) : null}
          <div className="mt-3 flex flex-wrap justify-end gap-2">
            <button type="button" className={controlClass} onClick={() => setTarget(null)}>
              {t("queue.add.cancel")}
            </button>
            <button
              type="button"
              className={controlClass}
              disabled={activate.isPending}
              onClick={() => activate.mutate({ path: { pack_id: target.id } })}
              data-testid="pack-confirm"
            >
              {t("config.packs.confirm.action")}
            </button>
          </div>
        </QueueDialog>
      ) : null}
    </>
  );
}
