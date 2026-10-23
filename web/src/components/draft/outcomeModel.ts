import { putOutcome } from "../../api/sdk.gen";
import type {
  CaseDetail,
  Disposition,
  HumanOutcome,
  OutcomeInput,
  Response,
} from "../../api/types.gen";
import { failureFromResponse, networkFailure, type Failure } from "../../lib/problem";

/** The reasons a reviewer can give for not using a draft. */
export const REJECT_REASONS = ["off_tone", "wrong_facts", "not_needed"] as const;
export type RejectReason = (typeof REJECT_REASONS)[number];

/** `If-Match` value for the outcome version the reviewer last saw: `W/"<version>"`. */
export function ifMatchHeader(version: number | null | undefined): string {
  return `W/"${Math.max(0, Math.trunc(version ?? 0))}"`;
}

/**
 * The disposition for approving a draft. Using a draft of the recommended kind agrees with the
 * recommendation (edited or not); using another allowed kind is a different response.
 */
export function approveDisposition(
  chosen: Response,
  recommended: Response | null | undefined,
): Disposition {
  return recommended != null && chosen === recommended ? "agree" : "different_response";
}

/** The disposition for rejecting a draft: no comment needed is "no action", otherwise a different response. */
export function rejectDisposition(reason: RejectReason): Disposition {
  return reason === "not_needed" ? "no_action" : "different_response";
}

/** What a 412 tells the reviewer: the decision someone else recorded first. */
export interface Conflict {
  currentVersion: number | null;
  outcome: Pick<
    HumanOutcome,
    "disposition" | "reviewer_display" | "created_at" | "note" | "reason_code"
  > | null;
}

function text(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

/** Read the live record out of a 412 problem body (`current` extension member), tolerating gaps. */
export function parseConflict(body: unknown): Conflict | null {
  if (typeof body !== "object" || body === null) return null;
  const current = (body as { current?: unknown }).current;
  if (typeof current !== "object" || current === null) return null;
  const record = current as { outcome_version?: unknown; outcome?: unknown };
  const outcome = record.outcome;
  let parsed: Conflict["outcome"] = null;
  if (typeof outcome === "object" && outcome !== null) {
    const o = outcome as Record<string, unknown>;
    const disposition = text(o.disposition);
    if (disposition) {
      parsed = {
        disposition: disposition as Disposition,
        reviewer_display: text(o.reviewer_display) ?? "",
        created_at: text(o.created_at) ?? "",
        note: text(o.note),
        reason_code: text(o.reason_code),
      };
    }
  }
  return {
    currentVersion: typeof record.outcome_version === "number" ? record.outcome_version : null,
    outcome: parsed,
  };
}

export type SubmitResult =
  | { kind: "ok"; detail: CaseDetail }
  | { kind: "conflict"; conflict: Conflict | null; failure: Failure }
  | { kind: "failed"; failure: Failure; code: string | null };

function problemCode(body: unknown): string | null {
  if (typeof body !== "object" || body === null) return null;
  const type = (body as { type?: unknown }).type;
  const prefix = "urn:cso:problem:";
  return typeof type === "string" && type.startsWith(prefix) ? type.slice(prefix.length) : null;
}

/**
 * Append an outcome. `If-Match` is always sent. A 412 returns the other decision and does not
 * retry: the reviewer looks at it and chooses (the record is append-only, nothing is overwritten).
 */
export async function submitOutcome(args: {
  caseId: string;
  version: number | null | undefined;
  input: OutcomeInput;
}): Promise<SubmitResult> {
  try {
    const result = await putOutcome({
      path: { id: args.caseId },
      body: args.input,
      headers: { "if-match": ifMatchHeader(args.version) },
      throwOnError: false,
    });
    const response = result.response;
    if (!response) return { kind: "failed", failure: networkFailure(), code: null };
    if (result.error === undefined && response.ok && result.data !== undefined) {
      return { kind: "ok", detail: result.data };
    }
    const failure = failureFromResponse(
      response.status,
      result.error,
      response.headers.get("Retry-After"),
    );
    if (response.status === 412) {
      return { kind: "conflict", conflict: parseConflict(result.error), failure };
    }
    return { kind: "failed", failure, code: problemCode(result.error) };
  } catch {
    return { kind: "failed", failure: networkFailure(), code: null };
  }
}

/**
 * The version "keep mine" should send after a 412. The other decision's version comes with the 412
 * when the server included it; when it did not, resending the stale version would only 412 again, so
 * ask for the case afresh. `null` means the latest version could not be established: do not resend.
 */
export async function versionForKeepMine(
  conflict: Conflict | null | undefined,
  fetchLatest: () => Promise<number | null | undefined>,
): Promise<{ version: number } | null> {
  if (typeof conflict?.currentVersion === "number") return { version: conflict.currentVersion };
  try {
    const latest = await fetchLatest();
    return typeof latest === "number" ? { version: latest } : null;
  } catch {
    return null;
  }
}
