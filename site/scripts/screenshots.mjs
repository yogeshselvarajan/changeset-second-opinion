// Takes the screenshots the docs use, in light and dark, from the app running in replay mode on the
// demo changesets (backend/fixtures/demo). Nothing here is mocked.
//
// Start the stack first (API: `uv run cso seed && uv run cso api` in backend/, web: `npm run dev` in
// web/), make an invite (`uv run cso auth create-invite --role reviewer`), then:
//
//   INVITE=<code> npm run screenshots          (BASE defaults to http://127.0.0.1:5173)
//
// The images go to src/assets/screens/<name>-light.png and <name>-dark.png. The four the README
// shows (case, queue, draft, receipt) are also copied to ../assets/screen-<name>-<scheme>.png.
// Re-run it when the UI changes. It uses the Playwright that web/ already installs.
import { createRequire } from "node:module";
import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const web = resolve(here, "..", "..", "web");
const require = createRequire(join(web, "package.json"));
const { chromium } = require("@playwright/test");

const base = process.env.BASE ?? "http://127.0.0.1:5173";
const invite = process.env.INVITE;
if (!invite) {
  console.error("Set INVITE to an invite code (cso auth create-invite --role reviewer).");
  process.exit(1);
}
const outDir = resolve(here, "..", "src", "assets", "screens");
const readmeDir = resolve(here, "..", "..", "assets");
mkdirSync(outDir, { recursive: true });
const channel = process.env.PW_CHANNEL || "chrome";
const size = { width: 1280, height: 800 };
// Nairobi: a road removed because houses were built, one discussion comment. Full coverage, a new
// mapper, and a fact panel with several yes and no readings.
const SAMPLE_CHANGESET = 190380899;
// Berlin: a few trees added with a plain comment. The suggested response is a source question.
const DRAFT_CHANGESET = 190761641;
const README_SHOTS = new Set(["case", "queue", "draft", "receipt"]);

const browser = await chromium.launch({ channel });

async function shot(page, scheme, name) {
  await page.waitForTimeout(900);
  const file = join(outDir, `${name}-${scheme}.png`);
  await page.screenshot({ path: file });
  if (README_SHOTS.has(name)) copyFileSync(file, join(readmeDir, `screen-${name}-${scheme}.png`));
  console.log(`${name}-${scheme}`);
}

// Scrolls so the heading sits just under the top bar.
async function scrollToHeading(page, name, offset) {
  await page
    .getByRole("heading", { name })
    .first()
    .evaluate((el, off) => window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - off), offset);
}

for (const scheme of ["light", "dark"]) {
  const context = await browser.newContext({
    viewport: size,
    colorScheme: scheme,
    reducedMotion: "reduce",
  });
  const page = await context.newPage();
  // The map would fetch tiles from a third party; the capture stays on this machine.
  await page.route(/tiles\.openfreemap\.org/, (route) => route.abort());

  await page.goto(`${base}/login`);
  await page.getByRole("heading", { level: 1 }).waitFor();
  await shot(page, scheme, "login");

  await page.getByLabel("Invite code").fill(invite);
  await page.getByLabel("Display name").fill("Docs reviewer");
  await page.getByRole("button", { name: "Sign in", exact: true }).last().click();
  await page.waitForURL(/queue/);
  await page.locator("[data-testid=case-row]").first().waitFor();
  await shot(page, scheme, "queue");

  const list = await (await page.request.get(`${base}/api/v1/cases?limit=100`)).json();
  const item = list.items.find((c) => c.changeset_id === SAMPLE_CHANGESET) ?? list.items[0];
  const runs = await (await page.request.get(`${base}/api/v1/cases/${item.id}/runs`)).json();
  const runId = (runs.items ?? runs)[0]?.id;

  await page.goto(`${base}/cases/${item.id}`);
  await page.getByRole("heading", { level: 1 }).waitFor();
  await page.getByRole("heading", { name: "Fact panel" }).first().waitFor();
  await shot(page, scheme, "case");

  await page.evaluate(() => window.scrollTo(0, 620));
  await shot(page, scheme, "case-evidence");

  await scrollToHeading(page, "Fact panel", 110);
  await shot(page, scheme, "case-readings");

  if (runId) {
    await page.goto(`${base}/r/${runId}`);
    await page.getByRole("heading", { level: 1 }).waitFor();
    await shot(page, scheme, "receipt");
  }

  // A case whose suggested response is a comment. In replay mode the draft is the offline template.
  const drafted = list.items.find((c) => c.changeset_id === DRAFT_CHANGESET) ?? item;
  await page.goto(`${base}/cases/${drafted.id}/draft`);
  await page.getByRole("heading", { level: 1 }).waitFor();
  const write = page.getByRole("button", { name: "Write a draft" });
  if (await write.isEnabled().catch(() => false)) await write.click();
  await page.waitForFunction(
    () => (document.querySelector("textarea")?.value.length ?? 0) > 20,
    null,
    { timeout: 60000 },
  );
  await page.waitForTimeout(800);
  await shot(page, scheme, "draft");

  await page.goto(`${base}/history`);
  await page.getByRole("heading", { level: 1 }).waitFor();
  await shot(page, scheme, "history");

  // Config and Settings are admin pages: set ADMIN=1 and use an admin invite to retake them.
  if (process.env.ADMIN) {
    await page.goto(`${base}/config`);
    await page.getByRole("heading", { level: 1 }).waitFor();
    await shot(page, scheme, "config");

    await page.goto(`${base}/settings`);
    await page.getByRole("heading", { level: 1 }).waitFor();
    await shot(page, scheme, "settings");
  }

  await context.close();
}
await browser.close();
