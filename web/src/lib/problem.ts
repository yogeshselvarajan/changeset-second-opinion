import { t } from "../i18n";

/** The parts of an `application/problem+json` body the UI looks at. */
export interface ProblemBody {
  title?: string;
  detail?: string | null;
  status?: number;
  request_id?: string;
  [key: string]: unknown;
}

export type FailureKind =
  | "unauthorized"
  | "forbidden"
  | "not_found"
  | "conflict"
  | "invalid"
  | "rate_limited"
  | "server"
  | "network"
  | "unknown";

export interface Failure {
  kind: FailureKind;
  status: number | null;
  /** Human message from the catalogue; never the raw server text. */
  message: string;
  /** Seconds to wait, when the server sent `Retry-After`. */
  retryAfterSeconds: number | null;
  /** Server request id, handy in a support message. */
  requestId: string | null;
}

/** Seconds from a `Retry-After` header (delta-seconds form only); null when absent or odd. */
export function parseRetryAfter(value: string | null | undefined): number | null {
  if (!value) return null;
  const seconds = Number(value.trim());
  if (!Number.isFinite(seconds) || seconds < 0) return null;
  return Math.ceil(seconds);
}

function kindFor(status: number): FailureKind {
  if (status === 401) return "unauthorized";
  if (status === 403) return "forbidden";
  if (status === 404) return "not_found";
  if (status === 409 || status === 412 || status === 428) return "conflict";
  if (status === 400 || status === 422) return "invalid";
  if (status === 429) return "rate_limited";
  if (status >= 500) return "server";
  return "unknown";
}

function messageFor(kind: FailureKind, retryAfter: number | null): string {
  switch (kind) {
    case "unauthorized":
      return t("api.error.unauthorized");
    case "forbidden":
      return t("api.error.forbidden");
    case "not_found":
      return t("api.error.notFound");
    case "conflict":
      return t("api.error.conflict");
    case "rate_limited":
      return retryAfter === null
        ? t("api.error.rateLimitedNoWait")
        : t("api.error.rateLimited", { seconds: retryAfter });
    case "server":
      return t("api.error.server");
    case "network":
      return t("api.error.network");
    default:
      return t("api.error.generic");
  }
}

/** Map an HTTP failure (status, problem+json body, Retry-After) to a typed, human failure. */
export function failureFromResponse(
  status: number,
  body: unknown,
  retryAfterHeader?: string | null,
): Failure {
  const kind = kindFor(status);
  const retryAfter = parseRetryAfter(retryAfterHeader);
  const problem = (typeof body === "object" && body !== null ? body : {}) as ProblemBody;
  return {
    kind,
    status,
    message: messageFor(kind, retryAfter),
    retryAfterSeconds: retryAfter,
    requestId: typeof problem.request_id === "string" ? problem.request_id : null,
  };
}

/** A fetch that never produced a response (offline, refused, aborted). */
export function networkFailure(): Failure {
  return {
    kind: "network",
    status: null,
    message: messageFor("network", null),
    retryAfterSeconds: null,
    requestId: null,
  };
}

/** The sign-in screen's wording for a failure. A rejected code always reads the same way. */
export function loginMessage(failure: Failure): string {
  switch (failure.kind) {
    case "unauthorized":
      return t("login.error.rejected");
    case "rate_limited":
      return failure.retryAfterSeconds === null
        ? t("login.error.rateLimitedNoWait")
        : t("login.error.rateLimited", { seconds: failure.retryAfterSeconds });
    case "forbidden":
      return t("login.error.forbidden");
    case "invalid":
      return t("login.error.invalid");
    case "network":
      return t("login.error.network");
    default:
      return t("login.error.generic");
  }
}
