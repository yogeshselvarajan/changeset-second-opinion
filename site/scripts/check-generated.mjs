// Runs the generator into the real folder, then fails when the committed reference pages differ
// from what the code produces. CI calls this; fix a failure with `npm run generate` and commit.
import { execFileSync, spawnSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const siteDir = resolve(here, "..");
const folder = "site/src/content/docs/reference";

execFileSync(process.execPath, [resolve(here, "generate.mjs")], { cwd: siteDir, stdio: "inherit" });

const repoRoot = execFileSync("git", ["rev-parse", "--show-toplevel"], {
  cwd: siteDir,
  encoding: "utf8",
}).trim();
const diff = spawnSync("git", ["diff", "--exit-code", "--", folder], {
  cwd: repoRoot,
  stdio: "inherit",
});
if (diff.status !== 0) {
  console.error(
    `check-generated: ${folder} is out of date. Run "npm run generate" in site/ and commit the result.`,
  );
  process.exit(1);
}
console.log("check-generated: the reference pages match the code");
