import type { Band, CaseStatus, CaseSummary, Lane, ListCasesData } from "../../api/types.gen";
import { t, type MessageKey } from "../../i18n";
import { LANES } from "../../lib/lanes";

/** Filters that live in the URL, so a view can be shared and the back button works. */
export interface QueueSearch {
  lane?: Lane;
  status?: CaseStatus;
  editor?: string;
  q?: string;
  stale?: boolean;
  /** Where the first page starts; "Load more" appends further pages after it. */
  cursor?: string;
}

export const PAGE_SIZE = 50;
const MAX_TEXT = 200;
const MAX_CURSOR = 600;

const LANE_VALUES: readonly string[] = LANES.map((meta) => meta.lane);
const STATUS_VALUES: readonly string[] = ["new", "analyzing", "analyzed", "decided"];
export const STATUSES = STATUS_VALUES as readonly CaseStatus[];

function text(value: unknown, max = MAX_TEXT): string | undefined {
  if (typeof value !== "string") return undefined;
  const trimmed = value.trim();
  return trimmed === "" ? undefined : trimmed.slice(0, max);
}

/** Validate untrusted URL search params: unknown or malformed values are dropped, never passed on. */
export function parseSearch(search: Record<string, unknown>): QueueSearch {
  const lane = text(search.lane);
  const status = text(search.status);
  const stale = search.stale === true || search.stale === "true";
  return {
    lane: lane !== undefined && LANE_VALUES.includes(lane) ? (lane as Lane) : undefined,
    status:
      status !== undefined && STATUS_VALUES.includes(status) ? (status as CaseStatus) : undefined,
    editor: text(search.editor),
    q: text(search.q),
    stale: stale ? true : undefined,
    cursor: text(search.cursor, MAX_CURSOR),
  };
}

/** The `GET /cases` query for these filters. The cursor is the page parameter, not a filter. */
export function toListQuery(
  search: QueueSearch,
  limit = PAGE_SIZE,
): NonNullable<ListCasesData["query"]> {
  const query: NonNullable<ListCasesData["query"]> = { limit };
  if (search.lane) query.lane = search.lane;
  if (search.status) query.status = search.status;
  if (search.editor) query.editor = search.editor;
  if (search.q) query.q = search.q;
  if (search.stale) query.stale = true;
  return query;
}

/** Change filters; any change returns to the first page. */
export function withFilters(search: QueueSearch, patch: Partial<QueueSearch>): QueueSearch {
  return { ...search, ...patch, cursor: undefined };
}

/** Number of narrowing filters other than the lane (status, editor, text, stale). */
export function activeFilterCount(search: QueueSearch): number {
  return [search.status, search.editor, search.q, search.stale].filter(Boolean).length;
}

export interface LaneCount {
  lane: Lane;
  count: number;
}

export interface LaneTotals {
  entries: LaneCount[];
  total: number;
}

/** Every lane in queue order with its count (missing means 0); `total` is their sum. */
export function laneTotals(counts: Partial<Record<Lane, number>> | undefined): LaneTotals {
  const entries = LANES.map((meta) => ({ lane: meta.lane, count: counts?.[meta.lane] ?? 0 }));
  return { entries, total: entries.reduce((sum, entry) => sum + entry.count, 0) };
}

/** How many cases the current view holds: the selected lane's count, or all lanes together. */
export function viewTotal(lane: Lane | undefined, totals: LaneTotals): number {
  if (!lane) return totals.total;
  return totals.entries.find((entry) => entry.lane === lane)?.count ?? 0;
}

/** Number keys: `1` to `5` pick a lane in queue order, `0` shows every lane. */
export function laneForKey(key: string): { lane: Lane | undefined } | null {
  if (key === "0") return { lane: undefined };
  if (!/^[1-5]$/.test(key)) return null;
  const meta = LANES[Number(key) - 1];
  return meta ? { lane: meta.lane } : null;
}

/** The queue's own keys. Quiet while typing and for any modifier is decided by the caller. */
export type QueueKeyAction =
  | { kind: "move"; delta: 1 | -1 }
  | { kind: "open" }
  | { kind: "mark" }
  | { kind: "search" }
  | { kind: "clearMarks" }
  | { kind: "lane"; lane: Lane | undefined };

export function queueKeyAction(key: string): QueueKeyAction | null {
  switch (key) {
    case "j":
      return { kind: "move", delta: 1 };
    case "k":
      return { kind: "move", delta: -1 };
    case "o":
      return { kind: "open" };
    case "x":
      return { kind: "mark" };
    case "/":
      return { kind: "search" };
    case "Escape":
      return { kind: "clearMarks" };
    default: {
      const lane = laneForKey(key);
      return lane ? { kind: "lane", lane: lane.lane } : null;
    }
  }
}

/** Next row index for j and k: starts at the first row, never leaves the list. */
export function moveIndex(current: number | null, delta: 1 | -1, length: number): number | null {
  if (length <= 0) return null;
  if (current === null || current < 0) return 0;
  return Math.min(length - 1, Math.max(0, current + delta));
}

// --- row text -----------------------------------------------------------------------------

export interface Age {
  short: string;
  long: string;
}

/** How long ago a case was created, short for the row and long for the accessible name. */
export function formatAge(iso: string, nowMs: number): Age {
  const created = Date.parse(iso);
  if (!Number.isFinite(created)) return { short: "", long: "" };
  const minutes = Math.max(0, Math.floor((nowMs - created) / 60_000));
  if (minutes < 1) return { short: t("queue.age.now"), long: t("queue.age.long.now") };
  if (minutes < 60) {
    return {
      short: t("queue.age.minutes", { n: minutes }),
      long: t("queue.age.long.minutes", { n: minutes }),
    };
  }
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    return {
      short: t("queue.age.hours", { n: hours }),
      long: t("queue.age.long.hours", { n: hours }),
    };
  }
  const days = Math.floor(hours / 24);
  return {
    short: t("queue.age.days", { n: days }),
    long: t("queue.age.long.days", { n: days }),
  };
}

export function bandText(band: Band | null | undefined): string {
  return band ? t(`queue.band.${band}` as MessageKey) : t("queue.band.none");
}

export function statusText(status: CaseStatus): string {
  return t(`queue.status.${status}` as MessageKey);
}

export function outcomeText(outcome: NonNullable<CaseSummary["latest_outcome"]>): string {
  return t(`queue.outcome.${outcome}` as MessageKey);
}

/** "+12 ~4 −0": created, modified, deleted. The accessible form spells the words out. */
export function countsGlyphs(counts: CaseSummary["element_counts"]): string {
  return `+${counts.create ?? 0} ~${counts.modify ?? 0} −${counts.delete ?? 0}`;
}

export function countsText(counts: CaseSummary["element_counts"]): string {
  return t("queue.row.counts", {
    create: counts.create ?? 0,
    modify: counts.modify ?? 0,
    delete: counts.delete ?? 0,
  });
}

/** The row's accessible name: lane, changeset, editor, place, counts, band, status, outcome, age. */
export function rowLabel(item: CaseSummary, nowMs: number): string {
  const body = t("queue.row.label", {
    id: item.changeset_id,
    editor: item.editor ? t("queue.row.editor", { name: item.editor }) : t("queue.editor.unknown"),
    place: item.place_label
      ? t("queue.row.place", { name: item.place_label })
      : t("queue.place.unknown"),
    counts: countsText(item.element_counts),
    band: bandText(item.band),
    status: statusText(item.status),
    age: formatAge(item.created_at, nowMs).long,
  });
  const extras: string[] = [];
  if (item.stale) extras.push(t("queue.row.stale"));
  if (item.latest_outcome) {
    extras.push(t("queue.row.outcome", { outcome: outcomeText(item.latest_outcome) }));
  }
  if (item.flags && item.flags.length > 0) {
    extras.push(t("queue.row.flags", { flags: item.flags.join(", ") }));
  }
  return [t(`lane.${item.lane}` as MessageKey), body, ...extras].join(", ");
}

// --- the "Add changeset" field ------------------------------------------------------------

const MAX_ID = 9_999_999_999_999;

/**
 * Read a changeset number from what a person typed or pasted: `167234981`, `#167234981` or a link
 * ending in `/changeset/167234981`. The text is only scanned for digits; no link is ever opened.
 */
export function parseChangesetInput(input: string): number | null {
  const value = input.trim();
  const match = /^#?(\d{1,13})$/.exec(value) ?? /\/changeset\/(\d{1,13})(?:[/?#]|$)/.exec(value);
  if (!match?.[1]) return null;
  const id = Number(match[1]);
  return id >= 1 && id <= MAX_ID ? id : null;
}

/** The problem code (`urn:cso:problem:<code>`, or a `code` member) from a problem+json body. */
export function problemCode(body: unknown): string | null {
  if (typeof body !== "object" || body === null) return null;
  const record = body as Record<string, unknown>;
  if (typeof record.code === "string") return record.code;
  const prefix = "urn:cso:problem:";
  if (typeof record.type === "string" && record.type.startsWith(prefix)) {
    return record.type.slice(prefix.length) || null;
  }
  return null;
}
