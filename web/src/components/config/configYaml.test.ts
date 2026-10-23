import { describe, expect, it } from "vitest";

import { toYaml } from "./configYaml";

describe("toYaml", () => {
  it("writes nested objects with two-space indentation and keeps key order", () => {
    expect(toYaml({ version: "sha256:abc", bands: { confident_min: 0.8, unsure_min: 0.5 } })).toBe(
      'version: "sha256:abc"\nbands:\n  confident_min: 0.8\n  unsure_min: 0.5\n',
    );
  });

  it("writes lists of scalars and lists of objects", () => {
    expect(
      toYaml({
        links: ["https://a.example/", "b"],
        rules: [{ code: "R1", label: "Mature deletion" }],
      }),
    ).toBe(
      'links:\n  - "https://a.example/"\n  - b\nrules:\n  - code: R1\n    label: "Mature deletion"\n',
    );
  });

  it("writes empty containers inline and null as null", () => {
    expect(toYaml({ none: [], also: {}, nothing: null })).toBe(
      "none: []\nalso: {}\nnothing: null\n",
    );
  });

  it("quotes strings that could be misread as something else", () => {
    const text = toYaml({
      a: "yes",
      b: "123",
      c: "has: colon",
      d: "",
      e: "line\nbreak",
      f: true,
      g: 0.35,
    });
    expect(text).toContain('a: "yes"');
    expect(text).toContain('b: "123"');
    expect(text).toContain('c: "has: colon"');
    expect(text).toContain('d: ""');
    expect(text).toContain('e: "line\\nbreak"');
    expect(text).toContain("f: true");
    expect(text).toContain("g: 0.35");
  });

  it("quotes keys that are not plain words", () => {
    expect(toYaml({ "a b": 1 })).toBe('"a b": 1\n');
  });

  it("is deterministic", () => {
    const value = { a: [1, { b: 2 }], c: { d: "x" } };
    expect(toYaml(value)).toBe(toYaml(structuredClone(value)));
  });
});
