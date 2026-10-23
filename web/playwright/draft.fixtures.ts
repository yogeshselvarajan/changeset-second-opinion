import type { Page, Route } from "@playwright/test";

import { CONFIG, FIXTURES, IDS } from "./case.fixtures";
import type { MockState } from "./support";

/*
 * API payloads for the draft editor, the decision history and the config screen, served by route
 * interception on top of the case mock. Register `mockDraftApi` AFTER `mockApi` and `mockCaseApi`:
 * it answers the paths it knows (config, drafts, jobs, outcomes, decisions, one run) and hands the
 * rest back with `route.fallback()`. The banned words here are stand-ins: the real list comes from
 * the server and is never written into the web source.
 */

export const TONE = {
  language_policy: "en",
  allowed_links: ["https://wiki.example.org/"],
  banned_words: ["blorp"],
};

export const DRAFT_CONFIG = { ...CONFIG, tone: TONE };

export const RUN_ID = "r-002";
export const VERSION_ZERO = 'W/"0"';

export interface DraftFixture {
  id: string;
  run_id: string;
  response_type: string;
  status: "generated" | "validated" | "rejected_by_validator" | "template_fallback";
  model_id: string | null;
  greeting: string;
  body: string;
  closing: string;
  cited_evidence_ids: string[];
  validation: { ok: boolean; violations: string[] };
  created_at: string;
}

export const DRAFT: DraftFixture = {
  id: "d-1",
  run_id: RUN_ID,
  response_type: "welcome_and_tips",
  status: "validated",
  model_id: "us.anthropic.claude-haiku-4-5-20251001-v1:0",
  greeting: "Hello, and welcome to OpenStreetMap!",
  body: "Thanks for adding names near E1. Could you tell us where the names came from, for example a survey or imagery?",
  closing: "Happy mapping!",
  cited_evidence_ids: ["E1"],
  validation: { ok: true, violations: [] },
  created_at: "2026-07-12T10:10:00Z",
};

export const TEMPLATE_DRAFT: DraftFixture = {
  ...DRAFT,
  id: "d-2",
  status: "template_fallback",
  model_id: null,
};

export const FINAL_TEXT =
  "Hello, and welcome to OpenStreetMap!\n\nThanks for adding names near E1. Could you tell us where the names came from?\n\nHappy mapping!";

export interface OutcomeCall {
  caseId: string;
  ifMatch: string | undefined;
  csrf: string | undefined;
  body: Record<string, unknown>;
}

export type OutcomeAnswer = "ok" | "conflict" | "rate_limited" | "server_error";

export interface DecisionRowFixture {
  outcome_id: string;
  case_id: string;
  changeset_id: number;
  disposition: string;
  response_type: string | null;
  lane_at_decision: string;
  band_at_decision: string | null;
  reviewer_display: string;
  created_at: string;
  config_version: string;
  decider_model: string | null;
}

const decision = (
  n: number,
  created_at: string,
  extra: Partial<DecisionRowFixture> = {},
): DecisionRowFixture => ({
  outcome_id: `o-${n}`,
  case_id: IDS.c02,
  changeset_id: 900000000000 + n,
  disposition: "agree",
  response_type: "welcome_and_tips",
  lane_at_decision: "review_suggested",
  band_at_decision: "unsure",
  reviewer_display: "Test Reviewer",
  created_at,
  config_version: CONFIG.version,
  decider_model: "strands-decider-2B-qwen3.5-v1-2610",
  ...extra,
});

/** Five decisions on two days, newest first. */
export const DECISIONS: DecisionRowFixture[] = [
  decision(5, "2026-07-13T09:30:00Z", { disposition: "needs_survey", reviewer_display: "Ann" }),
  decision(4, "2026-07-13T08:00:00Z", { disposition: "no_action", response_type: null }),
  decision(3, "2026-07-12T16:45:00Z", { disposition: "different_response" }),
  decision(2, "2026-07-12T11:10:00Z", { reviewer_display: "Ann" }),
  decision(1, "2026-07-12T10:06:00Z"),
];

type Json = Record<string, unknown>;

export interface DraftMockState {
  shell: MockState;
  config: Json;
  /** CaseDetail by case id; outcomes update it. */
  details: Record<string, Json>;
  draft: DraftFixture;
  /** What POST /drafts answers. */
  draftRequest: "accepted" | "not_allowed" | "rate_limited" | "daily_cap";
  draftRequests: { id: string; body: Json; csrf: string | undefined }[];
  /** How the draft job ends. */
  jobEnds: "succeeded" | "failed";
  failureCode: string;
  runningPolls: number;
  jobPolls: number;
  jobCount: number;
  /** The case the latest draft job was requested for. */
  lastDraftCase: string | null;
  /** What each PUT /outcome answers, in order; the last one repeats. */
  outcomeAnswers: OutcomeAnswer[];
  outcomeCalls: OutcomeCall[];
  /** The decision another reviewer recorded first (the 412 body). */
  rival: { version: number; disposition: string; reviewer: string; note: string | null };
  decisions: DecisionRowFixture[];
  decisionPageSize: number;
  decisionQueries: URLSearchParams[];
  decisionsFail: boolean;
  versions: { version: string; created_at: string; sha: string }[];
  /** The decision that case details report as the latest one (for the history detail view). */
  latestOutcome: Json | null;
  requestedUrls: string[];
  /** The pack the mocked server reports as active, and the activations it received. */
  activePack: string;
  packActivations: { id: string; csrf: string | undefined }[];
  packsFail: boolean;
  /** Calibration requests the mocked server received. */
  calibrations: { body: Json; csrf: string | undefined }[];
}

const RELIABILITY = {
  pack_id: "default",
  n_outcomes: 30,
  n_labelled_outcomes: 30,
  min_labels: 25,
  synthetic_outcomes: 0,
  probes: [
    {
      probe: "mature_feature_deleted",
      label: "A mature feature was deleted",
      n: 30,
      status: "fitted",
      default_low: 0.35,
      default_high: 0.65,
      low: 0.35,
      high: 0.8,
      correct: 25,
      decided: 30,
      lower: 0.66,
      upper: 0.92,
      tuned_correct: 25,
      tuned_decided: 25,
      tuned_lower: 0.87,
      tuned_upper: 1,
      coverage: 0.83,
    },
    {
      probe: "conventions_followed",
      label: "Tags follow the usual conventions",
      n: 4,
      status: "insufficient_data",
      default_low: 0.35,
      default_high: 0.65,
      low: 0.35,
      high: 0.65,
      correct: 4,
      decided: 4,
      lower: 0.51,
      upper: 1,
      tuned_correct: 4,
      tuned_decided: 4,
      tuned_lower: 0.51,
      tuned_upper: 1,
      coverage: 1,
    },
  ],
  bands: [
    {
      band: "confident",
      n: 12,
      correct: 12,
      decided: 12,
      lower: 0.76,
      upper: 1,
      status: "insufficient_data",
    },
    {
      band: "unsure",
      n: 30,
      correct: 25,
      decided: 30,
      lower: 0.66,
      upper: 0.92,
      status: "reported",
    },
    {
      band: "cannot_tell",
      n: 0,
      correct: 0,
      decided: 0,
      lower: 0,
      upper: 1,
      status: "insufficient_data",
    },
  ],
};

const PACKS = [
  {
    id: "default",
    title: "Default",
    description: "The balanced starting point.",
    author: "Changeset Second Opinion",
    version: "1.0",
    config_version: "sha256:aaaa",
  },
  {
    id: "strict-review",
    title: "Strict review",
    description: "Closer scrutiny.",
    author: "Changeset Second Opinion",
    version: "1.0",
    config_version: "sha256:bbbb",
  },
];

export function newDraftState(
  shell: MockState,
  overrides: Partial<DraftMockState> = {},
): DraftMockState {
  const details: Record<string, Json> = {};
  for (const [id, fixture] of Object.entries(FIXTURES)) {
    details[id] = structuredClone(fixture.detail);
  }
  (details[IDS.c02] as Json).allowed_responses = ["welcome_and_tips", "ask_source_question"];
  return {
    shell,
    config: structuredClone(DRAFT_CONFIG),
    details,
    draft: structuredClone(DRAFT),
    draftRequest: "accepted",
    draftRequests: [],
    jobEnds: "succeeded",
    failureCode: "draft_not_available",
    runningPolls: 1,
    jobPolls: 0,
    jobCount: 0,
    lastDraftCase: null,
    outcomeAnswers: ["ok"],
    outcomeCalls: [],
    rival: {
      version: 4,
      disposition: "needs_survey",
      reviewer: "Other Reviewer",
      note: "Looks odd",
    },
    decisions: structuredClone(DECISIONS),
    decisionPageSize: 3,
    decisionQueries: [],
    decisionsFail: false,
    versions: [
      { version: CONFIG.version, created_at: "2026-07-12T08:00:00Z", sha: "abc" },
      {
        version: "sha256:0000000000000000000000000000000000000000000000000000000000000000",
        created_at: "2026-07-01T08:00:00Z",
        sha: "def",
      },
    ],
    latestOutcome: null,
    requestedUrls: [],
    activePack: "default",
    packActivations: [],
    packsFail: false,
    calibrations: [],
    ...overrides,
  };
}

const problem = (status: number, title: string, extra: Json = {}) => ({
  type: "urn:cso:problem:test",
  title,
  status,
  request_id: "req-draft",
  ...extra,
});

function json(route: Route, status: number, body: unknown, headers: Record<string, string> = {}) {
  return route.fulfill({
    status,
    contentType: status >= 400 ? "application/problem+json" : "application/json",
    headers,
    body: JSON.stringify(body),
  });
}

/** The run the history detail reads probabilities from. */
const RUN = {
  id: RUN_ID,
  snapshot_id: "s-002",
  config_version: CONFIG.version,
  created_at: "2026-07-12T10:05:00Z",
  status: "succeeded",
  decider_model: "strands-decider-2B-qwen3.5-v1-2610",
  lane: "review_suggested",
  band: "unsure",
  nature: "likely_good_faith_mistake",
  response: "welcome_and_tips",
  nature_probabilities: {
    consistent_edit: 0.31,
    likely_good_faith_mistake: 0.27,
    possible_deliberate_damage: 0.22,
    needs_local_knowledge: 0.2,
  },
  response_probabilities: {
    no_action_suggested: 0.18,
    welcome_and_tips: 0.41,
    ask_source_question: 0.2,
    request_local_check: 0.11,
    escalate_to_experienced_reviewer: 0.1,
  },
  order_sensitivity: 0,
  reconciled: false,
  failure_code: null,
  rules_fired: [],
  panel: null,
  latency_ms: 1100,
  receipt: {
    config_version: CONFIG.version,
    coverage: {},
    decider: null,
    evidence_version: "v1",
    questions_hash: null,
    reconciliation: null,
    rules_fired: [],
  },
};

export async function mockDraftApi(page: Page, state: DraftMockState): Promise<void> {
  page.on("request", (request) => state.requestedUrls.push(request.url()));
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();

    if (path === "/api/v1/config" && method === "GET") return json(route, 200, state.config);

    if (path === "/api/v1/config/packs" && method === "GET") {
      if (state.packsFail) return json(route, 500, problem(500, "Server error"));
      return json(route, 200, {
        items: PACKS.map((pack) => ({ ...pack, is_active: pack.id === state.activePack })),
      });
    }

    if (path === "/api/v1/config/diff" && method === "GET") {
      const a = url.searchParams.get("a");
      const b = url.searchParams.get("b");
      return json(route, 200, {
        a,
        b,
        changes: [
          { area: "rules", key: "R1.min_age_days", a: "365", b: "180" },
          { area: "bands", key: "bands.confident_min", a: "0.8", b: "0.85" },
        ],
      });
    }

    if (path === "/api/v1/config/reliability" && method === "GET") {
      return json(route, 200, RELIABILITY);
    }

    if (path === "/api/v1/config/calibrate" && method === "POST") {
      const body = request.postDataJSON() as Json;
      state.calibrations.push({ body, csrf: request.headers()["x-csrf"] });
      return json(route, 200, {
        ...RELIABILITY,
        applied: body.apply === true,
        calibration_id: "cal-20261019000000-abcd1234",
        config_version: "sha256:cccc",
        reason: null,
      });
    }

    const activate = path.match(/^\/api\/v1\/config\/packs\/([^/]+)\/activate$/);
    if (activate && method === "POST") {
      const id = activate[1] as string;
      state.packActivations.push({ id, csrf: request.headers()["x-csrf"] });
      state.activePack = id;
      const pack = PACKS.find((candidate) => candidate.id === id) ?? PACKS[0]!;
      return json(route, 200, {
        pack: { ...pack, is_active: true },
        config_version: pack.config_version,
      });
    }

    if (path === "/api/v1/config/versions" && method === "GET") {
      if (state.shell.role !== "admin") return json(route, 403, problem(403, "Forbidden"));
      return json(route, 200, { items: state.versions });
    }

    const caseMatch = path.match(/^\/api\/v1\/cases\/([^/]+)$/);
    if (caseMatch && method === "GET") {
      const detail = state.details[caseMatch[1] as string];
      if (!detail) return route.fallback();
      return json(route, 200, detail, { ETag: `W/"${String(detail.outcome_version ?? 0)}"` });
    }

    const evidenceMatch = path.match(/^\/api\/v1\/cases\/([^/]+)\/evidence$/);
    if (evidenceMatch && method === "GET") {
      const fixture = FIXTURES[evidenceMatch[1] as string];
      if (!fixture) return route.fallback();
      return json(route, 200, fixture.evidence);
    }

    const draftMatch = path.match(/^\/api\/v1\/cases\/([^/]+)\/drafts$/);
    if (draftMatch && method === "POST") {
      state.draftRequests.push({
        id: draftMatch[1] as string,
        body: request.postDataJSON() as Json,
        csrf: request.headers()["x-csrf"],
      });
      if (state.draftRequest === "not_allowed") return json(route, 409, problem(409, "Conflict"));
      if (state.draftRequest === "rate_limited") {
        return json(route, 429, problem(429, "Too many requests"), { "Retry-After": "42" });
      }
      if (state.draftRequest === "daily_cap") {
        return json(
          route,
          429,
          { ...problem(429, "Limit"), type: "urn:cso:problem:daily_cap_reached" },
          { "Retry-After": "3600" },
        );
      }
      state.jobCount += 1;
      state.jobPolls = 0;
      state.lastDraftCase = draftMatch[1] as string;
      // A regenerate makes a new draft (a new id), as the server does.
      if ((request.postDataJSON() as Json).regenerate === true) {
        state.draft = { ...state.draft, id: `${state.draft.id}-r${state.jobCount}` };
      }
      return json(route, 202, { job_id: `draft-job-${state.jobCount}` });
    }

    const jobMatch = path.match(/^\/api\/v1\/jobs\/(draft-job-\d+)$/);
    if (jobMatch && method === "GET") {
      state.jobPolls += 1;
      const running = state.jobPolls <= state.runningPolls;
      const base = {
        id: jobMatch[1],
        kind: "draft",
        attempts: 1,
        created_at: "2026-07-12T10:09:00Z",
        updated_at: "2026-07-12T10:09:05Z",
      };
      if (running)
        return json(route, 200, { ...base, status: "running", step: "draft", result_ref: null });
      if (state.jobEnds === "failed") {
        return json(route, 200, {
          ...base,
          status: "failed",
          step: "draft",
          error: state.failureCode,
          result_ref: null,
        });
      }
      const forCase = state.lastDraftCase ? state.details[state.lastDraftCase] : undefined;
      if (forCase) forCase.latest_draft = structuredClone(state.draft);
      return json(route, 200, {
        ...base,
        status: "succeeded",
        step: "draft",
        result_ref: { draft_id: state.draft.id, run_id: RUN_ID },
      });
    }

    const draftGet = path.match(/^\/api\/v1\/drafts\/([^/]+)$/);
    if (draftGet && method === "GET") return json(route, 200, state.draft);

    const outcomeMatch = path.match(/^\/api\/v1\/cases\/([^/]+)\/outcome$/);
    if (outcomeMatch && method === "PUT") {
      const caseId = outcomeMatch[1] as string;
      const body = request.postDataJSON() as Json;
      state.outcomeCalls.push({
        caseId,
        ifMatch: request.headers()["if-match"],
        csrf: request.headers()["x-csrf"],
        body,
      });
      const index = Math.min(state.outcomeCalls.length - 1, state.outcomeAnswers.length - 1);
      const answer = state.outcomeAnswers[index] ?? "ok";
      const detail = state.details[caseId];
      if (answer === "conflict") {
        return json(
          route,
          412,
          problem(412, "Precondition failed", {
            current: {
              outcome_version: state.rival.version,
              outcome: {
                id: "o-rival",
                disposition: state.rival.disposition,
                reviewer_display: state.rival.reviewer,
                created_at: "2026-07-12T10:30:00Z",
                note: state.rival.note,
                run_id_seen: RUN_ID,
              },
            },
          }),
        );
      }
      if (answer === "rate_limited") {
        return json(route, 429, problem(429, "Too many requests"), { "Retry-After": "30" });
      }
      if (answer === "server_error" || !detail)
        return json(route, 500, problem(500, "Server error"));
      const version = Number(detail.outcome_version ?? 0) + 1;
      detail.outcome_version = version;
      detail.status = "decided";
      detail.latest_outcome = body.disposition;
      detail.latest_outcome_detail = {
        ...body,
        id: `o-new-${version}`,
        reviewer_display: "Test Reviewer",
        created_at: "2026-07-12T10:40:00Z",
      };
      return json(route, 200, detail, { ETag: `W/"${version}"` });
    }

    if (path === "/api/v1/decisions" && method === "GET") {
      state.decisionQueries.push(url.searchParams);
      if (state.decisionsFail) return json(route, 500, problem(500, "Server error"));
      const reviewer = url.searchParams.get("reviewer");
      const disposition = url.searchParams.get("disposition");
      const filtered = state.decisions.filter(
        (row) =>
          (!reviewer || row.reviewer_display.toLowerCase().includes(reviewer.toLowerCase())) &&
          (!disposition || row.disposition === disposition),
      );
      const start = Number(url.searchParams.get("cursor") ?? 0);
      const items = filtered.slice(start, start + state.decisionPageSize);
      const next = start + state.decisionPageSize;
      return json(route, 200, {
        items,
        next_cursor: next < filtered.length ? String(next) : null,
      });
    }

    if (path === "/api/v1/decisions/export.csv" && method === "GET") {
      return route.fulfill({ status: 200, contentType: "text/csv", body: "outcome_id\n" });
    }

    if (path === `/api/v1/runs/${RUN_ID}` && method === "GET") return json(route, 200, RUN);

    return route.fallback();
  });
}

/** Make the history detail view find a decision with text, a reason and a draft to compare. */
export function withRecordedDecision(state: DraftMockState): void {
  const detail = state.details[IDS.c02] as Json;
  detail.latest_draft = structuredClone(state.draft);
  detail.latest_outcome_detail = {
    id: "o-1",
    disposition: "agree",
    response_type: "welcome_and_tips",
    final_text: FINAL_TEXT,
    note: "Edited the question",
    reason_code: null,
    run_id_seen: RUN_ID,
    reviewer_display: "Test Reviewer",
    created_at: "2026-07-12T10:06:00Z",
  };
  detail.latest_outcome = "agree";
  detail.outcome_version = 1;
}
