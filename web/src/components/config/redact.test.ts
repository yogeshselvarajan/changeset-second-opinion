import { describe, expect, it } from "vitest";

import { redactFlaggedWords, toYaml } from "./configYaml";

const WORDS = ["vandal", "vandalism", "spam", "illegal", "stop", "must"];

describe("redactFlaggedWords", () => {
  it("replaces a banned_words list with a count, wherever it is", () => {
    const config = {
      tone: { banned_words: WORDS, max_length: 400 },
      nested: [{ banned_words: ["x"] }],
    };
    const text = toYaml(redactFlaggedWords(config));
    expect(text).toContain('banned_words: "[6 entries hidden]"');
    expect(text).toContain('banned_words: "[1 entries hidden]"');
    expect(text).toContain("max_length: 400");
    for (const word of WORDS) expect(text).not.toContain(word);
  });

  it("leaves everything else alone and does not change its input", () => {
    const config = { a: [1, "two"], tone: { banned_words: WORDS } };
    const before = structuredClone(config);
    expect(redactFlaggedWords({ a: config.a })).toEqual({ a: [1, "two"] });
    redactFlaggedWords(config);
    expect(config).toEqual(before);
  });
});
