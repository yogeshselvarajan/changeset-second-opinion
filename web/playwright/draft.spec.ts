import { expect, test, type BrowserContext, type Page } from "@playwright/test";

import { IDS, mockCaseApi, newCaseState } from "./case.fixtures";
import {
  DRAFT,
  FINAL_TEXT,
  RUN_ID,
  TEMPLATE_DRAFT,
  VERSION_ZERO,
  mockDraftApi,
  newDraftState,
  type DraftMockState,
} from "./draft.fixtures";
import { expectNoSeriousA11yIssues, mockApi, newState, type Role } from "./support";

const draftUrl = new RegExp(`/cases/${IDS.c02}/draft$`);

async function withCsrfCookie(page: Page, value = "csrf-token-123") {
  const base = test.info().project.use.baseURL ?? "http://127.0.0.1:4173";
  await page.context().addCookies([{ name: "cso_csrf", value, url: base }]);
}

/** Mock the shell, the case and the draft endpoints; the reviewer's CSRF cookie is set. */
async function setup(
  page: Page,
  options: { role?: Role; scheme?: "light" | "dark"; overrides?: Partial<DraftMockState> } = {},
): Promise<DraftMockState> {
  const shell = newState({ role: options.role ?? "reviewer", displayName: "Test Reviewer" });
  if (options.scheme) await page.emulateMedia({ colorScheme: options.scheme });
  await mockApi(page, shell);
  await mockCaseApi(page, newCaseState());
  const state = newDraftState(shell, options.overrides);
  await mockDraftApi(page, state);
  await withCsrfCookie(page);
  return state;
}

/** Open the draft screen, ask for the default kind of draft and wait for the editor. */
async function toEditor(page: Page) {
  await page.goto(`/cases/${IDS.c02}/draft`);
  await expect(page.getByTestId("draft-chooser")).toBeVisible();
  await page.getByTestId("draft-request").click();
  await expect(page.getByTestId("draft-editor")).toBeVisible({ timeout: 15_000 });
}

const announcements = (page: Page) => page.getByRole("status", { name: "Announcements" });
// The Windows clipboard turns every newline into CRLF; compare the text, not the line ending.
const readClipboard = async (page: Page) =>
  (await page.evaluate(() => navigator.clipboard.readText())).replace(/\r\n/g, "\n");

async function noHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
}

async function allowClipboard(context: BrowserContext) {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
}

test.describe("@draft draft editor", () => {
  test("keyboard-only path: case, d, request, edit, Ctrl+Enter, outcome recorded, clipboard equals the final text", async ({
    page,
    context,
  }) => {
    await allowClipboard(context);
    const state = await setup(page);
    await page.goto(`/cases/${IDS.c02}`);
    await expect(
      page.getByRole("heading", { level: 1, name: "Changeset 900000000002" }),
    ).toBeVisible();

    await page.keyboard.press("d");
    await expect(page).toHaveURL(draftUrl);
    await expect(page.getByTestId("draft-chooser")).toBeVisible();
    await page.getByTestId("draft-request").focus();
    await page.keyboard.press("Enter");

    await expect(page.getByTestId("draft-generating")).toBeVisible();
    await expect(page.getByTestId("draft-editor")).toBeVisible({ timeout: 15_000 });
    // The cursor is already in the text, so a keyboard user can type at once.
    await expect(page.getByTestId("draft-text")).toBeFocused();
    expect(state.draftRequests).toHaveLength(1);
    expect(state.draftRequests[0]?.body).toEqual({
      response_type: "welcome_and_tips",
      regenerate: false,
    });
    expect(state.draftRequests[0]?.csrf).toBe("csrf-token-123");

    await page.keyboard.press("Control+A");
    await page.keyboard.type(FINAL_TEXT);
    await expect(page.getByTestId("draft-checks-summary")).toHaveText("All checks pass.");
    await page.keyboard.press("Control+Enter");

    await expect(page.getByTestId("draft-recorded")).toBeVisible();
    await expect(announcements(page)).toContainText("Copied to the clipboard");
    expect(state.outcomeCalls).toHaveLength(1);
    const call = state.outcomeCalls[0];
    expect(call?.ifMatch).toBe(VERSION_ZERO);
    expect(call?.csrf).toBe("csrf-token-123");
    expect(call?.body).toEqual({
      disposition: "agree",
      response_type: "welcome_and_tips",
      final_text: FINAL_TEXT,
      run_id_seen: RUN_ID,
    });
    // The copied text is exactly the recorded final text.
    expect(await readClipboard(page)).toBe(FINAL_TEXT);
    await expect(page.getByTestId("draft-open-link")).toHaveAttribute(
      "href",
      "https://www.openstreetmap.org/changeset/900000000002",
    );
    await expect(page.getByTestId("draft-open-link")).toHaveAttribute("rel", "noopener noreferrer");
  });

  test("the editor says plainly that the tool never posts to OpenStreetMap", async ({ page }) => {
    await setup(page);
    await toEditor(page);
    await expect(page.getByTestId("draft-notice")).toContainText("never posts to OpenStreetMap");
    await expect(page.getByTestId("draft-kind")).toHaveText("Welcome and tips");
    await expect(page.getByTestId("draft-badge-model")).toBeVisible();
    await expect(page.getByTestId("draft-model")).toContainText("claude-haiku");
  });

  test("shows the generating state, then the offline template badge", async ({ page }) => {
    await setup(page, { overrides: { draft: structuredClone(TEMPLATE_DRAFT), runningPolls: 2 } });
    await page.goto(`/cases/${IDS.c02}/draft`);
    await page.getByTestId("draft-request").click();
    const generating = page.getByTestId("draft-generating");
    await expect(generating).toBeVisible();
    await expect(generating).toContainText("Drafting");
    await expect(generating).toHaveAttribute("aria-busy", "true");
    await expect(page.getByTestId("draft-editor")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("draft-badge-template")).toHaveText("Offline template");
    await expect(page.getByTestId("draft-model")).toContainText("no model");
    await expect(page.getByTestId("draft-model")).toContainText("template wording");
    await expect(page.getByTestId("draft-badge-model")).toHaveCount(0);
  });

  test("the checklist updates as you type and blocks approval until it passes", async ({
    page,
    context,
  }) => {
    await allowClipboard(context);
    const state = await setup(page);
    await toEditor(page);
    const text = page.getByTestId("draft-text");

    // A word from the community's avoid-list (a stand-in here) is flagged on its line.
    await text.fill("Hello\n\nThis is a Blorp edit?\n\nBye");
    const avoid = page.locator('[data-check="avoidList"]');
    await expect(avoid).toHaveAttribute("data-ok", "false");
    await expect(avoid).toContainText("line 3");
    await expect(page.getByTestId("draft-checks-summary")).toContainText("need attention");
    await expect(page.getByTestId("draft-counts")).toContainText("characters");

    // The button stays focusable but is marked unavailable; pressing it explains why and sends nothing.
    await expect(page.getByTestId("approve-copy")).toHaveAttribute("aria-disabled", "true");
    await page.getByTestId("approve-copy").click({ force: true });
    await expect(announcements(page)).toContainText("Fix the items in the checklist first");
    expect(state.outcomeCalls).toHaveLength(0);

    // A link the community has not allowed.
    await text.fill("Hello\n\nSee https://evil.example.net/x?\n\nBye");
    await expect(page.locator('[data-check="links"]')).toHaveAttribute("data-ok", "false");
    await text.fill("Hello\n\nSee https://wiki.example.org/Key:name?\n\nBye");
    await expect(page.locator('[data-check="links"]')).toHaveAttribute("data-ok", "true");

    // Markup and a missing question for a comment kind that asks one are not shown for this kind.
    await text.fill("Hello\n\nA **bold** claim?\n\nBye");
    await expect(page.locator('[data-check="markup"]')).toHaveAttribute("data-ok", "false");
    await expect(page.locator('[data-check="question"]')).toHaveCount(0);

    await text.fill("Hello\n\nA plain sentence?\n\nBye");
    await expect(page.getByTestId("draft-checks-summary")).toHaveText("All checks pass.");
    await page.getByTestId("approve-copy").click();
    await expect(page.getByTestId("draft-recorded")).toBeVisible();
    expect(state.outcomeCalls).toHaveLength(1);
    expect(await readClipboard(page)).toBe("Hello\n\nA plain sentence?\n\nBye");
  });

  test("shows what the server's own check found, in plain words", async ({ page }) => {
    await setup(page, {
      overrides: {
        draft: {
          ...structuredClone(DRAFT),
          status: "rejected_by_validator",
          validation: { ok: false, violations: ["banned_word", "uncited", "something_new"] },
        },
      },
    });
    await toEditor(page);
    const server = page.getByTestId("draft-server-validation");
    await expect(server).toContainText("found problems");
    await expect(server).toContainText("avoid-list");
    await expect(server).toContainText("No evidence id is cited.");
    await expect(server).toContainText("The check reported a problem.");
    await expect(page.getByTestId("draft-model")).toContainText("rejected by the check");
  });

  test("a passing draft shows the server check passed and the evidence it cites", async ({
    page,
  }) => {
    await setup(page);
    await toEditor(page);
    await expect(page.getByTestId("draft-server-validation")).toContainText("check passed");
    await expect(page.getByTestId("draft-cites")).toHaveText("Cites E1");
  });

  test("the lines a draft cites are listed beside the checklist", async ({ page }) => {
    await setup(page);
    await toEditor(page);
    const lines = page.getByTestId("draft-cited-lines");
    await expect(lines).toBeVisible();
    await expect(lines).toContainText("E1");
    await expect(lines).toContainText("way/101 modify");
  });

  test("shows the changes from the generated text, word by word, and can reset", async ({
    page,
  }) => {
    await setup(page);
    await toEditor(page);
    await page.getByTestId("draft-diff-toggle").click();
    await expect(page.getByTestId("draft-diff")).toContainText("No changes");
    await page.getByTestId("draft-text").fill(FINAL_TEXT);
    await expect(page.getByTestId("draft-diff").locator("del")).not.toHaveCount(0);
    await expect(page.getByTestId("draft-reset")).toBeEnabled();
    await page.getByTestId("draft-reset").click();
    await expect(page.getByTestId("draft-diff")).toContainText("No changes");
    await expect(page.getByTestId("draft-reset")).toBeDisabled();
  });

  test("reject needs a reason, then records it without any text", async ({ page }) => {
    const state = await setup(page);
    await toEditor(page);
    await page.getByTestId("reject-open").click();
    await expect(page.getByTestId("reject-panel")).toBeVisible();

    await page.getByTestId("reject-confirm").click();
    await expect(page.getByTestId("reject-reason-error")).toHaveText("Choose a reason first.");
    expect(state.outcomeCalls).toHaveLength(0);

    await page.getByTestId("reject-reason").selectOption("wrong_facts");
    await page.getByLabel("Note (optional)").last().fill("The names were not from E1");
    await page.getByTestId("reject-confirm").click();
    await expect(page.getByTestId("draft-recorded")).toContainText("rejection was recorded");
    expect(state.outcomeCalls).toHaveLength(1);
    const body = state.outcomeCalls[0]?.body;
    expect(body).toMatchObject({
      disposition: "different_response",
      reason_code: "wrong_facts",
      response_type: "welcome_and_tips",
      run_id_seen: RUN_ID,
      note: "The names were not from E1",
    });
    expect(body).not.toHaveProperty("final_text");
    expect(state.outcomeCalls[0]?.ifMatch).toBe(VERSION_ZERO);
  });

  test("rejecting because no comment is needed records no action", async ({ page }) => {
    const state = await setup(page);
    await toEditor(page);
    await page.getByTestId("reject-open").click();
    await page.getByTestId("reject-reason").selectOption("not_needed");
    await page.getByTestId("reject-confirm").click();
    await expect(page.getByTestId("draft-recorded")).toBeVisible();
    expect(state.outcomeCalls[0]?.body).toMatchObject({
      disposition: "no_action",
      reason_code: "not_needed",
    });
  });

  test("412: shows the other reviewer's decision, then records mine after theirs", async ({
    page,
  }) => {
    const state = await setup(page, { overrides: { outcomeAnswers: ["conflict", "ok"] } });
    await toEditor(page);
    await page.getByTestId("draft-text").fill(FINAL_TEXT);
    await page.getByTestId("approve-copy").click();

    const conflict = page.getByTestId("outcome-conflict");
    await expect(conflict).toBeVisible();
    await expect(page.getByTestId("conflict-current")).toContainText("Other Reviewer");
    await expect(page.getByTestId("conflict-current")).toContainText("Needs survey");
    await expect(page.getByTestId("conflict-current")).toContainText("2026-07-12 10:30 UTC");
    await expect(conflict).toContainText("Looks odd");
    await expect(page.getByTestId("draft-recorded")).toHaveCount(0);
    expect(state.outcomeCalls[0]?.ifMatch).toBe(VERSION_ZERO);

    await page.getByTestId("conflict-keep").click();
    await expect(page.getByTestId("draft-recorded")).toBeVisible();
    expect(state.outcomeCalls).toHaveLength(2);
    // The second entry carries the version that includes the other decision.
    expect(state.outcomeCalls[1]?.ifMatch).toBe('W/"4"');
    expect(state.outcomeCalls[1]?.body.final_text).toBe(FINAL_TEXT);
    // Every outcome request carries If-Match.
    expect(state.outcomeCalls.every((c) => c.ifMatch !== undefined)).toBe(true);
  });

  test("412: accepting the other decision closes the editor without recording", async ({
    page,
  }) => {
    const state = await setup(page, { overrides: { outcomeAnswers: ["conflict"] } });
    await toEditor(page);
    await page.getByTestId("approve-copy").click();
    await expect(page.getByTestId("outcome-conflict")).toBeVisible();
    await page.getByTestId("conflict-accept").click();
    await expect(page).toHaveURL(new RegExp(`/cases/${IDS.c02}$`));
    expect(state.outcomeCalls).toHaveLength(1);
  });

  test("a server failure when recording is shown and nothing is copied or lost", async ({
    page,
  }) => {
    const state = await setup(page, { overrides: { outcomeAnswers: ["rate_limited", "ok"] } });
    await toEditor(page);
    await page.getByTestId("approve-copy").click();
    await expect(page.getByTestId("draft-error")).toContainText("30 seconds");
    await expect(page.getByTestId("draft-recorded")).toHaveCount(0);
    await expect(page.getByTestId("draft-text")).not.toHaveValue("");
    await page.getByTestId("approve-copy").click();
    await expect(page.getByTestId("draft-recorded")).toBeVisible();
    expect(state.outcomeCalls).toHaveLength(2);
  });

  test("regenerate works once, with a new draft", async ({ page }) => {
    const state = await setup(page);
    await toEditor(page);
    const first = state.draft.id;
    await page.getByTestId("draft-regenerate").click();
    await expect(page.getByTestId("draft-generating")).toBeVisible();
    await expect(page.getByTestId("draft-editor")).toBeVisible({ timeout: 15_000 });
    expect(state.draftRequests).toHaveLength(2);
    expect(state.draftRequests[1]?.body).toEqual({
      response_type: "welcome_and_tips",
      regenerate: true,
    });
    expect(state.draft.id).not.toBe(first);
    await expect(page.getByTestId("draft-regenerate")).toBeDisabled();
    await expect(page.getByTestId("draft-regenerate")).toContainText("Regenerated once");
  });

  test("a failed draft job leaves a blank editable text, and you can still write one", async ({
    page,
  }) => {
    const state = await setup(page, {
      overrides: { jobEnds: "failed", failureCode: "draft_run_stale" },
    });
    await toEditor(page);
    await expect(page.getByTestId("draft-failure")).toContainText("newer analysis");
    await expect(page.getByTestId("draft-failure")).toContainText("write the comment yourself");
    await expect(page.getByTestId("draft-badge-manual")).toBeVisible();
    const text = page.getByTestId("draft-text");
    await expect(text).toHaveValue("");
    await expect(text).toBeEditable();
    await text.fill("Hello\n\nCould you share a source for the names?\n\nThanks");
    await page.getByTestId("approve-copy").click();
    await expect(page.getByTestId("draft-recorded")).toBeVisible();
    expect(state.outcomeCalls[0]?.body).toMatchObject({
      disposition: "agree",
      response_type: "welcome_and_tips",
      run_id_seen: RUN_ID,
    });
  });

  test("an unknown failure code gets a generic sentence, not the code", async ({ page }) => {
    await setup(page, { overrides: { jobEnds: "failed", failureCode: "totally_new_code" } });
    await toEditor(page);
    await expect(page.getByTestId("draft-failure")).toContainText("could not be made");
    await expect(page.getByTestId("draft-failure")).not.toContainText("totally_new_code");
  });

  test("request errors read plainly: not allowed, daily limit, too many requests", async ({
    page,
  }) => {
    const state = await setup(page, { overrides: { draftRequest: "not_allowed" } });
    await page.goto(`/cases/${IDS.c02}/draft`);
    await page.getByTestId("draft-request").click();
    await expect(page.getByTestId("draft-request-error")).toContainText("not allowed");
    state.draftRequest = "daily_cap";
    await page.getByTestId("draft-request").click();
    await expect(page.getByTestId("draft-request-error")).toContainText("daily limit");
    state.draftRequest = "rate_limited";
    await page.getByTestId("draft-request").click();
    await expect(page.getByTestId("draft-request-error")).toContainText("42 seconds");
    await expect(page.getByTestId("draft-chooser")).toBeVisible();
  });

  test("another allowed kind: a different response is recorded as such", async ({ page }) => {
    const state = await setup(page, {
      overrides: {
        draft: {
          ...structuredClone(DRAFT),
          response_type: "ask_source_question",
          body: "Could you share where the names came from, for example a survey?",
        },
      },
    });
    await page.goto(`/cases/${IDS.c02}/draft`);
    await expect(page.getByTestId("kind-welcome_and_tips")).toBeChecked();
    await expect(page.getByTestId("kind-ask_source_question")).toBeVisible();
    await expect(page.getByTestId("kind-request_local_check")).toHaveCount(0);
    await page.getByTestId("kind-ask_source_question").check();
    await page.getByTestId("draft-request").click();
    await expect(page.getByTestId("draft-editor")).toBeVisible({ timeout: 15_000 });
    expect(state.draftRequests[0]?.body.response_type).toBe("ask_source_question");
    await expect(page.locator('[data-check="question"]')).toHaveAttribute("data-ok", "true");
    await page.getByTestId("approve-copy").click();
    await expect(page.getByTestId("draft-recorded")).toBeVisible();
    expect(state.outcomeCalls[0]?.body).toMatchObject({
      disposition: "different_response",
      response_type: "ask_source_question",
    });
  });

  test("Back to the case and into the draft again keeps an edit made in this tab", async ({
    page,
  }) => {
    await setup(page);
    await toEditor(page);
    await page.getByTestId("draft-text").fill("An edit that should survive a round trip?");
    await page.keyboard.press("Escape");
    await expect(page).toHaveURL(new RegExp(`/cases/${IDS.c02}$`));
    await expect(page.getByTestId("case-view")).toBeVisible();
    await page.keyboard.press("d");
    await expect(page.getByTestId("draft-editor")).toBeVisible();
    await expect(page.getByTestId("draft-text")).toHaveValue(
      "An edit that should survive a round trip?",
    );
  });

  test("a viewer can read the latest draft but not change anything", async ({ page }) => {
    await setup(page, { role: "viewer" });
    await page.goto(`/cases/${IDS.c02}/draft`);
    await expect(page.getByTestId("draft-viewer")).toContainText("Sign in as a reviewer");
    await expect(page.getByTestId("approve-copy")).toHaveCount(0);
    await expect(page.getByTestId("draft-request")).toHaveCount(0);
  });

  test("approve and open: the changeset page opens in a new tab, the text is copied, and the app calls no OpenStreetMap API", async ({
    page,
    context,
  }) => {
    await allowClipboard(context);
    const everyUrl: string[] = [];
    context.on("request", (request) => everyUrl.push(request.url()));
    // The reviewer's own tab goes to the real site; here it is answered locally.
    await context.route("**://www.openstreetmap.org/**", (route) =>
      route.fulfill({ status: 200, contentType: "text/html", body: "<title>changeset</title>" }),
    );
    const state = await setup(page);
    await toEditor(page);
    await page.getByTestId("draft-text").fill(FINAL_TEXT);

    const [popup] = await Promise.all([
      context.waitForEvent("page"),
      page.keyboard.press("Control+Shift+Enter"),
    ]);
    // The tab is opened inside the click (blank) and sent to the changeset once the outcome is recorded.
    await popup.waitForURL("https://www.openstreetmap.org/changeset/900000000002");
    await expect(page.getByTestId("draft-recorded")).toBeVisible();
    expect(await readClipboard(page)).toBe(FINAL_TEXT);
    expect(state.outcomeCalls).toHaveLength(1);

    // The app page itself never asked any openstreetmap.org host for anything, and no request in
    // the whole browser went to the API host.
    expect(state.requestedUrls.filter((url) => /openstreetmap\.org/.test(url))).toEqual([]);
    expect(everyUrl.filter((url) => /api\.openstreetmap\.org/.test(url))).toEqual([]);
  });

  test("a failed copy keeps the text on screen to copy by hand", async ({ page, context }) => {
    await allowClipboard(context);
    await page.addInitScript(() => {
      Object.defineProperty(navigator, "clipboard", {
        value: { writeText: () => Promise.reject(new Error("blocked")) },
        configurable: true,
      });
      document.execCommand = () => false;
    });
    await setup(page);
    await toEditor(page);
    await page.getByTestId("draft-text").fill(FINAL_TEXT);
    await page.getByTestId("approve-copy").click();
    await expect(page.getByTestId("draft-recorded")).toContainText("could not be copied");
    await expect(page.getByTestId("draft-final-text")).toHaveValue(FINAL_TEXT);
  });
});

test.describe("@draft outcome without a draft", () => {
  async function openCase(page: Page, overrides: Partial<DraftMockState> = {}) {
    const state = await setup(page, { overrides });
    await page.goto(`/cases/${IDS.c02}`);
    await expect(
      page.getByRole("heading", { level: 1, name: "Changeset 900000000002" }),
    ).toBeVisible();
    return state;
  }

  test("a confirms an agreement and sends If-Match", async ({ page }) => {
    const state = await openCase(page);
    await page.keyboard.press("a");
    const dialog = page.getByRole("dialog", { name: "Agree with the recommendation" });
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText("Earlier entries are never changed");
    await dialog.getByTestId("outcome-note").fill("Looks fine to me");
    await dialog.getByTestId("outcome-confirm").click();
    await expect(dialog).toHaveCount(0);
    await expect(announcements(page)).toContainText("Decision recorded: Agreed");
    expect(state.outcomeCalls).toHaveLength(1);
    expect(state.outcomeCalls[0]?.ifMatch).toBe(VERSION_ZERO);
    expect(state.outcomeCalls[0]?.csrf).toBe("csrf-token-123");
    expect(state.outcomeCalls[0]?.body).toEqual({
      disposition: "agree",
      response_type: "welcome_and_tips",
      note: "Looks fine to me",
      run_id_seen: RUN_ID,
    });
  });

  test("s and x open their own dialogs, and Cancel records nothing", async ({ page }) => {
    const state = await openCase(page);
    await page.keyboard.press("s");
    await expect(page.getByRole("dialog", { name: "Mark as needs a survey" })).toBeVisible();
    await page.getByTestId("outcome-cancel").click();
    await page.keyboard.press("x");
    await expect(page.getByRole("dialog", { name: "Disagree with the model" })).toBeVisible();
    await page.getByTestId("outcome-confirm").click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    expect(state.outcomeCalls).toHaveLength(1);
    expect(state.outcomeCalls[0]?.body).toMatchObject({
      disposition: "disagree_with_model",
      response_type: null,
    });
  });

  test("the buttons open the same dialog", async ({ page }) => {
    await openCase(page);
    await page.getByTestId("action-needs_survey").click();
    await expect(page.getByRole("dialog", { name: "Mark as needs a survey" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);
  });

  test("412 shows the other reviewer's decision, then records mine after theirs", async ({
    page,
  }) => {
    const state = await openCase(page, { outcomeAnswers: ["conflict", "ok"] });
    await page.keyboard.press("a");
    const dialog = page.getByRole("dialog");
    await dialog.getByTestId("outcome-confirm").click();
    await expect(dialog.getByTestId("outcome-conflict")).toBeVisible();
    await expect(dialog.getByTestId("conflict-current")).toContainText("Other Reviewer");
    await expect(dialog.getByTestId("outcome-confirm")).toBeDisabled();
    await dialog.getByTestId("conflict-keep").click();
    await expect(dialog).toHaveCount(0);
    expect(state.outcomeCalls.map((c) => c.ifMatch)).toEqual([VERSION_ZERO, 'W/"4"']);
  });

  test("412 then accepting theirs closes the dialog without a second request", async ({ page }) => {
    const state = await openCase(page, { outcomeAnswers: ["conflict"] });
    await page.keyboard.press("a");
    await page.getByTestId("outcome-confirm").click();
    await page.getByTestId("conflict-accept").click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    expect(state.outcomeCalls).toHaveLength(1);
  });

  test("a failure is shown in the dialog and the reviewer can try again", async ({ page }) => {
    const state = await openCase(page, { outcomeAnswers: ["server_error", "ok"] });
    await page.keyboard.press("a");
    await page.getByTestId("outcome-confirm").click();
    await expect(page.getByTestId("outcome-error")).toContainText("server had a problem");
    await page.getByTestId("outcome-confirm").click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    expect(state.outcomeCalls).toHaveLength(2);
  });

  test("a viewer is told the screen is view-only", async ({ page }) => {
    const shell = newState({ role: "viewer" });
    await mockApi(page, shell);
    await mockCaseApi(page, newCaseState());
    await mockDraftApi(page, newDraftState(shell));
    await page.goto(`/cases/${IDS.c02}`);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await page.keyboard.press("a");
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(announcements(page)).toContainText("View only");
  });
});

test.describe("@draft accessibility and layout", () => {
  for (const scheme of ["light", "dark"] as const) {
    test(`axe is clean on the chooser, the editor and a conflict (${scheme})`, async ({ page }) => {
      await setup(page, { scheme, overrides: { outcomeAnswers: ["conflict"] } });
      await page.goto(`/cases/${IDS.c02}/draft`);
      await expect(page.getByTestId("draft-chooser")).toBeVisible();
      await expectNoSeriousA11yIssues(page, `chooser ${scheme}`);

      await page.getByTestId("draft-request").click();
      await expect(page.getByTestId("draft-generating")).toBeVisible();
      await expectNoSeriousA11yIssues(page, `generating ${scheme}`);
      await expect(page.getByTestId("draft-editor")).toBeVisible({ timeout: 15_000 });
      await expectNoSeriousA11yIssues(page, `editor ${scheme}`);

      await page.getByTestId("draft-text").fill("Hello\n\nA Blorp question?\n\nBye");
      await page.getByTestId("draft-diff-toggle").click();
      await page.getByTestId("reject-open").click();
      await page.getByTestId("reject-confirm").click();
      await expectNoSeriousA11yIssues(page, `checks failing and reject open ${scheme}`);

      await page.getByTestId("draft-text").fill(FINAL_TEXT);
      await page.getByTestId("approve-copy").click();
      await expect(page.getByTestId("outcome-conflict")).toBeVisible();
      await expectNoSeriousA11yIssues(page, `conflict ${scheme}`);
    });
  }

  test("axe is clean on the outcome dialog and the editor in the failure state", async ({
    page,
  }) => {
    await setup(page, { overrides: { jobEnds: "failed" } });
    await page.goto(`/cases/${IDS.c02}`);
    await expect(
      page.getByRole("heading", { level: 1, name: "Changeset 900000000002" }),
    ).toBeVisible();
    await page.keyboard.press("a");
    await expect(page.getByRole("dialog")).toBeVisible();
    await expectNoSeriousA11yIssues(page, "outcome dialog");
    await page.keyboard.press("Escape");
    await page.goto(`/cases/${IDS.c02}/draft`);
    await page.getByTestId("draft-request").click();
    await expect(page.getByTestId("draft-failure")).toBeVisible({ timeout: 15_000 });
    await expectNoSeriousA11yIssues(page, "failure state");
  });

  test("375 px: no horizontal scroll on the chooser, the editor or the conflict", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 375, height: 800 });
    await setup(page, { overrides: { outcomeAnswers: ["conflict"] } });
    await page.goto(`/cases/${IDS.c02}/draft`);
    await expect(page.getByTestId("draft-chooser")).toBeVisible();
    await noHorizontalScroll(page);
    await page.getByTestId("draft-request").click();
    await expect(page.getByTestId("draft-editor")).toBeVisible({ timeout: 15_000 });
    await noHorizontalScroll(page);
    await page.getByTestId("draft-diff-toggle").click();
    await page.getByTestId("draft-text").fill(FINAL_TEXT);
    await page.getByTestId("reject-open").click();
    await noHorizontalScroll(page);
    await page.getByTestId("approve-copy").click();
    await expect(page.getByTestId("outcome-conflict")).toBeVisible();
    await noHorizontalScroll(page);
    await page.screenshot({ path: "test-results/screenshots/draft-375.png", fullPage: true });
  });

  test("screenshots of the editor in light and dark at 1280 px", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await setup(page);
    await toEditor(page);
    await page.screenshot({
      path: "test-results/screenshots/draft-light-1280.png",
      fullPage: true,
    });
    await page.emulateMedia({ colorScheme: "dark" });
    await page.screenshot({ path: "test-results/screenshots/draft-dark-1280.png", fullPage: true });
  });
});
