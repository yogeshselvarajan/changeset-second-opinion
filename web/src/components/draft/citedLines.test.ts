import { describe, expect, it } from "vitest";

import { citedEvidenceLines } from "./citedLines";

const TEXT = [
  "E1 way/10 modify highway=residential name: Rd -> Road",
  "E2 node/11 delete amenity=cafe",
  "D1 discussion by Ann: Reverted",
].join("\n");

describe("citedEvidenceLines", () => {
  it("finds each cited line by its id", () => {
    expect(citedEvidenceLines(TEXT, ["E2", "D1"])).toEqual([
      { id: "E2", line: "E2 node/11 delete amenity=cafe" },
      { id: "D1", line: "D1 discussion by Ann: Reverted" },
    ]);
  });

  it("does not match a longer id that starts the same way", () => {
    expect(citedEvidenceLines("E12 node/1 x", ["E1"])).toEqual([]);
  });

  it("leaves out unknown ids, malformed ids and repeats", () => {
    expect(citedEvidenceLines(TEXT, ["E9", "../etc", "E1", "E1"])).toEqual([
      { id: "E1", line: "E1 way/10 modify highway=residential name: Rd -> Road" },
    ]);
  });

  it("cuts a very long line", () => {
    const [only] = citedEvidenceLines(`E1 ${"x".repeat(500)}`, ["E1"]);
    expect(only?.line.length).toBeLessThan(250);
    expect(only?.line.endsWith("...")).toBe(true);
  });

  it("returns nothing without text or ids", () => {
    expect(citedEvidenceLines(undefined, ["E1"])).toEqual([]);
    expect(citedEvidenceLines(TEXT, [])).toEqual([]);
    expect(citedEvidenceLines(TEXT, undefined)).toEqual([]);
  });
});
