import type { QueryClient, QueryKey } from "@tanstack/react-query";

import { t } from "../../i18n";
import { failureFromResponse, networkFailure, type Failure } from "../../lib/problem";
import { problemCode } from "./search";

/** True for every cached `GET /cases` query (any filters, finite or infinite). */
function isListKey(key: QueryKey): boolean {
  const first = key[0];
  return (
    typeof first === "object" && first !== null && (first as { _id?: string })._id === "listCases"
  );
}

/** Refetch the queue after something was added or imported. */
export function refreshQueue(queryClient: QueryClient): Promise<void> {
  return queryClient.invalidateQueries({ predicate: (query) => isListKey(query.queryKey) });
}

/** What a mutating call to the API returned, reduced to what the dialogs need. */
export type CallOutcome<T> =
  { ok: true; status: number; data: T } | { ok: false; failure: Failure; code: string | null };

interface SdkResult<T> {
  data?: T;
  error?: unknown;
  response?: Response;
}

/** Run an SDK call (made with `throwOnError: false`) and turn any outcome into a `CallOutcome`. */
export async function callApi<T>(run: () => Promise<SdkResult<T>>): Promise<CallOutcome<T>> {
  try {
    const result = await run();
    const response = result.response;
    if (!response) return { ok: false, failure: networkFailure(), code: null };
    if (result.error !== undefined || !response.ok || result.data === undefined) {
      return {
        ok: false,
        failure: failureFromResponse(
          response.status,
          result.error,
          response.headers.get("Retry-After"),
        ),
        code: problemCode(result.error),
      };
    }
    return { ok: true, status: response.status, data: result.data };
  } catch {
    return { ok: false, failure: networkFailure(), code: null };
  }
}

/** The sentence for a failed add or import; the daily cap gets its own wording. */
export function failureMessage(failure: Failure, code: string | null): string {
  if (failure.kind === "rate_limited" && code === "daily_cap_reached") {
    return t("queue.add.dailyCap");
  }
  return failure.message;
}
