import { describe, expect, it } from "vitest";

import { makeDetail, makeDiff, makeElement, makeRun } from "../../test/caseData";
import {
  ageBucket,
  bandMeta,
  barFraction,
  bboxText,
  changesetCountText,
  compositionText,
  deletionAges,
  describeTrigger,
  diffMeta,
  draftResponses,
  evidenceIdLabels,
  formatAge,
  formatProbability,
  gapCounts,
  groupTagDiffs,
  humanize,
  isCommentResponse,
  osmChangesetUrl,
  parseEvidenceIds,
  ruleExplanation,
  severityMeta,
  showControls,
} from "./caseModel";

describe("response types", () => {
  it("only the three comment responses can be drafted", () => {
    expect(isCommentResponse("welcome_and_tips")).toBe(true);
    expect(isCommentResponse("ask_source_question")).toBe(true);
    expect(isCommentResponse("request_local_check")).toBe(true);
    expect(isCommentResponse("no_action_suggested")).toBe(false);
    expect(isCommentResponse("escalate_to_experienced_reviewer")).toBe(false);
    expect(isCommentResponse(null)).toBe(false);
    expect(isCommentResponse(undefined)).toBe(false);
  });
});

describe("draftResponses", () => {
  it("uses the server's allowed_responses when it is present", () => {
    const detail = makeDetail({ allowed_responses: ["welcome_and_tips"] });
    expect(draftResponses(detail)).toEqual(["welcome_and_tips"]);
  });

  it("an empty server list wins over a comment-type response (stale, failed or no analysis)", () => {
    const detail = makeDetail({ response: "request_local_check", allowed_responses: [] });
    expect(draftResponses(detail)).toEqual([]);
  });

  it("falls back to the run's own comment response only when the field is missing", () => {
    const withoutField = makeDetail({
      response: "ask_source_question",
      allowed_responses: undefined,
    });
    expect(draftResponses(withoutField)).toEqual(["ask_source_question"]);
    expect(draftResponses({ ...withoutField, response: "no_action_suggested" })).toEqual([]);
    expect(draftResponses({ ...withoutField, latest_run: makeRun({ status: "failed" }) })).toEqual(
      [],
    );
    expect(draftResponses({ ...withoutField, latest_run: null })).toEqual([]);
    expect(draftResponses(undefined)).toEqual([]);
  });
});

describe("evidenceIdLabels", () => {
  it("reads each element's evidence_id from the server", () => {
    const labels = evidenceIdLabels({
      elements: [
        makeElement({ osm_type: "way", osm_id: 101, evidence_id: "E2" }),
        makeElement({ osm_type: "node", osm_id: 7, evidence_id: "E1" }),
      ],
      rendered_text: "E9 way/101 modify ...",
    });
    expect(labels.get("way/101")).toBe("E2");
    expect(labels.get("node/7")).toBe("E1");
    expect(labels.size).toBe(2);
  });

  it("gives no label to an element the evidence text does not show (null id)", () => {
    const labels = evidenceIdLabels({
      elements: [
        makeElement({ osm_id: 101, evidence_id: "E1" }),
        makeElement({ osm_id: 102, evidence_id: null }),
      ],
      rendered_text: "",
    });
    expect(labels.has("way/101")).toBe(true);
    expect(labels.has("way/102")).toBe(false);
  });

  it("does not read the text when the server named ids, even if all are null", () => {
    const labels = evidenceIdLabels({
      elements: [makeElement({ osm_id: 101, evidence_id: null })],
      rendered_text: "E1 way/101 modify age=1 tags: ...",
    });
    expect(labels.size).toBe(0);
  });

  it("falls back to the rendered text only when no element has the field", () => {
    const labels = evidenceIdLabels({
      elements: [makeElement({ osm_id: 101, evidence_id: undefined })],
      rendered_text: "E3 way/101 modify age=1 tags: ...",
    });
    expect(labels.get("way/101")).toBe("E3");
    expect(evidenceIdLabels(undefined).size).toBe(0);
  });
});

describe("numbers", () => {
  it("shows two decimals and never a percentage", () => {
    expect(formatProbability(0.484)).toBe("0.48");
    expect(formatProbability(1)).toBe("1.00");
    expect(formatProbability(0)).toBe("0.00");
    expect(formatProbability(0.3)).not.toContain("%");
    expect(formatProbability(Number.NaN)).toBe("n/a");
  });

  it("clamps only the bar, not the number", () => {
    expect(barFraction(1.4)).toBe(1);
    expect(barFraction(-0.2)).toBe(0);
    expect(barFraction(Number.NaN)).toBe(0);
    expect(formatProbability(1.4)).toBe("1.40");
  });

  it("gives every band a glyph and words", () => {
    expect(bandMeta("confident").glyph).toBe("●");
    expect(bandMeta("unsure").glyph).toBe("◐");
    expect(bandMeta("cannot_tell").glyph).toBe("○");
  });
});

describe("text", () => {
  it("humanizes a code when no label is known", () => {
    expect(humanize("possible_deliberate_damage")).toBe("Possible deliberate damage");
  });

  it("states the changeset count with its basis", () => {
    expect(changesetCountText({ changesets_count: 5, changesets_count_basis: "edit_time" })).toBe(
      "5 at the time of this edit",
    );
    expect(
      changesetCountText({ changesets_count: 29, changesets_count_basis: "current" }),
    ).toContain("in total now");
    expect(
      changesetCountText({ changesets_count: 29, changesets_count_basis: "current" }),
    ).toContain("not published");
    expect(changesetCountText({ changesets_count: 7, changesets_count_basis: null })).toContain(
      "was not recorded",
    );
    expect(changesetCountText({ changesets_count: null })).toBe("unknown");
    expect(changesetCountText(undefined)).toBe("unknown");
  });

  it("builds the bounding box text and the osm.org link from numbers only", () => {
    expect(bboxText([6.44, 3.37, 6.47, 3.41])).toBe("6.4400, 3.3700 → 6.4700, 3.4100");
    expect(bboxText(null)).toBeNull();
    expect(bboxText([1, 2, 3])).toBeNull();
    expect(bboxText([1, 2, 3, Number.NaN])).toBeNull();
    expect(osmChangesetUrl(900000000004)).toBe(
      "https://www.openstreetmap.org/changeset/900000000004",
    );
    expect(osmChangesetUrl(-1)).toBeNull();
    expect(osmChangesetUrl(Number.NaN)).toBeNull();
  });
});

describe("ages", () => {
  it("buckets like the evidence text: up to 30, 31 to 365, over 365", () => {
    expect(ageBucket(0)).toBe("recent");
    expect(ageBucket(30)).toBe("recent");
    expect(ageBucket(31)).toBe("year");
    expect(ageBucket(365)).toBe("year");
    expect(ageBucket(366)).toBe("older");
    expect(ageBucket(null)).toBe("unknown");
    expect(ageBucket(-3)).toBe("unknown");
  });

  it("formats ages in days, years and months", () => {
    expect(formatAge(12)).toBe("12 d");
    expect(formatAge(364)).toBe("364 d");
    expect(formatAge(730)).toBe("2 y");
    expect(formatAge(2190 + 65)).toBe("6 y 2 mo");
    expect(formatAge(null)).toBe("age unknown");
  });

  it("counts deleted elements into buckets and ignores everything else", () => {
    const ages = deletionAges([
      makeElement({ action: "delete", age_days: 5 }),
      makeElement({ action: "delete", age_days: 90, osm_id: 2 }),
      makeElement({ action: "delete", age_days: 4000, osm_id: 3 }),
      makeElement({ action: "delete", age_days: null, osm_id: 4 }),
      makeElement({ action: "modify", age_days: 4000, osm_id: 5 }),
    ]);
    expect(ages.total).toBe(4);
    expect(ages.buckets).toEqual({ recent: 1, year: 1, older: 1, unknown: 1 });
    expect(deletionAges(undefined).total).toBe(0);
  });
});

describe("tag diffs", () => {
  it("groups the API's rows by element and keeps their order", () => {
    const groups = groupTagDiffs([
      makeDiff({ osm_id: 1, key: "b" }),
      makeDiff({ osm_id: 2, key: "x" }),
      makeDiff({ osm_id: 1, key: "a" }),
    ]);
    expect(groups.map((g) => g.key)).toEqual(["way/1", "way/2"]);
    expect(groups[0]?.rows.map((r) => r.key)).toEqual(["b", "a"]);
    expect(groupTagDiffs(undefined)).toEqual([]);
  });

  it("gives each change a prefix glyph so colour is never the only cue", () => {
    expect(diffMeta("added").prefix).toBe("+");
    expect(diffMeta("removed").prefix).toBe("−");
    expect(diffMeta("changed").prefix).toBe("~");
  });
});

describe("evidence ids", () => {
  it("reads E ids from the server's rendered text without ranking anything itself", () => {
    const text = [
      "CHANGED OBJECTS",
      "E1 way/101 delete age=2190 tags: ...",
      "E2 node/7 modify age=12 tags: ...",
      "E10 relation/55 create age=? tags: ...",
      "not an id line",
    ].join("\n");
    const ids = parseEvidenceIds(text);
    expect(ids.get("way/101")).toBe("E1");
    expect(ids.get("node/7")).toBe("E2");
    expect(ids.get("relation/55")).toBe("E10");
    expect(ids.size).toBe(3);
    expect(parseEvidenceIds(undefined).size).toBe(0);
  });
});

describe("rules and panel text", () => {
  it("explains R1 to R6 and has no text for a code it does not know", () => {
    for (const code of ["R1", "R2", "R3", "R4", "R5", "R6"]) {
      expect(ruleExplanation(code)).toBeTruthy();
    }
    expect(ruleExplanation("R9")).toBeUndefined();
  });

  it("shows rule triggers as text pairs in the order given", () => {
    expect(describeTrigger({ osm_id: 123, kind: "way" })).toEqual([
      { name: "osm_id", value: "123" },
      { name: "kind", value: "way" },
    ]);
    expect(describeTrigger(undefined)).toEqual([]);
  });

  it("has a glyph and words for every severity", () => {
    expect(severityMeta("info").glyph).toBe("i");
    expect(severityMeta("warn").glyph).toBe("!");
    expect(severityMeta("block").glyph).toBe("×");
  });

  it("describes composition rows and falls back to the row id", () => {
    expect(compositionText("P1")).toContain("Escalate");
    expect(compositionText("N3")).toContain("good-faith");
    expect(compositionText("P9")).toBe("P9");
  });

  it("counts history gaps by reason", () => {
    const counts = gapCounts([
      { osm_type: "way", osm_id: 1, reason: "redacted" },
      { osm_type: "way", osm_id: 2, reason: "redacted" },
      { osm_type: "node", osm_id: 3, reason: "timeout" },
    ]);
    expect(counts.get("redacted")).toBe(2);
    expect(counts.get("timeout")).toBe(1);
    expect(gapCounts(undefined).size).toBe(0);
  });
});

describe("untrusted text", () => {
  it("makes invisible and reordering characters visible", () => {
    const rlo = String.fromCharCode(0x202e);
    const zwsp = String.fromCharCode(0x200b);
    const nul = String.fromCharCode(0);
    expect(showControls(`a${rlo}b${zwsp}c${nul}d`)).toBe("a�b�c�d");
    expect(showControls("plain text, tabs\tand newlines\nstay")).toBe(
      "plain text, tabs\tand newlines\nstay",
    );
  });
});
