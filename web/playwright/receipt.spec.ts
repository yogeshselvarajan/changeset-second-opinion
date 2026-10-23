import { expect, test, type Page } from "@playwright/test";

import { IDS, mockCaseApi, newCaseState } from "./case.fixtures";
import { expectNoSeriousA11yIssues, mockApi, newState } from "./support";

const RUN_ID = "11111111-2222-4333-8444-555555555555";

const RECEIPT = {
  run_id: RUN_ID,
  changeset_id: 900000000002,
  created_at: "2026-07-12T10:05:00Z",
  config_version: "sha256:01ae6fdd0000000000000000000000000000000000000000000000000000abcd",
  pack_id: null,
  calibration_version: null,
  decider: { model: "strands-decider-2B", checkpoint: "v1" },
  lane: "review_suggested",
  band: "unsure",
  nature: "likely_good_faith_mistake",
  response: "welcome_and_tips",
  probes: [
    {
      code: "comment_matches_changes",
      label: "The comment matches the changes",
      probability: 0.91,
      reading: "yes",
    },
    {
      code: "new_account_first_edits",
      label: "The account is new and these are among its first edits",
      probability: 0.5,
      reading: "unknown",
    },
    {
      code: "mature_feature_deleted",
      label: "A mature feature was deleted",
      probability: 0.04,
      reading: "no",
    },
  ],
  rules_fired: [{ code: "R3", label: "New account and deletions", severity: "warn" }],
  coverage: {
    score: 0.8,
    elements_in_changeset: 10,
    elements_detailed: 8,
    history_gaps_count: 2,
  },
  attribution: {
    copyright: "OpenStreetMap contributors",
    attribution: "https://www.openstreetmap.org/copyright",
    license: "Open Database License 1.0",
  },
};

async function mockReceipt(page: Page, status = 200): Promise<string[]> {
  const calls: string[] = [];
  page.on("request", (request) => calls.push(request.url()));
  await page.route("**/api/v1/receipts/*", (route) =>
    route.fulfill({
      status,
      contentType: status === 200 ? "application/json" : "application/problem+json",
      body: JSON.stringify(
        status === 200
          ? RECEIPT
          : { type: "urn:cso:problem:not_found", title: "Not found", status },
      ),
    }),
  );
  return calls;
}

test.describe("@receipt public receipt", () => {
  test("anyone can read a receipt: no account, no shell, no OpenStreetMap request", async ({
    browser,
  }) => {
    const context = await browser.newContext();
    const page = await context.newPage();
    const calls = await mockReceipt(page);
    await page.goto(`/r/${RUN_ID}`);

    await expect(
      page.getByRole("heading", { level: 1, name: "Decision receipt for changeset 900000000002" }),
    ).toBeVisible();
    await expect(page.getByTestId("receipt")).toContainText("Review suggested");
    await expect(page.getByTestId("receipt")).toContainText("Model is unsure");
    await expect(page.locator("[data-probe]")).toHaveCount(3);
    await expect(page.getByTestId("receipt-facts")).toContainText("0.91");
    await expect(page.getByTestId("rules")).toContainText("R3");
    await expect(page.getByTestId("receipt-coverage")).toContainText("2 elements had gaps");
    await expect(page.getByTestId("attribution")).toContainText("OpenStreetMap contributors");
    await expect(page.getByTestId("public-footer")).toHaveText(
      "A human decides. This tool never posts to OpenStreetMap.",
    );
    await expect(page.getByRole("link", { name: /Open the changeset/ })).toHaveAttribute(
      "href",
      "https://www.openstreetmap.org/changeset/900000000002",
    );

    // No sidebar, no sign-in state, no cookies, and only the receipt was asked for.
    await expect(page.getByRole("complementary")).toHaveCount(0);
    expect(await context.cookies()).toEqual([]);
    expect(calls.some((url) => /openstreetmap\.org/.test(url))).toBe(false);
    const api = calls.filter((url) => url.includes("/api/"));
    // The receipt itself, and the cookie-free branding every public page asks for.
    expect(api).toHaveLength(2);
    expect(api.filter((url) => url.includes("/api/v1/receipts/"))).toHaveLength(1);
    expect(api.filter((url) => url.endsWith("/api/v1/public/branding"))).toHaveLength(1);
    await context.close();
  });

  test("it never shows a reviewer, a decision or a draft", async ({ page }) => {
    await mockReceipt(page);
    await page.goto(`/r/${RUN_ID}`);
    await expect(page.getByTestId("receipt")).toBeVisible();
    const text = (await page.getByTestId("receipt").innerText()).toLowerCase();
    for (const word of ["reviewer", "approved", "draft", "session"]) {
      expect(text).not.toContain(word);
    }
  });

  test("an unknown receipt says so plainly", async ({ page }) => {
    await mockReceipt(page, 404);
    await page.goto(`/r/${RUN_ID}`);
    await expect(page.getByTestId("receipt-missing")).toContainText("Receipt not found");
  });

  for (const scheme of ["light", "dark"] as const) {
    test(`axe finds no serious issues on a receipt (${scheme})`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: scheme });
      await mockReceipt(page);
      await page.goto(`/r/${RUN_ID}`);
      await expect(page.getByTestId("receipt")).toBeVisible();
      await expectNoSeriousA11yIssues(page, `receipt ${scheme}`);
    });
  }

  test("the case screen copies the receipt link with the l key", async ({ page, context }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    await mockApi(page, newState({ role: "reviewer" }));
    await mockCaseApi(page, newCaseState());
    await page.goto(`/cases/${IDS.c02}`);
    await expect(page.getByTestId("copy-receipt")).toBeVisible();
    await page.locator("body").press("l");
    await expect(page.getByRole("status", { name: "Announcements" })).toContainText(
      "Receipt link copied",
    );
    const copied = await page.evaluate(() => navigator.clipboard.readText());
    // The link is the current origin plus the latest run's id (the fixture's ids are short).
    expect(copied).toMatch(/^http:\/\/127\.0\.0\.1:\d+\/r\/r-002$/);
  });
});
