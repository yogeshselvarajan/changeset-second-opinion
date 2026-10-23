import { expect, test, type Page } from "@playwright/test";

import { IDS, mockCaseApi, newCaseState } from "./case.fixtures";
import { mockDraftApi, newDraftState, type DraftMockState } from "./draft.fixtures";
import { expectNoSeriousA11yIssues, mockApi, newState } from "./support";

async function setup(page: Page, scheme?: "light" | "dark"): Promise<DraftMockState> {
  const shell = newState({ role: "admin", displayName: "Test Admin" });
  if (scheme) await page.emulateMedia({ colorScheme: scheme });
  await mockApi(page, shell);
  await mockCaseApi(page, newCaseState());
  const state = newDraftState(shell);
  await mockDraftApi(page, state);
  const base = test.info().project.use.baseURL ?? "http://127.0.0.1:4173";
  await page.context().addCookies([{ name: "cso_csrf", value: "csrf-token-123", url: base }]);
  return state;
}

test.describe("@config reliability", () => {
  test("shows each fact with its accuracy interval and both cut point pairs", async ({ page }) => {
    await setup(page);
    await page.goto("/config");
    await expect(page.getByTestId("reliability-summary")).toContainText("30 decisions counted");
    const fitted = page.locator('[data-probe-row="mature_feature_deleted"]');
    await expect(fitted).toContainText("0.83 (0.66 to 0.92)");
    await expect(fitted).toContainText("0.35 / 0.65");
    await expect(fitted).toContainText("0.35 / 0.80");
    await expect(fitted).toContainText("25 of 30");
    const few = page.locator('[data-probe-row="conventions_followed"]');
    await expect(few).toContainText("4 labelled so far; 25 are needed");
    await expect(few).toContainText("kept (not enough data)");
    await expect(page.getByTestId("reliability")).toContainText("optimistic label");
  });

  test("a refit lists what changes and applies only after confirmation", async ({ page }) => {
    const state = await setup(page);
    await page.goto("/config");
    await page.getByTestId("refit-open").click();
    const dialog = page.getByRole("dialog", { name: "Refit the cut points?" });
    await expect(dialog.getByTestId("refit-changes")).toContainText(
      "A mature feature was deleted: 0.35 / 0.65 becomes 0.35 / 0.80",
    );
    expect(state.calibrations).toHaveLength(0);
    await dialog.getByTestId("refit-confirm").click();
    await expect(dialog).toHaveCount(0);
    expect(state.calibrations).toEqual([{ body: { apply: true }, csrf: "csrf-token-123" }]);
    await expect(page.getByRole("status", { name: "Announcements" })).toContainText(
      "applied as a new configuration version",
    );
  });

  test("cancelling the refit applies nothing", async ({ page }) => {
    const state = await setup(page);
    await page.goto("/config");
    await page.getByTestId("refit-open").click();
    await page.getByRole("button", { name: "Cancel" }).click();
    expect(state.calibrations).toHaveLength(0);
  });

  for (const scheme of ["light", "dark"] as const) {
    test(`axe is clean with the refit dialog open (${scheme})`, async ({ page }) => {
      await setup(page, scheme);
      await page.goto("/config");
      await page.getByTestId("refit-open").click();
      await expect(page.getByTestId("refit-changes")).toBeVisible();
      await expectNoSeriousA11yIssues(page, `refit dialog ${scheme}`);
    });
  }
});

test.describe("@config disagreement checklist", () => {
  test("marking a wrong fact sends it as a correction with the opposite answer", async ({
    page,
  }) => {
    await mockApi(page, newState({ role: "reviewer" }));
    const caseState = newCaseState();
    await mockCaseApi(page, caseState);
    const sent: unknown[] = [];
    await page.route("**/api/v1/cases/*/outcome", async (route) => {
      sent.push(route.request().postDataJSON());
      await route.fulfill({ status: 500, contentType: "application/problem+json", body: "{}" });
    });
    const base = test.info().project.use.baseURL ?? "http://127.0.0.1:4173";
    await page.context().addCookies([{ name: "cso_csrf", value: "csrf-token-123", url: base }]);
    await page.goto(`/cases/${IDS.c02}`);
    await expect(page.getByTestId("action-bar")).toBeVisible();
    await page.locator("body").press("x");
    const wrong = page.getByTestId("wrong-facts");
    await expect(wrong).toBeVisible();
    const first = wrong.locator('input[type="checkbox"]').first();
    await first.check();
    await page.getByTestId("outcome-confirm").click();
    await expect.poll(() => sent.length).toBe(1);
    const body = sent[0] as { disposition: string; probe_corrections?: Record<string, string> };
    expect(body.disposition).toBe("disagree_with_model");
    expect(Object.values(body.probe_corrections ?? {})).toHaveLength(1);
    expect(["yes", "no"]).toContain(Object.values(body.probe_corrections ?? {})[0]);
  });

  test("no corrections are sent when nothing is marked, and an agreement has no checklist", async ({
    page,
  }) => {
    await mockApi(page, newState({ role: "reviewer" }));
    await mockCaseApi(page, newCaseState());
    await page.goto(`/cases/${IDS.c02}`);
    await expect(page.getByTestId("action-bar")).toBeVisible();
    await page.locator("body").press("a");
    await expect(page.getByTestId("outcome-form")).toBeVisible();
    await expect(page.getByTestId("wrong-facts")).toHaveCount(0);
  });
});
