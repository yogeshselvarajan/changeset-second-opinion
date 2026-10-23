import { describe, expect, it } from "vitest";

import { hasChanges, wordDiff, type DiffRun } from "./wordDiff";

const rebuild = (runs: DiffRun[], keep: DiffRun["kind"][]) =>
  runs
    .filter((run) => keep.includes(run.kind))
    .map((run) => run.text)
    .join("");

describe("wordDiff", () => {
  it("returns one unchanged run for equal text, and nothing for two empty texts", () => {
    expect(wordDiff("a b", "a b")).toEqual([{ kind: "same", text: "a b" }]);
    expect(wordDiff("", "")).toEqual([]);
  });

  it("marks added and removed words", () => {
    const runs = wordDiff("Hello and welcome", "Hello there and welcome");
    expect(runs.some((run) => run.kind === "ins" && run.text.includes("there"))).toBe(true);
    expect(runs.some((run) => run.kind === "del")).toBe(false);
    expect(hasChanges(runs)).toBe(true);
    const swapped = wordDiff("one two three", "one 2 three");
    expect(swapped.find((run) => run.kind === "del")?.text).toBe("two");
    expect(swapped.find((run) => run.kind === "ins")?.text).toBe("2");
  });

  it("reads back as the two originals", () => {
    const before = "Thanks for mapping around Ikeja.\n\nCould you share a source?";
    const after = "Thanks for mapping around Lagos.\n\nCould you share the source, please?";
    const runs = wordDiff(before, after);
    expect(rebuild(runs, ["same", "del"])).toBe(before);
    expect(rebuild(runs, ["same", "ins"])).toBe(after);
  });

  it("handles a whole replacement and one-sided texts", () => {
    expect(wordDiff("", "new")).toEqual([{ kind: "ins", text: "new" }]);
    expect(wordDiff("old", "")).toEqual([{ kind: "del", text: "old" }]);
    expect(hasChanges(wordDiff("x", "x"))).toBe(false);
  });

  it("falls back to a plain replace for very long texts instead of hanging", () => {
    const long = Array.from({ length: 700 }, (_, i) => `w${i}`).join(" ");
    const runs = wordDiff(long, `${long} extra`);
    expect(runs).toEqual([
      { kind: "del", text: long },
      { kind: "ins", text: `${long} extra` },
    ]);
  });
});
