import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { CaseSummary } from "../../api/types.gen";
import { CaseList } from "./CaseList";

const NOW = Date.parse("2026-07-12T12:00:00Z");
const RLO = String.fromCharCode(0x202e);

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
    flags: ["New mapper"],
    place_label: "Lyon, FR",
    stale: false,
    status: "analyzed",
    ...overrides,
  };
}

describe("CaseList evidence-derived text", () => {
  it("shows editor, place and flags as isolated plain text with controls made visible", () => {
    const { container } = render(
      <CaseList
        items={[
          summary({
            editor: `iD${RLO}txet`,
            place_label: `Lyon<img src=x onerror=alert(1)>${RLO}`,
            flags: [`<b>flag</b>${RLO}`, "R4"],
          }),
        ]}
        now={NOW}
        marked={new Set()}
        onMarkedChange={() => {}}
        onOpen={() => {}}
      />,
    );
    const row = container.querySelector('[data-testid="case-row"]');
    expect(row).not.toBeNull();
    expect(row?.querySelector("img, b")).toBeNull();
    expect(row?.textContent).not.toContain(RLO);
    const isolated = Array.from(row?.querySelectorAll("bdi") ?? []).map((n) => n.textContent);
    expect(isolated).toContain("iD�txet");
    expect(isolated.some((text) => text?.startsWith("Lyon<img"))).toBe(true);
    expect(isolated.some((text) => text?.startsWith("<b>flag</b>"))).toBe(true);
    expect(isolated).toContain("R4");
  });
});
