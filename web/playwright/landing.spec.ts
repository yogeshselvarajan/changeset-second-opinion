import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { expectNoSeriousA11yIssues } from "./support";

const PUBLIC_PAGES = ["/", "/about", "/privacy"] as const;
const HEADLINE = "Every flagged edit deserves a second opinion.";
const BANNED = /\b(vandal\w*|spam\w*|illegal\w*|stop|must)\b/i;
const DASHES = new RegExp(`[${String.fromCharCode(0x2013, 0x2014)}]`);

async function watchRequests(page: Page): Promise<string[]> {
  const urls: string[] = [];
  page.on("request", (request) => urls.push(request.url()));
  return urls;
}

test.describe("@landing home page", () => {
  test("its only API call is the public branding, with no cookie and no third party script", async ({
    page,
    context,
  }) => {
    const urls = await watchRequests(page);
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(HEADLINE);
    await page.waitForLoadState("networkidle");
    const origin = new URL(page.url()).origin;
    const api = urls.filter((u) => u.includes("/api/")).map((u) => new URL(u).pathname);
    expect(api).toEqual(["/api/v1/public/branding"]);
    expect(urls.filter((u) => !u.startsWith(origin) && !u.startsWith("data:"))).toEqual([]);
    expect(await context.cookies()).toEqual([]);
  });

  test("the workspace's name, logo, accent and paragraph replace the built-in ones", async ({
    page,
  }) => {
    await page.route("**/api/v1/public/branding", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          name: "Second Opinion Lyon",
          tagline: "Local eyes on flagged edits.",
          accent_hex: "#3A46B0",
          accent_dark_hex: "#6D76C5",
          community_paragraph: "We review for the Lyon mapping community.",
          has_logo: true,
          osm_signin_enabled: false,
        }),
      }),
    );
    await page.goto("/");
    await expect(page.locator("header").first()).toContainText("Second Opinion Lyon");
    await expect(page.getByTestId("community-paragraph")).toHaveText(
      "We review for the Lyon mapping community.",
    );
    await expect(page.locator('header img[src="/api/v1/public/branding/logo.svg"]')).toHaveCount(1);
    const accent = await page.evaluate(() =>
      getComputedStyle(document.documentElement).getPropertyValue("--color-accent").trim(),
    );
    expect(accent).toBe("#3A46B0");
    // The headline is the product's own sentence and stays.
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(HEADLINE);
  });

  test("the sections come in the order the brief gives", async ({ page }) => {
    await page.goto("/");
    const headings = await page.getByRole("heading", { level: 2 }).allInnerTexts();
    expect(headings).toEqual([
      "The map belongs to everyone. So does looking after it.",
      "Flaggers hand you a queue. They do not hand you understanding.",
      "From flag to reply on one calm screen.",
      "A small model that gives a reading, not a paragraph.",
      "From a flagged changeset to your reply.",
      "Every answer sits next to what it was shown.",
      "A receipt for every verdict.",
      "Three things it will not do.",
      "Tuned to how your community works.",
      "Two models, each with one small job.",
      "In the browser or on the command line.",
      "It does not replace your tools. It explains their output.",
      "What it can do today, said plainly.",
      "Built in the open, for everyone who looks after the map.",
      "Made by Yogesh Selvarajan.",
      "Give the next flagged edit a second opinion.",
    ]);
    await expect(page.locator("h1")).toHaveCount(1);
    await expect(page.getByTestId("open-queue")).toHaveAttribute("href", "/queue");
  });

  test("the decision model, the ways to use it and who made it are on the home page", async ({
    page,
  }) => {
    await page.goto("/");
    const decider = page.locator("#decider");
    await expect(decider.getByText("Strands Decider 2B").first()).toBeVisible();
    await expect(decider.locator(".flow-bar")).toHaveCount(5);
    await expect(decider.getByText(/real run on changeset 189806470/)).toBeVisible();
    await expect(page.locator("#use h3")).toHaveText([
      "The web app",
      "Workspaces and admins",
      "The command line",
    ]);
    const links = page.getByTestId("maker-links").getByRole("link");
    // Hackathon page, LinkedIn, Builder Center, email, sponsor.
    await expect(links).toHaveCount(5);
    await expect(links.nth(1)).toHaveAttribute(
      "href",
      "https://www.linkedin.com/in/yogesh-selvarajan/",
    );
    await expect(links.nth(2)).toHaveAttribute(
      "href",
      "https://builder.aws.com/community/@yogeshs",
    );
    await expect(links.nth(3)).toHaveAttribute("href", "mailto:yogeshselvarajan@gmail.com");
    await expect(page.getByTestId("made-by").getByRole("link")).toHaveAttribute(
      "href",
      "https://www.linkedin.com/in/yogesh-selvarajan/",
    );
  });

  test("the about page shows the figures counted from the demo runs", async ({ page }) => {
    await page.goto("/about");
    await expect(page.getByTestId("glance-tile")).toHaveCount(6);
    await expect(page.getByTestId("glance-tile").first()).toContainText("15");
    await expect(page.getByTestId("numbers-disclosure")).toContainText("answer key");
  });

  test("the home page sells the outcome: no engineering terms, no figures", async ({ page }) => {
    await page.goto("/");
    const text = await page.locator("main").innerText();
    for (const word of ["SQLite", "probe", "353 of 413", "&nearr;"]) {
      expect(text, word).not.toContain(word);
    }
    const engine = page.locator("#engine");
    await expect(engine.getByRole("link", { name: /Model on Hugging Face/ })).toHaveAttribute(
      "href",
      /huggingface\.co\/StrandsAgents\/strands-decider-2B/,
    );
    await expect(page.getByTestId("made-by")).toHaveText("Made by Yogesh");
    await expect(page.getByText(/written by an AI/)).toBeVisible();
    await expect(page.getByTestId("scorecard-link")).toHaveAttribute("href", "/about#numbers");
  });

  test("the map draws itself and the cards appear, or sit still when motion is reduced", async ({
    page,
  }) => {
    await page.goto("/");
    await expect(page.locator(".lm-callout")).toHaveCount(4);
    await expect(page.locator(".lm-callout").first()).toHaveCSS("opacity", "1", {
      timeout: 6000,
    });
    const reduced = await page.context().newPage();
    await reduced.emulateMedia({ reducedMotion: "reduce" });
    await reduced.goto("/");
    await expect(reduced.locator(".lm-callout").last()).toHaveCSS("opacity", "1");
    await reduced.close();
  });

  test("the pack picker changes its text with the keyboard", async ({ page }) => {
    await page.goto("/");
    // Until the script has run the radios are plain HTML, so try again until the page is live.
    await expect(async () => {
      await page.getByTestId("pack-default").focus();
      await page.keyboard.press("ArrowRight");
      await expect(page.getByTestId("pack-newcomer-friendly")).toBeChecked({ timeout: 1000 });
      await expect(page.getByText(/welcome before a question/)).toBeVisible({ timeout: 1000 });
    }).toPass({ timeout: 15_000 });
    await expect(page.getByText(/welcome before a question/)).toBeVisible();
  });
});

test.describe("@landing about page", () => {
  test("the figures and their disclosure come from the evaluation files", async ({ page }) => {
    await page.goto("/about");
    const numbers = page.locator("#numbers").locator("..");
    await expect(numbers).toContainText("353 of 413");
    await expect(numbers).toContainText("450 of 528");
    await expect(page.getByTestId("numbers-disclosure")).toContainText("written by an AI");
    await expect(page.getByTestId("numbers-disclosure")).toContainText("not human validated");
  });

  test("the written file holds the figures, so a crawler needs no script", () => {
    const html = readFileSync(resolve("dist", "about/index.html"), "utf-8");
    expect(html).toContain("353 of 413");
  });
});

test.describe("@landing home page, continued", () => {
  test("the example receipt says it is an example and links nowhere live", async ({ page }) => {
    await page.goto("/");
    const section = page.locator("#receipt");
    await expect(section).toContainText("An example receipt built from invented data");
    await expect(
      section.getByRole("heading", { level: 3, name: /Decision receipt/ }),
    ).toBeVisible();
    await expect(section.getByRole("link", { name: /Open the changeset/ })).toHaveCount(0);
  });

  test("the command block on the about page copies its text", async ({ page, context }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    await page.goto("/about");
    // The page is static HTML until the script has run; a click before that does nothing, so
    // click again until the button has been wired.
    await expect(async () => {
      await page.getByRole("button", { name: "Copy" }).click();
      await expect(page.getByRole("status").filter({ hasText: "Copied" })).toBeVisible({
        timeout: 1500,
      });
    }).toPass({ timeout: 15_000 });
    const text = await page.evaluate(() => navigator.clipboard.readText());
    expect(text).toContain("uv run cso api");
    expect(text).toContain("git clone ");
  });

  test("reduced motion gives a still strip", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/");
    await expect(page.getByTestId("evidence-strip").first()).toHaveAttribute(
      "data-animated",
      "false",
    );
  });

  test("the static file has the content, so a crawler needs no script", async ({ request }) => {
    const html = await (await request.get("/")).text();
    expect(html.match(/<h1[\s>]/g)).toHaveLength(1);
    expect(html).toContain("second opinion.");
    expect(html).toContain("Three things it will not do.");
    expect(html).toContain('"@type":"SoftwareApplication"');
  });
});

test.describe("@landing public pages", () => {
  for (const path of PUBLIC_PAGES) {
    test(`${path}: no banned words and no dashes in what a visitor reads`, async ({ page }) => {
      await page.goto(path);
      const text = await page.locator("body").innerText();
      expect(text).not.toMatch(BANNED);
      expect(text).not.toMatch(DASHES);
      expect(text).not.toContain("!");
    });

    for (const scheme of ["light", "dark"] as const) {
      test(`${path}: axe finds no serious issue (${scheme})`, async ({ page }) => {
        await page.emulateMedia({ colorScheme: scheme, reducedMotion: "reduce" });
        await page.goto(path);
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
        await expectNoSeriousA11yIssues(page, `${path} ${scheme}`);
      });
    }
  }

  // `vite preview` answers every address with the home page, so the written files are read from
  // dist/ (the Caddy config serves them as `/about/index.html` and so on).
  test("about and privacy are written as real pages with their own title and one h1", () => {
    for (const [file, title] of [
      ["about/index.html", "About · Changeset Second Opinion"],
      ["privacy/index.html", "Privacy · Changeset Second Opinion"],
    ] as const) {
      const html = readFileSync(resolve("dist", file), "utf-8");
      expect(html).toContain(`<title data-static-seo>${title}</title>`);
      expect(html.match(/<h1[\s>]/g)).toHaveLength(1);
      expect(html).not.toContain("noindex");
    }
  });

  test("the 404 page is written and asks not to be indexed", () => {
    const html = readFileSync(resolve("dist", "404.html"), "utf-8");
    expect(html).toContain("Page not found");
    expect(html).toMatch(/name="robots"[^>]*noindex/);
  });

  test("the app is not part of the public bundle: the home page loads no app chunk", async ({
    page,
  }) => {
    const urls = await watchRequests(page);
    await page.goto("/");
    await page.waitForLoadState("networkidle");
    const files = urls.filter((u) => u.includes("/assets/")).map((u) => u.split("/").pop() ?? "");
    for (const heavy of ["AppShell", "queue.page", "cases._id.page", "history.page", "maplibre"]) {
      expect(
        files.filter((f) => f.startsWith(heavy)),
        heavy,
      ).toEqual([]);
    }
  });

  test("a client side visit to the home page keeps one title and the page head", async ({
    page,
  }) => {
    await page.goto("/");
    // Same text as HOME_TITLE in src/landing/pages.ts.
    await expect(page).toHaveTitle("Changeset Second Opinion: flagged OpenStreetMap edits");
    expect(await page.locator("head title").count()).toBe(1);
    expect(await page.locator('head link[rel="canonical"]').count()).toBe(1);
    // React renders the structured data where the page puts it; the static copy was replaced.
    expect(await page.locator('script[type="application/ld+json"]').count()).toBe(1);
  });
});
