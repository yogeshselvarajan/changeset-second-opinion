import type {
  Band,
  CaseDetail,
  ChangedElement,
  ChangeAction,
  CoverageGapReason,
  EvidenceSnapshot,
  HistoryGap,
  OsmType,
  Response,
  Severity,
  TagChange,
  TagDiff,
  Tri,
  UserSummary,
} from "../../api/types.gen";
import { t, type MessageKey } from "../../i18n";

/*
 * Pure helpers for the case screen. Nothing here decides anything: bands, lanes, diffs and coverage
 * come from the API and are only grouped, labelled and formatted for display.
 */

/** Response types that a person can answer with a comment, which is when a draft makes sense. */
export const COMMENT_RESPONSES: ReadonlySet<Response> = new Set<Response>([
  "welcome_and_tips",
  "ask_source_question",
  "request_local_check",
]);

export function isCommentResponse(response: Response | null | undefined): boolean {
  return response !== null && response !== undefined && COMMENT_RESPONSES.has(response);
}

/**
 * Response types a draft can be requested for. The server decides: `allowed_responses` is the
 * rule `POST /cases/{id}/drafts` applies (empty with no analysis, a failed one, or a stale case).
 * Payloads without that field fall back to the run's own response when the run succeeded and the
 * response is a comment type, which is the same answer for a current case.
 */
export function draftResponses(
  detail: Pick<CaseDetail, "allowed_responses" | "response" | "latest_run"> | undefined,
): Response[] {
  if (!detail) return [];
  if (detail.allowed_responses !== undefined) return detail.allowed_responses;
  const response = detail.response;
  if (detail.latest_run?.status !== "succeeded" || !response) return [];
  return isCommentResponse(response) ? [response] : [];
}

// ---------------------------------------------------------------------------------------- bands

export interface BandMeta {
  glyph: string;
  label: MessageKey;
}

const BANDS: Record<Band, BandMeta> = {
  confident: { glyph: "●", label: "confidence.band.confident" },
  unsure: { glyph: "◐", label: "confidence.band.unsure" },
  cannot_tell: { glyph: "○", label: "confidence.band.cannot_tell" },
};

export function bandMeta(band: Band): BandMeta {
  return BANDS[band];
}

// -------------------------------------------------------------------------------------- numbers

/** A probability as a plain two-decimal number. Never a percentage, never a headline. */
export function formatProbability(value: number): string {
  if (!Number.isFinite(value)) return "n/a";
  return value.toFixed(2);
}

/** Clamp to 0..1 for a bar width; the number shown next to the bar is not clamped. */
export function barFraction(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.min(1, Math.max(0, value));
}

// ---------------------------------------------------------------------------------------- text

/** `possible_deliberate_damage` becomes "Possible deliberate damage" when no label is known. */
export function humanize(code: string): string {
  const spaced = code.replace(/_/g, " ").trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/** UTC date and time for evidence timestamps; an unparseable value is shown as given. */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return t("case.unknown");
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return `${date.toISOString().slice(0, 16).replace("T", " ")} UTC`;
}

// ------------------------------------------------------------------------------------------ ages

export type AgeBucket = "recent" | "year" | "older" | "unknown";

/** Display-only grouping that mirrors the evidence text: up to 30 days, 31 to 365, over 365. */
export function ageBucket(days: number | null | undefined): AgeBucket {
  if (days === null || days === undefined || !Number.isFinite(days) || days < 0) return "unknown";
  if (days <= 30) return "recent";
  if (days <= 365) return "year";
  return "older";
}

export const AGE_BUCKET_LABEL: Record<AgeBucket, MessageKey> = {
  recent: "case.age.bucket.recent",
  year: "case.age.bucket.year",
  older: "case.age.bucket.older",
  unknown: "case.age.bucket.unknown",
};

export function formatAge(days: number | null | undefined): string {
  if (days === null || days === undefined || !Number.isFinite(days) || days < 0) {
    return t("case.age.unknown");
  }
  if (days < 365) return t("case.age.days", { n: Math.round(days) });
  const years = Math.floor(days / 365);
  const months = Math.floor((days % 365) / 30);
  return months === 0
    ? t("case.age.years", { y: years })
    : t("case.age.yearsMonths", { y: years, m: months });
}

export interface DeletionAges {
  total: number;
  buckets: Record<AgeBucket, number>;
}

/** Count the deleted elements of a snapshot into the four age buckets. */
export function deletionAges(elements: readonly ChangedElement[] | undefined): DeletionAges {
  const buckets: Record<AgeBucket, number> = { recent: 0, year: 0, older: 0, unknown: 0 };
  let total = 0;
  for (const element of elements ?? []) {
    if (element.action !== "delete") continue;
    total += 1;
    buckets[ageBucket(element.age_days)] += 1;
  }
  return { total, buckets };
}

// --------------------------------------------------------------------------------- tag diffs

export interface DiffGroup {
  key: string;
  osm_type: OsmType;
  osm_id: number;
  rows: TagDiff[];
}

/** Group the API's tag diffs by element, keeping the order the API gave. */
export function groupTagDiffs(diffs: readonly TagDiff[] | undefined): DiffGroup[] {
  const groups = new Map<string, DiffGroup>();
  for (const diff of diffs ?? []) {
    const key = elementKey(diff.osm_type, diff.osm_id);
    let group = groups.get(key);
    if (!group) {
      group = { key, osm_type: diff.osm_type, osm_id: diff.osm_id, rows: [] };
      groups.set(key, group);
    }
    group.rows.push(diff);
  }
  return [...groups.values()];
}

export interface DiffMeta {
  /** Text prefix so the state never depends on colour alone. */
  prefix: string;
  label: MessageKey;
  tone: "added" | "removed" | "changed";
}

const DIFFS: Record<TagChange, DiffMeta> = {
  added: { prefix: "+", label: "case.diff.added", tone: "added" },
  removed: { prefix: "−", label: "case.diff.removed", tone: "removed" },
  changed: { prefix: "~", label: "case.diff.changed", tone: "changed" },
};

export function diffMeta(change: TagChange): DiffMeta {
  return DIFFS[change];
}

export function elementKey(type: OsmType, id: number): string {
  return `${type}/${id}`;
}

// ---------------------------------------------------------------------------- evidence ids (E3)

/**
 * The evidence ids ("E3") the model and the drafts cite, read from the server's own rendered text.
 * Each line of that text starts `E<n> <type>/<id> ...`. The screen only looks the id up; it never
 * ranks elements itself.
 */
export function parseEvidenceIds(renderedText: string | undefined): Map<string, string> {
  const found = new Map<string, string>();
  if (!renderedText) return found;
  for (const match of renderedText.matchAll(/^E(\d+) (node|way|relation)\/(\d+)\b/gm)) {
    const [, n, type, id] = match;
    if (n && type && id) found.set(`${type}/${id}`, `E${n}`);
  }
  return found;
}

/**
 * Evidence ids ("E3") by `type/id`, as the server names them: each element's `evidence_id`. A null
 * id means the evidence text does not show that element, so it gets no label. Only a payload with
 * no `evidence_id` fields at all falls back to reading the ids out of the rendered text.
 */
export function evidenceIdLabels(
  evidence: Pick<EvidenceSnapshot, "elements" | "rendered_text"> | undefined,
): Map<string, string> {
  const found = new Map<string, string>();
  if (!evidence) return found;
  let hasField = false;
  for (const element of evidence.elements ?? []) {
    if (element.evidence_id !== undefined) hasField = true;
    if (element.evidence_id)
      found.set(`${element.osm_type}/${element.osm_id}`, element.evidence_id);
  }
  return hasField ? found : parseEvidenceIds(evidence.rendered_text);
}

// ------------------------------------------------------------------------------------ actions

export const ACTION_LABEL: Record<ChangeAction, MessageKey> = {
  create: "case.action.create",
  modify: "case.action.modify",
  delete: "case.action.delete",
};

export const ACTION_GLYPH: Record<ChangeAction, string> = {
  create: "+",
  modify: "~",
  delete: "−",
};

// -------------------------------------------------------------------------------------- rules

export interface SeverityMeta {
  glyph: string;
  label: MessageKey;
}

const SEVERITIES: Record<Severity, SeverityMeta> = {
  info: { glyph: "i", label: "case.severity.info" },
  warn: { glyph: "!", label: "case.severity.warn" },
  block: { glyph: "×", label: "case.severity.block" },
};

export function severityMeta(severity: Severity): SeverityMeta {
  return SEVERITIES[severity];
}

const RULE_KEYS: Record<string, MessageKey> = {
  R1: "case.rule.R1",
  R2: "case.rule.R2",
  R3: "case.rule.R3",
  R4: "case.rule.R4",
  R5: "case.rule.R5",
  R6: "case.rule.R6",
};

/** The plain-language explanation for a rule code, or undefined for a code we have no text for. */
export function ruleExplanation(code: string): string | undefined {
  const key = RULE_KEYS[code];
  return key ? t(key) : undefined;
}

/** `triggered_by` as label and value text pairs, in the order given; values are shown as text. */
export function describeTrigger(
  triggeredBy: Record<string, unknown> | undefined,
): { name: string; value: string }[] {
  if (!triggeredBy) return [];
  return Object.entries(triggeredBy).map(([name, value]) => ({
    name,
    value: typeof value === "string" ? value : JSON.stringify(value),
  }));
}

// ------------------------------------------------------------------------------ fact panel

export const TRI_LABEL: Record<Tri, MessageKey> = {
  no: "case.reading.no",
  unknown: "case.reading.unknown",
  yes: "case.reading.yes",
};

export const TRI_GLYPH: Record<Tri, string> = { no: "−", unknown: "?", yes: "+" };

export const USE_LABEL: Record<"composed" | "cross_check_only" | "advisory", MessageKey> = {
  composed: "case.panel.use.composed",
  cross_check_only: "case.panel.use.cross_check_only",
  advisory: "case.panel.use.advisory",
};

export const CROSS_CHECK_LABEL: Record<string, MessageKey> = {
  agree: "case.crossCheck.agree",
  disagree: "case.crossCheck.disagree",
  undecided: "case.crossCheck.undecided",
  "n/a": "case.crossCheck.na",
};

export const CROSS_CHECK_GLYPH: Record<string, string> = {
  agree: "=",
  disagree: "≠",
  undecided: "?",
  "n/a": "-",
};

const COMPOSITION_KEYS: Record<string, MessageKey> = {
  P1: "case.composition.P1",
  P2: "case.composition.P2",
  P3: "case.composition.P3",
  P4: "case.composition.P4",
  P5: "case.composition.P5",
  P6: "case.composition.P6",
  N1: "case.composition.N1",
  N2: "case.composition.N2",
  N3: "case.composition.N3",
  N4: "case.composition.N4",
  N5: "case.composition.N5",
};

/** Text for a composition row id ("P4", "N3"); an unknown id is shown as the id itself. */
export function compositionText(row: string): string {
  const key = COMPOSITION_KEYS[row];
  return key ? t(key) : row;
}

// ------------------------------------------------------------------------------------ coverage

export const GAP_REASON_LABEL: Record<CoverageGapReason, MessageKey> = {
  redacted: "case.gap.redacted",
  not_found: "case.gap.not_found",
  timeout: "case.gap.timeout",
  budget: "case.gap.budget",
};

export function gapCounts(gaps: readonly HistoryGap[] | undefined): Map<CoverageGapReason, number> {
  const counts = new Map<CoverageGapReason, number>();
  for (const gap of gaps ?? []) counts.set(gap.reason, (counts.get(gap.reason) ?? 0) + 1);
  return counts;
}

// -------------------------------------------------------------------------------------- user

/** The changeset count with an honest label for which count it is. */
export function changesetCountText(user: UserSummary | null | undefined): string {
  const n = user?.changesets_count;
  if (n === null || n === undefined) return t("case.user.changesetsUnknown");
  switch (user?.changesets_count_basis) {
    case "edit_time":
      return t("case.user.changesetsAtEdit", { n });
    case "current":
      return t("case.user.changesetsNow", { n });
    default:
      return t("case.user.changesetsUnspecified", { n });
  }
}

// ---------------------------------------------------------------------------------------- place

/** "west, south → east, north", four decimals, from the API's bbox. */
export function bboxText(bbox: readonly number[] | null | undefined): string | null {
  if (!bbox || bbox.length !== 4 || bbox.some((value) => !Number.isFinite(value))) return null;
  const [w, s, e, n] = bbox.map((value) => (value as number).toFixed(4));
  return `${w}, ${s} → ${e}, ${n}`;
}

/** The changeset's own page on osm.org, built from the numeric id only (never from evidence). */
export function osmChangesetUrl(changesetId: number): string | null {
  if (!Number.isSafeInteger(changesetId) || changesetId < 0) return null;
  return `https://www.openstreetmap.org/changeset/${changesetId}`;
}

// ------------------------------------------------------------------------- untrusted text

const HIDDEN_CHARACTERS =
  // eslint-disable-next-line no-control-regex -- finding control characters is the point
  /[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F-\u009F\u200B-\u200F\u202A-\u202E\u2066-\u2069\uFEFF]/g;

/**
 * Evidence text is data. Characters that draw nothing (controls, zero-width marks, bidirectional
 * overrides) are replaced by a visible placeholder, so a reviewer sees that something was there
 * and text cannot silently reorder what is shown around it.
 */
export function showControls(value: string): string {
  return value.replace(HIDDEN_CHARACTERS, "\uFFFD");
}
