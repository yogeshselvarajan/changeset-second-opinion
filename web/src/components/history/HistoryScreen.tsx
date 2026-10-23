import { keepPreviousData, useInfiniteQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import { listDecisionsInfiniteOptions } from "../../api/@tanstack/react-query.gen";
import type { DecisionListResponse } from "../../api/types.gen";
import { t } from "../../i18n";
import { isTypingTarget } from "../../lib/hotkeys";
import { isAdmin } from "../../lib/roles";
import { useMe } from "../../lib/useMe";
import { failureFromError } from "../case/failure";
import { SectionSkeleton } from "../case/Section";
import { dispositionLabel } from "../draft/draftModel";
import { controlClass, fieldClass } from "../queue/QueueDialog";
import { useAnnounce } from "../shell/Announcer";
import { HistoryTimeline } from "./HistoryTimeline";
import {
  DISPOSITIONS,
  cleanFilters,
  csvHref,
  decisionQuery,
  groupByDay,
  isFiltered,
  uniqueDecisions,
  type HistoryFilters,
} from "./historyModel";

/**
 * `/history`: every recorded decision, newest first, as a day-grouped timeline. Filters live in the
 * URL, the list loads a page at a time, and an entry expands to show what was decided and what the
 * model said at that moment. An admin also gets the CSV export link.
 */
export function HistoryScreen({
  filters,
  onFilters,
}: {
  filters: HistoryFilters;
  onFilters: (next: HistoryFilters) => void;
}) {
  const announce = useAnnounce();
  const { me } = useMe();
  const clean = useMemo(() => cleanFilters(filters), [filters]);
  const [open, setOpen] = useState<ReadonlySet<string>>(() => new Set());
  const reviewerField = useRef<HTMLInputElement>(null);
  const [draftFilters, setDraftFilters] = useState<HistoryFilters>(clean);
  // Follow the URL when it changes under us (back and forward); keep typing otherwise.
  const [seen, setSeen] = useState(clean);
  if (seen !== clean) {
    setSeen(clean);
    setDraftFilters(clean);
  }

  const query = useInfiniteQuery({
    ...listDecisionsInfiniteOptions({ query: decisionQuery(clean) }),
    // An empty object, not null, means "no cursor yet" for the generated client.
    initialPageParam: {},
    getNextPageParam: (last: DecisionListResponse) => last.next_cursor ?? undefined,
    placeholderData: keepPreviousData,
    retry: 1,
    retryDelay: 400,
  });
  const rows = useMemo(
    () => uniqueDecisions((query.data?.pages ?? []).flatMap((page) => page.items)),
    [query.data],
  );
  const groups = useMemo(() => groupByDay(rows), [rows]);

  const moveFocus = useCallback((step: 1 | -1) => {
    const buttons = [...document.querySelectorAll<HTMLElement>("[data-history-row]")];
    if (buttons.length === 0) return;
    const index = buttons.indexOf(document.activeElement as HTMLElement);
    const next = index === -1 ? (step === 1 ? 0 : buttons.length - 1) : index + step;
    buttons[Math.min(buttons.length - 1, Math.max(0, next))]?.focus();
  }, []);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.ctrlKey || event.metaKey || event.altKey || isTypingTarget(event.target)) return;
      if (event.key === "f") {
        event.preventDefault();
        reviewerField.current?.focus();
        announce(t("history.filters.focused"));
      } else if (event.key === "j") moveFocus(1);
      else if (event.key === "k") moveFocus(-1);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [announce, moveFocus]);

  function apply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onFilters(cleanFilters(draftFilters));
    announce(t("history.filters.applied"));
  }

  function toggle(id: string) {
    setOpen((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const filtered = isFiltered(clean);
  const failure = query.isError ? failureFromError(query.error) : null;

  return (
    <section aria-labelledby="history-title" className="cso-page" data-testid="history-screen">
      <header className="cso-pagehead flex flex-wrap items-center justify-between gap-2">
        <h1 id="history-title" className="text-xl font-semibold">
          {t("history.title")}
        </h1>
        <div className="flex items-center gap-3 text-sm">
          <span className="text-ink-2">{t("history.keys")}</span>
          {isAdmin(me?.role) ? (
            <a
              href={csvHref(clean)}
              download="decisions.csv"
              className="inline-flex min-h-8 items-center rounded-[var(--radius-control)] border border-control-border px-3 underline"
              data-testid="history-csv"
            >
              {t("history.csv")}
            </a>
          ) : null}
        </div>
      </header>

      <form
        onSubmit={apply}
        aria-label={t("history.filters.label")}
        className="cso-card mt-4 flex flex-wrap items-end gap-3 text-sm"
        data-testid="history-filters"
      >
        <label className="flex flex-col">
          {t("history.filters.reviewer")}
          <input
            ref={reviewerField}
            type="text"
            maxLength={80}
            value={draftFilters.reviewer ?? ""}
            onChange={(event) => setDraftFilters({ ...draftFilters, reviewer: event.target.value })}
            className={`${fieldClass} mt-1 w-44`}
            data-testid="filter-reviewer"
          />
        </label>
        <label className="flex flex-col">
          {t("history.filters.disposition")}
          <select
            value={draftFilters.disposition ?? ""}
            onChange={(event) =>
              setDraftFilters({ ...draftFilters, disposition: event.target.value || undefined })
            }
            className={`${fieldClass} mt-1 w-52`}
            data-testid="filter-disposition"
          >
            <option value="">{t("history.filters.any")}</option>
            {DISPOSITIONS.map((code) => (
              <option key={code} value={code}>
                {dispositionLabel(code)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col">
          {t("history.filters.from")}
          <input
            type="date"
            value={draftFilters.from ?? ""}
            onChange={(event) =>
              setDraftFilters({ ...draftFilters, from: event.target.value || undefined })
            }
            className={`${fieldClass} mt-1`}
            data-testid="filter-from"
          />
        </label>
        <label className="flex flex-col">
          {t("history.filters.to")}
          <input
            type="date"
            value={draftFilters.to ?? ""}
            onChange={(event) =>
              setDraftFilters({ ...draftFilters, to: event.target.value || undefined })
            }
            className={`${fieldClass} mt-1`}
            data-testid="filter-to"
          />
        </label>
        <button type="submit" className={controlClass} data-testid="filter-apply">
          {t("history.filters.apply")}
        </button>
        {filtered ? (
          <button
            type="button"
            className={controlClass}
            onClick={() => {
              setDraftFilters({});
              onFilters({});
              announce(t("history.filters.cleared"));
            }}
            data-testid="filter-clear"
          >
            {t("history.filters.clear")}
          </button>
        ) : null}
      </form>

      <div className="mt-5" aria-busy={query.isFetching}>
        {query.isPending ? (
          <SectionSkeleton label={t("history.loading")} />
        ) : failure && rows.length === 0 ? (
          <div role="alert" data-testid="history-error">
            <p>{failure.message}</p>
            <button
              type="button"
              onClick={() => void query.refetch()}
              className={`${controlClass} mt-2`}
            >
              {t("app.retry")}
            </button>
          </div>
        ) : rows.length === 0 ? (
          <p data-testid="history-empty" className="cso-empty m-0">
            {filtered ? t("history.empty.filtered") : t("history.empty")}
          </p>
        ) : (
          <>
            <HistoryTimeline groups={groups} open={open} onToggle={toggle} />
            <div className="mt-4 flex flex-wrap items-center gap-3 text-sm">
              {failure ? (
                <span role="alert" data-testid="history-more-error">
                  {failure.message}
                </span>
              ) : null}
              {query.hasNextPage ? (
                <button
                  type="button"
                  disabled={query.isFetchingNextPage}
                  onClick={() => void query.fetchNextPage()}
                  className={controlClass}
                  data-testid="history-more"
                >
                  {query.isFetchingNextPage ? t("history.loadingMore") : t("history.loadMore")}
                </button>
              ) : (
                <span className="text-ink-2" data-testid="history-end">
                  {t("history.allLoaded", { count: rows.length })}
                </span>
              )}
            </div>
          </>
        )}
      </div>
    </section>
  );
}
