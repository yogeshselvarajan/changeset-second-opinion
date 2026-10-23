import type { Disposition, ListDecisionsData, DecisionRow } from "../../api/types.gen";

/** The filters of `/history`, as kept in the URL. */
export interface HistoryFilters {
  reviewer?: string;
  disposition?: string;
  from?: string;
  to?: string;
}

export const DISPOSITIONS: readonly Disposition[] = [
  "agree",
  "different_response",
  "needs_survey",
  "disagree_with_model",
  "no_action",
];

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

/** A date input value (`YYYY-MM-DD`) that is a real calendar date, else undefined. */
export function cleanDate(value: string | undefined): string | undefined {
  if (!value || !DATE_RE.test(value)) return undefined;
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isNaN(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== value
    ? undefined
    : value;
}

/** Drop anything the API would reject, so a hand-edited URL shows an unfiltered list, not an error. */
export function cleanFilters(filters: HistoryFilters): HistoryFilters {
  const reviewer = filters.reviewer?.trim().slice(0, 80);
  const disposition = DISPOSITIONS.find((d) => d === filters.disposition);
  return {
    reviewer: reviewer || undefined,
    disposition,
    from: cleanDate(filters.from),
    to: cleanDate(filters.to),
  };
}

/** The query of `GET /decisions`: dates become whole UTC days (the API wants aware datetimes). */
export function decisionQuery(filters: HistoryFilters): NonNullable<ListDecisionsData["query"]> {
  const clean = cleanFilters(filters);
  return {
    limit: 50,
    ...(clean.reviewer ? { reviewer: clean.reviewer } : {}),
    ...(clean.disposition ? { disposition: clean.disposition as Disposition } : {}),
    ...(clean.from ? { from: `${clean.from}T00:00:00Z` } : {}),
    ...(clean.to ? { to: `${clean.to}T23:59:59Z` } : {}),
  };
}

/** The CSV export link with the same filters (admin only; the browser downloads it itself). */
export function csvHref(filters: HistoryFilters): string {
  const query = decisionQuery(filters);
  const params = new URLSearchParams();
  for (const key of ["reviewer", "disposition", "from", "to"] as const) {
    const value = query[key];
    if (value) params.set(key, value);
  }
  const text = params.toString();
  return `/api/v1/decisions/export.csv${text ? `?${text}` : ""}`;
}

/** True when any filter narrows the list. */
export function isFiltered(filters: HistoryFilters): boolean {
  const clean = cleanFilters(filters);
  return Boolean(clean.reviewer || clean.disposition || clean.from || clean.to);
}

/** The UTC calendar day (`YYYY-MM-DD`) of a timestamp; the original text when it cannot be read. */
export function dayOf(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toISOString().slice(0, 10);
}

/** The UTC time of day (`HH:MM`) of a timestamp. */
export function timeOf(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "" : date.toISOString().slice(11, 16);
}

export interface DayGroup {
  day: string;
  rows: DecisionRow[];
}

/** Group rows (already newest first) into one block per UTC day, keeping their order. */
export function groupByDay(rows: readonly DecisionRow[]): DayGroup[] {
  const groups: DayGroup[] = [];
  for (const row of rows) {
    const day = dayOf(row.created_at);
    const last = groups[groups.length - 1];
    if (last && last.day === day) last.rows.push(row);
    else groups.push({ day, rows: [row] });
  }
  return groups;
}

/** The same row can arrive on two pages when something was recorded between them. */
export function uniqueDecisions(rows: readonly DecisionRow[]): DecisionRow[] {
  const seen = new Set<string>();
  const out: DecisionRow[] = [];
  for (const row of rows) {
    if (seen.has(row.outcome_id)) continue;
    seen.add(row.outcome_id);
    out.push(row);
  }
  return out;
}

/** A short form of a config version (`sha256:abcdef…`) for a table cell. */
export function shortVersion(version: string): string {
  const [scheme, hash] = version.includes(":") ? version.split(":", 2) : ["", version];
  return `${scheme ? `${scheme}:` : ""}${(hash ?? "").slice(0, 8)}`;
}
