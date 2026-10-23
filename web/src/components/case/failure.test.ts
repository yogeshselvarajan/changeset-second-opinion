import { describe, expect, it } from "vitest";

import { failureFromError, retryTransient } from "./failure";

describe("failureFromError", () => {
  it("reads the status out of a problem+json body", () => {
    expect(failureFromError({ status: 404, title: "Not found" }).kind).toBe("not_found");
    expect(failureFromError({ status: 403 }).kind).toBe("forbidden");
    expect(failureFromError({ status: 401 }).kind).toBe("unauthorized");
    expect(failureFromError({ status: 503 }).kind).toBe("server");
  });

  it("treats anything without a numeric status as a network failure", () => {
    expect(failureFromError(new TypeError("Failed to fetch")).kind).toBe("network");
    expect(failureFromError({ status: "404" }).kind).toBe("network");
    expect(failureFromError(undefined).kind).toBe("network");
  });

  it("never shows the server's own text", () => {
    const failure = failureFromError({ status: 500, detail: "stack trace with secrets" });
    expect(failure.message).not.toContain("secrets");
  });
});

describe("retryTransient", () => {
  it("retries network and server errors at most twice", () => {
    expect(retryTransient(0, new TypeError("offline"))).toBe(true);
    expect(retryTransient(1, { status: 502 })).toBe(true);
    expect(retryTransient(2, { status: 502 })).toBe(false);
  });

  it("does not retry what a retry cannot fix", () => {
    expect(retryTransient(0, { status: 404 })).toBe(false);
    expect(retryTransient(0, { status: 403 })).toBe(false);
    expect(retryTransient(0, { status: 401 })).toBe(false);
  });
});
