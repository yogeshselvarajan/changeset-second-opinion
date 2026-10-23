import { expect, test, type Page } from "@playwright/test";

import { newSettingsState, mockSettingsApi, type SettingsMockState } from "./settings.fixtures";
import { expectNoSeriousA11yIssues, mockApi, newState, shellReady, type Role } from "./support";

const BANNED = /\b(vandal\w*|spam\w*|illegal|stop\w*|must)\b/i;
const LOGO =
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10"/></svg>';

async function setup(
  page: Page,
  options: {
    role?: Role;
    scheme?: "light" | "dark";
    overrides?: Partial<SettingsMockState>;
  } = {},
): Promise<SettingsMockState> {
  const shell = newState({ role: options.role ?? "admin", displayName: "Test Admin" });
  await page.emulateMedia({ colorScheme: options.scheme ?? "light", reducedMotion: "reduce" });
  await mockApi(page, shell);
  const state = newSettingsState(options.overrides);
  await mockSettingsApi(page, state);
  const base = test.info().project.use.baseURL ?? "http://127.0.0.1:4173";
  await page.context().addCookies([{ name: "cso_csrf", value: "csrf-token-123", url: base }]);
  return state;
}

async function open(page: Page) {
  await page.goto("/settings");
  await expect(page.getByTestId("settings-screen")).toBeVisible();
  await expect(page.locator("#ws-name")).toBeVisible();
}

const accentOnRoot = (page: Page) =>
  page.evaluate(() =>
    getComputedStyle(document.documentElement).getPropertyValue("--color-accent").trim(),
  );

test.describe("@settings access", () => {
  test("an admin sees the link and the page; a reviewer gets the 403 page and no link", async ({
    page,
  }) => {
    await setup(page);
    await page.goto("/queue");
    await shellReady(page);
    await page.getByTestId("nav-settings").click();
    await expect(page).toHaveURL(/\/settings$/);
    await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
    await expect(page.getByTestId("breadcrumb")).toHaveText("Settings");
    await expect(page).toHaveTitle(/Settings/);
  });

  test("a reviewer cannot open it", async ({ page }) => {
    await setup(page, { role: "reviewer" });
    await page.goto("/settings");
    await expect(page.getByRole("heading", { name: "No access" })).toBeVisible();
    await expect(page.getByTestId("settings-screen")).toHaveCount(0);
    await expect(page.getByTestId("nav-settings")).toHaveCount(0);
  });
});

test.describe("@settings tabs", () => {
  test("there are four tabs, reachable with the arrow keys", async ({ page }) => {
    await setup(page);
    await open(page);
    const tabs = page.getByRole("tab");
    await expect(tabs).toHaveText(["Workspace", "Review", "Access", "Export"]);
    await expect(page.getByRole("tab", { name: "Workspace" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await page.getByRole("tab", { name: "Workspace" }).focus();
    await page.keyboard.press("ArrowRight");
    await expect(page.getByRole("tab", { name: "Review" })).toBeFocused();
    await expect(page.getByTestId("settings-review")).toBeVisible();
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("ArrowRight");
    await expect(page.getByRole("tab", { name: "Export" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expect(page.getByTestId("settings-export")).toBeVisible();
  });

  test("the review tab names the pack in force and points to Config", async ({ page }) => {
    await setup(page);
    await open(page);
    await page.getByRole("tab", { name: "Review" }).click();
    await expect(page.getByTestId("review-pack")).toHaveText("default");
    await expect(page.getByTestId("review-calibration")).toContainText("None yet");
    await page.getByTestId("review-open-config").click();
    await expect(page).toHaveURL(/\/config$/);
  });
});

test.describe("@settings workspace tab", () => {
  test("the contrast readout follows what is typed", async ({ page }) => {
    await setup(page);
    await open(page);
    const accent = page.getByLabel("Accent colour");
    await expect(page.getByTestId("accent-light")).toHaveAttribute("data-passes", "true");
    await accent.fill("#F0F0F0");
    await expect(page.getByTestId("accent-light")).toHaveAttribute("data-passes", "false");
    await expect(page.getByTestId("accent-light")).toContainText("too low");
    await accent.fill("#3A46B0");
    await expect(page.getByTestId("accent-light")).toContainText("enough");
    await expect(page.getByTestId("accent-dark")).toContainText("#6D76C5");
    await accent.fill("#3A4");
    await expect(page.getByTestId("accent-readout")).toContainText("Enter a colour as #rrggbb");
  });

  test("save waits for an edit, then sends If-Match and the CSRF header", async ({ page }) => {
    const state = await setup(page);
    await open(page);
    const save = page.getByTestId("settings-save");
    await expect(save).toBeDisabled();
    await page.getByLabel("Name").fill("Second Opinion Lyon");
    await page.getByLabel("Accent colour").fill("#3A46B0");
    await expect(page.getByTestId("settings-unsaved")).toBeVisible();
    await save.click();

    await expect(page.getByRole("status", { name: "Announcements" })).toContainText(
      "Settings saved",
    );
    expect(state.puts).toHaveLength(1);
    expect(state.puts[0]).toMatchObject({
      ifMatch: 'W/"1"',
      csrf: "csrf-token-123",
      body: { name: "Second Opinion Lyon", accent_hex: "#3A46B0", logo_svg: null },
    });
    expect(state.version).toBe(2);
    await expect(save).toBeDisabled();
    // The shell follows without a reload: new name in the rail, new accent on the page.
    await expect(page.getByTestId("brand-name")).toHaveText("Second Opinion Lyon");
    expect(await accentOnRoot(page)).toBe("#3A46B0");
  });

  test("a second save uses the new version", async ({ page }) => {
    const state = await setup(page);
    await open(page);
    await page.getByLabel("Name").fill("One");
    await page.getByTestId("settings-save").click();
    await expect(page.getByTestId("settings-save")).toBeDisabled();
    await page.getByLabel("Name").fill("Two");
    await page.getByTestId("settings-save").click();
    await expect(page.getByRole("status", { name: "Announcements" })).toContainText("saved");
    expect(state.puts.map((p) => p.ifMatch)).toEqual(['W/"1"', 'W/"2"']);
  });

  test("a refused save lists each field, keeps the edits and applies nothing", async ({ page }) => {
    const state = await setup(page, {
      overrides: {
        rejectNext: {
          tagline: "This uses a word the tool does not use.",
          accent_hex: "Contrast on the light canvas is 1.10; at least 4.5 is needed.",
        },
      },
    });
    await open(page);
    await page.getByLabel("Tagline").fill("Edited tagline");
    await page.getByTestId("settings-save").click();

    const summary = page.getByTestId("settings-problems");
    await expect(summary).toBeVisible();
    await expect(summary).toBeFocused();
    await expect(summary).toContainText("Tagline");
    await expect(summary).toContainText("Accent colour");
    await expect(page.getByTestId("ws-tagline-error")).toContainText(
      "a word the tool does not use",
    );
    await expect(page.getByLabel("Tagline")).toHaveAttribute("aria-invalid", "true");
    await expect(page.getByLabel("Tagline")).toHaveValue("Edited tagline");
    expect(state.version).toBe(1);
    expect(await accentOnRoot(page)).toBe("#4e5bd8");

    await summary.getByRole("button", { name: "Tagline" }).click();
    await expect(page.getByLabel("Tagline")).toBeFocused();
    await expectNoSeriousA11yIssues(page, "settings refused save");
  });

  test("a change made by someone else shows the reload message and loses nothing silently", async ({
    page,
  }) => {
    const state = await setup(page, { overrides: { conflictNext: true } });
    await open(page);
    await page.getByLabel("Name").fill("Mine");
    await page.getByTestId("settings-save").click();
    await expect(page.getByTestId("settings-conflict")).toContainText(
      "Someone else changed settings, reload",
    );
    expect(state.name).toBe("Changeset Second Opinion"); // nothing was written
    await expect(page.getByLabel("Name")).toHaveValue("Mine"); // the edit is still on screen

    await page.getByTestId("settings-reload").click();
    await expect(page.getByTestId("settings-conflict")).toHaveCount(0);
    await expect(page.getByLabel("Name")).toHaveValue("Changeset Second Opinion");
    // After the reload a save goes through with the newer version.
    await page.getByLabel("Name").fill("Mine");
    await page.getByTestId("settings-save").click();
    await expect(page.getByRole("status", { name: "Announcements" })).toContainText("saved");
    expect(state.puts.at(-1)?.ifMatch).toBe('W/"2"');
  });

  test("a server error says so and keeps the edits", async ({ page }) => {
    await setup(page, { overrides: { failNext: true } });
    await open(page);
    await page.getByLabel("Name").fill("Kept");
    await page.getByTestId("settings-save").click();
    await expect(page.getByTestId("settings-failed")).toBeVisible();
    await expect(page.getByLabel("Name")).toHaveValue("Kept");
  });

  test("discard puts the saved values back", async ({ page }) => {
    await setup(page);
    await open(page);
    await page.getByLabel("Name").fill("Scratch");
    await page.getByTestId("settings-discard").click();
    await expect(page.getByLabel("Name")).toHaveValue("Changeset Second Opinion");
    await expect(page.getByTestId("settings-save")).toBeDisabled();
  });

  test("a logo is chosen, previewed, saved and removed", async ({ page }) => {
    const state = await setup(page);
    await open(page);
    await expect(page.getByTestId("logo-none")).toBeVisible();

    await page
      .getByTestId("logo-file")
      .setInputFiles({ name: "logo.svg", mimeType: "image/svg+xml", buffer: Buffer.from(LOGO) });
    await expect(page.getByTestId("logo-preview")).toBeVisible();
    await expect(page.getByTestId("logo-note")).toContainText("Chosen file: logo.svg");
    await page.getByTestId("settings-save").click();
    await expect(page.getByRole("status", { name: "Announcements" })).toContainText("saved");
    expect(state.puts[0]?.body.logo_svg).toBe(LOGO);
    // The rail's brand link now shows the stored logo through an img tag.
    await expect(page.locator('img[src="/api/v1/public/branding/logo.svg"]').first()).toHaveCount(
      1,
    );

    await page.getByTestId("logo-remove").click();
    await expect(page.getByTestId("logo-note")).toContainText("removed when you save");
    await page.getByTestId("settings-save").click();
    await expect(page.getByTestId("logo-none")).toBeVisible();
    expect(state.logo_svg).toBeNull();
  });

  test("a file that is not an SVG is turned away before any request", async ({ page }) => {
    const state = await setup(page);
    await open(page);
    await page
      .getByTestId("logo-file")
      .setInputFiles({ name: "logo.png", mimeType: "image/png", buffer: Buffer.from("x") });
    await expect(page.getByTestId("logo-note")).toContainText("ending in .svg");
    await expect(page.getByTestId("settings-save")).toBeDisabled();
    expect(state.puts).toHaveLength(0);
  });
});

test.describe("@settings access tab", () => {
  test("the invite table lists label, role, dates, uses and status", async ({ page }) => {
    await setup(page);
    await open(page);
    await page.getByRole("tab", { name: "Access" }).click();
    const table = page.getByTestId("invite-table");
    await expect(table.locator("tbody tr")).toHaveCount(2);
    const first = table.locator("tbody tr").nth(0);
    await expect(first).toContainText("Lyon team");
    await expect(first).toContainText("Reviewer");
    await expect(first).toContainText("Never");
    await expect(first).toContainText("2 of 5");
    await expect(first.getByTestId("invite-status")).toHaveText("Active");
    const second = table.locator("tbody tr").nth(1);
    await expect(second.getByTestId("invite-status")).toHaveText("Revoked");
    await expect(second.getByTestId("invite-revoke")).toHaveCount(0);
  });

  test("a new code is shown once, and the list then holds it", async ({ page }) => {
    const state = await setup(page);
    await open(page);
    await page.getByRole("tab", { name: "Access" }).click();
    await page.getByTestId("invite-create").click();
    const dialog = page.getByRole("dialog", { name: "New invite code" });
    await dialog.getByTestId("invite-label").fill("Paris group");
    await dialog.getByTestId("invite-uses").fill("3");
    await dialog.getByTestId("invite-submit").click();

    const shown = page.getByRole("dialog", { name: "Copy this code now" });
    await expect(shown.getByTestId("invite-code")).toHaveText("cso-test-code-shown-once");
    expect(state.created).toEqual([
      { label: "Paris group", role: "reviewer", ttl_hours: null, max_uses: 3 },
    ]);
    await shown.getByTestId("invite-done").click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(page.getByTestId("invite-table")).toContainText("Paris group");
    await expect(page.getByTestId("invite-table")).not.toContainText("cso-test-code");
  });

  test("a bad number is caught in the dialog", async ({ page }) => {
    const state = await setup(page);
    await open(page);
    await page.getByRole("tab", { name: "Access" }).click();
    await page.getByTestId("invite-create").click();
    await page.getByTestId("invite-ttl").fill("0");
    await page.getByTestId("invite-submit").click();
    await expect(page.getByTestId("invite-error")).toBeVisible();
    expect(state.created).toHaveLength(0);
  });

  test("revoking asks first, then marks the code revoked", async ({ page }) => {
    const state = await setup(page);
    await open(page);
    await page.getByRole("tab", { name: "Access" }).click();
    const row = page.getByTestId("invite-table").locator("tbody tr").first();
    await row.getByTestId("invite-revoke").click();
    const dialog = page.getByRole("dialog", { name: "Revoke this invite code?" });
    await expect(dialog).toContainText("signed out");
    await dialog.getByRole("button", { name: "Cancel" }).click();
    expect(state.revoked).toEqual([]);

    await row.getByTestId("invite-revoke").click();
    await page.getByTestId("revoke-confirm").click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    expect(state.revoked).toEqual(["00000000-0000-4000-8000-000000000a01"]);
    await expect(row.getByTestId("invite-status")).toHaveText("Revoked");
  });

  test("the sign-in switch saves on its own with the saved values", async ({ page }) => {
    const state = await setup(page);
    await open(page);
    await page.getByLabel("Name").fill("Unsaved edit"); // must not ride along with the switch
    await page.getByRole("tab", { name: "Access" }).click();
    const toggle = page.getByTestId("signin-toggle");
    await expect(toggle).toBeChecked();
    await toggle.click();
    await expect(page.getByRole("status", { name: "Announcements" })).toContainText(
      "Sign in with OpenStreetMap is now off",
    );
    expect(state.puts[0]?.body).toMatchObject({
      osm_signin_enabled: false,
      name: "Changeset Second Opinion",
    });
    expect(state.puts[0]?.ifMatch).toBe('W/"1"');
    await expect(toggle).not.toBeChecked();
  });

  test("the switch is off and explained when the server has no OpenStreetMap application", async ({
    page,
  }) => {
    await setup(page, { overrides: { osm_signin_configured: false } });
    await open(page);
    await page.getByRole("tab", { name: "Access" }).click();
    await expect(page.getByTestId("signin-toggle")).toBeDisabled();
    await expect(page.getByTestId("signin-toggle")).not.toBeChecked();
    await expect(page.getByTestId("signin-reason")).toContainText("no OpenStreetMap application");
  });
});

test.describe("@settings export tab", () => {
  test("downloads the settings as JSON without secrets", async ({ page }) => {
    await setup(page);
    await open(page);
    await page.getByRole("tab", { name: "Export" }).click();
    const download = page.waitForEvent("download");
    await page.getByTestId("export-run").click();
    const file = await download;
    expect(file.suggestedFilename()).toBe("settings.json");
    const path = await file.path();
    const { readFile } = await import("node:fs/promises");
    const parsed = JSON.parse(await readFile(path, "utf-8")) as Record<string, unknown>;
    expect(parsed).toMatchObject({ name: "Changeset Second Opinion", version: 1 });
    expect(Object.keys(parsed).join(" ")).not.toMatch(/secret|token|code/i);
  });
});

test.describe("@settings wording and accessibility", () => {
  for (const scheme of ["light", "dark"] as const) {
    for (const tab of ["Workspace", "Review", "Access", "Export"]) {
      test(`axe is clean and no banned word shows on ${tab} (${scheme})`, async ({ page }) => {
        await setup(page, { scheme });
        await open(page);
        await page.getByRole("tab", { name: tab }).click();
        if (tab === "Access") await expect(page.getByTestId("invite-table")).toBeVisible();
        await expectNoSeriousA11yIssues(page, `settings ${tab} ${scheme}`);
        const text = await page.getByTestId("settings-screen").innerText();
        expect(text).not.toMatch(BANNED);
        expect(text).not.toMatch(/[–—]/);
      });
    }
  }

  test("axe is clean with the invite dialogs open", async ({ page }) => {
    await setup(page);
    await open(page);
    await page.getByRole("tab", { name: "Access" }).click();
    await page.getByTestId("invite-create").click();
    await expectNoSeriousA11yIssues(page, "invite create dialog");
    await page.keyboard.press("Escape");
    await page
      .getByTestId("invite-table")
      .locator("tbody tr")
      .first()
      .getByTestId("invite-revoke")
      .click();
    await expectNoSeriousA11yIssues(page, "invite revoke dialog");
  });

  test("the accent follows the theme: the lightened copy shows on the dark page", async ({
    page,
  }) => {
    await setup(page, {
      scheme: "dark",
      overrides: { accent_hex: "#3A46B0", accent_dark_hex: "#6D76C5" },
    });
    await page.goto("/queue");
    await shellReady(page);
    await expect.poll(() => accentOnRoot(page)).toBe("#6D76C5");
    await page.emulateMedia({ colorScheme: "light" });
    await expect.poll(() => accentOnRoot(page)).toBe("#3A46B0");
  });
});
