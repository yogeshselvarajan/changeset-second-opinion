import { expect, test, type Page } from "@playwright/test";

import { expectNoSeriousA11yIssues, mockApi, newState, shellReady } from "./support";

const ORIGIN = "http://127.0.0.1:4173";

async function withCsrfCookie(page: Page) {
  await page.context().addCookies([{ name: "cso_csrf", value: "csrf-token-123", url: ORIGIN }]);
}

test.describe("@claim claiming a fresh workspace", () => {
  test("the first OpenStreetMap sign-in is offered the claim, and one confirmed step makes them admin", async ({
    page,
  }) => {
    const state = newState({
      role: "reviewer",
      mode: "live",
      displayName: "First Mapper",
      viaOsm: true,
      osmSignin: true,
      canClaim: true,
    });
    await mockApi(page, state);
    await withCsrfCookie(page);
    await page.goto("/queue");
    await shellReady(page);

    const banner = page.getByTestId("claim-banner");
    await expect(banner).toContainText("This workspace has no admin yet");
    await expect(page.getByTestId("nav-settings")).toHaveCount(0);

    await page.getByTestId("claim-open").click();
    const dialog = page.getByRole("dialog", { name: "Claim this workspace?" });
    await expect(dialog).toContainText("only once");
    await dialog.getByTestId("claim-confirm").click();

    await expect(banner).toHaveCount(0);
    expect(state.claimRequests).toHaveLength(1);
    expect(state.claimRequests[0]?.csrf).toBe("csrf-token-123");
    await expect(page.getByTestId("role-badge")).toContainText("Admin");
    await expect(page.getByTestId("nav-settings")).toBeVisible();
  });

  test("Not now closes the dialog and sends nothing", async ({ page }) => {
    const state = newState({ role: "reviewer", viaOsm: true, canClaim: true });
    await mockApi(page, state);
    await page.goto("/queue");
    await shellReady(page);
    await page.getByTestId("claim-open").click();
    await page.getByRole("button", { name: "Not now" }).click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    expect(state.claimRequests).toHaveLength(0);
    await expect(page.getByTestId("claim-banner")).toBeVisible();
  });

  test("if someone else claimed first, the dialog says so in plain words", async ({ page }) => {
    const state = newState({ role: "reviewer", viaOsm: true, canClaim: true, claim: 409 });
    await mockApi(page, state);
    await withCsrfCookie(page);
    await page.goto("/queue");
    await shellReady(page);
    await page.getByTestId("claim-open").click();
    await page.getByTestId("claim-confirm").click();
    await expect(page.getByTestId("claim-error")).toContainText("Someone else may have claimed");
    await expect(page.getByRole("dialog")).toBeVisible();
  });

  test("nobody else sees the banner: not an admin, not a viewer, not a claimed workspace", async ({
    page,
  }) => {
    for (const role of ["viewer", "admin"] as const) {
      const state = newState({ role, canClaim: false });
      await page.unroute("**/api/v1/**");
      await mockApi(page, state);
      await page.goto("/queue");
      await shellReady(page);
      await expect(page.getByTestId("claim-banner")).toHaveCount(0);
    }
  });

  test("the banner passes the accessibility scan", async ({ page }) => {
    await mockApi(page, newState({ role: "reviewer", viaOsm: true, canClaim: true }));
    await page.goto("/queue");
    await shellReady(page);
    await expect(page.getByTestId("claim-banner")).toBeVisible();
    await expectNoSeriousA11yIssues(page, "claim banner");
  });
});
