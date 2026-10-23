// Writes the public pages into dist/ as static HTML, from the bundle built by
// `vite build --ssr src/entry-prerender.tsx --outDir dist-ssr`.
//
//   dist/_shell.html        the untouched app shell (what an app address falls back to)
//   dist/index.html         the home page
//   dist/about/index.html   dist/privacy/index.html   dist/404.html
//   dist/sitemap.xml        written from the same route list as the pages
//
// The page head is the template's head with the title, description and canonical replaced by the
// page's own, plus robots and JSON-LD where a page has them. The replaced tags are marked
// data-static-seo, so the client removes them when it renders its own (see src/seo/Seo.tsx).
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const dist = join(root, "dist");
const bundle = join(root, "dist-ssr", "entry-prerender.js");

const escapeAttr = (value) =>
  value.replaceAll("&", "&amp;").replaceAll('"', "&quot;").replaceAll("<", "&lt;");

/** Marks every head tag of `head` as replaceable by the client. */
export function markStatic(head) {
  return head.replace(/<(title|meta|link|script)(?=[\s>/])/g, "<$1 data-static-seo");
}

/** The template with one page's head and body in it. Pure, so a test can run it. */
export function applyPage(template, { html, head, meta }, origin) {
  const url = `${origin}${meta.path === "/404" ? "/" : meta.path}`;
  let out = template;
  const take = (pattern, label) => {
    if (!pattern.test(out)) throw new Error(`prerender: the template has no ${label}`);
  };
  take(/<title data-static-seo>[\s\S]*?<\/title>/, "static title");
  take(/<meta\s+data-static-seo\s+name="description"[\s\S]*?\/>\s*/, "static description");
  take(/<link data-static-seo rel="canonical"[^>]*\/>\s*/, "static canonical");
  take(/<div id="root"><\/div>/, "empty root");
  out = out.replace(/<meta\s+data-static-seo\s+name="description"[\s\S]*?\/>\s*/, "");
  out = out.replace(/<link data-static-seo rel="canonical"[^>]*\/>\s*/, "");
  out = out.replace(/<title data-static-seo>[\s\S]*?<\/title>/, () => markStatic(head));
  const title = /<title[^>]*>([\s\S]*?)<\/title>/.exec(head)?.[1] ?? meta.title;
  // The template may wrap a tag over several lines, so the patterns allow any whitespace.
  const social = [
    [/(<meta\s+property="og:title"\s+content=")[^"]*(")/, title],
    [/(<meta\s+property="og:description"\s+content=")[^"]*(")/, meta.description],
    [/(<meta\s+property="og:url"\s+content=")[^"]*(")/, url],
    [/(<meta\s+name="twitter:title"\s+content=")[^"]*(")/, title],
    [/(<meta\s+name="twitter:description"\s+content=")[^"]*(")/, meta.description],
  ];
  for (const [pattern, value] of social) {
    if (!pattern.test(out)) throw new Error(`prerender: the template has no ${pattern.source}`);
    out = out.replace(pattern, (_m, a, b) => `${a}${escapeAttr(value)}${b}`);
  }
  return out.replace('<div id="root"></div>', () => `<div id="root">${html}</div>`);
}

async function main() {
  const { render, PAGES, sitemapXml } = await import(pathToFileURL(bundle).href);
  const shell = await readFile(join(dist, "index.html"), "utf-8");
  if (shell.includes("data-prerendered"))
    throw new Error("prerender: dist/index.html is already done");
  const origin = (process.env.CSO_PUBLIC_ORIGIN ?? "http://localhost:5173").replace(/\/+$/, "");

  await writeFile(join(dist, "_shell.html"), shell);
  for (const page of PAGES) {
    const rendered = render(page.path);
    const html = applyPage(shell, rendered, origin).replace(
      '<div id="root">',
      '<div id="root" data-prerendered="true">',
    );
    const target =
      page.path === "/"
        ? join(dist, "index.html")
        : page.path === "/404"
          ? join(dist, "404.html")
          : join(dist, page.path.slice(1), "index.html");
    await mkdir(dirname(target), { recursive: true });
    await writeFile(target, html);
    console.log(`prerendered ${page.path} -> ${target.slice(root.length + 1)}`);
  }
  await writeFile(join(dist, "sitemap.xml"), sitemapXml(origin));
  // robots.txt came from public/ with the origin filled in by the build; make sure of it.
  const robotsPath = join(dist, "robots.txt");
  const robots = await readFile(robotsPath, "utf-8");
  await writeFile(robotsPath, robots.replaceAll("__CSO_PUBLIC_ORIGIN__", origin));
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  await main();
}
