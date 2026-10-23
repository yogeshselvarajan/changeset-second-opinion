import type { Response } from "../../api/types.gen";

/*
 * A client-side mirror of the server's draft rules that need no evidence text, so the checklist can
 * update while the reviewer types. The server's validation of the generated draft stays the
 * authority and is shown next to this list. Two things come from the config response and are never
 * written into this file: the words the community avoids (`tone.banned_words`) and the links it
 * allows (`tone.allowed_links`). Keep the limits and term lists below in step with
 * backend/src/cso/domain/draft_validation.py.
 */

export const LIMITS = {
  greetingChars: 80,
  closingChars: 80,
  bodyChars: 700,
  bodyWords: 120,
} as const;

/** The tone settings the checker needs, as the config endpoint returns them. */
export interface ToneRules {
  bannedWords: readonly string[];
  allowedLinks: readonly string[];
  languagePolicy?: string;
}

export type CheckId =
  "present" | "length" | "avoidList" | "tone" | "markup" | "links" | "language" | "question";

export interface CheckResult {
  id: CheckId;
  /** False when the rule does not apply to this kind of comment (it is then not shown as a failure). */
  applies: boolean;
  ok: boolean;
  /** 1-based lines that contain the problem, for rules that can point at text. */
  lines: number[];
}

/** Words that assign intent or blame; a draft describes what is visible and asks questions. */
const ACCUSATORY_TERMS: readonly string[] = [
  "deliberate",
  "deliberately",
  "intentional",
  "intentionally",
  "purposely",
  "malicious",
  "maliciously",
  "sabotage",
  "sabotaged",
  "troll",
  "trolling",
  "liar",
  "lying",
  "lied",
  "fraud",
  "fraudulent",
  "cheat",
  "cheating",
  "abuse",
  "abusive",
  "offender",
  "guilty",
  "blame",
  "culprit",
  "bad faith",
  "bad-faith",
  "destroyed",
  "wrecked",
  "ruined",
];

/** Text that tries to steer a drafting model; it must not reappear in a draft. */
const INSTRUCTION_PHRASES: readonly string[] = [
  "ignore previous",
  "ignore all previous",
  "ignore the above",
  "ignore your instructions",
  "disregard",
  "system prompt",
  "as an ai",
  "you are now",
  "mark as fine",
  "mark this as",
  "new instructions",
  "jailbreak",
];

const INFLECTIONS = "(?:s|es|ed|d|ing|ism|ist|ists|ize|ized|izing|ped|ping)?";
const URL_RE = /\b(?:https?:\/\/|hxxps?:\/\/|www\.)[^\s<>"')\]]+/gi;
const BARE_DOMAIN_RE =
  /\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|org|net|io|ly|me|co|info|xyz|ru|cn|de|fr)\b/gi;
const HTML_RE = /<[A-Za-z/!][^>]*>|&(?:[A-Za-z]+|#\d+);/;
const MARKDOWN_RES: readonly RegExp[] = [
  /\*\*|__|`/,
  /^\s{0,3}#{1,6}\s/m,
  /^\s*[-*+•]\s+\S/m,
  /\[[^\]]+\]\([^)]+\)/,
  /^\s*>\s/m,
];

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function wordCount(text: string): number {
  return (text.match(/\S+/g) ?? []).length;
}

/** The greeting, body and closing of a draft text: paragraphs split by a blank line. */
export interface Parts {
  greeting: string;
  body: string;
  closing: string;
}

export function splitParts(text: string): Parts {
  const paragraphs = text
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .filter((p) => p !== "");
  if (paragraphs.length >= 3) {
    return {
      greeting: paragraphs[0] as string,
      body: paragraphs.slice(1, -1).join("\n\n"),
      closing: paragraphs[paragraphs.length - 1] as string,
    };
  }
  if (paragraphs.length === 2) {
    return { greeting: paragraphs[0] as string, body: paragraphs[1] as string, closing: "" };
  }
  return { greeting: "", body: paragraphs[0] ?? "", closing: "" };
}

/** Put a generated draft's three fields into the one text the reviewer edits. */
export function joinParts(parts: Pick<Parts, "greeting" | "body" | "closing">): string {
  return [parts.greeting, parts.body, parts.closing]
    .map((p) => p.trim())
    .filter((p) => p !== "")
    .join("\n\n");
}

function linesMatching(text: string, test: (line: string) => boolean): number[] {
  const out: number[] = [];
  text.split("\n").forEach((line, index) => {
    if (test(line)) out.push(index + 1);
  });
  return out;
}

function urlAllowed(url: string, allowed: readonly string[]): boolean {
  const lowered = url.replace(/[.,;:!?]+$/, "").toLowerCase();
  return allowed.some((link) => {
    const prefix = link.toLowerCase();
    return lowered.startsWith(prefix) || `${lowered}/` === prefix;
  });
}

function hostOf(link: string): string {
  try {
    return new URL(link).hostname.toLowerCase();
  } catch {
    return "";
  }
}

/** Does this text contain a link the community has not allowed? */
function hasDisallowedLink(text: string, allowedLinks: readonly string[]): boolean {
  const allowed = allowedLinks.filter((link) => link.trim() !== "");
  const allowedHosts = new Set(allowed.map(hostOf));
  const spans: [number, number][] = [];
  for (const match of text.matchAll(URL_RE)) {
    spans.push([match.index, match.index + match[0].length]);
    if (!urlAllowed(match[0], allowed)) return true;
  }
  for (const match of text.matchAll(BARE_DOMAIN_RE)) {
    const inside = spans.some(([start, end]) => start <= match.index && match.index < end);
    if (!inside && !allowedHosts.has(match[0].toLowerCase())) return true;
  }
  return false;
}

function nonLatinShare(text: string): number {
  const letters = [...text].filter((c) => /\p{L}/u.test(c));
  if (letters.length === 0) return 0;
  const other = letters.filter((c) => !/\p{Script=Latin}/u.test(c)).length;
  return other / letters.length;
}

function bannedPattern(word: string): RegExp {
  return new RegExp(`\\b${escapeRegExp(word.trim())}${INFLECTIONS}\\b`, "i");
}

/** Comment kinds that are phrased as a question to the mapper. */
const QUESTION_TYPES: ReadonlySet<Response> = new Set<Response>([
  "ask_source_question",
  "request_local_check",
]);

/** Run every client-side rule over the text. The order is the order the checklist shows. */
export function runChecks(
  text: string,
  tone: ToneRules,
  responseType: Response | null,
): CheckResult[] {
  const parts = splitParts(text);
  const lowered = text.toLowerCase();
  const results: CheckResult[] = [];

  results.push({
    id: "present",
    applies: true,
    ok: parts.body.trim() !== "" && text.trim() !== "",
    lines: [],
  });

  const lengthOk =
    parts.greeting.length <= LIMITS.greetingChars &&
    parts.closing.length <= LIMITS.closingChars &&
    parts.body.length <= LIMITS.bodyChars &&
    wordCount(parts.body) <= LIMITS.bodyWords;
  results.push({ id: "length", applies: true, ok: lengthOk, lines: [] });

  const patterns = tone.bannedWords.filter((w) => w.trim() !== "").map(bannedPattern);
  const avoidLines = linesMatching(text, (line) => patterns.some((rx) => rx.test(line)));
  results.push({ id: "avoidList", applies: true, ok: avoidLines.length === 0, lines: avoidLines });

  const tonePhraseHit = ACCUSATORY_TERMS.some((term) =>
    new RegExp(`\\b${escapeRegExp(term)}\\b`).test(lowered),
  );
  const instructionHit = INSTRUCTION_PHRASES.some((phrase) => lowered.includes(phrase));
  results.push({ id: "tone", applies: true, ok: !tonePhraseHit && !instructionHit, lines: [] });

  const markupHit = HTML_RE.test(text) || MARKDOWN_RES.some((rx) => rx.test(text));
  results.push({ id: "markup", applies: true, ok: !markupHit, lines: [] });

  results.push({
    id: "links",
    applies: true,
    ok: !hasDisallowedLink(text, tone.allowedLinks),
    lines: [],
  });

  const english = (tone.languagePolicy ?? "en").toLowerCase().startsWith("en");
  results.push({
    id: "language",
    applies: english,
    ok: !english || nonLatinShare(text) <= 0.2,
    lines: [],
  });

  const asksQuestion = QUESTION_TYPES.has(responseType as Response);
  results.push({
    id: "question",
    applies: asksQuestion,
    ok: !asksQuestion || text.includes("?"),
    lines: [],
  });

  return results;
}

/** True when every rule that applies holds. */
export function allOk(results: readonly CheckResult[]): boolean {
  return results.every((result) => !result.applies || result.ok);
}

export function countWords(text: string): number {
  return wordCount(text);
}
