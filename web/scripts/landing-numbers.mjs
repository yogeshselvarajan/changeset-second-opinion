// Computes the figures on the landing page from the committed evaluation files, so no number is
// ever typed by hand. `npm run numbers` writes src/landing/numbers.json; the build runs it first
// and fails if a source file is missing. The same arithmetic lives in
// backend/src/cso/evaluation (spike report); a test checks the two agree.
import { existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
export const REPO = join(here, "..", "..");
export const SPIKE = "evaluation/results/spike-2026-10-17.json";
export const GOLD = "evaluation/labels/dev.adjudicated.jsonl";
export const LABELLER_ROWS = "evaluation/labels/dev.jsonl";
export const OUTPUT = join(here, "..", "src", "landing", "numbers.json");
const Z = 1.959963984540054;
const AI_NAMES = new Set(["claude"]);

/** Wilson 95 percent interval for k of n, as in cso.evaluation.stats. */
export function wilson(k, n) {
  if (n === 0) return { k, n, lower: 0, upper: 1 };
  const p = k / n;
  const denom = 1 + (Z * Z) / n;
  const centre = (p + (Z * Z) / (2 * n)) / denom;
  const half = (Z * Math.sqrt((p * (1 - p)) / n + (Z * Z) / (4 * n * n))) / denom;
  return { k, n, lower: Math.max(0, centre - half), upper: Math.min(1, centre + half) };
}

function readJson(path) {
  const full = join(REPO, path);
  if (!existsSync(full)) throw new Error(`landing numbers: ${path} is missing`);
  return JSON.parse(readFileSync(full, "utf-8"));
}

function readJsonl(path) {
  const full = join(REPO, path);
  if (!existsSync(full)) throw new Error(`landing numbers: ${path} is missing`);
  return readFileSync(full, "utf-8")
    .split("\n")
    .filter((line) => line.trim())
    .map((line) => JSON.parse(line));
}

/** Who produced the labels, in words a visitor can read; AI only unless a person took part. */
export function disclosure(items, labellers, adjudicators) {
  const people = [...new Set([...labellers, ...adjudicators])]
    .filter((name) => name && !AI_NAMES.has(String(name).toLowerCase()))
    .sort();
  if (people.length === 0) {
    return {
      ai_only: true,
      people,
      text:
        `Measured on ${items} real edits. The answer key for every one was written by an AI, in two ` +
        "passes, and settled by the same AI. No person wrote or checked it, so these figures " +
        "are indicative and not human validated.",
    };
  }
  return {
    ai_only: false,
    people,
    text:
      `Measured on ${items} real edits. The answer key was written by an AI together ` +
      `with ${people.join(", ")}.`,
  };
}

export const DEMO_CASES = "backend/fixtures/demo/cases";

/** What the recorded demo set shows: real runs of the Decider on 15 real changesets. */
export function demoStats() {
  const root = join(REPO, DEMO_CASES);
  if (!existsSync(root)) throw new Error(`landing numbers: ${DEMO_CASES} is missing`);
  const timings = [];
  const lanes = {};
  let readings = 0;
  let unknown = 0;
  let cases = 0;
  let bboxCountries = 0;
  for (const name of readdirSync(root).sort()) {
    const expectedPath = join(root, name, "expected.json");
    if (!existsSync(expectedPath)) continue;
    const expected = JSON.parse(readFileSync(expectedPath, "utf-8"));
    const receipt = expected.receipt;
    if (!receipt?.panel) continue;
    cases += 1;
    timings.push(receipt.timing_ms.decide_server);
    lanes[receipt.lane] = (lanes[receipt.lane] ?? 0) + 1;
    for (const reading of Object.values(receipt.panel.readings)) {
      readings += 1;
      if (reading.state === "unknown") unknown += 1;
    }
    if (expected.place_label) bboxCountries += 1;
  }
  timings.sort((a, b) => a - b);
  const mid = timings.length >> 1;
  const median = timings.length % 2 ? timings[mid] : (timings[mid - 1] + timings[mid]) / 2;
  return {
    source: DEMO_CASES,
    cases,
    questions_per_case: readings / Math.max(cases, 1),
    readings,
    unknown_readings: unknown,
    median_model_ms: median,
    slowest_model_ms: timings.at(-1) ?? 0,
    lanes,
    placed: bboxCountries,
  };
}

export function computeNumbers() {
  const spike = readJson(SPIKE);
  const gold = new Map(readJsonl(GOLD).map((row) => [row.changeset_id, row]));
  const labellers = readJsonl(LABELLER_ROWS).map((row) => row.labeller);
  const adjudicators = [...gold.values()].map((row) => row.adjudicator);

  let decidedK = 0;
  let decidedN = 0;
  let unknownK = 0;
  let readingsN = 0;
  const gold_counts = new Map(); // probe -> { yes, no }
  let natureComposedK = 0;
  let natureRulesK = 0;
  let natureN = 0;
  for (const item of spike.items) {
    const label = gold.get(item.changeset_id);
    if (!label || item.error || !item.states) continue;
    for (const [probe, answer] of Object.entries(label.probes ?? {})) {
      if (answer !== "yes" && answer !== "no") continue;
      const state = item.states[probe];
      if (state === undefined) continue;
      readingsN += 1;
      const tally = gold_counts.get(probe) ?? { yes: 0, no: 0 };
      tally[answer] += 1;
      gold_counts.set(probe, tally);
      if (state === "unknown") {
        unknownK += 1;
        continue;
      }
      decidedN += 1;
      if (state === answer) decidedK += 1;
    }
    if (label.nature !== "ambiguous") {
      natureN += 1;
      if (item.composed_nature === label.nature) natureComposedK += 1;
      if (item.rules_nature === label.nature) natureRulesK += 1;
    }
  }
  // What answering each probe's commonest gold answer, with no model at all, would score.
  let majorityK = 0;
  let majorityN = 0;
  for (const { yes, no } of gold_counts.values()) {
    majorityK += Math.max(yes, no);
    majorityN += yes + no;
  }
  return {
    source: SPIKE,
    date: spike.date,
    model: spike.model,
    items: spike.items.length,
    labels: disclosure(gold.size, labellers, adjudicators),
    pooled_decided: wilson(decidedK, decidedN),
    unknown_rate: wilson(unknownK, readingsN),
    majority_baseline: wilson(majorityK, majorityN),
    nature_composed: wilson(natureComposedK, natureN),
    nature_rules: wilson(natureRulesK, natureN),
    demo: demoStats(),
  };
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const numbers = computeNumbers();
  writeFileSync(OUTPUT, JSON.stringify(numbers, null, 2) + "\n");
  console.log(
    `wrote ${OUTPUT} (pooled ${numbers.pooled_decided.k}/${numbers.pooled_decided.n}, ` +
      `nature ${numbers.nature_composed.k}/${numbers.nature_composed.n})`,
  );
}
