// Takes the product screenshots used by the home page.
//
//   npm run build && npm run screenshots
//
// It runs the real stack on this machine: the API in replay mode on a throwaway database seeded
// with the 15 demo changesets (backend/fixtures/demo), which carry the saved Decider readings. It
// signs in with a freshly made invite, opens the Nairobi demo case (changeset 190380899) and
// captures it in light and dark at 1600 x 1000.
// Nothing here reaches OpenStreetMap or any other host. Every process it starts is stopped by its
// own process id when it finishes.
//
// Outputs: web/public/screenshots/case-light.webp and case-dark.webp (home page).
import { Buffer } from "node:buffer";
import { spawn, spawnSync } from "node:child_process";
import { request as httpRequest } from "node:http";
import { existsSync } from "node:fs";
import { mkdir, mkdtemp, rm } from "node:fs/promises";
import { createConnection } from "node:net";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "@playwright/test";
import sharp from "sharp";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const repo = join(root, "..");
const backend = join(repo, "backend");
const API_PORT = 8000; // the preview server proxies /api here
const WEB_PORT = 4173;
const CHANGESET = 190380899;
const SIZE = { width: 1600, height: 1000 };

const children = [];

function stopAll() {
  for (const child of children) {
    if (child.exitCode !== null || child.pid === undefined) continue;
    if (process.platform === "win32") {
      spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore" });
    } else {
      child.kill("SIGTERM");
    }
  }
}

function portInUse(port) {
  return new Promise((resolve) => {
    const socket = createConnection({ port, host: "127.0.0.1" });
    socket.once("connect", () => (socket.destroy(), resolve(true)));
    socket.once("error", () => resolve(false));
  });
}

async function waitFor(url, label, ms = 60_000) {
  const until = Date.now() + ms;
  while (Date.now() < until) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 400));
  }
  throw new Error(`screenshots: ${label} did not come up at ${url}`);
}

function run(command, args, env) {
  const result = spawnSync(command, args, { cwd: backend, env, encoding: "utf-8" });
  if (result.status !== 0) {
    throw new Error(`screenshots: ${command} ${args.join(" ")} failed\n${result.stderr}`);
  }
  return result.stdout;
}

function start(command, args, env, cwd = backend) {
  const child = spawn(command, args, { cwd, env, stdio: "ignore" });
  children.push(child);
  return child;
}

async function main() {
  if (!existsSync(join(root, "dist", "index.html"))) {
    throw new Error("screenshots: run `npm run build` first");
  }
  for (const port of [API_PORT, WEB_PORT]) {
    if (await portInUse(port)) throw new Error(`screenshots: port ${port} is already in use`);
  }
  const work = await mkdtemp(join(tmpdir(), "cso-shots-"));
  const db = `sqlite+aiosqlite:///${join(work, "shots.db").replaceAll("\\", "/")}`;
  const env = {
    ...process.env,
    PYTHONUTF8: "1",
    CSO_MODE: "replay",
    CSO_DATABASE_URL: db,
    CSO_OSM_OAUTH_CLIENT_ID: "",
    CSO_OSM_OAUTH_CLIENT_SECRET: "",
    CSO_OSM_OAUTH_REDIRECT_URL: "",
  };
  try {
    run("uv", ["run", "cso", "db", "upgrade"], env);
    run("uv", ["run", "cso", "seed"], env);
    const invite = run(
      "uv",
      [
        "run",
        "cso",
        "auth",
        "create-invite",
        "--role",
        "reviewer",
        "--ttl-hours",
        "1",
        "--label",
        "screenshots",
      ],
      env,
    )
      .split(/\s+/)
      .find((word) => /^cso-[0-9a-f]{8}-/.test(word));
    if (!invite) throw new Error("screenshots: could not read the invite code");

    start("uv", ["run", "cso", "api"], env);
    start(
      process.execPath,
      [
        join(root, "node_modules", "vite", "bin", "vite.js"),
        "preview",
        "--host",
        "127.0.0.1",
        "--port",
        String(WEB_PORT),
        "--strictPort",
      ],
      env,
      root,
    );
    await waitFor(`http://127.0.0.1:${API_PORT}/healthz`, "the API");
    await waitFor(`http://127.0.0.1:${WEB_PORT}/`, "the web server");

    // Sign in over the API and find the case; the demo seed already holds its saved analysis.
    const base = `http://127.0.0.1:${API_PORT}`;
    // Node's fetch will not send a Cookie header, so these calls use the http module.
    const call = (method, path, { cookie, csrf, body } = {}) =>
      new Promise((resolve, reject) => {
        const payload = body === undefined ? undefined : JSON.stringify(body);
        const headers = { accept: "application/json" };
        if (payload !== undefined) headers["content-type"] = "application/json";
        if (payload !== undefined) headers["content-length"] = Buffer.byteLength(payload);
        if (cookie) headers.cookie = cookie;
        if (csrf) headers["x-csrf"] = csrf;
        const request = httpRequest(`${base}${path}`, { method, headers }, (response) => {
          const chunks = [];
          response.on("data", (chunk) => chunks.push(chunk));
          response.on("end", () => {
            const text = Buffer.concat(chunks).toString("utf-8");
            let json = null;
            try {
              json = JSON.parse(text);
            } catch {
              /* not JSON */
            }
            resolve({ status: response.statusCode ?? 0, headers: response.headers, text, json });
          });
        });
        request.on("error", reject);
        request.end(payload);
      });
    const login = await call("POST", "/api/v1/auth/login", {
      body: { invite_code: invite, display_name: "Docs reviewer" },
    });
    if (login.status !== 200) throw new Error(`screenshots: sign-in failed (${login.status})`);
    const cookies = (login.headers["set-cookie"] ?? []).map((line) => {
      const [pair, ...attrs] = line.split(";");
      const [name, ...value] = pair.split("=");
      return { name: name.trim(), value: value.join("="), attrs: attrs.join(";").toLowerCase() };
    });
    const header = cookies.map((c) => `${c.name}=${c.value}`).join("; ");
    const list = await call("GET", "/api/v1/cases?limit=50", { cookie: header });
    const found = list.json?.items?.find((item) => item.changeset_id === CHANGESET);
    if (!found) throw new Error(`screenshots: changeset ${CHANGESET} is not in the seeded queue`);

    const browser = await chromium.launch({ channel: process.env.PW_CHANNEL || undefined });
    await mkdir(join(root, "public", "screenshots"), { recursive: true });
    try {
      for (const scheme of ["light", "dark"]) {
        const context = await browser.newContext({ viewport: SIZE, colorScheme: scheme });
        await context.addCookies(
          cookies.map((c) => ({
            name: c.name,
            value: c.value,
            url: `http://127.0.0.1:${WEB_PORT}`,
            httpOnly: c.attrs.includes("httponly"),
          })),
        );
        const page = await context.newPage();
        // The map would fetch tiles from a third party; the capture stays on this machine.
        await page.route(/tiles\.openfreemap\.org/, (route) => route.abort());
        await page.goto(`http://127.0.0.1:${WEB_PORT}/cases/${found.id}`);
        await page.getByTestId("panel-probes").first().waitFor({ timeout: 30_000 });
        await page.waitForLoadState("networkidle");
        await page.waitForTimeout(600);
        const png = await page.screenshot({ type: "png" });
        await sharp(png)
          .webp({ quality: 82 })
          .toFile(join(root, "public", "screenshots", `case-${scheme}.webp`));
        console.log(`wrote case-${scheme} (web/public/screenshots)`);
        await context.close();
      }
    } finally {
      await browser.close();
    }
  } finally {
    stopAll();
    await rm(work, { recursive: true, force: true }).catch(() => {});
  }
}

try {
  await main();
} catch (error) {
  console.error(error instanceof Error ? error.message : error);
  stopAll();
  process.exitCode = 1;
}
