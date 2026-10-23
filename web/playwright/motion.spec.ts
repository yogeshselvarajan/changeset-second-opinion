import { existsSync, readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { expectNoSeriousA11yIssues } from "./support";

/**
 * Motion on the home page: the animation library loads lazily, the
 * page is complete without it, the pinned story settles on finished pictures, and less motion means
 * no triggers at all.
 */

const DIST = resolve(process.cwd(), "dist", "assets");

function chunkTexts(): { name: string; text: string }[] {
  if (!existsSync(DIST)) return [];
  return readdirSync(DIST)
    .filter((name) => name.endsWith(".js"))
    .map((name) => ({ name, text: readFileSync(resolve(DIST, name), "utf-8") }));
}

async function settle(page: Page, pixels: number) {
  await page.mouse.move(700, 450);
  for (let done = 0; done < pixels; done += 100) {
    await page.mouse.wheel(0, 100);
    await page.waitForTimeout(30);
  }
  await page.waitForTimeout(1600);
}

async function reachStory(page: Page) {
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("data-motion", "gsap", { timeout: 10_000 });
  const top = await page.evaluate(() => {
    const el = document.querySelector(".story-stage");
    return el ? Math.round(el.getBoundingClientRect().top + window.scrollY) : 0;
  });
  await page.evaluate((y) => window.scrollTo(0, y), top - 400);
  await page.waitForTimeout(500);
}

const ringsOpacity = (page: Page) =>
  page.evaluate(() => Number(document.querySelector<SVGElement>(".st-rings")?.style.opacity ?? 0));

test.describe("@motion home page motion", () => {
  test("the animation library is its own chunk, not in the first load", () => {
    const chunks = chunkTexts();
    test.skip(chunks.length === 0, "needs a build");
    const holders = chunks.filter((chunk) => chunk.text.includes("ScrollTrigger"));
    expect(holders.length).toBeGreaterThan(0);
    for (const chunk of chunks) {
      if (/^(index|LandingRoutes)-/.test(chunk.name)) {
        expect(chunk.text, chunk.name).not.toContain("ScrollTrigger");
      }
    }
  });

  test("with reduced motion nothing is fetched or animated, and the page is complete", async ({
    page,
  }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    const urls: string[] = [];
    page.on("request", (request) => urls.push(request.url()));
    await page.goto("/");
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(800);
    await expect(page.locator("html")).not.toHaveAttribute("data-motion", "gsap");
    await expect(page.locator("[data-story]")).toBeHidden();
    const animationChunks = chunkTexts()
      .filter((chunk) => chunk.text.includes("ScrollTrigger"))
      .map((chunk) => chunk.name);
    expect(animationChunks.length).toBeGreaterThan(0);
    expect(urls.filter((url) => animationChunks.some((name) => url.endsWith(`/${name}`)))).toEqual(
      [],
    );
    const running = await page.evaluate(
      () =>
        document
          .getAnimations()
          .filter((animation) => animation.playState === "running" && animation.effect !== null)
          .length,
    );
    expect(running).toBe(0);
    await expect(page.locator("#decider .flow-bar")).toHaveCount(5);
    await expect(page.getByTestId("made-by")).toBeVisible();
  });

  test("on a wide screen the story pins and settles on a finished picture each time", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await reachStory(page);
    await expect(page.locator("[data-story]")).toHaveClass(/is-on/);
    await settle(page, 1100);
    // Read: the evidence has moved into its column and the rings have not started.
    expect(await ringsOpacity(page)).toBe(0);
    await settle(page, 900);
    // Ask: every ring is drawn.
    expect(await ringsOpacity(page)).toBeGreaterThan(0.9);
    const drawn = await page.evaluate(() => {
      const fill = document.querySelector(".st-ring .st-fill");
      return fill ? getComputedStyle(fill).strokeDasharray : "none";
    });
    expect(drawn).not.toBe("none");
    await settle(page, 1500);
    // Write: the draft card is shown and the rings step back.
    const draft = await page.evaluate(() =>
      Number(document.querySelector<SVGElement>(".st-draft")?.style.opacity ?? 0),
    );
    expect(draft).toBeGreaterThan(0.9);
    expect(await ringsOpacity(page)).toBeLessThan(0.3);
  });

  test("the story is accessible at each stop", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await reachStory(page);
    for (const pixels of [1100, 900, 1500]) {
      await settle(page, pixels);
      await expectNoSeriousA11yIssues(page, `the story after ${pixels} px`);
    }
  });

  test("on a phone nothing pins, nothing overflows and the three cards carry the story", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    await expect(page.locator("html")).toHaveAttribute("data-motion", "gsap", { timeout: 10_000 });
    await expect(page.locator("[data-story]")).toBeHidden();
    await expect(page.locator(".pin-spacer")).toHaveCount(0);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
    await expect(page.locator("#how h3")).toHaveCount(3);
  });

  test("the Less motion switch does what the system setting does, and is remembered", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/");
    await expect(page.locator("html")).toHaveAttribute("data-motion", "gsap", { timeout: 10_000 });
    const toggle = page.getByTestId("motion-switch");
    await toggle.click();
    await expect(page.locator("html")).toHaveAttribute("data-less-motion", "true");
    await expect(page.locator("html")).not.toHaveAttribute("data-motion", "gsap");
    await expect(page.locator("[data-story]")).toBeHidden();
    await expect(toggle).toHaveText("Full motion");
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-less-motion", "true");
    await expect(page.locator("html")).not.toHaveAttribute("data-motion", "gsap");
    await page.getByTestId("motion-switch").click();
    await expect(page.locator("html")).not.toHaveAttribute("data-less-motion", "true");
    await expect(page.locator("html")).toHaveAttribute("data-motion", "gsap", { timeout: 10_000 });
  });

  test("the headlines are split for the eye and still read as one heading", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/");
    await expect(page.locator("html")).toHaveAttribute("data-motion", "gsap", { timeout: 10_000 });
    const heading = page.locator("#modes-title");
    await heading.scrollIntoViewIfNeeded();
    await expect(heading).toHaveAccessibleName("In the browser or on the command line.");
  });
});
