import { expect, test, type Page } from "@playwright/test";

import {
  expectNoSeriousA11yIssues,
  mockApi,
  newState,
  shellReady,
  type MockState,
} from "./support";

const SHOTS = "playwright/screenshots/frame";

const COUNTS = {
  looks_consistent: 12,
  review_suggested: 27,
  needs_local_knowledge: 3,
  insufficient_evidence: 2,
  rules_only: 0,
};

/** The shell mock plus an empty queue that reports lane counts (the rail reads them). */
async function setup(page: Page, overrides: Partial<MockState> = {}, counts = COUNTS) {
  await mockApi(page, newState(overrides));
  await page.route("**/api/v1/cases?**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [], next_cursor: null, counts_by_lane: counts }),
    }),
  );
  return counts;
}

test.describe("@shell app frame and command menu", () => {
  for (const path of ["/login", "/queue", "/history", "/config"]) {
    test(`Ctrl+K opens the menu from ${path} and Escape returns focus`, async ({ page }) => {
      await setup(page, { role: "admin" });
      await page.goto(path);
      const trigger = page.getByTestId("palette-trigger");
      await trigger.focus();
      await page.keyboard.press("Control+k");
      const dialog = page.getByRole("dialog", { name: "Command menu" });
      await expect(dialog).toBeVisible();
      await expect(page.getByRole("combobox", { name: "Search commands" })).toBeFocused();
      await page.keyboard.press("Escape");
      await expect(dialog).toHaveCount(0);
      await expect(trigger).toBeFocused();
    });
  }

  test("every rail destination is reachable from the menu", async ({ page }) => {
    await setup(page, { role: "reviewer" });
    await page.goto("/history");
    await shellReady(page);
    await page.keyboard.press("Control+k");
    const dialog = page.getByRole("dialog", { name: "Command menu" });
    for (const name of [
      "All lanes",
      "Looks consistent",
      "Review suggested",
      "Needs local knowledge",
      "Insufficient evidence",
      "Rules only",
      "History",
      "Config",
      "Keyboard shortcuts",
      "Toggle theme",
      "Toggle density",
      "Add changeset",
      "Import from MapRoulette",
      "Sign out",
    ]) {
      await expect(dialog.getByRole("option", { name }), name).toBeVisible();
    }
    await dialog.getByRole("option", { name: "Review suggested" }).click();
    await expect(page).toHaveURL(/\/queue\?lane=review_suggested/);
    await expect(page.getByRole("dialog", { name: "Command menu" })).toHaveCount(0);
  });

  test("a viewer is not offered add or import", async ({ page }) => {
    await setup(page, { role: "viewer" });
    await page.goto("/queue");
    await shellReady(page);
    await page.keyboard.press("Control+k");
    const dialog = page.getByRole("dialog", { name: "Command menu" });
    await expect(dialog.getByRole("option", { name: "Add changeset" })).toHaveCount(0);
    await expect(dialog.getByRole("option", { name: "Import from MapRoulette" })).toHaveCount(0);
    await expect(dialog.getByRole("option", { name: "Sign in" })).toBeVisible();
  });

  test("typing filters and Enter runs the choice", async ({ page }) => {
    await setup(page, { role: "reviewer" });
    await page.goto("/queue");
    await shellReady(page);
    await page.keyboard.press("Control+k");
    await page.keyboard.type("hist");
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/history$/);
  });

  test("the slash key opens the menu away from the queue", async ({ page }) => {
    await setup(page);
    await page.goto("/history");
    await shellReady(page);
    await page.keyboard.press("/");
    await expect(page.getByRole("dialog", { name: "Command menu" })).toBeVisible();
  });

  test("the rail shows the lane counts from the API", async ({ page }) => {
    await setup(page);
    await page.goto("/queue");
    await expect(page.getByTestId("rail-count-review_suggested")).toHaveText("27");
    await expect(page.getByTestId("rail-count-rules_only")).toHaveText("0");
    await expect(page.getByTestId("rail-total")).toHaveText("44");
  });

  test("counts are plain text under reduced motion", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await setup(page);
    await page.goto("/queue");
    await expect(page.getByTestId("rail-count-review_suggested")).toHaveText("27");
    await expect(page.getByTestId("rolling-count")).toHaveCount(0);
  });
});

test.describe("@shell frame reflow", () => {
  for (const width of [1280, 1024, 800, 375]) {
    test(`no horizontal scroll at ${width} px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 800 });
      await setup(page, { role: "reviewer" });
      await page.goto("/queue");
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(0);
      await expect(page.getByRole("navigation", { name: "Main navigation" })).toBeVisible();
    });
  }

  test("no horizontal scroll at 200 % zoom (640 px wide)", async ({ page }) => {
    await page.setViewportSize({ width: 640, height: 480 });
    await setup(page, { role: "reviewer" });
    await page.goto("/queue");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });

  test("below 800 px the rail is a bar at the bottom of the screen", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 700 });
    await setup(page);
    await page.goto("/queue");
    const box = await page.getByRole("complementary", { name: "Sidebar" }).boundingBox();
    expect(box).not.toBeNull();
    expect(Math.round(box!.y + box!.height)).toBe(700);
    expect(box!.height).toBeLessThanOrEqual(64);
  });
});

test.describe("@shell frame screenshots", () => {
  for (const scheme of ["light", "dark"] as const) {
    test(`screenshots of /queue and /login (${scheme})`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: scheme });
      await page.setViewportSize({ width: 1280, height: 800 });
      await setup(page, { role: "reviewer", displayName: "Test Reviewer" });
      await page.goto("/queue");
      await expect(page.getByTestId("rail-count-review_suggested")).toHaveText("27");
      await expectNoSeriousA11yIssues(page, `/queue ${scheme}`);
      await page.screenshot({ path: `${SHOTS}/queue-${scheme}.png` });
      await page.goto("/login");
      await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
      await expectNoSeriousA11yIssues(page, `/login ${scheme}`);
      await page.screenshot({ path: `${SHOTS}/login-${scheme}.png` });
    });
  }

  test("screenshot of the menu", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await setup(page, { role: "reviewer" });
    await page.goto("/queue");
    await shellReady(page);
    await page.keyboard.press("Control+k");
    await expect(page.getByRole("dialog", { name: "Command menu" })).toBeVisible();
    await expectNoSeriousA11yIssues(page, "command menu");
    await page.screenshot({ path: `${SHOTS}/menu-light.png` });
  });
});
