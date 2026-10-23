import { expect, test, type Page } from "@playwright/test";

import { expectNoSeriousA11yIssues, mockApi, newState, shellReady } from "./support";

const ORIGIN = "http://127.0.0.1:4173";
const SHOTS = "test-results/screenshots";

async function withCsrfCookie(page: Page, value = "csrf-token-123") {
  await page.context().addCookies([{ name: "cso_csrf", value, url: ORIGIN }]);
}

test.describe("@shell app shell", () => {
  test("the root is the home page, not the app", async ({ page }) => {
    await mockApi(page, newState());
    await page.goto("/");
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(/second opinion/);
    await expect(page.getByRole("navigation", { name: "Main navigation" })).toHaveCount(0);
  });

  test("the queue has the shell's landmarks", async ({ page }) => {
    await mockApi(page, newState());
    await page.goto("/queue");
    await shellReady(page);
    await expect(page.getByRole("banner")).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Main navigation" })).toBeVisible();
    await expect(page.getByRole("main")).toBeVisible();
    await expect(page.getByRole("heading", { level: 1, name: "Queue" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Skip to main content" })).toHaveCount(1);
  });

  test("replay mode explains itself with text and a badge", async ({ page }) => {
    await mockApi(page, newState({ mode: "replay" }));
    await page.goto("/queue");
    await expect(page.getByTestId("replay-banner")).toContainText("Nothing is fetched");
    await expect(page.getByTestId("mode-badge")).toContainText("Demo");
    await expect(page.getByTestId("role-badge")).toContainText("Viewer");
  });

  test("live mode shows no replay banner", async ({ page }) => {
    await mockApi(page, newState({ mode: "live" }));
    await page.goto("/queue");
    await expect(page.getByTestId("mode-badge")).toContainText("Live");
    await expect(page.getByTestId("replay-banner")).toHaveCount(0);
  });

  for (const scheme of ["light", "dark"] as const) {
    test(`axe finds no serious issues on /queue and /login (${scheme})`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: scheme });
      await mockApi(page, newState());
      await page.goto("/queue");
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await expectNoSeriousA11yIssues(page, `/queue ${scheme}`);
      await page.goto("/login");
      await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
      await expectNoSeriousA11yIssues(page, `/login ${scheme}`);
    });
  }

  test("axe finds no serious issues with the shortcut sheet open", async ({ page }) => {
    await mockApi(page, newState());
    await page.goto("/queue");
    await shellReady(page);
    await page.keyboard.type("?");
    await expect(page.getByRole("dialog", { name: "Keyboard shortcuts" })).toBeVisible();
    await expectNoSeriousA11yIssues(page, "shortcut sheet");
  });
});

test.describe("@shell sign in", () => {
  test("a rejected code shows one plain message and keeps nothing", async ({ page }) => {
    const state = newState({ login: 401 });
    await mockApi(page, state);
    await withCsrfCookie(page);
    await page.goto("/login");
    await page.getByLabel("Invite code").fill("cso-deadbeef-supersecretvalue");
    await page.getByLabel("Display name").fill("Pat");
    await page.getByRole("button", { name: "Sign in" }).click();

    await expect(page.getByTestId("login-error")).toContainText("not accepted");
    await expect(page.getByLabel("Invite code")).toHaveValue("");
    expect(page.url()).not.toContain("deadbeef");
    const stored = await page.evaluate(() =>
      JSON.stringify({ local: { ...localStorage }, session: { ...sessionStorage } }),
    );
    expect(stored).not.toContain("deadbeef");
    expect(state.loginRequests).toHaveLength(1);
  });

  test("the CSRF header from the cookie is sent on the login request", async ({ page }) => {
    const state = newState({ login: 401 });
    await mockApi(page, state);
    await withCsrfCookie(page, "tok-abc");
    await page.goto("/login");
    await page.getByLabel("Invite code").fill("cso-aaaa-bbbb");
    await page.getByLabel("Display name").fill("Pat");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByTestId("login-error")).toBeVisible();
    expect(state.loginRequests[0]?.csrf).toBe("tok-abc");
    expect(state.loginRequests[0]?.body).toEqual({
      invite_code: "cso-aaaa-bbbb",
      display_name: "Pat",
    });
  });

  test("a rate limit says how long to wait", async ({ page }) => {
    await mockApi(page, newState({ login: 429 }));
    await page.goto("/login");
    await page.getByLabel("Invite code").fill("cso-aaaa-bbbb");
    await page.getByLabel("Display name").fill("Pat");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByTestId("login-error")).toContainText("42 seconds");
  });

  test("a successful sign in returns to the page you asked for", async ({ page }) => {
    await mockApi(page, newState());
    await page.goto("/login?redirect=/history");
    await page.getByLabel("Invite code").fill("cso-aaaa-bbbb");
    await page.getByLabel("Display name").fill("Test Reviewer");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(/\/history$/);
    await expect(page.getByTestId("role-badge")).toContainText("Reviewer");
    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  });

  test("an off-site redirect target is ignored", async ({ page }) => {
    await mockApi(page, newState());
    await page.goto("/login?redirect=https://evil.example/");
    await page.getByLabel("Invite code").fill("cso-aaaa-bbbb");
    await page.getByLabel("Display name").fill("Test Reviewer");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(/\/queue$/);
  });

  test("signing out returns to the viewer role", async ({ page }) => {
    await mockApi(page, newState({ role: "reviewer", displayName: "Test Reviewer" }));
    await withCsrfCookie(page);
    await page.goto("/queue");
    await expect(page.getByTestId("role-badge")).toContainText("Reviewer");
    await page.getByRole("button", { name: "Sign out" }).click();
    await expect(page.getByTestId("role-badge")).toContainText("Viewer");
  });
});

test.describe("@shell preferences and keyboard", () => {
  test("theme and density persist across a reload", async ({ page }) => {
    await mockApi(page, newState());
    await page.goto("/queue");
    await page.getByLabel("Theme").selectOption("dark");
    await page.getByLabel("Density").selectOption("compact");
    await page.reload();
    const html = page.locator("html");
    await expect(html).toHaveAttribute("data-theme", "dark");
    await expect(html).toHaveAttribute("data-density", "compact");
    await expect(page.getByLabel("Theme")).toHaveValue("dark");
    const rowHeight = await page.evaluate(() =>
      getComputedStyle(document.documentElement).getPropertyValue("--row-h").trim(),
    );
    expect(rowHeight).toBe("32px");
  });

  test("choosing the system theme removes the explicit attribute", async ({ page }) => {
    await mockApi(page, newState());
    await page.goto("/queue");
    await page.getByLabel("Theme").selectOption("dark");
    await page.getByLabel("Theme").selectOption("system");
    await expect(page.locator("html")).not.toHaveAttribute("data-theme", /.+/);
  });

  test("every control in the header shows a 2 px focus ring", async ({ page }) => {
    await mockApi(page, newState());
    await page.goto("/queue");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    const seen: { tag: string; style: string; width: string; offset: string }[] = [];
    for (let i = 0; i < 14; i++) {
      await page.keyboard.press("Tab");
      const info = await page.evaluate(() => {
        const el = document.activeElement as HTMLElement | null;
        if (!el || el === document.body) return null;
        // A select sits inside a rounded pill; the pill carries the ring, not the square select.
        const ringed = (el.tagName === "SELECT" && el.closest<HTMLElement>(".cso-select")) || el;
        const css = getComputedStyle(ringed);
        return {
          tag: el.tagName,
          // the rail (an aside) holds the navigation now; the strip is still the header
          inHeaderOrSkip: !!el.closest("header, aside") || el.classList.contains("skip-link"),
          style: css.outlineStyle,
          width: css.outlineWidth,
          offset: css.outlineOffset,
        };
      });
      if (!info || !info.inHeaderOrSkip) break;
      seen.push(info);
    }
    expect(seen.length).toBeGreaterThanOrEqual(8);
    for (const entry of seen) {
      expect(entry.style).toBe("solid");
      expect(entry.width).toBe("2px");
      expect(entry.offset).toBe("2px");
    }
  });

  test("reduced motion zeroes the motion duration", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await mockApi(page, newState());
    await page.goto("/queue");
    const motion = await page.evaluate(() =>
      getComputedStyle(document.documentElement).getPropertyValue("--motion").trim(),
    );
    // the production CSS minifier writes 0ms as 0s; both are a zero duration
    expect(motion).toMatch(/^0(ms|s)$/);
  });

  test("? opens the shortcut sheet, Escape closes it, g then h goes to history", async ({
    page,
  }) => {
    await mockApi(page, newState());
    await page.goto("/queue");
    await shellReady(page);
    await page.keyboard.type("?");
    const dialog = page.getByRole("dialog", { name: "Keyboard shortcuts" });
    await expect(dialog).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await page.keyboard.press("g");
    await page.keyboard.press("h");
    await expect(page).toHaveURL(/\/history$/);
  });

  test("shortcuts stay quiet while typing in a field", async ({ page }) => {
    await mockApi(page, newState());
    await page.goto("/login");
    await page.getByLabel("Display name").focus();
    await page.keyboard.type("?gh");
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByLabel("Display name")).toHaveValue("?gh");
  });
});

test.describe("@shell routes and access", () => {
  test("an unknown address shows the not-found page inside the shell", async ({ page }) => {
    await mockApi(page, newState());
    await page.goto("/no-such-page");
    await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
    await expect(page.getByRole("banner")).toBeVisible();
  });

  test("config shows the no-access page to a viewer and the screen to an admin", async ({
    page,
  }) => {
    await mockApi(page, newState({ role: "viewer" }));
    await page.goto("/config");
    await expect(page.getByRole("heading", { name: "No access" })).toBeVisible();

    const admin = await page.context().newPage();
    await mockApi(admin, newState({ role: "admin" }));
    await admin.goto("/config");
    await expect(admin.getByRole("heading", { name: "Configuration" })).toBeVisible();
  });

  test("case, draft and history routes render their screens", async ({ page }) => {
    await mockApi(page, newState());
    await page.goto("/cases/abc");
    // The case and draft screens are real now; the shell mock knows no such
    // case, so each says so instead of showing a placeholder.
    await expect(page.getByRole("heading", { name: "Case not found" })).toBeVisible();
    await page.goto("/cases/abc/draft");
    await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
    await page.goto("/history?reviewer=x");
    await expect(page.getByRole("heading", { name: "Decision history" })).toBeVisible();
  });

  test("the browser never calls OpenStreetMap", async ({ page }) => {
    const hosts = new Set<string>();
    page.on("request", (request) => hosts.add(new URL(request.url()).hostname));
    await mockApi(page, newState());
    for (const path of ["/queue", "/login", "/history", "/cases/abc"]) await page.goto(path);
    const offSite = [...hosts].filter((host) => host.includes("openstreetmap"));
    expect(offSite).toEqual([]);
    expect([...hosts].every((host) => host === "127.0.0.1")).toBe(true);
  });
});

test.describe("@shell layout and screenshots", () => {
  for (const [name, width] of [
    ["desktop", 1280],
    ["phone", 375],
    ["zoom200", 640],
  ] as const) {
    test(`no horizontal scroll at ${width}px (${name})`, async ({ page }) => {
      await page.setViewportSize({ width, height: 800 });
      await mockApi(page, newState());
      for (const path of ["/queue", "/login"]) {
        await page.goto(path);
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
        const overflow = await page.evaluate(
          () => document.documentElement.scrollWidth - window.innerWidth,
        );
        expect(overflow, `${path} at ${width}px`).toBeLessThanOrEqual(0);
      }
    });
  }

  for (const scheme of ["light", "dark"] as const) {
    for (const [name, width] of [
      ["1280", 1280],
      ["375", 375],
    ] as const) {
      test(`screenshots ${scheme} ${name}`, async ({ page }) => {
        await page.emulateMedia({ colorScheme: scheme });
        await page.setViewportSize({ width, height: 800 });
        await mockApi(page, newState());
        for (const path of ["/queue", "/login"]) {
          await page.goto(path);
          await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
          await page.screenshot({
            path: `${SHOTS}/${path.slice(1)}-${scheme}-${name}.png`,
            fullPage: true,
          });
        }
      });
    }
  }
});

test.describe("@e2e real backend", () => {
  test.skip(!process.env.CSO_E2E_INVITE, "set CSO_E2E_INVITE (and run the API on :8000)");

  test("an invite code signs a reviewer in against the replay backend", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel("Invite code").fill(process.env.CSO_E2E_INVITE ?? "");
    await page.getByLabel("Display name").fill("E2E Reviewer");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(/\/queue$/);
    await expect(page.getByTestId("role-badge")).toContainText("Reviewer");
    await expect(page.getByTestId("replay-banner")).toBeVisible();
  });
});
