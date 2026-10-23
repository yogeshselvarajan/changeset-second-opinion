// Runs the shell blocks in the docs that are marked as tested, so a Quickstart that has rotted fails
// a nightly build instead of failing a new reader.
//
// A block is tested when its fence says `sh test`:
//
//   ```sh test
//   uv run cso db upgrade
//   ```
//
// Blocks run in order, from backend/, against a throwaway database in the system temp folder, with
// no network and no secrets. Only offline, quick commands belong in a tested block.
import { spawnSync } from "node:child_process";
import { mkdtempSync, readdirSync, readFileSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");
const backend = resolve(root, "..", "backend");
const docs = join(root, "src", "content", "docs");

function walk(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) out.push(...walk(path));
    else if (/\.mdx?$/.test(name)) out.push(path);
  }
  return out;
}

const blocks = [];
for (const file of walk(docs).sort()) {
  const lines = readFileSync(file, "utf8").split(/\r?\n/);
  let current = null;
  for (const line of lines) {
    const open = line.match(/^\s*```(\w+)\s+test\b/);
    if (!current && open) current = { file, body: [] };
    else if (current && /^\s*```\s*$/.test(line)) {
      blocks.push(current);
      current = null;
    } else if (current) current.body.push(line);
  }
}

if (!blocks.length) {
  console.log("run-tested-commands: no tested blocks found");
  process.exit(0);
}

const dir = mkdtempSync(join(tmpdir(), "cso-docs-"));
const env = {
  ...process.env,
  PYTHONUTF8: "1",
  CSO_MODE: "replay",
  CSO_DATABASE_URL: `sqlite+aiosqlite:///${join(dir, "docs.db").replace(/\\/g, "/")}`,
};

let failed = 0;
for (const block of blocks) {
  const script = block.body.join("\n");
  console.log(`\n# ${relative(root, block.file)}\n${script}`);
  const run = spawnSync("bash", ["-c", `set -e\n${script}`], {
    cwd: backend,
    env,
    stdio: "inherit",
  });
  if (run.status !== 0) {
    failed += 1;
    console.error(`FAILED (exit ${run.status}): ${relative(root, block.file)}`);
  }
}
console.log(`\nrun-tested-commands: ${blocks.length - failed} of ${blocks.length} blocks passed`);
process.exit(failed ? 1 : 0);
