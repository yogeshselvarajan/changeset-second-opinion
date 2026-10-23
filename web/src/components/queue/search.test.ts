import { describe, expect, it } from "vitest";

import type { CaseSummary } from "../../api/types.gen";
import {
  activeFilterCount,
  bandText,
  countsGlyphs,
  formatAge,
  laneForKey,
  laneTotals,
  moveIndex,
  parseChangesetInput,
  parseSearch,
  problemCode,
  queueKeyAction,
  rowLabel,
  toListQuery,
  viewTotal,
  withFilters,
} from "./search";

const NOW = Date.parse("2026-07-12T12:00:00Z");

function summary(overrides: Partial<CaseSummary> = {}): CaseSummary {
  return {
    id: "case-1",
    changeset_id: 167234981,
    lane: "review_suggested",
    band: "unsure",
    coverage_score: 1,
    created_at: "2026-07-12T10:00:00Z",
    updated_at: "2026-07-12T10:00:00Z",
    editor: "iD 2.31",
    element_counts: { create: 12, modify: 4, delete: 0 },
    flags: ["New mapper", "R4"],
    place_label: "Lyon, FR",
    stale: false,
    status: "analyzed",
    ...overrides,
  };
}

describe("parseSearch", () => {
  it("keeps valid values and drops unknown ones", () => {
    expect(
      parseSearch({
        lane: "review_suggested",
        status: "analyzing",
        editor: " JOSM ",
        q: "lyon",
        stale: "true",
        cursor: "abc",
      }),
    ).toEqual({
      lane: "review_suggested",
      status: "analyzing",
      editor: "JOSM",
      q: "lyon",
      stale: true,
      cursor: "abc",
    });
    const dropped = parseSearch({ lane: "everything", status: "nope", stale: "no", q: "  " });
    expect(dropped.lane).toBeUndefined();
    expect(dropped.status).toBeUndefined();
    expect(dropped.stale).toBeUndefined();
    expect(dropped.q).toBeUndefined();
  });

  it("accepts a boolean stale from the router and ignores non-strings", () => {
    expect(parseSearch({ stale: true }).stale).toBe(true);
    expect(parseSearch({ editor: 5, q: { a: 1 } })).toMatchObject({
      editor: undefined,
      q: undefined,
    });
  });

  it("limits the length of text it keeps", () => {
    expect(parseSearch({ q: "x".repeat(500) }).q).toHaveLength(200);
  });
});

describe("toListQuery and filters", () => {
  it("sends only the filters that are set, never the cursor", () => {
    expect(toListQuery({ lane: "rules_only", q: "a", cursor: "c" }, 50)).toEqual({
      limit: 50,
      lane: "rules_only",
      q: "a",
    });
    expect(toListQuery({})).toEqual({ limit: 50 });
    expect(toListQuery({ stale: true, status: "new", editor: "iD" })).toEqual({
      limit: 50,
      stale: true,
      status: "new",
      editor: "iD",
    });
  });

  it("returns to the first page whenever a filter changes", () => {
    expect(withFilters({ lane: "rules_only", cursor: "next" }, { q: "x" })).toEqual({
      lane: "rules_only",
      q: "x",
      cursor: undefined,
    });
  });

  it("counts the narrowing filters but not the lane", () => {
    expect(activeFilterCount({ lane: "rules_only" })).toBe(0);
    expect(activeFilterCount({ status: "new", editor: "e", q: "q", stale: true })).toBe(4);
  });
});

describe("lane counts", () => {
  it("lists every lane in queue order and adds them up (nothing is hidden)", () => {
    const totals = laneTotals({
      looks_consistent: 12,
      review_suggested: 27,
      needs_local_knowledge: 3,
    });
    expect(totals.entries.map((entry) => entry.lane)).toEqual([
      "looks_consistent",
      "review_suggested",
      "needs_local_knowledge",
      "insufficient_evidence",
      "rules_only",
    ]);
    expect(totals.entries.map((entry) => entry.count)).toEqual([12, 27, 3, 0, 0]);
    expect(totals.total).toBe(42);
  });

  it("treats a missing map as zero everywhere", () => {
    expect(laneTotals(undefined).total).toBe(0);
  });

  it("shows the lane's own count, or every lane together", () => {
    const totals = laneTotals({ looks_consistent: 5, rules_only: 2 });
    expect(viewTotal(undefined, totals)).toBe(7);
    expect(viewTotal("rules_only", totals)).toBe(2);
    expect(viewTotal("review_suggested", totals)).toBe(0);
  });
});

describe("keys", () => {
  it("maps 1 to 5 onto the lanes in queue order and 0 onto all lanes", () => {
    expect(laneForKey("1")).toEqual({ lane: "looks_consistent" });
    expect(laneForKey("2")).toEqual({ lane: "review_suggested" });
    expect(laneForKey("5")).toEqual({ lane: "rules_only" });
    expect(laneForKey("0")).toEqual({ lane: undefined });
    expect(laneForKey("6")).toBeNull();
    expect(laneForKey("a")).toBeNull();
    expect(laneForKey("12")).toBeNull();
  });

  it("recognises the queue's own keys and ignores everything else", () => {
    expect(queueKeyAction("j")).toEqual({ kind: "move", delta: 1 });
    expect(queueKeyAction("k")).toEqual({ kind: "move", delta: -1 });
    expect(queueKeyAction("o")).toEqual({ kind: "open" });
    expect(queueKeyAction("x")).toEqual({ kind: "mark" });
    expect(queueKeyAction("/")).toEqual({ kind: "search" });
    expect(queueKeyAction("Escape")).toEqual({ kind: "clearMarks" });
    expect(queueKeyAction("3")).toEqual({ kind: "lane", lane: "needs_local_knowledge" });
    expect(queueKeyAction("Enter")).toBeNull();
    expect(queueKeyAction("z")).toBeNull();
    expect(queueKeyAction("?")).toBeNull();
  });

  it("moves the focused row without leaving the list", () => {
    expect(moveIndex(null, 1, 5)).toBe(0);
    expect(moveIndex(null, -1, 5)).toBe(0);
    expect(moveIndex(0, 1, 5)).toBe(1);
    expect(moveIndex(4, 1, 5)).toBe(4);
    expect(moveIndex(0, -1, 5)).toBe(0);
    expect(moveIndex(2, 1, 0)).toBeNull();
  });
});

describe("row text", () => {
  it("spells out the age for the accessible name", () => {
    expect(formatAge("2026-07-12T11:59:40Z", NOW)).toEqual({ short: "now", long: "just now" });
    expect(formatAge("2026-07-12T11:15:00Z", NOW)).toEqual({
      short: "45 min",
      long: "45 minutes ago",
    });
    expect(formatAge("2026-07-12T10:00:00Z", NOW)).toEqual({ short: "2 h", long: "2 hours ago" });
    expect(formatAge("2026-07-09T12:00:00Z", NOW)).toEqual({ short: "3 d", long: "3 days ago" });
    expect(formatAge("not a date", NOW)).toEqual({ short: "", long: "" });
  });

  it("shows created, modified and deleted as +, ~ and a minus sign", () => {
    expect(countsGlyphs({ create: 12, modify: 4, delete: 0 })).toBe("+12 ~4 −0");
    expect(countsGlyphs({})).toBe("+0 ~0 −0");
  });

  it("uses the API's band as is and says so when there is none", () => {
    expect(bandText("confident")).toBe("Model is confident");
    expect(bandText("unsure")).toBe("Model is unsure");
    expect(bandText("cannot_tell")).toBe("Model cannot tell");
    expect(bandText(null)).toBe("No model reading");
    expect(bandText(undefined)).toBe("No model reading");
  });

  it("reads lane, changeset, editor, place, counts, band, status and age", () => {
    const label = rowLabel(summary(), NOW);
    expect(label).toBe(
      "Review suggested, changeset 167234981, editor iD 2.31, place Lyon, FR, " +
        "12 created, 4 modified, 0 deleted, Model is unsure, status Analyzed, created 2 hours ago, " +
        "flags New mapper, R4",
    );
  });

  it("says what is missing instead of leaving a gap, and marks stale and decided cases", () => {
    const label = rowLabel(
      summary({
        editor: null,
        place_label: null,
        band: null,
        flags: [],
        stale: true,
        latest_outcome: "needs_survey",
        lane: "rules_only",
        status: "decided",
      }),
      NOW,
    );
    expect(label).toContain("editor unknown");
    expect(label).toContain("place unknown");
    expect(label).toContain("No model reading");
    expect(label).toContain("stale");
    expect(label).toContain("outcome Needs survey");
    expect(label).not.toContain("flags");
    expect(label.startsWith("Rules only, ")).toBe(true);
  });
});

describe("parseChangesetInput", () => {
  it.each([
    ["167234981", 167234981],
    ["  167234981 ", 167234981],
    ["#167234981", 167234981],
    ["https://www.openstreetmap.org/changeset/167234981", 167234981],
    ["https://www.openstreetmap.org/changeset/167234981/", 167234981],
    ["https://www.openstreetmap.org/changeset/167234981?x=1", 167234981],
    ["https://example.org/changeset/42#map", 42],
    ["900000000001", 900000000001],
  ])("reads %s", (input, expected) => {
    expect(parseChangesetInput(input)).toBe(expected);
  });

  it.each([
    "",
    "abc",
    "0",
    "-5",
    "1.5",
    "12345678901234",
    "https://www.openstreetmap.org/user/someone",
    "https://www.openstreetmap.org/changeset/",
    "javascript:alert(1)",
    "changeset 12",
  ])("rejects %j", (input) => {
    expect(parseChangesetInput(input)).toBeNull();
  });
});

describe("problemCode", () => {
  it("reads the code from the problem type or a code member", () => {
    expect(problemCode({ type: "urn:cso:problem:daily_cap_reached" })).toBe("daily_cap_reached");
    expect(problemCode({ code: "rate_limited", type: "urn:cso:problem:other" })).toBe(
      "rate_limited",
    );
  });

  it("returns null for anything else", () => {
    expect(problemCode(undefined)).toBeNull();
    expect(problemCode("text")).toBeNull();
    expect(problemCode({ type: "about:blank" })).toBeNull();
    expect(problemCode({ type: "nocolons" })).toBeNull();
  });
});
