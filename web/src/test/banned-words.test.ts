import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

import en from "../messages/en.json";

// Rule 6 in CONTRIBUTING.md ("invariant 6" in the local-only agent files): the UI never uses these words.
const ALWAYS = /\b(vandal\w*|spam\w*|illegal\w*)\b/i;
const IN_STRINGS = /\b(stop|must)\b/i;
const SRC = join(__dirname, "..");
// Skipped at the top of src only in effect: `api` is the generated client (its OpenAPI text is not UI copy),
// `fonts` holds binaries and `test` holds fixtures that legitimately contain the words. Comments are
// ignored by the literal scan; test files are excluded because they assert on the banned words.
const SKIP_DIRS = new Set(["api", "fonts", "test"]);

function sourceFiles(dir: string): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) {
      if (!SKIP_DIRS.has(name)) out.push(...sourceFiles(full));
    } else if (/\.(ts|tsx|css|json)$/.test(name) && !/\.test\.tsx?$/.test(name)) {
      out.push(full);
    }
  }
  return out;
}

/** Drop comments so an apostrophe in one cannot pair with a quote in code (URLs inside strings survive). */
function withoutComments(text: string): string {
  return text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:"'`\\])\/\/[^\n]*/g, "$1");
}

/**
 * Every quoted string and every JSX text node in a source file. Single and double quoted strings end
 * at a newline or an unescaped quote; template literals may span lines. (The earlier class `[^\n]`
 * excluded a backslash and the letter "n", so any literal containing "n" was never scanned.)
 */
function stringLiterals(source: string): string[] {
  const text = withoutComments(source);
  const found: string[] = [];
  const quoted = /"((?:\\.|[^"\\\n])*)"|'((?:\\.|[^'\\\n])*)'|`((?:\\[\s\S]|[^`\\])*)`/g;
  for (const match of text.matchAll(quoted)) found.push(match[1] ?? match[2] ?? match[3] ?? "");
  // JSX text: between a `>` and the next `<` or `{`.
  for (const match of text.matchAll(/>([^<>{}]*[A-Za-z][^<>{}]*)(?=[<{])/g)) {
    const node = (match[1] ?? "").trim();
    if (node) found.push(node);
  }
  return found;
}

describe("banned words in user-facing text", () => {
  const files = sourceFiles(SRC);

  it("scans real files", () => {
    expect(files.length).toBeGreaterThan(10);
  });

  it("keeps the strongest words out of every source file", () => {
    const hits = files
      .filter((file) => ALWAYS.test(readFileSync(file, "utf8")))
      .map((file) => relative(SRC, file));
    expect(hits).toEqual([]);
  });

  it("really finds string literals (the scan is not blind to letters such as n)", () => {
    expect(stringLiterals(`const a = "You must not delete"; const b = 'stop now';`)).toEqual([
      "You must not delete",
      "stop now",
    ]);
    expect(stringLiterals("<p>You must wait</p>")).toContain("You must wait");
    expect(stringLiterals("// it's fine\nconst c = 'x';")).toEqual(["x"]);
  });

  it("keeps 'stop' and 'must' out of string literals", () => {
    const hits: string[] = [];
    for (const file of files.filter((f) => /\.tsx?$/.test(f))) {
      for (const literal of stringLiterals(readFileSync(file, "utf8"))) {
        if (IN_STRINGS.test(literal)) hits.push(`${relative(SRC, file)}: ${literal}`);
      }
    }
    expect(hits).toEqual([]);
  });

  it("keeps every banned word out of the message catalogue", () => {
    const hits = Object.entries(en).filter(
      ([, value]) => ALWAYS.test(value) || IN_STRINGS.test(value),
    );
    expect(hits).toEqual([]);
  });

  it("never renders a single vandalism percentage", () => {
    const all = files.map((file) => readFileSync(file, "utf8")).join("\n");
    expect(all).not.toMatch(/%\s*vandal|probability of vandal/i);
  });
});
