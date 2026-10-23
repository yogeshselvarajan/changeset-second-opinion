// Fails the build when the prerendered pages are not what the page list says they should be.
import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");

const FILES = { "/": "index.html", "/about": "about/index.html", "/privacy": "privacy/index.html" };
FILES["/404"] = "404.html";

/** Problems with the built pages, as a list of sentences (empty when all is well). */
export function distProblems({ files, renderedTitles, sitemap, robots, shell }) {
  const problems = [];
  for (const [path, text] of Object.entries(files)) {
    const h1 = (text.match(/<h1[\s>]/g) ?? []).length;
    if (h1 !== 1) problems.push(`${path}: expected one <h1>, found ${h1}`);
    const title = /<title[^>]*>([\s\S]*?)<\/title>/.exec(text)?.[1];
    if (title !== renderedTitles[path]) {
      problems.push(
        `${path}: title is ${JSON.stringify(title)}, expected ${JSON.stringify(renderedTitles[path])}`,
      );
    }
    if ((text.match(/<title[\s>]/g) ?? []).length !== 1)
      problems.push(`${path}: more than one <title>`);
    if (text.includes("__CSO_PUBLIC_ORIGIN__"))
      problems.push(`${path}: origin placeholder left in`);
    if (!/<div id="root"[^>]*>\s*<div/.test(text)) problems.push(`${path}: the root is empty`);
    const noindex = /<meta[^>]*name="robots"[^>]*noindex/.test(text);
    if (path === "/404" && !noindex) problems.push("/404: should ask not to be indexed");
    if (path !== "/404" && noindex) problems.push(`${path}: must be indexable`);
    if (/\/api\/v1\//.test(text)) problems.push(`${path}: mentions the API`);
  }
  if (!/<div id="root"><\/div>/.test(shell)) problems.push("_shell.html: the root should be empty");
  for (const path of ["/", "/about", "/privacy"]) {
    if (!sitemap.includes(`${path}</loc>`)) problems.push(`sitemap.xml: missing ${path}`);
  }
  if (sitemap.includes("/queue")) problems.push("sitemap.xml: lists an app address");
  if (!/Sitemap: https?:\/\/\S+\/sitemap\.xml/.test(robots))
    problems.push("robots.txt: no sitemap line");
  return problems;
}

async function main() {
  const dist = join(root, "dist");
  const { render } = await import(pathToFileURL(join(root, "dist-ssr", "entry-prerender.js")).href);
  const files = {};
  const renderedTitles = {};
  for (const [path, rel] of Object.entries(FILES)) {
    const full = join(dist, rel);
    if (!existsSync(full)) throw new Error(`check-dist: ${rel} was not written`);
    files[path] = await readFile(full, "utf-8");
    renderedTitles[path] = /<title[^>]*>([\s\S]*?)<\/title>/.exec(render(path).head)?.[1];
  }
  const problems = distProblems({
    files,
    renderedTitles,
    sitemap: await readFile(join(dist, "sitemap.xml"), "utf-8"),
    robots: await readFile(join(dist, "robots.txt"), "utf-8"),
    shell: await readFile(join(dist, "_shell.html"), "utf-8"),
  });
  if (process.env.CSO_SKIP_DOCS !== "1") {
    for (const rel of ["docs/index.html", "docs/start/quickstart/index.html"]) {
      if (!existsSync(join(dist, rel))) problems.push(`${rel} was not written (the docs build)`);
    }
  }
  if (problems.length > 0) {
    for (const problem of problems) console.error(`check-dist: ${problem}`);
    process.exit(1);
  }
  console.log(`check-dist: ${Object.keys(files).length} pages, sitemap and robots look right`);
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  await main();
}
