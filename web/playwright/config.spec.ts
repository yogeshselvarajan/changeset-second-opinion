import { expect, test, type Page } from "@playwright/test";

import { CONFIG, IDS, mockCaseApi, newCaseState } from "./case.fixtures";
import { mockDraftApi, newDraftState, type DraftMockState } from "./draft.fixtures";
import { expectNoSeriousA11yIssues, mockApi, newState, type Role } from "./support";

async function setup(
  page: Page,
  options: { role?: Role; scheme?: "light" | "dark"; overrides?: Partial<DraftMockState> } = {},
): Promise<DraftMockState> {
  const shell = newState({ role: options.role ?? "admin", displayName: "Test Admin" });
  if (options.scheme) await page.emulateMedia({ colorScheme: options.scheme });
  await mockApi(page, shell);
  await mockCaseApi(page, newCaseState());
  const state = newDraftState(shell, options.overrides);
  await mockDraftApi(page, state);
  return state;
}

async function noHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
}

test.describe("@config configuration (admin)", () => {
  test("shows the active version, the settings, and the YAML with line numbers", async ({
    page,
  }) => {
    await setup(page);
    await page.goto("/config");
    await expect(page.getByRole("heading", { level: 1, name: "Configuration" })).toBeVisible();
    await expect(page.getByTestId("config-version-hash")).toHaveText(CONFIG.version);
    await expect(page.getByTestId("config-bands")).toContainText("Confident from 0.8 upward");
    await expect(page.getByTestId("config-bands")).toContainText("Unsure from 0.5 upward");
    await expect(page.getByTestId("config-bands")).toContainText("no below 0.35");
    await expect(page.getByTestId("config-rules")).toContainText("R1");
    await expect(page.getByTestId("config-tone")).toContainText("Language policy: en");
    await expect(page.getByTestId("config-tone")).toContainText("https://wiki.example.org/");
    // The count of flagged words is shown; the words themselves are not echoed on screen.
    await expect(page.getByTestId("config-tone")).toContainText("1 words are flagged");
    await expect(page.getByTestId("config-tone")).not.toContainText("blorp");

    const yaml = page.getByTestId("config-yaml-text");
    await expect(yaml).toContainText("version:");
    await expect(yaml).toContainText("tone:");
    await expect(yaml).toContainText("language_policy: en");
    // The YAML view hides the flagged words the same way: a count, never the words.
    await expect(yaml).toContainText("1 entries hidden");
    await expect(yaml).not.toContainText("blorp");
    // The line numbers sit in a separate, hidden-from-screen-readers column.
    const gutter = page.getByTestId("config-yaml").locator("pre[aria-hidden='true']");
    await expect(gutter).toContainText("1");
    const lineCount = ((await yaml.innerText()).match(/\n/g) ?? []).length;
    await expect(gutter).toContainText(String(lineCount));
  });

  test("the YAML region is focusable and has a name", async ({ page }) => {
    await setup(page);
    await page.goto("/config");
    const region = page.getByRole("region", { name: "Configuration YAML (scrollable)" });
    await expect(region).toHaveAttribute("tabindex", "0");
    await region.focus();
    await expect(region).toBeFocused();
  });

  test("Copy YAML puts exactly the shown text on the clipboard", async ({ page, context }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    await setup(page);
    await page.goto("/config");
    const shown = await page.getByTestId("config-yaml-text").innerText();
    await page.getByTestId("config-copy").click();
    await expect(page.getByRole("status", { name: "Announcements" })).toContainText(
      "Configuration copied",
    );
    const copied = (await page.evaluate(() => navigator.clipboard.readText())).replace(
      /\r\n/g,
      "\n",
    );
    expect(copied.trimEnd()).toBe(shown.trimEnd());
    expect(copied).not.toMatch(/^\s*\d+\s/m); // no line numbers in the copy
  });

  test("lists the versions and marks the active one", async ({ page }) => {
    await setup(page);
    await page.goto("/config");
    const table = page.getByTestId("config-versions-table");
    await expect(table.getByRole("row")).toHaveCount(3); // header + 2 versions
    await expect(table.locator('tr[data-active="true"]')).toContainText("Active");
    await expect(table.locator('tr[data-active="false"]')).toHaveCount(1);
    await expect(page.getByRole("table", { name: "Stored configuration versions" })).toBeVisible();
  });

  test("a failed config load shows a message and Retry", async ({ page }) => {
    await setup(page);
    let fail = true;
    await page.route("**/api/v1/config", (route) =>
      fail
        ? route.fulfill({
            status: 500,
            contentType: "application/problem+json",
            body: JSON.stringify({
              type: "urn:cso:problem:test",
              title: "x",
              status: 500,
              request_id: "r",
            }),
          })
        : route.fallback(),
    );
    await page.goto("/config");
    await expect(page.getByTestId("config-error")).toContainText("server had a problem", {
      timeout: 20_000,
    });
    fail = false;
    await page.getByTestId("config-error").getByRole("button", { name: "Retry" }).click();
    await expect(page.getByTestId("config-version-hash")).toBeVisible();
  });

  for (const role of ["reviewer", "viewer"] as const) {
    test(`a ${role} gets the 403 page and no configuration`, async ({ page }) => {
      const state = await setup(page, { role });
      await page.goto("/config");
      await expect(page.getByRole("heading", { level: 1 })).toContainText(
        /not allowed|forbidden|access/i,
      );
      await expect(page.getByTestId("config-screen")).toHaveCount(0);
      await expect(page.getByTestId("config-yaml-text")).toHaveCount(0);
      // The admin-only versions list was never requested either.
      expect(state.requestedUrls.filter((url) => url.endsWith("/config/versions"))).toEqual([]);
    });
  }

  test("the browser never calls an OpenStreetMap host from this screen", async ({ page }) => {
    const state = await setup(page);
    await page.goto("/config");
    await expect(page.getByTestId("config-version-hash")).toBeVisible();
    expect(state.requestedUrls.filter((url) => /openstreetmap\.org/.test(url))).toEqual([]);
    expect(IDS.c02).toBeTruthy();
  });
});

test.describe("@config accessibility and layout", () => {
  for (const scheme of ["light", "dark"] as const) {
    test(`axe is clean (${scheme})`, async ({ page }) => {
      await setup(page, { scheme });
      await page.goto("/config");
      await expect(page.getByTestId("config-versions-table")).toBeVisible();
      await expectNoSeriousA11yIssues(page, `config ${scheme}`);
    });
  }

  test("axe is clean on the 403 page", async ({ page }) => {
    await setup(page, { role: "reviewer" });
    await page.goto("/config");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expectNoSeriousA11yIssues(page, "config forbidden");
  });

  test("375 px: no horizontal scroll, the YAML scrolls inside its own region", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 800 });
    await setup(page);
    await page.goto("/config");
    await expect(page.getByTestId("config-yaml-text")).toBeVisible();
    await noHorizontalScroll(page);
    await page.screenshot({ path: "test-results/screenshots/config-375.png", fullPage: true });
  });

  test("screenshots in light and dark at 1280 px", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await setup(page);
    await page.goto("/config");
    await expect(page.getByTestId("config-versions-table")).toBeVisible();
    await page.screenshot({
      path: "test-results/screenshots/config-light-1280.png",
      fullPage: true,
    });
    await page.emulateMedia({ colorScheme: "dark" });
    await page.screenshot({
      path: "test-results/screenshots/config-dark-1280.png",
      fullPage: true,
    });
  });
});
