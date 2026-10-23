import { afterEach, describe, expect, it, vi } from "vitest";

import { client } from "../../api/client.gen";

import {
  approveDisposition,
  ifMatchHeader,
  parseConflict,
  rejectDisposition,
  submitOutcome,
  versionForKeepMine,
} from "./outcomeModel";

const INPUT = { disposition: "agree", run_id_seen: "run-1" } as const;

interface Seen {
  method: string;
  url: string;
  ifMatch: string | null;
  body: unknown;
}

function stubFetch(respond: (seen: Seen) => Response | Promise<Response>) {
  const calls: Seen[] = [];
  const fake = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = input instanceof Request ? input : new Request(input, init);
    const text = await request.clone().text();
    const seen: Seen = {
      method: request.method,
      url: request.url,
      ifMatch: request.headers.get("if-match"),
      body: text ? JSON.parse(text) : null,
    };
    calls.push(seen);
    return respond(seen);
  });
  // The generated client keeps the fetch it was created with, so hand it the fake directly.
  client.setConfig({ baseUrl: "http://localhost", fetch: fake as unknown as typeof fetch });
  return calls;
}

afterEach(() => {
  client.setConfig({ baseUrl: "", fetch: globalThis.fetch });
});

describe("If-Match and dispositions", () => {
  it("formats the weak ETag the server expects", () => {
    expect(ifMatchHeader(0)).toBe('W/"0"');
    expect(ifMatchHeader(7)).toBe('W/"7"');
    expect(ifMatchHeader(undefined)).toBe('W/"0"');
    expect(ifMatchHeader(null)).toBe('W/"0"');
    expect(ifMatchHeader(-3)).toBe('W/"0"');
  });

  it("approving the recommended kind agrees; another kind is a different response", () => {
    expect(approveDisposition("welcome_and_tips", "welcome_and_tips")).toBe("agree");
    expect(approveDisposition("ask_source_question", "welcome_and_tips")).toBe(
      "different_response",
    );
    expect(approveDisposition("welcome_and_tips", null)).toBe("different_response");
  });

  it("rejecting maps the reason to a disposition", () => {
    expect(rejectDisposition("not_needed")).toBe("no_action");
    expect(rejectDisposition("off_tone")).toBe("different_response");
    expect(rejectDisposition("wrong_facts")).toBe("different_response");
  });
});

describe("parseConflict", () => {
  it("reads the live record from the `current` extension member", () => {
    const parsed = parseConflict({
      current: {
        outcome_version: 4,
        outcome: {
          disposition: "needs_survey",
          reviewer_display: "Other Reviewer",
          created_at: "2026-07-12T10:00:00Z",
          note: "Needs a look",
        },
      },
    });
    expect(parsed).toEqual({
      currentVersion: 4,
      outcome: {
        disposition: "needs_survey",
        reviewer_display: "Other Reviewer",
        created_at: "2026-07-12T10:00:00Z",
        note: "Needs a look",
        reason_code: null,
      },
    });
  });

  it("tolerates a missing outcome, a missing version and garbage", () => {
    expect(parseConflict({ current: { outcome_version: 2, outcome: null } })).toEqual({
      currentVersion: 2,
      outcome: null,
    });
    expect(parseConflict({ current: { outcome: { disposition: 5 } } })).toEqual({
      currentVersion: null,
      outcome: null,
    });
    expect(parseConflict({})).toBeNull();
    expect(parseConflict(null)).toBeNull();
    expect(parseConflict("nope")).toBeNull();
  });
});

describe("submitOutcome", () => {
  it("sends PUT with If-Match and the body, and returns the new case on 200", async () => {
    const calls = stubFetch(
      () =>
        new Response(JSON.stringify({ id: "case-1", outcome_version: 3 }), {
          status: 200,
          headers: { "content-type": "application/json", etag: 'W/"3"' },
        }),
    );
    const result = await submitOutcome({ caseId: "case-1", version: 2, input: INPUT });
    expect(result.kind).toBe("ok");
    expect(calls).toHaveLength(1);
    expect(calls[0]?.method).toBe("PUT");
    expect(calls[0]?.url).toContain("/api/v1/cases/case-1/outcome");
    expect(calls[0]?.ifMatch).toBe('W/"2"');
    expect(calls[0]?.body).toEqual(INPUT);
  });

  it("returns the other reviewer's decision on 412 and does not retry", async () => {
    const calls = stubFetch(
      () =>
        new Response(
          JSON.stringify({
            type: "urn:cso:problem:precondition_failed",
            title: "Precondition failed",
            status: 412,
            request_id: "r1",
            current: {
              outcome_version: 5,
              outcome: {
                disposition: "agree",
                reviewer_display: "Someone",
                created_at: "2026-07-12T11:00:00Z",
              },
            },
          }),
          { status: 412, headers: { "content-type": "application/problem+json" } },
        ),
    );
    const result = await submitOutcome({ caseId: "case-1", version: 2, input: INPUT });
    expect(result.kind).toBe("conflict");
    if (result.kind === "conflict") {
      expect(result.conflict?.currentVersion).toBe(5);
      expect(result.conflict?.outcome?.reviewer_display).toBe("Someone");
    }
    expect(calls).toHaveLength(1);
  });

  it("reports other failures with a human message and the problem code", async () => {
    stubFetch(
      () =>
        new Response(
          JSON.stringify({
            type: "urn:cso:problem:daily_cap_reached",
            title: "Limit",
            status: 429,
            request_id: "r2",
          }),
          {
            status: 429,
            headers: { "content-type": "application/problem+json", "retry-after": "30" },
          },
        ),
    );
    const result = await submitOutcome({ caseId: "case-1", version: 0, input: INPUT });
    expect(result.kind).toBe("failed");
    if (result.kind === "failed") {
      expect(result.code).toBe("daily_cap_reached");
      expect(result.failure.kind).toBe("rate_limited");
      expect(result.failure.retryAfterSeconds).toBe(30);
    }
  });

  it("treats a missing network as a failure, not a crash", async () => {
    client.setConfig({
      baseUrl: "http://localhost",
      fetch: vi.fn(async () => {
        throw new TypeError("offline");
      }) as unknown as typeof fetch,
    });
    const result = await submitOutcome({ caseId: "case-1", version: 0, input: INPUT });
    expect(result.kind).toBe("failed");
    if (result.kind === "failed") expect(result.failure.kind).toBe("network");
  });
});

describe("versionForKeepMine", () => {
  it("uses the version that came with the 412 without another request", async () => {
    const fetchLatest = vi.fn(async () => 99);
    const conflict = { outcome: null, currentVersion: 4 } as unknown as Parameters<
      typeof versionForKeepMine
    >[0];
    expect(await versionForKeepMine(conflict, fetchLatest)).toEqual({ version: 4 });
    expect(fetchLatest).not.toHaveBeenCalled();
  });

  it("refetches when the 412 carried no version, instead of resending the stale one", async () => {
    const fetchLatest = vi.fn(async () => 5);
    expect(await versionForKeepMine(null, fetchLatest)).toEqual({ version: 5 });
    expect(fetchLatest).toHaveBeenCalledOnce();
  });

  it("gives up (null) when the latest version cannot be established", async () => {
    expect(
      await versionForKeepMine(null, async () => {
        throw new Error("offline");
      }),
    ).toBeNull();
    expect(await versionForKeepMine(null, async () => undefined)).toBeNull();
  });
});
