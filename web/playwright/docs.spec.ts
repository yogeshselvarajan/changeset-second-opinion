import { expect, test } from "@playwright/test";

// The docs site (site/) is built into dist/docs by `npm run build` and served at /docs/ on the same
// origin as the app. `vite preview` answers /docs through the docs middleware in vite.docs.ts, which
// returns a real 404 for an unknown docs path, the same as the Caddy edge does.
test.describe("@docs the docs route", () => {
  test("the docs home is served at /docs/", async ({ page }) => {
    const response = await page.goto("/docs/");
    expect(response?.status()).toBe(200);
    await expect(page).toHaveTitle(/Changeset Second Opinion/);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  });

  test("a nested page renders its heading", async ({ page }) => {
    const response = await page.goto("/docs/start/quickstart/");
    expect(response?.status()).toBe(200);
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Quickstart");
  });

  test("/docs redirects to /docs/", async ({ request }) => {
    const response = await request.get("/docs", { maxRedirects: 0 });
    expect([301, 302, 307, 308]).toContain(response.status());
    expect(new URL(response.headers()["location"] ?? "", "http://x").pathname).toBe("/docs/");
  });

  test("the public nav Docs link opens the docs", async ({ page }) => {
    await page.goto("/");
    await page
      .getByRole("navigation", { name: "Site" })
      .first()
      .getByRole("link", { name: "Docs" })
      .click();
    await expect(page).toHaveURL(/\/docs\/$/);
    await expect(page).toHaveTitle(/Changeset Second Opinion/);
  });

  test("an unknown docs path is a 404 and not the app shell", async ({ page }) => {
    const response = await page.goto("/docs/nope/");
    expect(response?.status()).toBe(404);
    // The app shell mounts a #root element; the docs 404 page never does.
    await expect(page.locator("#root")).toHaveCount(0);
  });
});
