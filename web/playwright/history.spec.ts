import { expect, test, type Page } from "@playwright/test";

import { IDS, mockCaseApi, newCaseState } from "./case.fixtures";
import {
  mockDraftApi,
  newDraftState,
  withRecordedDecision,
  type DraftMockState,
} from "./draft.fixtures";
import { expectNoSeriousA11yIssues, mockApi, newState, type Role } from "./support";

async function setup(
  page: Page,
  options: {
    role?: Role;
    scheme?: "light" | "dark";
    overrides?: Partial<DraftMockState>;
    recorded?: boolean;
  } = {},
): Promise<DraftMockState> {
  const shell = newState({ role: options.role ?? "reviewer", displayName: "Test Reviewer" });
  if (options.scheme) await page.emulateMedia({ colorScheme: options.scheme });
  await mockApi(page, shell);
  await mockCaseApi(page, newCaseState());
  const state = newDraftState(shell, options.overrides);
  if (options.recorded) withRecordedDecision(state);
  await mockDraftApi(page, state);
  return state;
}

const rows = (page: Page) => page.getByTestId("history-row");
const lastQuery = (state: DraftMockState) =>
  state.decisionQueries[state.decisionQueries.length - 1];

async function noHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
}

test.describe("@history decision history", () => {
  test("groups decisions by day, newest first, and loads more by cursor", async ({ page }) => {
    const state = await setup(page);
    await page.goto("/history");
    await expect(page.getByRole("heading", { level: 1, name: "Decision history" })).toBeVisible();
    await expect(rows(page)).toHaveCount(3);
    const days = page.getByTestId("history-day");
    await expect(days).toHaveCount(2);
    await expect(days.nth(0).getByRole("heading", { level: 2 })).toHaveText("2026-07-13");
    await expect(days.nth(1).getByRole("heading", { level: 2 })).toHaveText("2026-07-12");
    await expect(
      days.nth(0).getByRole("list", { name: "Decisions recorded on 2026-07-13" }),
    ).toBeVisible();
    await expect(page.getByTestId("row-disposition").first()).toHaveText("Needs survey");

    await page.getByTestId("history-more").click();
    await expect(rows(page)).toHaveCount(5);
    await expect(page.getByTestId("history-end")).toHaveText("All 5 decisions are shown.");
    await expect(page.getByTestId("history-more")).toHaveCount(0);
    // The second page was asked for with the cursor the first page returned.
    expect(state.decisionQueries.map((q) => q.get("cursor"))).toEqual([null, "3"]);
  });

  test("each row links to its case and shows lane, band, reviewer and config", async ({ page }) => {
    await setup(page);
    await page.goto("/history");
    const first = rows(page).first();
    await expect(first.getByRole("link")).toHaveText("900000000005");
    await expect(first.getByRole("link")).toHaveAttribute("href", `/cases/${IDS.c02}`);
    await expect(first).toContainText("Review suggested");
    await expect(first).toContainText("Model is unsure");
    await expect(first).toContainText("Ann");
    await expect(first).toContainText("sha256:01ae6fdd");
  });

  test("a row expands to the final text next to the draft, with the probabilities of that run", async ({
    page,
  }) => {
    await setup(page, { recorded: true, overrides: { decisionPageSize: 10 } });
    await page.goto("/history");
    const row = page.locator('[data-outcome="o-1"]');
    const toggle = row.getByTestId("row-toggle");
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-expanded", "true");

    const detail = page.getByTestId("decision-detail");
    await expect(detail).toBeVisible();
    await expect(page.getByTestId("detail-final")).toContainText(
      "Could you tell us where the names came from?",
    );
    await expect(detail).toContainText("Edited the question");
    // Word-level changes against the generated draft: words that were cut are struck, none added.
    const diff = page.getByTestId("detail-diff");
    await expect(diff.locator("del")).not.toHaveCount(0);
    await expect(diff).toContainText("survey or imagery");
    // Probabilities as they were at that run, every option with its own number.
    await expect(page.getByTestId("probs-nature").getByTestId("probability")).toHaveText([
      "0.31",
      "0.27",
      "0.22",
      "0.20",
    ]);
    await expect(page.getByTestId("probs-response").getByTestId("probability").nth(1)).toHaveText(
      "0.41",
    );
    await expect(page.getByTestId("detail-probabilities")).toContainText("not recalculated");
    await expect(page.getByTestId("detail-probabilities")).not.toContainText("%");

    await toggle.click();
    await expect(page.getByTestId("decision-detail")).toHaveCount(0);
  });

  test("arrow keys move between timeline entries and Enter opens one", async ({ page }) => {
    await setup(page, { recorded: true, overrides: { decisionPageSize: 10 } });
    await page.goto("/history");
    const toggles = page.getByTestId("row-toggle");
    await expect(toggles).toHaveCount(5);
    await toggles.nth(0).focus();
    await page.keyboard.press("ArrowDown");
    await expect(toggles.nth(1)).toBeFocused();
    await page.keyboard.press("ArrowDown");
    await expect(toggles.nth(2)).toBeFocused();
    await page.keyboard.press("ArrowUp");
    await expect(toggles.nth(1)).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(toggles.nth(1)).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByTestId("decision-detail")).toBeVisible();
  });

  test("day headings are real headings and the day count is announced once", async ({ page }) => {
    await setup(page);
    await page.goto("/history");
    await expect(page.getByRole("heading", { level: 2 })).toHaveCount(2);
    await expect(page.getByTestId("day-count").first()).toHaveText(/^\d+$/);
  });

  test("with reduced motion the connector does not animate and counts are plain text", async ({
    page,
  }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await setup(page);
    await page.goto("/history");
    await expect(rows(page)).toHaveCount(3);
    await expect(page.getByTestId("rolling-count")).toHaveCount(0);
    const running = await page.evaluate(
      () =>
        document.getAnimations().filter((animation) => animation.playState === "running").length,
    );
    expect(running).toBe(0);
  });

  test("an older decision says a later one replaced it", async ({ page }) => {
    await setup(page, { recorded: true, overrides: { decisionPageSize: 10 } });
    await page.goto("/history");
    await page.locator('[data-outcome="o-2"]').getByTestId("row-toggle").click();
    await expect(page.getByTestId("detail-superseded")).toContainText("later decision replaced");
  });

  test("filters narrow the list and go into the URL and the request", async ({ page }) => {
    const state = await setup(page, { overrides: { decisionPageSize: 10 } });
    await page.goto("/history");
    await expect(rows(page)).toHaveCount(5);

    await page.getByTestId("filter-reviewer").fill("ann");
    await page.getByTestId("filter-disposition").selectOption("needs_survey");
    await page.getByTestId("filter-from").fill("2026-07-12");
    await page.getByTestId("filter-to").fill("2026-07-13");
    await page.getByTestId("filter-apply").click();

    await expect(rows(page)).toHaveCount(1);
    await expect(page).toHaveURL(/reviewer=ann/);
    await expect(page).toHaveURL(/disposition=needs_survey/);
    const query = lastQuery(state);
    expect(query?.get("reviewer")).toBe("ann");
    expect(query?.get("disposition")).toBe("needs_survey");
    expect(query?.get("from")).toBe("2026-07-12T00:00:00Z");
    expect(query?.get("to")).toBe("2026-07-13T23:59:59Z");

    await page.getByTestId("filter-clear").click();
    await expect(rows(page)).toHaveCount(5);
    await expect(page).not.toHaveURL(/reviewer=/);
    await expect(page.getByTestId("filter-reviewer")).toHaveValue("");
  });

  test("a hand-edited URL with bad values shows the plain list instead of an error", async ({
    page,
  }) => {
    const state = await setup(page, { overrides: { decisionPageSize: 10 } });
    await page.goto("/history?reviewer=Ann&disposition=bogus&from=nope&to=2026-02-30");
    await expect(rows(page)).toHaveCount(2);
    const query = lastQuery(state);
    expect(query?.get("reviewer")).toBe("Ann");
    expect(query?.has("disposition")).toBe(false);
    expect(query?.has("from")).toBe(false);
    expect(query?.has("to")).toBe(false);
  });

  test("keys: f jumps to the filters, j and k move between rows, Enter opens one", async ({
    page,
  }) => {
    await setup(page, { recorded: true, overrides: { decisionPageSize: 10 } });
    await page.goto("/history");
    await expect(rows(page)).toHaveCount(5);
    await page.keyboard.press("f");
    await expect(page.getByTestId("filter-reviewer")).toBeFocused();
    await page.getByTestId("filter-reviewer").blur();

    await page.keyboard.press("j");
    await expect(rows(page).nth(0).getByTestId("row-toggle")).toBeFocused();
    await page.keyboard.press("j");
    await expect(rows(page).nth(1).getByTestId("row-toggle")).toBeFocused();
    await page.keyboard.press("k");
    await expect(rows(page).nth(0).getByTestId("row-toggle")).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(rows(page).nth(0).getByTestId("row-toggle")).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  test("typing in a filter does not trigger the shortcuts", async ({ page }) => {
    await setup(page);
    await page.goto("/history");
    await page.getByTestId("filter-reviewer").focus();
    await page.keyboard.type("fjk");
    await expect(page.getByTestId("filter-reviewer")).toHaveValue("fjk");
    await expect(page.getByTestId("filter-reviewer")).toBeFocused();
  });

  test("only an admin gets the CSV link, and it carries the filters", async ({ page }) => {
    await setup(page, { role: "admin" });
    await page.goto("/history?reviewer=Ann&disposition=agree");
    const link = page.getByTestId("history-csv");
    await expect(link).toBeVisible();
    const href = (await link.getAttribute("href")) ?? "";
    expect(href.startsWith("/api/v1/decisions/export.csv?")).toBe(true);
    const params = new URLSearchParams(href.split("?")[1]);
    expect(params.get("reviewer")).toBe("Ann");
    expect(params.get("disposition")).toBe("agree");
    expect(params.has("cursor")).toBe(false);
    await expect(link).toHaveAttribute("download", "decisions.csv");
  });

  for (const role of ["reviewer", "viewer"] as const) {
    test(`a ${role} sees the history but no CSV link`, async ({ page }) => {
      await setup(page, { role });
      await page.goto("/history");
      await expect(rows(page)).toHaveCount(3);
      await expect(page.getByTestId("history-csv")).toHaveCount(0);
    });
  }

  test("empty states: no decisions yet, and no match for the filters", async ({ page }) => {
    await setup(page, { overrides: { decisions: [] } });
    await page.goto("/history");
    await expect(page.getByTestId("history-empty")).toHaveText("No decisions yet.");
    await page.goto("/history?reviewer=nobody");
    await expect(page.getByTestId("history-empty")).toHaveText("No decisions match these filters.");
  });

  test("a failed load shows a message and Retry works", async ({ page }) => {
    const state = await setup(page, { overrides: { decisionsFail: true } });
    await page.goto("/history");
    const error = page.getByTestId("history-error");
    await expect(error).toBeVisible();
    await expect(error).toContainText("server had a problem");
    state.decisionsFail = false;
    await error.getByRole("button", { name: "Retry" }).click();
    await expect(rows(page)).toHaveCount(3);
  });

  test("the browser never calls an OpenStreetMap host from this screen", async ({ page }) => {
    const state = await setup(page, { recorded: true, overrides: { decisionPageSize: 10 } });
    await page.goto("/history");
    await page.locator('[data-outcome="o-1"]').getByTestId("row-toggle").click();
    await expect(page.getByTestId("decision-detail")).toBeVisible();
    expect(state.requestedUrls.filter((url) => /openstreetmap\.org/.test(url))).toEqual([]);
  });
});

test.describe("@history accessibility and layout", () => {
  for (const scheme of ["light", "dark"] as const) {
    test(`axe is clean with a row expanded (${scheme})`, async ({ page }) => {
      await setup(page, { scheme, recorded: true, overrides: { decisionPageSize: 10 } });
      await page.goto("/history");
      await expect(rows(page)).toHaveCount(5);
      await expectNoSeriousA11yIssues(page, `history ${scheme}`);
      await page.locator('[data-outcome="o-1"]').getByTestId("row-toggle").click();
      await expect(page.getByTestId("decision-detail")).toBeVisible();
      await expectNoSeriousA11yIssues(page, `history expanded ${scheme}`);
    });
  }

  test("axe is clean on the empty and error states", async ({ page }) => {
    const state = await setup(page, { overrides: { decisionsFail: true } });
    await page.goto("/history");
    await expect(page.getByTestId("history-error")).toBeVisible();
    await expectNoSeriousA11yIssues(page, "history error");
    state.decisionsFail = false;
    state.decisions = [];
    await page.getByRole("button", { name: "Retry" }).click();
    await expect(page.getByTestId("history-empty")).toBeVisible();
    await expectNoSeriousA11yIssues(page, "history empty");
  });

  test("375 px: no horizontal scroll, the timeline wraps instead", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 800 });
    await setup(page, { recorded: true, overrides: { decisionPageSize: 10 } });
    await page.goto("/history");
    await expect(rows(page)).toHaveCount(5);
    await noHorizontalScroll(page);
    await page.locator('[data-outcome="o-1"]').getByTestId("row-toggle").click();
    await expect(page.getByTestId("decision-detail")).toBeVisible();
    await noHorizontalScroll(page);
    await page.screenshot({ path: "test-results/screenshots/history-375.png", fullPage: true });
  });

  test("screenshots in light and dark at 1280 px", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await setup(page, { recorded: true, overrides: { decisionPageSize: 10 } });
    await page.goto("/history");
    await page.locator('[data-outcome="o-1"]').getByTestId("row-toggle").click();
    await expect(page.getByTestId("decision-detail")).toBeVisible();
    await page.screenshot({
      path: "test-results/screenshots/history-light-1280.png",
      fullPage: true,
    });
    await page.emulateMedia({ colorScheme: "dark" });
    await page.screenshot({
      path: "test-results/screenshots/history-dark-1280.png",
      fullPage: true,
    });
  });
});
