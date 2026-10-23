import { expect, test, type Page } from "@playwright/test";

import { HOSTILE, IDS, mockCaseApi, newCaseState, type CaseMockState } from "./case.fixtures";
import { expectNoSeriousA11yIssues, mockApi, newState, type Role } from "./support";

const SHOTS = "test-results/screenshots";

// Software WebGL, so the opt-in map can start in a headless browser.
test.use({ launchOptions: { args: ["--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] } });

async function open(
  page: Page,
  id: string,
  options: { role?: Role; state?: CaseMockState; scheme?: "light" | "dark" } = {},
): Promise<CaseMockState> {
  const state = options.state ?? newCaseState();
  if (options.scheme) await page.emulateMedia({ colorScheme: options.scheme });
  await mockApi(page, newState({ role: options.role ?? "viewer" }));
  await mockCaseApi(page, state);
  await page.goto(`/cases/${id}`);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  return state;
}

async function withCsrfCookie(page: Page, value = "csrf-token-123") {
  const base = test.info().project.use.baseURL ?? "http://127.0.0.1:4173";
  await page.context().addCookies([{ name: "cso_csrf", value, url: base }]);
}

const announcements = (page: Page) => page.getByRole("status", { name: "Announcements" });
const activeId = (page: Page) => page.evaluate(() => document.activeElement?.id ?? "");

test.describe("@case case detail: fixtures", () => {
  test("fixture 02: the recommendation, the whole panel and every option probability", async ({
    page,
  }) => {
    await open(page, IDS.c02);
    await expect(
      page.getByRole("heading", { level: 1, name: "Changeset 900000000002" }),
    ).toBeVisible();
    await expect(page.getByTestId("case-header")).toContainText("Review suggested");
    await expect(page.getByTestId("case-header")).toContainText("Model is unsure");
    await expect(page.getByTestId("recommendation-response")).toHaveText("Welcome and tips");
    await expect(page.getByTestId("recommendation-nature")).toHaveText("Likely good-faith mistake");

    // All four option probabilities, numeric, in the option set's order, and flagged advisory.
    const nature = page.getByTestId("confidence-nature");
    await expect(nature.getByTestId("option-value")).toHaveText(["0.31", "0.27", "0.22", "0.20"]);
    await expect(page.getByTestId("nature-advisory")).toContainText(
      "not used to place the case in a lane",
    );
    await expect(nature).not.toContainText("%");

    // The fact panel lists every probe, and the composition rows say how the answer was reached.
    await expect(page.locator("[data-probe]")).toHaveCount(6);
    await expect(page.getByTestId("composition")).toContainText("P4");
    await expect(page.getByTestId("composition")).toContainText("N3");
    await expect(page.getByTestId("no-rules")).toHaveText("No rule fired.");
    await expect(page.getByTestId("user-changesets")).toHaveText("5 at the time of this edit");
    await expect(page.getByTestId("attribution")).toContainText("OpenStreetMap contributors");
    await page.screenshot({ path: `${SHOTS}/case-02-light.png`, fullPage: true });
  });

  test("fixture 04: the R1 block flag, skipped elements and deletion ages", async ({ page }) => {
    await open(page, IDS.c04, { role: "reviewer" });
    await expect(page.getByTestId("case-header")).toContainText("Insufficient evidence");
    const r1 = page.locator('[data-rule="R1"]');
    await expect(r1).toHaveAttribute("data-severity", "block");
    await expect(r1).toContainText("Blocks reassurance");
    await expect(r1).toContainText("Mature deletion");
    await expect(r1).toContainText("age_days");
    await expect(page.locator('[data-rule="R2"]')).toHaveAttribute("data-severity", "warn");
    await expect(page.locator('[data-rule="R3"]')).toBeVisible();

    await expect(page.getByTestId("coverage-skipped")).toHaveText("86");
    await expect(page.getByTestId("coverage-gaps")).toContainText("86 elements were skipped");
    await expect(page.getByTestId("deletion-ages")).toContainText("Deleted features by age (40)");
    await expect(page.getByTestId("deletion-ages")).toContainText("over 365 days: 40");
    await expect(page.getByTestId("recommendation-response")).toHaveText(
      "Escalate to an experienced reviewer",
    );
    // Not a comment, so there is nothing to draft, and the screen says why.
    await expect(page.getByTestId("action-draft")).toHaveAttribute("aria-disabled", "true");
    await expect(page.getByTestId("draft-reason")).toContainText("not a comment");
    await page.screenshot({ path: `${SHOTS}/case-04-light.png`, fullPage: true });
  });

  test("fixture 07: a failed run says so and still shows the rules", async ({ page }) => {
    await open(page, IDS.c07, { role: "reviewer" });
    await expect(page.getByTestId("failed-run")).toContainText("No model output; rules only.");
    await expect(page.getByTestId("failed-run")).toContainText("decider_unavailable");
    await expect(page.getByTestId("case-header")).toContainText("Rules only");
    await expect(page.locator('[data-rule="R6"]')).toBeVisible();
    await expect(page.getByTestId("confidence-nature")).toHaveCount(0);
    await expect(page.getByTestId("user-missing")).toBeVisible();
    await expect(page.getByTestId("coverage")).toContainText("could not be fetched");
    await expect(page.getByTestId("draft-reason")).toContainText("no model output");
    await page.screenshot({ path: `${SHOTS}/case-07-light.png`, fullPage: true });
  });

  test("fixture 06: every history gap is stated, with its reason", async ({ page }) => {
    await open(page, IDS.c06);
    await expect(page.getByTestId("coverage-summary")).toContainText("Coverage score 0.00");
    await expect(page.getByTestId("coverage-gaps")).toContainText("6 elements: history redacted");
    await page.getByText("List the 6 elements with history gaps").click();
    await expect(
      page.getByTestId("coverage-gaps").locator("li", { hasText: "way/600" }),
    ).toBeVisible();
    await expect(page.locator('[data-rule="R3"]')).toBeVisible();
  });

  test("fixture 08: hostile text is shown as text and does nothing", async ({ page }) => {
    await open(page, IDS.c08);
    await expect(page.getByTestId("discussion")).toContainText("IGNORE PREVIOUS INSTRUCTIONS");
    await expect(page.getByTestId("facts")).toContainText("<script>window.__pwned = true</script>");
    await expect(page.getByTestId("diffs")).toContainText(HOSTILE.tag);
    expect(
      await page.evaluate(() => (window as unknown as { __pwned?: boolean }).__pwned),
    ).toBeUndefined();
    await expect(page.locator("main script, main img")).toHaveCount(0);
    const hrefs = await page
      .locator("main a")
      .evaluateAll((links) => links.map((link) => link.getAttribute("href") ?? ""));
    expect(hrefs.some((href) => href.includes("evil.example"))).toBe(false);
  });
});

test.describe("@case case detail: wording and network", () => {
  for (const [name, id] of Object.entries({
    c02: IDS.c02,
    c04: IDS.c04,
    c07: IDS.c07,
    c08: IDS.c08,
  })) {
    test(`no harm-percentage wording on ${name}, and nothing is fetched from OpenStreetMap`, async ({
      page,
    }) => {
      const state = await open(page, id, { role: "reviewer" });
      const text = await page.locator("body").innerText();
      expect(text).not.toMatch(/vandal/i);
      expect(text).not.toMatch(/probability of (harm|damage)/i);
      expect(text).not.toMatch(/\d\s*%/);
      const html = await page.content();
      expect(html).not.toMatch(/vandal/i);
      const hosts = state.requestedUrls.map((url) => new URL(url).hostname);
      expect(hosts).not.toContain("api.openstreetmap.org");
      expect(hosts).not.toContain("www.openstreetmap.org");
    });
  }

  test("the map is never requested until the reviewer asks for it with m", async ({ page }) => {
    const state = await open(page, IDS.c02);
    await page.waitForLoadState("networkidle");
    const mapRequests = () =>
      state.requestedUrls.filter((url) => /maplibre|MapPanel|openfreemap/i.test(url));
    expect(mapRequests()).toEqual([]);
    await expect(page.getByTestId("map-panel")).toHaveCount(0);

    await page.keyboard.press("m");
    await expect(page.getByTestId("map-panel")).toBeVisible();
    await expect.poll(mapRequests).not.toEqual([]);
    await expect(page.getByTestId("map-attribution")).toContainText("OpenStreetMap contributors");
    await expect(page.getByTestId("map-attribution")).toContainText("OpenFreeMap");
    // The text description of the area is always there.
    await expect(page.getByTestId("facts")).toContainText("6.4400, 3.3700 → 6.4700, 3.4100");

    await page.keyboard.press("m");
    await expect(page.getByTestId("map-panel")).toHaveCount(0);
  });
});

test.describe("@case case detail: keyboard and roles", () => {
  test("j and k move between sections and say which one", async ({ page }) => {
    await open(page, IDS.c02);
    await expect(page.locator("[data-case-section]").first()).toBeVisible();
    await page.keyboard.press("j");
    await expect.poll(() => activeId(page)).toBe("coverage");
    await page.keyboard.press("j");
    await expect.poll(() => activeId(page)).toBe("facts");
    await expect(announcements(page)).toContainText("Changeset and account");
    await page.keyboard.press("k");
    await expect.poll(() => activeId(page)).toBe("coverage");
  });

  test("t switches the diff layout and the choice is remembered", async ({ page }) => {
    await open(page, IDS.c02);
    await expect(page.locator("table[data-mode]").first()).toHaveAttribute("data-mode", "side");
    await page.keyboard.press("t");
    await expect(page.locator("table[data-mode]").first()).toHaveAttribute("data-mode", "unified");
    await page.reload();
    await expect(page.locator("table[data-mode]").first()).toHaveAttribute("data-mode", "unified");
    await page.keyboard.press("t");
    await expect(page.locator("table[data-mode]").first()).toHaveAttribute("data-mode", "side");
  });

  test("from a case, u and g q return to the queue; n and p walk the list", async ({ page }) => {
    await page.addInitScript(
      (ids) => {
        window.sessionStorage.setItem("cso.queue.context", JSON.stringify(ids));
      },
      [IDS.c02, IDS.c04, IDS.c07],
    );
    await open(page, IDS.c04);
    await expect(page.getByTestId("queue-position")).toHaveText("Case 2 of 3");
    await page.keyboard.press("n");
    await expect(page).toHaveURL(new RegExp(`/cases/${IDS.c07}$`));
    await expect(page.getByTestId("queue-position")).toHaveText("Case 3 of 3");
    await page.keyboard.press("p");
    await expect(page).toHaveURL(new RegExp(`/cases/${IDS.c04}$`));
    await page.keyboard.press("u");
    await expect(page).toHaveURL(/\/queue$/);

    await page.goBack();
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await page.keyboard.press("g");
    await page.keyboard.press("q");
    await expect(page).toHaveURL(/\/queue$/);
  });

  test("a case opened without a list has no next or previous", async ({ page }) => {
    await open(page, IDS.c04);
    await expect(page.getByTestId("queue-position")).toHaveCount(0);
    await page.keyboard.press("n");
    await expect(announcements(page)).toContainText("There is no case in that direction.");
  });

  test("a viewer sees no actions and is told so", async ({ page }) => {
    await open(page, IDS.c02, { role: "viewer" });
    await expect(page.getByTestId("action-bar")).toHaveCount(0);
    await expect(page.getByTestId("view-only")).toBeVisible();
    await page.keyboard.press("d");
    await expect(announcements(page)).toContainText("View only");
  });

  test("a reviewer can open the draft for a comment response with d", async ({ page }) => {
    await open(page, IDS.c02, { role: "reviewer" });
    const draft = page.getByTestId("action-draft");
    await expect(draft).toHaveAttribute("href", `/cases/${IDS.c02}/draft`);
    await page.keyboard.press("d");
    await expect(page).toHaveURL(new RegExp(`/cases/${IDS.c02}/draft$`));
  });

  test("the server's empty allowed_responses disables drafting even for a comment response", async ({
    page,
  }) => {
    const state = newCaseState();
    const fixture = state.fixtures[IDS.c02];
    if (!fixture) throw new Error("fixture 02 is missing");
    fixture.detail.allowed_responses = [];
    fixture.detail.stale = true;
    await open(page, IDS.c02, { role: "reviewer", state });
    await expect(page.getByTestId("recommendation-response")).toBeVisible();
    await expect(page.getByTestId("action-draft")).toHaveAttribute("aria-disabled", "true");
    await expect(page.getByTestId("draft-reason")).toContainText("changed since the last analysis");
    await page.keyboard.press("d");
    await expect(page).not.toHaveURL(/\/draft$/);
  });

  test("evidence ids come from the server, not from the text, and null means no label", async ({
    page,
  }) => {
    const state = newCaseState();
    const fixture = state.fixtures[IDS.c02];
    if (!fixture) throw new Error("fixture 02 is missing");
    const elements = fixture.evidence.elements as Record<string, unknown>[];
    // The rendered text still says E1 and E2; the API's ids win.
    elements[0] = { ...elements[0], evidence_id: "E7" };
    elements[1] = { ...elements[1], evidence_id: null };
    await open(page, IDS.c02, { role: "reviewer", state });
    const row101 = page.locator("tr[data-action]").filter({ hasText: "way/101" }).first();
    await expect(row101.locator("td").first()).toHaveText("E7");
    const row102 = page.locator("tr[data-action]").filter({ hasText: "way/102" }).first();
    await expect(row102.locator("td").first()).toHaveText("");
  });

  test("outcome buttons are live: the key opens the confirm dialog and cancel closes it", async ({
    page,
  }) => {
    await open(page, IDS.c02, { role: "reviewer" });
    // The outcome dialog is wired: the old "arrives with the draft screen" notice is gone.
    await expect(page.getByTestId("outcome-later")).toHaveCount(0);
    await expect(page.getByTestId("action-agree")).not.toHaveAttribute("aria-disabled", "true");
    await page.keyboard.press("a");
    await expect(page.getByTestId("outcome-form")).toBeVisible();
    await expect(page.getByText("Agree with the recommendation")).toBeVisible();
    await page.getByTestId("outcome-cancel").click();
    await expect(page.getByTestId("outcome-form")).toHaveCount(0);
  });
});

test.describe("@case case detail: re-analysis", () => {
  function staleState(overrides: Partial<CaseMockState> = {}) {
    const state = newCaseState(overrides);
    (state.fixtures[IDS.c02]!.detail as { stale: boolean }).stale = true;
    return state;
  }

  test("a stale case can be re-analyzed: 202, progress by step, then done", async ({ page }) => {
    await withCsrfCookie(page);
    const state = staleState();
    await open(page, IDS.c02, { role: "reviewer", state });
    await expect(page.getByTestId("stale-banner")).toContainText(
      "The evidence changed after the last analysis.",
    );
    await page.getByTestId("reanalyze").click();
    await expect.poll(() => state.analysisRequests.length).toBe(1);
    expect(state.analysisRequests[0]?.csrf).toBe("csrf-token-123");
    await expect(page.getByTestId("analysis-progress")).toContainText("Analysis in progress");
    await expect(page.getByTestId("analysis-progress")).toContainText(
      "reading the evidence with the model",
    );
    await expect(page.getByTestId("case-notice")).toHaveText("The analysis finished.", {
      timeout: 20_000,
    });
    await expect(page.getByTestId("analysis-progress")).toHaveCount(0);
  });

  test("a running analysis (409) is followed, not repeated", async ({ page }) => {
    await withCsrfCookie(page);
    const state = staleState({ analysis: "conflict" });
    await open(page, IDS.c02, { role: "reviewer", state });
    await page.getByTestId("reanalyze").click();
    await expect(page.getByTestId("case-notice")).toContainText("already running");
    await expect(page.getByTestId("analysis-progress")).toBeVisible();
    expect(state.analysisRequests).toHaveLength(1);
  });

  test("a current run (200) says so", async ({ page }) => {
    await withCsrfCookie(page);
    await open(page, IDS.c02, { role: "reviewer", state: staleState({ analysis: "current" }) });
    await page.getByTestId("reanalyze").click();
    await expect(page.getByTestId("case-notice")).toHaveText(
      "The latest analysis is already current.",
    );
  });

  test("rate limiting (429) shows the wait", async ({ page }) => {
    await withCsrfCookie(page);
    await open(page, IDS.c02, {
      role: "reviewer",
      state: staleState({ analysis: "rate_limited" }),
    });
    await page.getByTestId("reanalyze").click();
    await expect(page.getByRole("alert")).toContainText("42");
  });

  test("a viewer is told to sign in instead of being offered the button", async ({ page }) => {
    await open(page, IDS.c02, { role: "viewer", state: staleState() });
    await expect(page.getByTestId("reanalyze")).toHaveCount(0);
    await expect(page.getByTestId("stale-banner")).toContainText("Sign in as a reviewer");
  });
});

test.describe("@case case detail: states", () => {
  test("an unknown case is a clear not-found page", async ({ page }) => {
    await open(page, "c0000000-0000-4000-8000-00000000dead");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Case not found");
  });

  test("a case the caller may not see is the no-access page", async ({ page }) => {
    await open(page, IDS.forbidden);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("No access");
  });

  test("a live server that wants sign-in sends the reader to the login page", async ({ page }) => {
    await open(page, IDS.signIn);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Sign in to see this case");
    const href = await page
      .getByTestId("case-message")
      .getByRole("link", { name: "Sign in" })
      .getAttribute("href");
    expect(href).toContain("/login");
    expect(href).toContain(encodeURIComponent(`/cases/${IDS.signIn}`));
  });
});

test.describe("@case case detail: accessibility", () => {
  for (const scheme of ["light", "dark"] as const) {
    for (const [name, id] of Object.entries({
      c02: IDS.c02,
      c04: IDS.c04,
      c07: IDS.c07,
      c08: IDS.c08,
    })) {
      test(`axe finds no serious issues on ${name} (${scheme})`, async ({ page }) => {
        await open(page, id, { role: "reviewer", scheme });
        await expect(page.getByTestId("case-view")).toBeVisible();
        await expectNoSeriousA11yIssues(page, `${name} ${scheme}`);
        if (name !== "c08")
          await page.screenshot({
            path: `${SHOTS}/case-${name.slice(1)}-${scheme}.png`,
            fullPage: true,
          });
      });
    }
  }

  test("axe is clean with the map open", async ({ page }) => {
    await open(page, IDS.c02);
    await expect(page.locator("[data-case-section]").first()).toBeVisible();
    await page.keyboard.press("m");
    await expect(page.getByTestId("map-panel")).toBeVisible();
    await expectNoSeriousA11yIssues(page, "c02 with map");
  });

  for (const [name, id] of Object.entries({ c02: IDS.c02, c04: IDS.c04 })) {
    test(`at 375 px ${name} has no horizontal page scroll and is axe clean`, async ({ page }) => {
      await page.setViewportSize({ width: 375, height: 800 });
      await open(page, id, { role: "reviewer" });
      await expect(page.getByTestId("case-view")).toBeVisible();
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(1);
      // On a narrow screen the recommendation comes first.
      const order = await page.evaluate(() => {
        const evidence = document
          .querySelector('[data-testid="pane-evidence"]')!
          .getBoundingClientRect().top;
        const rec = document
          .querySelector('[data-testid="pane-recommendation"]')!
          .getBoundingClientRect().top;
        return { evidence, rec };
      });
      expect(order.rec).toBeLessThan(order.evidence);
      await expectNoSeriousA11yIssues(page, `${name} 375px`);
      await page.screenshot({ path: `${SHOTS}/case-${name.slice(1)}-375.png`, fullPage: true });
    });
  }

  test("focused sections are not hidden under the sticky bars", async ({ page }) => {
    await open(page, IDS.c04, { role: "reviewer" });
    for (let i = 0; i < 6; i += 1) await page.keyboard.press("j");
    const box = await page.evaluate(() => {
      const node = document.activeElement as HTMLElement;
      const top = node.getBoundingClientRect().top;
      const header = document.querySelector("header")!.getBoundingClientRect().bottom;
      const bar = document.querySelector('[data-testid="action-bar"]')!.getBoundingClientRect().top;
      return { top, header, bar, height: window.innerHeight };
    });
    expect(box.top).toBeGreaterThanOrEqual(box.header - 1);
    expect(box.top).toBeLessThan(box.bar);
  });
});
