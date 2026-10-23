import { expect, test, type Page } from "@playwright/test";

import { mockCaseApi, newCaseState } from "./case.fixtures";
import { mockDraftApi, newDraftState, type DraftMockState } from "./draft.fixtures";
import { expectNoSeriousA11yIssues, mockApi, newState } from "./support";

async function setup(
  page: Page,
  options: { scheme?: "light" | "dark"; overrides?: Partial<DraftMockState> } = {},
): Promise<DraftMockState> {
  const shell = newState({ role: "admin", displayName: "Test Admin" });
  if (options.scheme) await page.emulateMedia({ colorScheme: options.scheme });
  await mockApi(page, shell);
  await mockCaseApi(page, newCaseState());
  const state = newDraftState(shell, options.overrides);
  await mockDraftApi(page, state);
  const base = test.info().project.use.baseURL ?? "http://127.0.0.1:4173";
  await page.context().addCookies([{ name: "cso_csrf", value: "csrf-token-123", url: base }]);
  return state;
}

test.describe("@config community packs", () => {
  test("lists the packs and marks the one in use", async ({ page }) => {
    await setup(page);
    await page.goto("/config");
    const list = page.getByTestId("pack-list");
    await expect(list.locator("[data-pack]")).toHaveCount(2);
    await expect(list.locator('[data-pack="default"]')).toContainText("In use");
    await expect(list.locator('[data-pack="default"]').getByTestId("pack-switch")).toHaveCount(0);
    await expect(list.locator('[data-pack="strict-review"]')).toContainText("Closer scrutiny.");
  });

  test("switching shows what would change first, then switches with the CSRF header", async ({
    page,
  }) => {
    const state = await setup(page);
    await page.goto("/config");
    await page.locator('[data-pack="strict-review"]').getByTestId("pack-switch").click();

    const dialog = page.getByRole("dialog", { name: "Switch to the Strict review pack?" });
    await expect(dialog).toBeVisible();
    const diff = dialog.getByTestId("pack-diff");
    await expect(diff).toContainText("R1.min_age_days");
    await expect(diff).toContainText("365");
    await expect(diff).toContainText("180");
    expect(state.packActivations).toHaveLength(0); // nothing happens before the confirmation

    await dialog.getByTestId("pack-confirm").click();
    await expect(dialog).toHaveCount(0);
    expect(state.packActivations).toEqual([{ id: "strict-review", csrf: "csrf-token-123" }]);
    await expect(page.locator('[data-pack="strict-review"]')).toContainText("In use");
    await expect(page.locator('[data-pack="default"]').getByTestId("pack-switch")).toBeVisible();
    await expect(page.getByRole("status", { name: "Announcements" })).toContainText(
      "Switched to the Strict review pack",
    );
  });

  test("cancelling the dialog changes nothing", async ({ page }) => {
    const state = await setup(page);
    await page.goto("/config");
    await page.locator('[data-pack="strict-review"]').getByTestId("pack-switch").click();
    await page.getByRole("button", { name: "Cancel" }).click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    expect(state.packActivations).toHaveLength(0);
    await expect(page.locator('[data-pack="default"]')).toContainText("In use");
  });

  test("Escape closes the dialog and returns focus to the switch button", async ({ page }) => {
    await setup(page);
    await page.goto("/config");
    const button = page.locator('[data-pack="strict-review"]').getByTestId("pack-switch");
    await button.click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(button).toBeFocused();
  });

  test("a failed pack list says so without breaking the rest of the screen", async ({ page }) => {
    await setup(page, { overrides: { packsFail: true } });
    await page.goto("/config");
    await expect(page.getByTestId("packs-error")).toBeVisible();
    await expect(page.getByTestId("config-yaml-text")).toBeVisible();
  });

  for (const scheme of ["light", "dark"] as const) {
    test(`axe is clean with the switch dialog open (${scheme})`, async ({ page }) => {
      await setup(page, { scheme });
      await page.goto("/config");
      await page.locator('[data-pack="strict-review"]').getByTestId("pack-switch").click();
      await expect(page.getByTestId("pack-diff")).toBeVisible();
      await expectNoSeriousA11yIssues(page, `packs dialog ${scheme}`);
    });
  }
});
