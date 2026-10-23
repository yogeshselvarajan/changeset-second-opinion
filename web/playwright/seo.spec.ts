import { expect, test } from "@playwright/test";

import { mockApi, newState } from "./support";

test.describe("@seo head and static files", () => {
  test("the queue has its own title and one title element", async ({ page }) => {
    await mockApi(page, newState());
    await page.goto("/queue");
    await expect(page).toHaveTitle("Queue · Changeset Second Opinion");
    expect(await page.locator("head title").count()).toBe(1);
    expect(await page.locator('head meta[name="description"]').count()).toBe(1);
  });

  test("the login page asks not to be indexed", async ({ page }) => {
    await mockApi(page, newState());
    await page.goto("/login");
    await expect(page).toHaveTitle("Sign in · Changeset Second Opinion");
    await expect(page.locator('head meta[name="robots"]')).toHaveAttribute("content", "noindex");
  });

  test("moving between screens keeps one title and follows the screen", async ({ page }) => {
    await mockApi(page, newState());
    await page.goto("/queue");
    await page.getByRole("link", { name: "History" }).first().click();
    await expect(page).toHaveTitle("History · Changeset Second Opinion");
    expect(await page.locator("head title").count()).toBe(1);
  });

  test("an unknown address keeps the plain site title", async ({ page }) => {
    await mockApi(page, newState());
    await page.goto("/nowhere-at-all");
    await expect(page).toHaveTitle("Changeset Second Opinion");
  });

  test("the head carries the icons, the manifest and the social card", async ({ page }) => {
    await mockApi(page, newState());
    await page.goto("/queue");
    for (const selector of [
      'link[rel="icon"][href="/favicon.svg"]',
      'link[rel="icon"][href="/favicon.ico"]',
      'link[rel="apple-touch-icon"][href="/apple-touch-icon.png"]',
      'link[rel="manifest"][href="/site.webmanifest"]',
      'meta[name="color-scheme"][content="light dark"]',
      'meta[property="og:type"][content="website"]',
      'meta[name="twitter:card"][content="summary_large_image"]',
    ]) {
      expect(await page.locator(`head ${selector}`).count(), selector).toBe(1);
    }
    const image = await page.locator('head meta[property="og:image"]').getAttribute("content");
    expect(image).toMatch(/\/og\.png$/);
    expect(await page.locator('head meta[name="theme-color"]').count()).toBe(2);
  });

  test("the static files are served with a sensible type", async ({ request }) => {
    const expected: Record<string, RegExp> = {
      "/favicon.ico": /icon/,
      "/favicon.svg": /svg/,
      "/site.webmanifest": /(manifest|json)/,
      "/robots.txt": /text\/plain/,
      "/sitemap.xml": /xml/,
      "/og.png": /png/,
      "/apple-touch-icon.png": /png/,
    };
    for (const [path, type] of Object.entries(expected)) {
      const response = await request.get(path);
      expect(response.status(), path).toBe(200);
      expect(response.headers()["content-type"], path).toMatch(type);
    }
  });

  test("robots.txt and the sitemap carry a real origin, not the placeholder", async ({
    request,
  }) => {
    const robots = await (await request.get("/robots.txt")).text();
    expect(robots).not.toContain("__CSO_PUBLIC_ORIGIN__");
    expect(robots).toMatch(/Sitemap: https?:\/\/\S+\/sitemap\.xml/);
    const sitemap = await (await request.get("/sitemap.xml")).text();
    expect(sitemap).toContain("<loc>");
    expect(sitemap).not.toContain("/queue");
  });
});
