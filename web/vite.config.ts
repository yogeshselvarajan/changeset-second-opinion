/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import type { IncomingMessage } from "node:http";

import { defineConfig } from "vite";

import { docsPlugin } from "./vite.docs.ts";
import { publicOrigin, publicOriginPlugin } from "./vite.public-origin.ts";

interface ProxyRequest {
  setHeader(name: string, value: string): void;
}

// The API refuses requests whose Origin differs from the Host it sees, so the proxy must forward
// the browser's Host header instead of rewriting it to the backend address.
const backend = {
  target: "http://127.0.0.1:8000",
  changeOrigin: false,
  configure: (proxy: {
    on(event: "proxyReq", handler: (proxyReq: ProxyRequest, req: IncomingMessage) => void): void;
  }) => {
    proxy.on("proxyReq", (proxyReq, req) => {
      if (req.headers.host) proxyReq.setHeader("host", req.headers.host);
    });
  },
};
const apiProxy = { "/api": backend, "/healthz": backend, "/readyz": backend };

const origin = publicOrigin();
const repoUrl = (
  process.env.CSO_REPO_URL ?? "https://github.com/yogeshselvarajan/changeset-second-opinion"
).replace(/\/+$/, "");

export default defineConfig(({ isSsrBuild }) => ({
  plugins: [react(), tailwindcss(), docsPlugin(), publicOriginPlugin(origin)],
  define: {
    __CSO_PUBLIC_ORIGIN__: JSON.stringify(origin),
    __CSO_REPO_URL__: JSON.stringify(repoUrl),
  },
  // The prerender bundle needs no copy of the public files; they are already in dist/.
  build: { copyPublicDir: !isSsrBuild },
  // maplibre-gl starts its own worker file; the dev pre-bundle does not copy it (the map then says
  // "could not be loaded"), so serve the package as it ships. The production build is unaffected.
  optimizeDeps: { exclude: ["maplibre-gl"] },
  server: { port: 5173, proxy: apiProxy },
  preview: { proxy: apiProxy },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
  },
}));
