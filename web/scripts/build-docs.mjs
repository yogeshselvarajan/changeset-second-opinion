// Builds the docs site (site/) with base /docs and copies it to dist/docs, so the app and the docs
// are served from one origin. Fails loudly when the site build fails. Set CSO_SKIP_DOCS=1 to skip
// it for a fast local build.
import { spawnSync } from "node:child_process";
import { cpSync, existsSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const site = join(root, "..", "site");
const target = join(root, "dist", "docs");

function run(args) {
  const npm = process.platform === "win32" ? "npm.cmd" : "npm";
  const result = spawnSync(npm, args, {
    cwd: root,
    stdio: "inherit",
    shell: process.platform === "win32",
    env: { ...process.env, DOCS_BASE: "/docs" },
  });
  if (result.status !== 0) {
    throw new Error(
      `build-docs: "npm ${args.join(" ")}" failed (${result.status ?? result.error})`,
    );
  }
}

if (process.env.CSO_SKIP_DOCS === "1") {
  console.log("build-docs: skipped (CSO_SKIP_DOCS=1)");
} else {
  if (!existsSync(join(site, "package.json"))) throw new Error("build-docs: ../site was not found");
  if (!existsSync(join(site, "node_modules"))) run(["--prefix", "../site", "ci"]);
  run(["--prefix", "../site", "run", "build"]);
  const built = join(site, "dist");
  if (!existsSync(join(built, "index.html")))
    throw new Error("build-docs: site/dist has no index.html");
  rmSync(target, { recursive: true, force: true });
  cpSync(built, target, { recursive: true });
  console.log("build-docs: copied site/dist to dist/docs");
}
