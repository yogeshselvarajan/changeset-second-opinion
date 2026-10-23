// The docs' prose rules, as a script that needs nothing installed. CI also runs Vale with the same
// three rules (site/.vale); this one runs anywhere, including the pre-publish check on your laptop.
//
//   1. no em dash and no en dash, anywhere
//   2. none of the words the product never uses: vandal, spam, illegal, stop, must
//   3. no exclamation marks in prose
//
// Code fences and inline code are skipped for rule 3 only (a shell command may hold `!`), never for
// 1 and 2. Exit 1 prints every hit as file:line.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");
const docs = join(root, "src", "content", "docs");

const DASH = /[–—]/;
const BANNED = /\b(vandal\w*|spam\w*|illegal\w*|stop(?:s|ped|ping)?|must)\b/i;

function walk(dir) {
  const files = [];
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) files.push(...walk(path));
    else if (/\.(md|mdx)$/.test(name)) files.push(path);
  }
  return files;
}

const problems = [];
for (const file of walk(docs)) {
  const lines = readFileSync(file, "utf8").split(/\r?\n/);
  let fenced = false;
  lines.forEach((line, index) => {
    if (/^\s*```/.test(line)) fenced = !fenced;
    const where = `${relative(root, file)}:${index + 1}`;
    if (DASH.test(line)) problems.push(`${where}: an em or en dash`);
    const banned = line.match(BANNED);
    if (banned) problems.push(`${where}: the word "${banned[0]}"`);
    const prose = fenced ? "" : line.replace(/`[^`]*`/g, "");
    if (/!(?!\[)(?!=)/.test(prose) && !/^\s*import\b|^\s*<|^\s*\{\/\*/.test(line)) {
      problems.push(`${where}: an exclamation mark`);
    }
  });
}

if (problems.length) {
  console.error(problems.join("\n"));
  console.error(`\n${problems.length} prose problem(s).`);
  process.exit(1);
}
console.log("prose-lint: ok");
