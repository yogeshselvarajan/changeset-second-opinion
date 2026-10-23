import { describe, expect, it } from "vitest";

import type { DecisionRow } from "../../api/types.gen";
import {
  cleanDate,
  cleanFilters,
  csvHref,
  dayOf,
  decisionQuery,
  groupByDay,
  isFiltered,
  shortVersion,
  timeOf,
  uniqueDecisions,
} from "./historyModel";

const row = (id: string, created_at: string): DecisionRow => ({
  outcome_id: id,
  case_id: `case-${id}`,
  changeset_id: 900000000000 + Number(id),
  config_version: "sha256:0123456789abcdef",
  created_at,
  disposition: "agree",
  lane_at_decision: "review_suggested",
  reviewer_display: "Reviewer",
});

describe("filters", () => {
  it("accepts only real calendar dates", () => {
    expect(cleanDate("2026-07-12")).toBe("2026-07-12");
    expect(cleanDate("2026-02-30")).toBeUndefined();
    expect(cleanDate("12/07/2026")).toBeUndefined();
    expect(cleanDate(undefined)).toBeUndefined();
  });

  it("drops what the API would reject so a hand-edited URL shows the plain list", () => {
    expect(
      cleanFilters({ reviewer: "  ", disposition: "bogus", from: "nope", to: "2026-07-13" }),
    ).toEqual({ reviewer: undefined, disposition: undefined, from: undefined, to: "2026-07-13" });
    expect(cleanFilters({ disposition: "needs_survey" }).disposition).toBe("needs_survey");
    expect(cleanFilters({ reviewer: "x".repeat(200) }).reviewer).toHaveLength(80);
  });

  it("turns date inputs into whole UTC days for the API", () => {
    expect(
      decisionQuery({
        from: "2026-07-01",
        to: "2026-07-02",
        reviewer: "Ann",
        disposition: "agree",
      }),
    ).toEqual({
      limit: 50,
      reviewer: "Ann",
      disposition: "agree",
      from: "2026-07-01T00:00:00Z",
      to: "2026-07-02T23:59:59Z",
    });
    expect(decisionQuery({})).toEqual({ limit: 50 });
  });

  it("builds the CSV link with the same filters and no paging", () => {
    expect(csvHref({})).toBe("/api/v1/decisions/export.csv");
    const href = csvHref({ reviewer: "Ann", disposition: "agree", from: "2026-07-01" });
    expect(href.startsWith("/api/v1/decisions/export.csv?")).toBe(true);
    const params = new URLSearchParams(href.split("?")[1]);
    expect(params.get("reviewer")).toBe("Ann");
    expect(params.get("disposition")).toBe("agree");
    expect(params.get("from")).toBe("2026-07-01T00:00:00Z");
    expect(params.has("limit")).toBe(false);
    expect(params.has("cursor")).toBe(false);
  });

  it("knows when the list is narrowed", () => {
    expect(isFiltered({})).toBe(false);
    expect(isFiltered({ reviewer: "Ann" })).toBe(true);
    expect(isFiltered({ from: "bad" })).toBe(false);
  });
});

describe("grouping", () => {
  it("reads the UTC day and time", () => {
    expect(dayOf("2026-07-12T23:30:00Z")).toBe("2026-07-12");
    expect(timeOf("2026-07-12T23:30:00Z")).toBe("23:30");
    expect(dayOf("not a date")).toBe("not a date");
    expect(timeOf("not a date")).toBe("");
  });

  it("groups newest-first rows into one block per day, keeping order", () => {
    const groups = groupByDay([
      row("3", "2026-07-13T09:00:00Z"),
      row("2", "2026-07-12T22:00:00Z"),
      row("1", "2026-07-12T08:00:00Z"),
    ]);
    expect(groups.map((g) => [g.day, g.rows.map((r) => r.outcome_id)])).toEqual([
      ["2026-07-13", ["3"]],
      ["2026-07-12", ["2", "1"]],
    ]);
    expect(groupByDay([])).toEqual([]);
  });

  it("drops a row that arrives on two pages", () => {
    const rows = [
      row("1", "2026-07-12T08:00:00Z"),
      row("2", "2026-07-12T07:00:00Z"),
      row("1", "2026-07-12T08:00:00Z"),
    ];
    expect(uniqueDecisions(rows).map((r) => r.outcome_id)).toEqual(["1", "2"]);
  });

  it("shortens a config version for a table cell", () => {
    expect(shortVersion("sha256:0123456789abcdef")).toBe("sha256:01234567");
    expect(shortVersion("abcdef0123456789")).toBe("abcdef01");
  });
});
