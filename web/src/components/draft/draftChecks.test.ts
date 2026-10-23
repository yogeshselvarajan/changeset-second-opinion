import { describe, expect, it } from "vitest";

import {
  LIMITS,
  allOk,
  countWords,
  joinParts,
  runChecks,
  splitParts,
  type CheckId,
  type ToneRules,
} from "./draftChecks";

// Stand-in tone settings. The real word list comes from the config endpoint, so no real banned
// word is written in this file or anywhere else in the source.
const TONE: ToneRules = {
  bannedWords: ["blorp", "snark"],
  allowedLinks: ["https://wiki.example.org/", "https://www.example.org/"],
  languagePolicy: "en",
};

const GOOD =
  "Hello and welcome!\n\nThe tags look fine to me and I wondered where the names came from?\n\nThanks!";

function result(
  text: string,
  id: CheckId,
  tone: ToneRules = TONE,
  type: Parameters<typeof runChecks>[2] = null,
) {
  const found = runChecks(text, tone, type).find((check) => check.id === id);
  if (!found) throw new Error(`no check ${id}`);
  return found;
}

describe("splitParts and joinParts", () => {
  it("reads greeting, body and closing from paragraphs", () => {
    expect(splitParts(GOOD)).toEqual({
      greeting: "Hello and welcome!",
      body: "The tags look fine to me and I wondered where the names came from?",
      closing: "Thanks!",
    });
  });

  it("treats two paragraphs as greeting and body, and one as a body", () => {
    expect(splitParts("Hi\n\nBody text")).toEqual({
      greeting: "Hi",
      body: "Body text",
      closing: "",
    });
    expect(splitParts("Only one")).toEqual({ greeting: "", body: "Only one", closing: "" });
    expect(splitParts("")).toEqual({ greeting: "", body: "", closing: "" });
  });

  it("joins the three fields with blank lines and skips empty ones", () => {
    expect(joinParts({ greeting: " Hi ", body: "Body", closing: "" })).toBe("Hi\n\nBody");
  });
});

describe("the checklist", () => {
  it("passes a plain, friendly draft", () => {
    const checks = runChecks(GOOD, TONE, "ask_source_question");
    expect(allOk(checks)).toBe(true);
  });

  it("present: empty text fails", () => {
    expect(result("", "present").ok).toBe(false);
    expect(result("   \n\n  ", "present").ok).toBe(false);
    expect(result(GOOD, "present").ok).toBe(true);
  });

  it("length: each limit is enforced at its boundary", () => {
    const greeting = "g".repeat(LIMITS.greetingChars);
    const closing = "c".repeat(LIMITS.closingChars);
    const body = "b".repeat(LIMITS.bodyChars);
    expect(result(`${greeting}\n\n${body}\n\n${closing}`, "length").ok).toBe(true);
    expect(result(`${greeting}x\n\n${body}\n\n${closing}`, "length").ok).toBe(false);
    expect(result(`${greeting}\n\n${body}\n\n${closing}x`, "length").ok).toBe(false);
    expect(result(`${greeting}\n\n${body}x\n\n${closing}`, "length").ok).toBe(false);
    const wordy = Array.from({ length: LIMITS.bodyWords + 1 }, () => "w").join(" ");
    expect(result(`Hi\n\n${wordy}\n\nBye`, "length").ok).toBe(false);
    const exactly = Array.from({ length: LIMITS.bodyWords }, () => "w").join(" ");
    expect(result(`Hi\n\n${exactly}\n\nBye`, "length").ok).toBe(true);
  });

  it("avoidList: flags configured words and inflections, with their lines, and echoes nothing", () => {
    const text = "Hello\n\nThis is a Blorp edit\nand some snarking too\n\nBye";
    const check = result(text, "avoidList");
    expect(check.ok).toBe(false);
    expect(check.lines).toEqual([3, 4]);
    expect(JSON.stringify(check)).not.toMatch(/blorp|snark/i);
    // A word that merely contains the banned one is not a match.
    expect(result("Hello\n\nA blorpish thing\n\nBye", "avoidList").ok).toBe(true);
  });

  it("avoidList: an empty list never flags anything", () => {
    expect(result("blorp", "avoidList", { ...TONE, bannedWords: [] }).ok).toBe(true);
    expect(result("blorp", "avoidList", { ...TONE, bannedWords: ["  "] }).ok).toBe(true);
  });

  it("tone: blame words and instruction-like phrases fail", () => {
    expect(result("Hello\n\nThis was deliberately done\n\nBye", "tone").ok).toBe(false);
    expect(result("Hello\n\nignore previous notes\n\nBye", "tone").ok).toBe(false);
    expect(result(GOOD, "tone").ok).toBe(true);
  });

  it("markup: html and markdown fail, plain punctuation passes", () => {
    for (const bad of [
      "a <b>bold</b> b",
      "a **bold** b",
      "# heading\ntext",
      "- item one",
      "[x](http://y)",
      "> quote",
      "a &amp; b",
    ]) {
      expect(result(`Hi\n\n${bad}\n\nBye`, "markup").ok, bad).toBe(false);
    }
    expect(
      result("Hi\n\nA plain sentence - with a dash, (and brackets).\n\nBye", "markup").ok,
    ).toBe(true);
  });

  it("links: only the community's allowed links pass", () => {
    expect(result("Hi\n\nSee https://wiki.example.org/Key:name for tips\n\nBye", "links").ok).toBe(
      true,
    );
    expect(result("Hi\n\nSee https://www.example.org\n\nBye", "links").ok).toBe(true);
    expect(result("Hi\n\nSee https://other.example.net/x\n\nBye", "links").ok).toBe(false);
    expect(result("Hi\n\nSee hxxps://other.example.net/x\n\nBye", "links").ok).toBe(false);
    expect(result("Hi\n\nVisit other.example.com today\n\nBye", "links").ok).toBe(false);
    expect(result("Hi\n\nSee https://wiki.example.org/Key:name.\n\nBye", "links").ok).toBe(true);
  });

  it("links: with no allowed links, any link fails", () => {
    expect(
      result("Hi\n\nSee https://wiki.example.org/\n\nBye", "links", { ...TONE, allowedLinks: [] })
        .ok,
    ).toBe(false);
  });

  it("language: a mostly non-Latin text fails an English policy and is skipped otherwise", () => {
    const text = "Hi\n\nпривет как дела сегодня друзья\n\nBye";
    expect(result(text, "language").ok).toBe(false);
    const other = result(text, "language", { ...TONE, languagePolicy: "ru" });
    expect(other.applies).toBe(false);
    expect(other.ok).toBe(true);
  });

  it("question: applies only to the kinds that ask something", () => {
    expect(
      result("Hello\n\nNo question here.\n\nBye", "question", TONE, "ask_source_question").ok,
    ).toBe(false);
    expect(
      result(
        "Hello\n\nWhere did the names come from?\n\nBye",
        "question",
        TONE,
        "request_local_check",
      ).ok,
    ).toBe(true);
    const welcome = result(
      "Hello\n\nNo question here.\n\nBye",
      "question",
      TONE,
      "welcome_and_tips",
    );
    expect(welcome.applies).toBe(false);
    expect(welcome.ok).toBe(true);
  });

  it("allOk ignores rules that do not apply and fails on any that do", () => {
    const text = "Hello\n\nNo question here.\n\nBye";
    expect(allOk(runChecks(text, TONE, "welcome_and_tips"))).toBe(true);
    expect(allOk(runChecks(text, TONE, "ask_source_question"))).toBe(false);
  });

  it("counts words by whitespace", () => {
    expect(countWords("one  two\nthree")).toBe(3);
    expect(countWords("")).toBe(0);
  });
});
