import { expect, test, type Page, type Route } from "@playwright/test";

import { expectNoSeriousA11yIssues, mockApi, newState, type MockState } from "./support";

const ORIGIN = `http://127.0.0.1:${process.env.PW_PORT ?? "4173"}`;
const SHOTS = "test-results/screenshots";

type Lane =
  | "looks_consistent"
  | "review_suggested"
  | "needs_local_knowledge"
  | "insufficient_evidence"
  | "rules_only";
const LANE_ORDER: Lane[] = [
  "looks_consistent",
  "review_suggested",
  "needs_local_knowledge",
  "insufficient_evidence",
  "rules_only",
];
const LANE_SIZES: Record<Lane, number> = {
  looks_consistent: 12,
  review_suggested: 60,
  needs_local_knowledge: 30,
  insufficient_evidence: 10,
  rules_only: 8,
};
const TOTAL = Object.values(LANE_SIZES).reduce((sum, n) => sum + n, 0); // 120

interface MockCase {
  id: string;
  changeset_id: number;
  lane: Lane;
  band: "confident" | "unsure" | "cannot_tell" | null;
  editor: string | null;
  place_label: string | null;
  element_counts: { create: number; modify: number; delete: number };
  flags: string[];
  coverage_score: number;
  stale: boolean;
  status: "new" | "analyzing" | "analyzed" | "decided";
  latest_outcome: string | null;
  created_at: string;
  updated_at: string;
}

const EDITORS = ["iD 2.31", "JOSM/19253", "StreetComplete", "Rapid 2.1"];
const BAND: Record<Lane, MockCase["band"]> = {
  looks_consistent: "confident",
  review_suggested: "unsure",
  needs_local_knowledge: "cannot_tell",
  insufficient_evidence: null,
  rules_only: null,
};

function makeCases(): MockCase[] {
  const now = Date.now();
  const cases: MockCase[] = [];
  let index = 0;
  for (const lane of LANE_ORDER) {
    for (let n = 0; n < LANE_SIZES[lane]; n += 1) {
      cases.push({
        id: `00000000-0000-4000-8000-${String(index).padStart(12, "0")}`,
        changeset_id: 167230000 + index,
        lane,
        band: BAND[lane],
        editor: index % 17 === 0 ? null : (EDITORS[index % EDITORS.length] ?? null),
        place_label: index % 5 === 0 ? null : `Place ${index}, FR`,
        element_counts: { create: index % 9, modify: (index * 3) % 20, delete: index % 4 },
        flags: index % 3 === 0 ? ["New mapper", "R4"] : [],
        coverage_score: 1,
        stale: index % 11 === 0,
        status: "analyzed",
        latest_outcome: null,
        created_at: new Date(now - index * 600_000).toISOString(),
        updated_at: new Date(now - index * 600_000).toISOString(),
      });
      index += 1;
    }
  }
  return cases;
}

interface QueueMock {
  cases: MockCase[];
  /** What GET /cases answers: ok, a 500, or a 500 only for pages after the first. */
  list: "ok" | "error" | "error-after-first";
  create: "real" | "daily-cap" | "rate";
  importing: "ok" | 400 | 502;
  listRequests: URLSearchParams[];
  createRequests: { body: { changeset_id: number }; csrf: string | undefined }[];
  importRequests: unknown[];
  /** Called for every list request; lets a test change the data over time. */
  onList?: (state: QueueMock) => void;
}

function newQueue(overrides: Partial<QueueMock> = {}): QueueMock {
  return {
    cases: makeCases(),
    list: "ok",
    create: "real",
    importing: "ok",
    listRequests: [],
    createRequests: [],
    importRequests: [],
    ...overrides,
  };
}

function fulfil(route: Route, status: number, body: unknown, headers: Record<string, string> = {}) {
  return route.fulfill({
    status,
    contentType: status >= 400 ? "application/problem+json" : "application/json",
    headers,
    body: JSON.stringify(body),
  });
}

const problem = (status: number, code: string, title: string) => ({
  type: `urn:cso:problem:${code}`,
  title,
  status,
  request_id: "req-queue-test",
});

function detail(item: MockCase) {
  return {
    ...item,
    changeset: null,
    latest_snapshot_id: null,
    latest_run: null,
    latest_draft: null,
    outcome_version: 0,
    latest_outcome_detail: null,
    attribution: { copyright: "", attribution: "", license: "" },
  };
}

/** Layer the queue endpoints over the shell mock (later routes win; the rest fall through). */
async function mockQueue(page: Page, queue: QueueMock): Promise<void> {
  await page.route("**/api/v1/cases**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());

    if (url.pathname === "/api/v1/cases" && request.method() === "GET") {
      const params = url.searchParams;
      queue.listRequests.push(params);
      queue.onList?.(queue);
      const cursor = params.get("cursor");
      if (queue.list === "error" || (queue.list === "error-after-first" && cursor)) {
        return fulfil(route, 500, problem(500, "internal", "Server error"));
      }
      const limit = Number(params.get("limit") ?? 50);
      const search = (params.get("q") ?? "").toLowerCase();
      const editor = (params.get("editor") ?? "").toLowerCase();
      const withoutLane = queue.cases.filter(
        (item) =>
          (!params.get("status") || item.status === params.get("status")) &&
          (!editor || (item.editor ?? "").toLowerCase().includes(editor)) &&
          (params.get("stale") !== "true" || item.stale) &&
          (!search ||
            String(item.changeset_id).includes(search) ||
            (item.editor ?? "").toLowerCase().includes(search) ||
            (item.place_label ?? "").toLowerCase().includes(search)),
      );
      const filtered = withoutLane.filter(
        (item) => !params.get("lane") || item.lane === params.get("lane"),
      );
      const offset = cursor ? Number(cursor) : 0;
      const counts = Object.fromEntries(
        LANE_ORDER.map((lane) => [lane, withoutLane.filter((item) => item.lane === lane).length]),
      );
      return fulfil(route, 200, {
        items: filtered.slice(offset, offset + limit),
        next_cursor: offset + limit < filtered.length ? String(offset + limit) : null,
        counts_by_lane: counts,
      });
    }

    if (url.pathname === "/api/v1/cases" && request.method() === "POST") {
      const body = request.postDataJSON() as { changeset_id: number };
      queue.createRequests.push({ body, csrf: request.headers()["x-csrf"] });
      if (queue.create === "daily-cap") {
        return fulfil(route, 429, problem(429, "daily_cap_reached", "Daily cap"), {
          "Retry-After": "3600",
        });
      }
      if (queue.create === "rate") {
        return fulfil(route, 429, problem(429, "rate_limited", "Too many requests"), {
          "Retry-After": "42",
        });
      }
      const existing = queue.cases.find((item) => item.changeset_id === body.changeset_id);
      if (existing) return fulfil(route, 200, { case: detail(existing), job_id: null });
      const created: MockCase = {
        ...queue.cases[0]!,
        id: `00000000-0000-4000-9000-${String(body.changeset_id).slice(-12).padStart(12, "0")}`,
        changeset_id: body.changeset_id,
        lane: "rules_only",
        band: null,
        status: "new",
        editor: null,
        place_label: null,
        flags: [],
        stale: false,
      };
      queue.cases.push(created);
      return fulfil(route, 201, { case: detail(created), job_id: "job-1" });
    }

    if (url.pathname === "/api/v1/cases/import" && request.method() === "POST") {
      queue.importRequests.push(request.postDataJSON());
      if (queue.importing === 400)
        return fulfil(route, 400, problem(400, "bad_request", "Bad request"));
      if (queue.importing === 502)
        return fulfil(route, 502, problem(502, "bad_gateway", "Bad gateway"));
      return fulfil(route, 202, { created: 3, existing: 2, job_ids: ["a", "b", "c"] });
    }
    return route.fallback();
  });
}

async function withCsrfCookie(page: Page, value = "csrf-token-123") {
  await page.context().addCookies([{ name: "cso_csrf", value, url: ORIGIN }]);
}

const rowsOf = (page: Page) => page.getByTestId("case-row");

async function openQueue(page: Page, state: MockState, queue: QueueMock, path = "/queue") {
  await mockApi(page, state);
  await mockQueue(page, queue);
  await page.goto(path);
  await expect(rowsOf(page).first()).toBeVisible();
}

const reviewer = () => newState({ role: "reviewer", displayName: "Test Reviewer" });

test.describe("@queue keyboard", () => {
  test("j k Enter x o 0-5 / ? all work, focus is visible, rows have readable names", async ({
    page,
  }) => {
    const queue = newQueue();
    await openQueue(page, reviewer(), queue);
    const rows = rowsOf(page);
    await expect(rows).toHaveCount(50);

    // Each row's accessible name reads lane, changeset, editor, place, counts, band, status, age.
    const grid = page.getByRole("grid", { name: "Cases" });
    await expect(rows.first()).toHaveAccessibleName(
      /^Looks consistent, changeset \d+, (editor .+|editor unknown), (place .+|place unknown), \d+ created, \d+ modified, \d+ deleted, Model is confident, status Analyzed, created .+/,
    );
    expect(await grid.ariaSnapshot()).toMatch(
      /row "(Looks consistent|Review suggested), changeset \d+, /,
    );

    const announcements = page.getByRole("status", { name: "Announcements" });

    await page.keyboard.press("j");
    await expect(rows.nth(0)).toBeFocused();
    await page.keyboard.press("j");
    await expect(rows.nth(1)).toBeFocused();
    await expect(announcements).toContainText(`Case 2 of ${TOTAL} selected`);
    await page.keyboard.press("k");
    await expect(rows.nth(0)).toBeFocused();
    await page.keyboard.press("k");
    await expect(rows.nth(0)).toBeFocused(); // never leaves the list

    // The focus ring is a 2 px solid outline on the focused row.
    const outline = await rows.nth(0).evaluate((el) => {
      const style = getComputedStyle(el);
      return { style: style.outlineStyle, width: style.outlineWidth };
    });
    expect(outline.style).toBe("solid");
    expect(outline.width).toBe("2px");

    // x marks and unmarks the focused row; Escape clears every mark.
    await page.keyboard.press("x");
    await expect(rows.nth(0)).toHaveAttribute("aria-selected", "true");
    await page.keyboard.press("x");
    await expect(rows.nth(0)).toHaveAttribute("aria-selected", "false");
    await page.keyboard.press("x");
    await page.keyboard.press("j");
    await page.keyboard.press("x");
    await expect(announcements).toContainText("2 marked");
    await page.keyboard.press("Escape");
    await expect(page.locator('[data-testid="case-row"][aria-selected="true"]')).toHaveCount(0);
    await expect(announcements).toContainText("Marks cleared");

    // Number keys pick a lane; 0 shows every lane again.
    await page.keyboard.press("2");
    await expect(page).toHaveURL(/lane=review_suggested/);
    await expect(page.getByRole("tab", { name: /Review suggested/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expect(rows.first()).toHaveAccessibleName(/^Review suggested, /);
    await page.keyboard.press("5");
    await expect(page).toHaveURL(/lane=rules_only/);
    await page.keyboard.press("0");
    await expect(page).not.toHaveURL(/lane=/);
    await expect(page.getByRole("tab", { name: /All lanes/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );

    // ? opens the shortcut sheet (shell), then Escape closes it.
    await page.keyboard.type("?");
    await expect(page.getByRole("dialog", { name: "Keyboard shortcuts" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);

    // / focuses the search box and the slash is not typed into it.
    await page.keyboard.press("/");
    const search = page.getByRole("searchbox", { name: "Search" });
    await expect(search).toBeFocused();
    await expect(search).toHaveValue("");
    // While typing, the queue keys stay quiet.
    await page.keyboard.type("j2x");
    await expect(search).toHaveValue("j2x");
    await expect(page).not.toHaveURL(/lane=/);
  });

  test("the focused row is never hidden under the sticky top bar", async ({ page }) => {
    for (const width of [1280, 375]) {
      await page.setViewportSize({ width, height: 700 });
      const queue = newQueue();
      await openQueue(page, reviewer(), queue);
      const header = page.getByRole("banner");
      const rows = rowsOf(page);
      // Walk down the list, then back up: the row that has focus must always be fully clear of
      // the bar (WCAG 2.4.11 Focus Not Obscured).
      for (let step = 0; step < 14; step += 1) await page.keyboard.press("j");
      for (let step = 0; step < 10; step += 1) await page.keyboard.press("k");
      const index = 3;
      await expect(rows.nth(index)).toBeFocused();
      const bar = (await header.boundingBox())!;
      const row = (await rows.nth(index).boundingBox())!;
      expect(row.y, `row top vs top bar bottom at ${width}px`).toBeGreaterThanOrEqual(
        bar.y + bar.height - 1,
      );
      await page.keyboard.press("0");
    }
  });

  test("Enter and o open the focused case", async ({ page }) => {
    const queue = newQueue();
    await openQueue(page, reviewer(), queue);
    // The list order is kept so the case screen can offer next and previous.
    const saved = await page.evaluate(() => sessionStorage.getItem("cso.queue.context"));
    const shown = await rowsOf(page).evaluateAll((els) =>
      els.map((el) => el.getAttribute("data-case-id")),
    );
    expect(JSON.parse(saved ?? "[]")).toEqual(shown);
    await page.keyboard.press("j");
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/cases\/00000000-0000-4000-8000-000000000000$/);
    await page.goBack();
    await expect(rowsOf(page).first()).toBeVisible();
    await page.waitForLoadState("networkidle"); // the screen is drawn again and its keys are bound
    // Coming back may restore the earlier focus, so start from the first row explicitly.
    await rowsOf(page).first().focus();
    await page.keyboard.press("j");
    await page.keyboard.press("o");
    await expect(page).toHaveURL(/\/cases\/00000000-0000-4000-8000-000000000001$/);
  });

  test("clicking a row opens it; marks switch clicks to marking until they are cleared", async ({
    page,
  }) => {
    const queue = newQueue();
    await openQueue(page, reviewer(), queue);
    // The box marks without opening.
    await rowsOf(page).nth(2).locator("label").click(); // React Aria hides the real input
    await expect(page).toHaveURL(/\/queue/);
    await expect(rowsOf(page).nth(2)).toHaveAttribute("aria-selected", "true");
    // While anything is marked, clicking a row marks it too (like a mail list), it does not open.
    await rowsOf(page).nth(3).click();
    await expect(page).toHaveURL(/\/queue/);
    await expect(rowsOf(page).nth(3)).toHaveAttribute("aria-selected", "true");
    // Escape clears the marks and a click opens the case again.
    await page.keyboard.press("Escape");
    await expect(page.locator('[data-testid="case-row"][aria-selected="true"]')).toHaveCount(0);
    await rowsOf(page).nth(3).click();
    await expect(page).toHaveURL(/\/cases\/00000000-0000-4000-8000-000000000003$/);
  });
});

test.describe("@queue lanes and counts", () => {
  test("lane counts add up to the total and never change when a lane is picked", async ({
    page,
  }) => {
    const queue = newQueue();
    await openQueue(page, reviewer(), queue);
    const read = async () => {
      const counts: number[] = [];
      for (const lane of LANE_ORDER) {
        const text = await page.getByTestId(`lane-count-${lane}`).innerText();
        counts.push(Number(text.replace(/[()]/g, "")));
      }
      const all = Number(
        (await page.getByTestId("lane-count-all").innerText()).replace(/[()]/g, ""),
      );
      return { counts, all };
    };
    const first = await read();
    expect(first.counts).toEqual(LANE_ORDER.map((lane) => LANE_SIZES[lane]));
    expect(first.counts.reduce((a, b) => a + b, 0)).toBe(first.all);
    expect(first.all).toBe(TOTAL);

    await page.getByRole("tab", { name: /Needs local knowledge/ }).click();
    await expect(page).toHaveURL(/lane=needs_local_knowledge/);
    await expect(rowsOf(page)).toHaveCount(30);
    const second = await read();
    expect(second).toEqual(first); // lanes order and group; they never hide the other lanes

    // Nothing is hidden: opening every page of every lane yields every case exactly once.
    await page.getByRole("tab", { name: /All lanes/ }).click();
    while (await page.getByRole("button", { name: "Load more" }).isVisible()) {
      await page.getByRole("button", { name: "Load more" }).click();
      await expect(page.getByRole("button", { name: /Load more|Loading more/ }))
        .toBeVisible({
          timeout: 5000,
        })
        .catch(() => undefined);
    }
    await expect(rowsOf(page)).toHaveCount(TOTAL);
    await expect(page.getByTestId("queue-summary")).toHaveText(`${TOTAL} of ${TOTAL} cases shown`);
    const ids = await rowsOf(page).evaluateAll((els) =>
      els.map((el) => el.getAttribute("data-case-id")),
    );
    expect(new Set(ids).size).toBe(TOTAL);
  });

  test("load more appends the next page and ends when everything is loaded", async ({ page }) => {
    const queue = newQueue();
    await openQueue(page, reviewer(), queue);
    await expect(rowsOf(page)).toHaveCount(50);
    await expect(page.getByTestId("queue-summary")).toHaveText(`50 of ${TOTAL} cases shown`);
    await page.getByRole("button", { name: "Load more" }).click();
    await expect(rowsOf(page)).toHaveCount(100);
    await expect(page.getByRole("status", { name: "Announcements" })).toContainText(
      "Loaded 50 more cases",
    );
    await page.getByRole("button", { name: "Load more" }).click();
    await expect(rowsOf(page)).toHaveCount(TOTAL);
    await expect(page.getByRole("button", { name: "Load more" })).toHaveCount(0);
    await expect(page.getByText("All cases in this view are loaded.")).toBeVisible();
    // Pages were requested by keyset cursor, in order.
    const cursors = queue.listRequests.map((p) => p.get("cursor"));
    expect(cursors).toContain("50");
    expect(cursors).toContain("100");
  });
});

test.describe("@queue filters", () => {
  test("filters live in the URL, narrow the request and survive a reload", async ({ page }) => {
    const queue = newQueue();
    await openQueue(page, reviewer(), queue);

    await page.getByRole("combobox", { name: "Status" }).selectOption("analyzed");
    await expect(page).toHaveURL(/status=analyzed/);

    await page.getByRole("textbox", { name: "Editor", exact: true }).fill("JOSM");
    await expect(page).toHaveURL(/editor=JOSM/); // after the short typing pause
    await page.getByLabel("Only stale").check();
    await expect(page).toHaveURL(/stale=true/);
    await page.getByRole("searchbox", { name: "Search" }).fill("Place 4");
    await expect(page).toHaveURL(/q=Place(\+|%20)4/);

    const last = queue.listRequests.at(-1)!;
    expect(last.get("status")).toBe("analyzed");
    expect(last.get("editor")).toBe("JOSM");
    expect(last.get("stale")).toBe("true");
    expect(last.get("q")).toBe("Place 4");
    expect(last.get("cursor")).toBeNull();

    await page.reload();
    await expect(page.getByRole("combobox", { name: "Status" })).toHaveValue("analyzed");
    await expect(page.getByRole("textbox", { name: "Editor", exact: true })).toHaveValue("JOSM");
    await expect(page.getByLabel("Only stale")).toBeChecked();
    await expect(page.getByRole("searchbox", { name: "Search" })).toHaveValue("Place 4");
  });

  test("an empty result says so and Clear filters brings the list back", async ({ page }) => {
    const queue = newQueue();
    await openQueue(page, reviewer(), queue);
    await page.getByRole("searchbox", { name: "Search" }).fill("no such place");
    await expect(page.getByTestId("queue-empty")).toContainText("No cases match these filters.");
    await expect(page.getByRole("status", { name: "Announcements" })).toContainText("0 cases");
    await page.getByTestId("queue-empty").getByRole("button", { name: "Clear filters" }).click();
    await expect(rowsOf(page).first()).toBeVisible();
    await expect(page).not.toHaveURL(/q=/);
  });

  test("an empty lane and an empty queue read differently", async ({ page }) => {
    const queue = newQueue({ cases: makeCases().filter((item) => item.lane !== "rules_only") });
    await openQueue(page, reviewer(), queue);
    await page.keyboard.press("5");
    await expect(page.getByTestId("queue-empty")).toHaveText("No cases in this lane.");
    // A queue with no cases at all.
    const none = newQueue({ cases: [] });
    const other = await page.context().newPage();
    await mockApi(other, reviewer());
    await mockQueue(other, none);
    await other.goto("/queue");
    await expect(other.getByTestId("queue-empty")).toContainText("No cases yet.");
    await other.close();
  });
});

test.describe("@queue errors", () => {
  test("a failed first load shows an alert and Retry recovers", async ({ page }) => {
    const queue = newQueue({ list: "error" });
    await mockApi(page, reviewer());
    await mockQueue(page, queue);
    await page.goto("/queue");
    const alert = page.getByTestId("queue-error");
    await expect(alert).toBeVisible({ timeout: 10_000 });
    await expect(alert).toContainText("The queue could not be loaded.");
    await expect(rowsOf(page)).toHaveCount(0);
    queue.list = "ok";
    await alert.getByRole("button", { name: "Retry" }).click();
    await expect(rowsOf(page).first()).toBeVisible();
    await expect(page.getByTestId("queue-error")).toHaveCount(0);
  });

  test("a failed refresh keeps the last rows and offers Retry", async ({ page }) => {
    // A case that is still being analyzed makes the queue refresh itself every 2 s.
    const cases = makeCases();
    cases[0]!.status = "analyzing";
    const queue = newQueue({ cases });
    await openQueue(page, reviewer(), queue);
    await expect(rowsOf(page)).toHaveCount(50);
    queue.list = "error";
    const banner = page.getByTestId("queue-stale-error");
    await expect(banner).toBeVisible({ timeout: 15_000 });
    await expect(banner).toContainText("Showing the last list that loaded.");
    await expect(rowsOf(page)).toHaveCount(50);
    queue.list = "ok";
    await banner.getByRole("button", { name: "Retry" }).click();
    await expect(page.getByTestId("queue-stale-error")).toHaveCount(0);
    await expect(rowsOf(page)).toHaveCount(50);
  });

  test("a failed Load more keeps the rows and Retry loads the page", async ({ page }) => {
    const queue = newQueue({ list: "error-after-first" });
    await openQueue(page, reviewer(), queue);
    await page.getByRole("button", { name: "Load more" }).click();
    await expect(page.getByTestId("queue-more-error")).toBeVisible({ timeout: 10_000 });
    await expect(rowsOf(page)).toHaveCount(50);
    queue.list = "ok";
    await page.getByRole("button", { name: "Retry" }).click();
    await expect(rowsOf(page)).toHaveCount(100);
    await expect(page.getByTestId("queue-more-error")).toHaveCount(0);
  });
});

test.describe("@queue add and import", () => {
  test("a reviewer adds a changeset by number or link: 201 new, 200 existing", async ({ page }) => {
    const queue = newQueue();
    await withCsrfCookie(page);
    await openQueue(page, reviewer(), queue);
    await page.getByRole("button", { name: "Add changeset" }).click();
    const dialog = page.getByRole("dialog", { name: "Add a changeset" });
    await expect(dialog).toBeVisible();
    const field = dialog.getByLabel("Changeset id or openstreetmap.org link");
    await expect(field).toBeFocused();

    await expectNoSeriousA11yIssues(page, "add dialog");

    // A pasted link is read for its number only; nothing is fetched from it.
    await field.fill("https://www.openstreetmap.org/changeset/900000000777");
    await dialog.getByRole("button", { name: "Add to queue" }).click();
    await expect(dialog.getByTestId("add-result")).toContainText(
      "Added changeset 900000000777. Its analysis is queued.",
    );
    expect(queue.createRequests.at(-1)).toEqual({
      body: { changeset_id: 900000000777, source: "manual" },
      csrf: "csrf-token-123",
    });
    await expect(page.getByTestId("lane-count-all")).toHaveText(`(${TOTAL + 1})`); // list refreshed

    await field.fill("167230003");
    await dialog.getByRole("button", { name: "Add to queue" }).click();
    await expect(dialog.getByTestId("add-result")).toContainText(
      "Changeset 167230003 is already in the queue.",
    );
    await expect(page.getByTestId("lane-count-all")).toHaveText(`(${TOTAL + 1})`);

    await dialog.getByRole("link", { name: "Open case" }).click();
    await expect(page).toHaveURL(/\/cases\//);
  });

  test("bad input is explained and sends nothing; Esc closes the dialog", async ({ page }) => {
    const queue = newQueue();
    await openQueue(page, reviewer(), queue);
    await page.getByRole("button", { name: "Add changeset" }).click();
    const dialog = page.getByRole("dialog", { name: "Add a changeset" });
    await dialog.getByLabel("Changeset id or openstreetmap.org link").fill("not a changeset");
    await dialog.getByRole("button", { name: "Add to queue" }).click();
    await expect(dialog.getByRole("alert")).toContainText("Enter a changeset number");
    expect(queue.createRequests).toHaveLength(0);
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Add changeset" })).toBeFocused();
  });

  test("the daily cap and the per-session limit are told apart", async ({ page }) => {
    const queue = newQueue({ create: "daily-cap" });
    await openQueue(page, reviewer(), queue);
    await page.getByRole("button", { name: "Add changeset" }).click();
    const dialog = page.getByRole("dialog", { name: "Add a changeset" });
    const field = dialog.getByLabel("Changeset id or openstreetmap.org link");
    await field.fill("900000000001");
    await dialog.getByRole("button", { name: "Add to queue" }).click();
    await expect(dialog.getByRole("alert")).toContainText(
      "The daily analysis limit has been reached. Try again after midnight UTC.",
    );
    queue.create = "rate";
    await dialog.getByRole("button", { name: "Add to queue" }).click();
    await expect(dialog.getByRole("alert")).toContainText(
      "Too many requests. Try again in 42 seconds.",
    );
  });

  test("a viewer sees the buttons disabled with the reason", async ({ page }) => {
    const queue = newQueue();
    await openQueue(page, newState({ role: "viewer" }), queue);
    await expect(page.getByRole("button", { name: "Add changeset" })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Import from MapRoulette" })).toBeDisabled();
    await expect(page.getByText("Sign in as a reviewer to add changesets.")).toBeVisible();
    // Viewers still browse and open cases.
    await rowsOf(page).first().click();
    await expect(page).toHaveURL(/\/cases\//);
  });

  test("import from MapRoulette: 202 counts, then the replay-mode 400 and a 502", async ({
    page,
  }) => {
    const queue = newQueue();
    await openQueue(page, reviewer(), queue);
    await page.getByRole("button", { name: "Import from MapRoulette" }).click();
    const dialog = page.getByRole("dialog", { name: "Import from MapRoulette" });
    await dialog.getByLabel("Challenge id").fill("55814");
    await dialog.getByLabel(/How many to import/).fill("25");
    await dialog.getByRole("button", { name: "Import" }).click();
    await expect(dialog.getByTestId("import-result")).toHaveText(
      "Imported 3 new and found 2 already in the queue.",
    );
    expect(queue.importRequests.at(-1)).toEqual({
      source: "maproulette",
      challenge_id: 55814,
      limit: 25,
    });

    queue.importing = 400;
    await dialog.getByRole("button", { name: "Import" }).click();
    await expect(dialog.getByRole("alert")).toHaveText(
      "Importing from a challenge is only available in live mode.",
    );
    queue.importing = 502;
    await dialog.getByRole("button", { name: "Import" }).click();
    await expect(dialog.getByRole("alert")).toHaveText(
      "MapRoulette could not be reached. Try again later.",
    );

    await dialog.getByLabel(/How many to import/).fill("500");
    const before = queue.importRequests.length;
    await dialog.getByRole("button", { name: "Import" }).click();
    await expect(dialog.getByRole("alert")).toContainText("between 1 and 100");
    expect(queue.importRequests).toHaveLength(before);
  });
});

test.describe("@queue polling", () => {
  test("rows being analyzed refresh every 2 s and polling ends when they are done", async ({
    page,
  }) => {
    test.setTimeout(45_000);
    const cases = makeCases();
    cases[0]!.status = "analyzing";
    cases[0]!.lane = "rules_only";
    let polls = 0;
    const queue = newQueue({
      cases,
      onList: (state) => {
        polls += 1;
        if (polls >= 3) state.cases[0]!.status = "analyzed";
      },
    });
    await openQueue(page, reviewer(), queue);
    await expect(rowsOf(page).first()).toContainText("Analyzing");
    await expect(rowsOf(page).first()).toContainText("Analyzed", { timeout: 15_000 });
    const settled = queue.listRequests.length;
    await page.waitForTimeout(3500);
    expect(queue.listRequests.length - settled).toBeLessThanOrEqual(1); // no polling once done
  });
});

test.describe("@queue accessibility and layout", () => {
  for (const scheme of ["light", "dark"] as const) {
    for (const density of ["comfortable", "compact"] as const) {
      test(`axe finds no serious issues on /queue (${scheme}, ${density})`, async ({ page }) => {
        await page.emulateMedia({ colorScheme: scheme });
        await page.addInitScript((value) => localStorage.setItem("cso.density", value), density);
        const queue = newQueue();
        await openQueue(page, reviewer(), queue);
        await expect(page.locator("html")).toHaveAttribute("data-density", density);
        await expectNoSeriousA11yIssues(page, `/queue ${scheme} ${density}`);
        await rowsOf(page).first().locator("label").click();
        await expectNoSeriousA11yIssues(page, `/queue marked ${scheme} ${density}`);
      });
    }
  }

  test("axe is clean for the empty, error and import states", async ({ page }) => {
    const queue = newQueue();
    await openQueue(page, reviewer(), queue);
    await page.getByRole("searchbox", { name: "Search" }).fill("no such place");
    await expect(page.getByTestId("queue-empty")).toBeVisible();
    await expectNoSeriousA11yIssues(page, "empty state");
    await page.getByRole("button", { name: "Import from MapRoulette" }).click();
    await expect(page.getByRole("dialog", { name: "Import from MapRoulette" })).toBeVisible();
    await expectNoSeriousA11yIssues(page, "import dialog");
  });

  test("at 375 px rows have two lines, nothing scrolls sideways and filters sit behind a button", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 375, height: 800 });
    const queue = newQueue();
    await openQueue(page, reviewer(), queue);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);

    const toggle = page.getByRole("button", { name: "Filters" });
    await expect(toggle).toBeVisible();
    await expect(page.getByRole("combobox", { name: "Status" })).toBeHidden();
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByRole("combobox", { name: "Status" })).toBeVisible();
    await page.getByRole("combobox", { name: "Status" }).selectOption("analyzed");
    await expect(page.getByRole("button", { name: "Filters (1)" })).toBeVisible();

    const box = await rowsOf(page).first().boundingBox();
    expect(box?.width ?? 0).toBeLessThanOrEqual(375);
    const overflowAfter = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflowAfter).toBeLessThanOrEqual(0);
    await page.screenshot({ path: `${SHOTS}/queue-375.png`, fullPage: false });
  });

  test("at 1280 px the filters are shown inline and the queue fits", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    const queue = newQueue();
    await openQueue(page, reviewer(), queue);
    await expect(page.getByRole("button", { name: "Filters" })).toBeHidden();
    await expect(page.getByRole("combobox", { name: "Status" })).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
    await page.screenshot({ path: `${SHOTS}/queue-1280.png`, fullPage: false });
  });

  test("evidence-derived text is shown as text, never as markup", async ({ page }) => {
    const cases = makeCases();
    cases[0]!.place_label = '<img src=x onerror="window.__pwned=1">';
    cases[0]!.editor = "<b>bold</b>";
    cases[0]!.flags = ["<script>window.__pwned=1</script>"];
    const queue = newQueue({ cases });
    await openQueue(page, reviewer(), queue);
    await expect(rowsOf(page).first()).toContainText('<img src=x onerror="window.__pwned=1">');
    await expect(rowsOf(page).first().locator("img, b, script")).toHaveCount(0);
    expect(
      await page.evaluate(() => (window as unknown as { __pwned?: number }).__pwned),
    ).toBeUndefined();
  });

  test("the page makes no request to OpenStreetMap", async ({ page }) => {
    const hosts = new Set<string>();
    page.on("request", (request) => hosts.add(new URL(request.url()).host));
    const queue = newQueue();
    await openQueue(page, reviewer(), queue);
    await page.getByRole("button", { name: "Add changeset" }).click();
    await page
      .getByRole("dialog", { name: "Add a changeset" })
      .getByLabel("Changeset id or openstreetmap.org link")
      .fill("https://www.openstreetmap.org/changeset/42");
    await page.getByRole("button", { name: "Add to queue" }).click();
    await expect(page.getByTestId("add-result")).toBeVisible();
    expect([...hosts].filter((host) => /openstreetmap/i.test(host))).toEqual([]);
  });
});
