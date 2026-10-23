import { existsSync } from "node:fs";
import { readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import type { Plugin } from "vite";

import { sitemapXml } from "./src/landing/site.ts";

export const PLACEHOLDER = "__CSO_PUBLIC_ORIGIN__";
const DEFAULT_ORIGIN = "http://localhost:5173";

/** `CSO_PUBLIC_ORIGIN` without a trailing slash, or the dev server's address. */
export function publicOrigin(raw: string | undefined = process.env.CSO_PUBLIC_ORIGIN): string {
  const value = (raw ?? "").trim().replace(/\/+$/, "");
  return value || DEFAULT_ORIGIN;
}

/**
 * Fills the site origin into index.html and robots.txt. The dev server also serves a sitemap
 * from memory; the production sitemap is written by `scripts/prerender.mjs` from the same list.
 */
export function publicOriginPlugin(origin: string): Plugin {
  const fill = (text: string) => text.replaceAll(PLACEHOLDER, origin);
  let ssr = false;
  return {
    name: "cso-public-origin",
    configResolved(config) {
      ssr = Boolean(config.build.ssr);
    },
    transformIndexHtml: (html) => fill(html),
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        const path = (req.url ?? "").split("?")[0];
        if (path === "/robots.txt") {
          const text = await readFile(join(server.config.publicDir, "robots.txt"), "utf-8");
          res.setHeader("Content-Type", "text/plain; charset=utf-8");
          res.end(fill(text));
        } else if (path === "/sitemap.xml") {
          res.setHeader("Content-Type", "application/xml; charset=utf-8");
          res.end(sitemapXml(origin));
        } else {
          next();
        }
      });
    },
    // `vite preview` should answer like the Caddy edge: a written page where there is one, and the
    // empty app shell (`_shell.html`) for every other address, never the home page's markup.
    configurePreviewServer(server) {
      const dist = join(server.config.root, server.config.build.outDir);
      server.middlewares.use((req, _res, next) => {
        const [path = "", query] = (req.url ?? "").split("?");
        const skip = path.startsWith("/api") || path.includes(".") || path === "/";
        if (!skip && !existsSync(join(dist, path, "index.html"))) {
          req.url = `/_shell.html${query ? `?${query}` : ""}`;
        }
        next();
      });
    },
    async writeBundle(options) {
      if (ssr || !options.dir) return;
      const robots = join(options.dir, "robots.txt");
      await writeFile(robots, fill(await readFile(robots, "utf-8")));
    },
  };
}
