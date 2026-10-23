import { describe, expect, it } from "vitest";

import { failureFromResponse, loginMessage, networkFailure, parseRetryAfter } from "./problem";

describe("parseRetryAfter", () => {
  it("reads delta-seconds and rounds up", () => {
    expect(parseRetryAfter("30")).toBe(30);
    expect(parseRetryAfter("1.2")).toBe(2);
  });

  it("ignores absent, negative or non-numeric values", () => {
    expect(parseRetryAfter(null)).toBeNull();
    expect(parseRetryAfter("")).toBeNull();
    expect(parseRetryAfter("-5")).toBeNull();
    expect(parseRetryAfter("Wed, 21 Oct 2026 07:28:00 GMT")).toBeNull();
  });
});

describe("failureFromResponse", () => {
  it.each([
    [401, "unauthorized"],
    [403, "forbidden"],
    [404, "not_found"],
    [409, "conflict"],
    [412, "conflict"],
    [428, "conflict"],
    [400, "invalid"],
    [422, "invalid"],
    [429, "rate_limited"],
    [500, "server"],
    [503, "server"],
    [418, "unknown"],
  ])("maps status %i to %s", (status, kind) => {
    expect(failureFromResponse(status, {}).kind).toBe(kind);
  });

  it("carries the request id and the wait time", () => {
    const failure = failureFromResponse(429, { request_id: "req-1" }, "12");
    expect(failure.requestId).toBe("req-1");
    expect(failure.retryAfterSeconds).toBe(12);
    expect(failure.message).toContain("12");
  });

  it("never shows the server's raw detail text", () => {
    const failure = failureFromResponse(500, {
      detail: "Traceback: secret internals",
      title: "Internal",
    });
    expect(failure.message).not.toContain("Traceback");
  });

  it("copes with a non-object body", () => {
    expect(failureFromResponse(500, "oops").requestId).toBeNull();
    expect(failureFromResponse(500, null).kind).toBe("server");
  });
});

describe("loginMessage", () => {
  it("reads the same for every rejected code", () => {
    const a = loginMessage(failureFromResponse(401, { detail: "unknown code" }));
    const b = loginMessage(failureFromResponse(401, { detail: "code expired" }));
    expect(a).toBe(b);
  });

  it("explains a rate limit with the wait time when known", () => {
    expect(loginMessage(failureFromResponse(429, {}, "45"))).toContain("45");
    expect(loginMessage(failureFromResponse(429, {}))).toMatch(/wait/i);
  });

  it("has a message for network failures", () => {
    expect(loginMessage(networkFailure())).toMatch(/reach the server/i);
  });

  it("falls back to a generic message", () => {
    expect(loginMessage(failureFromResponse(500, {}))).toMatch(/something went wrong/i);
  });
});
