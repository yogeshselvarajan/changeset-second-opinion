import { keepPreviousData, useInfiniteQuery, type InfiniteData } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { listCasesInfiniteOptions } from "../../api/@tanstack/react-query.gen";
import type { CaseListResponse, CaseSummary, Lane } from "../../api/types.gen";
import { t, type MessageKey } from "../../i18n";
import { isTypingTarget } from "../../lib/hotkeys";
import { failureFromResponse, networkFailure, type Failure } from "../../lib/problem";
import { saveQueueContext } from "../../lib/queueContext";
import { canMutate } from "../../lib/roles";
import { useMe } from "../../lib/useMe";
import { useCommandMenu } from "../command/CommandContext";
import { EvidenceStrip, SAMPLE_DIFFS } from "../evidence/EvidenceStrip";
import { useAnnounce } from "../shell/Announcer";
import { AddChangesetDialog } from "./AddChangesetDialog";
import { CaseList } from "./CaseList";
import { FilterBar } from "./FilterBar";
import { ImportDialog } from "./ImportDialog";
import { LaneTabs } from "./LaneTabs";
import { useTopBarOffset } from "./useTopBarOffset";
import { controlClass } from "./QueueDialog";
import {
  activeFilterCount,
  laneTotals,
  moveIndex,
  queueKeyAction,
  toListQuery,
  viewTotal,
  withFilters,
  type QueueSearch,
} from "./search";

const primaryClass =
  "min-h-8 rounded-[var(--radius-control)] bg-accent px-3 text-accent-fg disabled:opacity-60";

/** Rows still being analyzed are refreshed this often, and only while the tab is in use. */
const POLL_MS = 2000;
const ROW = '[role="row"][data-case-id]';

function hasAnalyzing(data: InfiniteData<CaseListResponse> | undefined): boolean {
  return (
    data?.pages.some((page) => page.items.some((item) => item.status === "analyzing")) ?? false
  );
}

/** A thrown query error (the problem body, or a network error) as a typed, human failure. */
function failureOf(error: unknown): Failure {
  if (typeof error === "object" && error !== null && "status" in error) {
    const status = Number((error as { status: unknown }).status);
    if (Number.isFinite(status) && status > 0) return failureFromResponse(status, error);
  }
  if (error instanceof TypeError) return networkFailure();
  return failureFromResponse(0, error);
}

function uniqueById(items: CaseSummary[]): CaseSummary[] {
  const seen = new Set<string>();
  return items.filter((item) => (seen.has(item.id) ? false : (seen.add(item.id), true)));
}

function Skeleton() {
  return (
    <div aria-busy="true" data-testid="queue-skeleton">
      <p role="status" className="sr-only">
        {t("queue.loading")}
      </p>
      {Array.from({ length: 8 }, (_, index) => (
        <div
          key={index}
          aria-hidden="true"
          style={{ minHeight: "var(--row-h)" }}
          className="border-b border-border bg-surface"
        />
      ))}
    </div>
  );
}

/**
 * The queue: lane tabs with counts, filters in the URL, keyboard-first rows, "Load more" paging,
 * and (for reviewers) add and import. Lanes only order and group the cases; every case stays
 * reachable, and every number shown comes straight from the API.
 */
export function QueueScreen({
  search,
  onSearch,
}: {
  search: QueueSearch;
  onSearch: (next: QueueSearch) => void;
}) {
  const { me } = useMe();
  const mayMutate = canMutate(me?.role);
  const announce = useAnnounce();
  const navigate = useNavigate();
  const { queueAction, clearQueueAction } = useCommandMenu();
  useTopBarOffset();
  const [dialog, setDialog] = useState<"add" | "import" | null>(null);
  const [marked, setMarked] = useState<ReadonlySet<string>>(new Set());
  const [now, setNow] = useState(() => Date.now());
  const searchRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const lastRow = useRef<string | null>(null);

  const query = useInfiniteQuery({
    ...listCasesInfiniteOptions({ query: toListQuery(search) }),
    // The generated client reads properties of the page parameter when it is an object, and
    // `typeof null` is "object": use an empty object, not null, for "no cursor yet".
    initialPageParam: search.cursor ?? {},
    getNextPageParam: (last: CaseListResponse) => last.next_cursor ?? undefined,
    placeholderData: keepPreviousData,
    refetchInterval: (state) => (hasAnalyzing(state.state.data) ? POLL_MS : false),
    retry: 1,
    retryDelay: 400,
  });

  const pages = useMemo(() => query.data?.pages ?? [], [query.data]);
  const items = useMemo(() => uniqueById(pages.flatMap((page) => page.items)), [pages]);
  const totals = pages[0] ? laneTotals(pages[0].counts_by_lane) : null;
  const total = totals ? viewTotal(search.lane, totals) : null;
  const filtered = activeFilterCount(search) > 0;

  // The case screen offers next and previous from this list, in the order shown here.
  useEffect(() => {
    if (query.data) saveQueueContext(items.map((item) => item.id));
  }, [query.data, items]);

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(timer);
  }, []);

  // Tell screen reader users what a lane or filter change produced, and when more rows arrive.
  const signature = JSON.stringify([
    search.lane,
    search.status,
    search.editor,
    search.q,
    search.stale,
  ]);
  const lastSignature = useRef<string | null>(null);
  const lastPageCount = useRef(0);
  useEffect(() => {
    if (!query.isSuccess || query.isPlaceholderData || total === null) return;
    if (lastSignature.current !== null && lastSignature.current !== signature) {
      const laneName = search.lane ? t(`lane.${search.lane}` as MessageKey) : t("queue.tab.all");
      announce(t("queue.announce.lane", { lane: laneName, count: total }));
    }
    lastSignature.current = signature;
  }, [query.isSuccess, query.isPlaceholderData, signature, total, search.lane, announce]);
  useEffect(() => {
    const count = pages.length;
    if (lastPageCount.current > 0 && count > lastPageCount.current) {
      const added = pages
        .slice(lastPageCount.current)
        .reduce((sum, page) => sum + page.items.length, 0);
      announce(t("queue.announce.loaded", { n: added }));
    }
    lastPageCount.current = count;
  }, [pages, announce]);

  // "Add changeset" and "Import" chosen in the command menu arrive as a request; the dialog on
  // screen is the one opened here, or else the one requested from the menu.
  const shownDialog = dialog ?? (mayMutate ? queueAction : null);
  const closeDialog = useCallback(() => {
    setDialog(null);
    clearQueueAction();
  }, [clearQueueAction]);

  const open = useCallback(
    (id: string) => void navigate({ to: "/cases/$id", params: { id } }),
    [navigate],
  );

  // Queue keys run in the capture phase so the list's own type-ahead never sees j, k, o or x.
  useEffect(() => {
    function rowElements(): HTMLElement[] {
      return Array.from(listRef.current?.querySelectorAll<HTMLElement>(ROW) ?? []);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (shownDialog !== null || event.ctrlKey || event.metaKey || event.altKey) return;
      if (isTypingTarget(event.target)) return;
      if (event.target instanceof Element && event.target.closest('[role="dialog"]')) return;
      const action = queueKeyAction(event.key);
      if (!action) return;
      const rows = rowElements();
      const current = rows.findIndex((row) => row === document.activeElement?.closest(ROW));
      const activeId = current >= 0 ? rows[current]?.getAttribute("data-case-id") : null;
      const consume = () => {
        event.preventDefault();
        event.stopPropagation();
      };
      switch (action.kind) {
        case "move": {
          const next = moveIndex(current >= 0 ? current : null, action.delta, rows.length);
          if (next !== null) {
            consume();
            rows[next]?.focus();
          }
          break;
        }
        case "open":
          if (activeId) {
            consume();
            open(activeId);
          }
          break;
        case "mark":
          if (activeId) {
            consume();
            const next = new Set(marked);
            if (next.has(activeId)) next.delete(activeId);
            else next.add(activeId);
            setMarked(next);
            announce(t("queue.announce.marked", { n: next.size }));
          }
          break;
        case "search":
          consume();
          searchRef.current?.focus();
          break;
        case "clearMarks":
          if (marked.size > 0) {
            consume();
            setMarked(new Set());
            announce(t("queue.announce.cleared"));
          }
          break;
        case "lane":
          consume();
          onSearch(withFilters(search, { lane: action.lane }));
          break;
      }
    }
    window.addEventListener("keydown", onKeyDown, true);
    return () => window.removeEventListener("keydown", onKeyDown, true);
  }, [shownDialog, marked, search, onSearch, open, announce]);

  function announceFocusedRow(target: EventTarget) {
    const row = target instanceof Element ? target.closest(ROW) : null;
    const id = row?.getAttribute("data-case-id") ?? null;
    if (!id || id === lastRow.current) return;
    lastRow.current = id;
    const position = items.findIndex((item) => item.id === id) + 1;
    if (position > 0) {
      announce(t("queue.announce.selected", { position, total: total ?? items.length }));
    }
  }

  const patch = useCallback(
    (next: Partial<QueueSearch>) => onSearch(withFilters(search, next)),
    [search, onSearch],
  );

  const failure = query.isError ? failureOf(query.error) : null;
  const moreFailed = query.isFetchNextPageError;

  let body;
  if (query.isPending) {
    body = <Skeleton />;
  } else if (query.isError && !query.data) {
    body = (
      <div role="alert" className="px-4 py-6" data-testid="queue-error">
        <p className="font-semibold">{t("queue.error.title")}</p>
        <p className="text-text-muted">{failure?.message}</p>
        {failure?.kind === "unauthorized" ? (
          <Link
            to="/login"
            search={{ redirect: "/queue" }}
            className={`${controlClass} mt-3 inline-flex items-center`}
          >
            {t("nav.signIn")}
          </Link>
        ) : null}
        <button
          type="button"
          onClick={() => void query.refetch()}
          className={`${controlClass} mt-3`}
        >
          {t("app.retry")}
        </button>
      </div>
    );
  } else if (items.length === 0) {
    const key: MessageKey = filtered
      ? "queue.empty.filtered"
      : search.lane
        ? "queue.empty.lane"
        : "queue.empty.none";
    body = (
      <div className="flex flex-col items-start gap-3 px-4 py-6" data-testid="queue-empty">
        {filtered || search.lane ? null : (
          <div className="w-full max-w-md">
            <EvidenceStrip diffs={SAMPLE_DIFFS} muted label={t("evidence.stripSample")} />
          </div>
        )}
        <p>{t(key)}</p>
        {!filtered && !search.lane && mayMutate ? (
          <button type="button" onClick={() => setDialog("add")} className={primaryClass}>
            {t("queue.empty.action")}
          </button>
        ) : null}
        {filtered ? (
          <button
            type="button"
            onClick={() =>
              patch({ status: undefined, editor: undefined, q: undefined, stale: undefined })
            }
            className={`${controlClass} mt-3`}
          >
            {t("queue.filter.clear")}
          </button>
        ) : null}
      </div>
    );
  } else {
    body = (
      <>
        {query.isError && !moreFailed ? (
          <div
            role="alert"
            className="border-b border-border px-4 py-3"
            data-testid="queue-stale-error"
          >
            <p>
              {t("queue.error.title")} {t("queue.error.keepsData")}
            </p>
            <button
              type="button"
              onClick={() => void query.refetch()}
              className={`${controlClass} mt-2`}
            >
              {t("app.retry")}
            </button>
          </div>
        ) : null}
        <div ref={listRef} onFocus={(event) => announceFocusedRow(event.target)}>
          <CaseList
            items={items}
            now={now}
            marked={marked}
            onMarkedChange={setMarked}
            onOpen={open}
          />
        </div>
        <div className="flex flex-wrap items-center gap-3 px-4 py-3">
          <span data-testid="queue-summary">
            {t("queue.summary", { shown: items.length, total: total ?? items.length })}
          </span>
          {moreFailed ? (
            <span role="alert" data-testid="queue-more-error">
              {t("queue.error.more")}
            </span>
          ) : null}
          {query.hasNextPage ? (
            <button
              type="button"
              disabled={query.isFetchingNextPage}
              onClick={() => void query.fetchNextPage()}
              className={controlClass}
            >
              {query.isFetchingNextPage
                ? t("queue.loadingMore")
                : moreFailed
                  ? t("app.retry")
                  : t("queue.loadMore")}
            </button>
          ) : (
            <span className="text-text-muted">{t("queue.allLoaded")}</span>
          )}
        </div>
      </>
    );
  }

  return (
    <section aria-labelledby="queue-title" className="cso-page cso-page-wide">
      <div className="cso-pagehead flex flex-wrap items-center gap-3">
        <div>
          <h1 id="queue-title" className="text-xl font-semibold">
            {t("queue.title")}
          </h1>
          <p className="m-0 mt-1 text-sm text-ink-2">{t("queue.subtitle")}</p>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <button
            type="button"
            disabled={!mayMutate}
            aria-describedby={mayMutate ? undefined : "queue-mutate-hint"}
            onClick={() => setDialog("add")}
            className={controlClass}
          >
            {t("queue.add.button")}
          </button>
          <button
            type="button"
            disabled={!mayMutate}
            aria-describedby={mayMutate ? undefined : "queue-mutate-hint"}
            onClick={() => setDialog("import")}
            className={controlClass}
          >
            {t("queue.import.button")}
          </button>
        </div>
      </div>
      {mayMutate ? null : (
        <p id="queue-mutate-hint" className="pt-2 text-text-muted">
          {t("queue.add.viewerHint")}
        </p>
      )}

      <div className="mt-3">
        <LaneTabs
          lane={search.lane}
          totals={totals}
          onLane={(lane: Lane | undefined) => patch({ lane })}
        >
          <div className="cso-card cso-listcard mt-3 overflow-hidden p-0">
            <FilterBar search={search} onChange={patch} searchRef={searchRef} />
            <div aria-busy={query.isFetching && !query.isFetchingNextPage}>{body}</div>
          </div>
        </LaneTabs>
      </div>

      <p className="pt-3 pb-6 text-text-muted" data-testid="queue-key-hint">
        {t("queue.keys.hint")}
      </p>

      {shownDialog === "add" ? <AddChangesetDialog onClose={closeDialog} /> : null}
      {shownDialog === "import" ? <ImportDialog onClose={closeDialog} /> : null}
    </section>
  );
}
