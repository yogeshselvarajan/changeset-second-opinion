import { existsSync, readFileSync, statSync } from "node:fs";
import type { IncomingMessage, ServerResponse } from "node:http";
import { extname, join, normalize, resolve, sep } from "node:path";
import type { Connect, Plugin } from "vite";

const TYPES: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".xml": "application/xml; charset=utf-8",
  ".txt": "text/plain; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".webp": "image/webp",
  ".ico": "image/x-icon",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".wasm": "application/wasm",
};

function isFile(path: string): boolean {
  return existsSync(path) && statSync(path).isFile();
}

/** Answers everything under /docs from `root`, with a 404 (never the app shell) for a miss. */
function docsMiddleware(root: string): Connect.NextHandleFunction {
  return (req: IncomingMessage, res: ServerResponse, next: Connect.NextFunction) => {
    const [rawPath = "", query] = (req.url ?? "").split("?");
    if (rawPath !== "/docs" && !rawPath.startsWith("/docs/")) return next();
    if (rawPath === "/docs") {
      res.statusCode = 301;
      res.setHeader("Location", `/docs/${query ? `?${query}` : ""}`);
      res.end();
      return;
    }
    let rel: string;
    try {
      rel = decodeURIComponent(rawPath.slice("/docs/".length));
    } catch {
      rel = "\0";
    }
    const base = resolve(root);
    let file = resolve(join(base, normalize(rel)));
    const inside = !rel.includes("\0") && (file === base || file.startsWith(base + sep));
    if (inside && !isFile(file)) file = join(file, "index.html");
    if (inside && isFile(file)) {
      res.setHeader("Content-Type", TYPES[extname(file)] ?? "application/octet-stream");
      res.end(readFileSync(file));
      return;
    }
    const notFound = join(base, "404.html");
    res.statusCode = 404;
    res.setHeader("Content-Type", "text/html; charset=utf-8");
    res.end(isFile(notFound) ? readFileSync(notFound) : "Not found");
  };
}

/**
 * Serves the docs site at /docs: from `dist/docs` in `vite preview`, and in dev from `../site/dist`
 * unless a built `dist/docs` exists. Production serves the same files from Caddy.
 */
export function docsPlugin(): Plugin {
  return {
    name: "cso-docs",
    configureServer(server) {
      const built = join(server.config.root, server.config.build.outDir, "docs");
      const root = existsSync(built) ? built : join(server.config.root, "..", "site", "dist");
      if (existsSync(root)) server.middlewares.use(docsMiddleware(root));
    },
    configurePreviewServer(server) {
      server.middlewares.use(
        docsMiddleware(join(server.config.root, server.config.build.outDir, "docs")),
      );
    },
  };
}
