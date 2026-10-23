import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, type Route } from "@playwright/test";

export type Role = "viewer" | "reviewer" | "admin";

export interface MockState {
  role: Role;
  mode: "replay" | "live";
  displayName: string | null;
  /** The server is set up for "Sign in with OpenStreetMap" (shows the login button). */
  osmSignin: boolean;
  /** The current session came from that sign-in. */
  viaOsm: boolean;
  /** The workspace has no owner yet, so this OSM session is offered the claim. */
  canClaim: boolean;
  /** What POST /workspace/claim answers: "ok", or an HTTP status to fail with. */
  claim: "ok" | 409;
  claimRequests: { csrf: string | undefined }[];
  /** What POST /auth/login answers: "ok", or an HTTP status to fail with. */
  login: "ok" | 401 | 429 | 403;
  loginRequests: { body: unknown; csrf: string | undefined }[];
}

export function newState(overrides: Partial<MockState> = {}): MockState {
  return {
    role: "viewer",
    mode: "replay",
    displayName: null,
    osmSignin: false,
    viaOsm: false,
    canClaim: false,
    claim: "ok",
    claimRequests: [],
    login: "ok",
    loginRequests: [],
    ...overrides,
  };
}

const problem = (status: number, title: string) => ({
  type: "urn:cso:problem:test",
  title,
  status,
  request_id: "req-test",
});

function json(route: Route, status: number, body: unknown, headers: Record<string, string> = {}) {
  return route.fulfill({
    status,
    contentType: status >= 400 ? "application/problem+json" : "application/json",
    headers,
    body: JSON.stringify(body),
  });
}

/**
 * Wait until the app shell has drawn. The shell loads on demand, so a test that presses a key right
 * after `goto` must wait for it first.
 */
export async function shellReady(page: Page): Promise<void> {
  await expect(page.getByRole("navigation", { name: "Main navigation" })).toBeVisible();
}

/** Answer every call the shell makes; anything else under /api fails loudly. */
export async function mockApi(page: Page, state: MockState): Promise<void> {
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/api/v1/me") {
      return json(route, 200, {
        id: "00000000-0000-7000-8000-000000000001",
        display_name: state.displayName,
        role: state.role,
        mode: state.mode,
        osm_signin: state.osmSignin,
        via_osm: state.viaOsm,
        can_claim: state.canClaim,
      });
    }
    if (path === "/api/v1/workspace/claim" && request.method() === "POST") {
      state.claimRequests.push({ csrf: request.headers()["x-csrf"] });
      if (state.claim === 409) return json(route, 409, problem(409, "Already claimed"));
      state.role = "admin";
      state.canClaim = false;
      return json(route, 200, {
        id: "00000000-0000-7000-8000-000000000001",
        display_name: state.displayName,
        role: "admin",
        mode: state.mode,
        osm_signin: state.osmSignin,
        via_osm: true,
        can_claim: false,
      });
    }
    if (path === "/api/v1/auth/login" && request.method() === "POST") {
      state.loginRequests.push({
        body: request.postDataJSON(),
        csrf: request.headers()["x-csrf"],
      });
      if (state.login === 401) return json(route, 401, problem(401, "Unauthorized"));
      if (state.login === 403) return json(route, 403, problem(403, "Forbidden"));
      if (state.login === 429) {
        return json(route, 429, problem(429, "Too many requests"), { "Retry-After": "42" });
      }
      state.role = "reviewer";
      state.displayName = "Test Reviewer";
      return json(route, 200, {
        me: {
          id: "00000000-0000-7000-8000-000000000002",
          display_name: state.displayName,
          role: state.role,
          mode: state.mode,
        },
      });
    }
    if (path === "/api/v1/auth/logout" && request.method() === "POST") {
      state.role = "viewer";
      state.displayName = null;
      return route.fulfill({ status: 204 });
    }
    return json(route, 404, problem(404, `unmocked ${path}`));
  });
}

/** WCAG 2.2 AA axe scan; fails on serious or critical findings and attaches the full list. */
export async function expectNoSeriousA11yIssues(page: Page, label: string): Promise<void> {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag22aa"])
    .analyze();
  const blocking = results.violations.filter(
    (violation) => violation.impact === "serious" || violation.impact === "critical",
  );
  const summary = results.violations.map((v) => `${v.impact}: ${v.id} (${v.nodes.length})`);
  expect(blocking, `${label}: ${summary.join("; ")}`).toEqual([]);
}
