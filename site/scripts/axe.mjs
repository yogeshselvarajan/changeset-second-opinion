// Runs axe on every built page, in light and dark. It uses the Playwright and axe that web/ already
// installs, and serves site/dist with `astro preview`.
//
//   npm run build && node scripts/axe.mjs
//
// Exit 1 on any serious or critical violation.
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, extname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");
const web = resolve(root, "..", "web");
const require = createRequire(join(web, "package.json"));
const { chromium } = require("@playwright/test");
const AxeBuilder = require("@axe-core/playwright").default;

const port = 4399;
const base = process.env.DOCS_BASE ?? "/docs";
const dist = join(root, "dist");

function pages(dir, prefix = "") {
  const out = [];
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) out.push(...pages(path, `${prefix}${name}/`));
    else if (name === "index.html") out.push(prefix);
  }
  return out;
}

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css",
  ".js": "text/javascript",
  ".json": "application/json",
  ".svg": "image/svg+xml",
  ".webp": "image/webp",
  ".png": "image/png",
  ".woff2": "font/woff2",
  ".xml": "application/xml",
  ".txt": "text/plain; charset=utf-8",
};
// A small static server for dist/, mounted at the site's base path, as the web server does.
const server = createServer((request, response) => {
  let path = decodeURIComponent(new URL(request.url ?? "/", "http://x").pathname);
  if (path.startsWith(base)) path = path.slice(base.length);
  let file = join(dist, path);
  if (existsSync(file) && statSync(file).isDirectory()) file = join(file, "index.html");
  if (!existsSync(file)) {
    response.writeHead(404);
    response.end("not found");
    return;
  }
  response.writeHead(200, { "content-type": TYPES[extname(file)] ?? "application/octet-stream" });
  response.end(readFileSync(file));
});
await new Promise((ok) => server.listen(port, "127.0.0.1", ok));

const channel = process.env.PW_CHANNEL || undefined;
const browser = await chromium.launch({ channel });
const failures = [];
const only = process.env.ONLY; // for example ONLY=api/operations/get_case to check one page
const list = pages(dist).filter(
  (p) => !p.startsWith("_") && !p.startsWith("pagefind") && (!only || p.includes(only)),
);
for (const scheme of ["light", "dark"]) {
  const context = await browser.newContext({ colorScheme: scheme, reducedMotion: "reduce" });
  const page = await context.newPage();
  for (const path of list) {
    await page.goto(`http://127.0.0.1:${port}${base}/${path}`, { waitUntil: "load" });
    await page.evaluate((s) => document.documentElement.setAttribute("data-theme", s), scheme);
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag22aa"])
      .analyze();
    for (const v of results.violations) {
      if (v.impact === "serious" || v.impact === "critical") {
        failures.push(`${scheme} /${path}: ${v.id} (${v.nodes.length})`);
        if (process.env.DEBUG) {
          for (const node of v.nodes.slice(0, 4)) {
            const data = node.any[0]?.data ?? {};
            failures.push(
              `   ${node.html.slice(0, 110)} fg ${data.fgColor} bg ${data.bgColor} ratio ${data.contrastRatio}`,
            );
          }
        }
      }
    }
  }
  await context.close();
}
await browser.close();
server.close();
if (failures.length) {
  console.error(failures.join("\n"));
  process.exit(1);
}
console.log(`axe: ${list.length} pages, light and dark, no serious issues`);
process.exit(0);
