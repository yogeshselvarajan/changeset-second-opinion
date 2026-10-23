import { expect, test } from "@playwright/test";

import { expectNoSeriousA11yIssues, mockApi, newState } from "./support";

test.describe("@auth sign in with OpenStreetMap", () => {
  test("the button is hidden when the server has not set the feature up", async ({ page }) => {
    await mockApi(page, newState({ osmSignin: false }));
    await page.goto("/login");
    await expect(page.getByRole("heading", { level: 1, name: "Sign in" })).toBeVisible();
    await expect(page.getByTestId("osm-signin")).toHaveCount(0);
    await expect(page.getByLabel("Invite code")).toBeVisible();
  });

  test("the button leads to the server's start route and says what is read", async ({ page }) => {
    await mockApi(page, newState({ osmSignin: true }));
    await page.goto("/login");
    const button = page.getByRole("link", { name: "Sign in with OpenStreetMap" });
    await expect(button).toHaveAttribute("href", "/api/v1/auth/osm/start");
    await expect(
      page.getByText("Nothing is ever changed on the map", { exact: false }),
    ).toBeVisible();
    await expect(page.getByLabel("Invite code")).toBeVisible(); // the invite form stays
  });

  test("a sign-in that comes back denied shows a plain message and the form", async ({ page }) => {
    await mockApi(page, newState({ osmSignin: true }));
    await page.route("**/api/v1/auth/osm/start", (route) =>
      route.fulfill({ status: 302, headers: { location: "/login?osm_error=denied" } }),
    );
    await page.goto("/login");
    await page.getByTestId("osm-signin").click();
    await expect(page).toHaveURL(/osm_error=denied/);
    await expect(page.getByTestId("osm-error")).toContainText("cancelled");
    await expect(page.getByLabel("Invite code")).toBeVisible();
  });

  const cases: Record<string, string> = {
    denied: "cancelled",
    expired: "expired or was already used",
    failed: "did not complete",
    busy: "Too many sign-in attempts",
    not_allowed: "not on the list",
  };
  for (const [code, text] of Object.entries(cases)) {
    test(`the ${code} error is explained`, async ({ page }) => {
      await mockApi(page, newState({ osmSignin: true }));
      await page.goto(`/login?osm_error=${code}`);
      await expect(page.getByTestId("osm-error")).toContainText(text);
    });
  }

  test("an unknown error code shows nothing and is never echoed", async ({ page }) => {
    await mockApi(page, newState({ osmSignin: true }));
    await page.goto("/login?osm_error=%3Cb%3Ehello%3C%2Fb%3E");
    await expect(page.getByTestId("osm-error")).toHaveCount(0);
    await expect(page.getByText("hello")).toHaveCount(0);
  });

  test("the top strip says who is reviewing after an OpenStreetMap sign-in", async ({ page }) => {
    await mockApi(
      page,
      newState({ role: "reviewer", displayName: "Mapper Mae", osmSignin: true, viaOsm: true }),
    );
    await page.goto("/queue");
    await expect(page.getByTestId("reviewing-as")).toHaveText(/Reviewing as Mapper Mae/);
  });

  test("an invite-code session does not claim to be an OpenStreetMap account", async ({ page }) => {
    await mockApi(page, newState({ role: "reviewer", displayName: "Invited", viaOsm: false }));
    await page.goto("/queue");
    await expect(page.getByTestId("reviewing-as")).toHaveCount(0);
  });

  for (const scheme of ["light", "dark"] as const) {
    test(`axe is clean on the login page with the button and an error (${scheme})`, async ({
      page,
    }) => {
      // the sample strip on this page fades in; axe must not sample it mid-fade
      await page.emulateMedia({ colorScheme: scheme, reducedMotion: "reduce" });
      await mockApi(page, newState({ osmSignin: true }));
      await page.goto("/login?osm_error=expired");
      await expect(page.getByTestId("osm-error")).toBeVisible();
      await expectNoSeriousA11yIssues(page, `login osm ${scheme}`);
    });
  }
});
