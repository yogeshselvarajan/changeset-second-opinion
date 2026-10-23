import { failureFromResponse, networkFailure, type Failure } from "../../lib/problem";

/**
 * Turn whatever a failed query threw into a typed failure. The generated query functions throw the
 * parsed problem+json body (which carries `status`), or a TypeError when nothing came back.
 */
export function failureFromError(error: unknown): Failure {
  if (typeof error === "object" && error !== null && "status" in error) {
    const status = (error as { status: unknown }).status;
    if (typeof status === "number") return failureFromResponse(status, error, null);
  }
  return networkFailure();
}

/** Retry only what could be temporary: network errors and 5xx, at most twice. */
export function retryTransient(failureCount: number, error: unknown): boolean {
  if (failureCount >= 2) return false;
  const failure = failureFromError(error);
  return failure.kind === "network" || failure.kind === "server";
}
