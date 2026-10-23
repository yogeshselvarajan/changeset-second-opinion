import { render, screen } from "@testing-library/react";
import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import {
  HOSTILE_COMMENT,
  HOSTILE_TAG,
  INJECTION,
  makeCoverage,
  makeDetail,
  makeDiff,
  makeElement,
  makeEvidence,
  makePanel,
  makeRule,
} from "../../test/caseData";
import { DiscussionList } from "./DiscussionList";
import { EvidencePane } from "./EvidencePane";
import { FactPanelBlock } from "./FactPanelBlock";
import { RulesBlock } from "./RulesBlock";

afterEach(() => {
  delete (window as unknown as { __pwned?: boolean }).__pwned;
});

function hostileDetail() {
  const detail = makeDetail();
  return {
    ...detail,
    flags: [HOSTILE_TAG],
    place_label: HOSTILE_TAG,
    editor: INJECTION,
    changeset: {
      ...detail.changeset!,
      comment: HOSTILE_COMMENT,
      source: INJECTION,
      user: { ...detail.changeset!.user!, display_name: HOSTILE_TAG },
    },
  };
}

function hostileEvidence() {
  return makeEvidence({
    elements: [makeElement({ osm_id: 101 })],
    tag_diffs: [
      makeDiff({ key: HOSTILE_TAG, before: HOSTILE_TAG, after: INJECTION }),
      makeDiff({ key: "note", change: "added", before: null, after: HOSTILE_COMMENT }),
    ],
    discussion: [
      {
        id: 1,
        author_display: HOSTILE_TAG,
        date: "2026-07-12T10:00:00Z",
        text: `${HOSTILE_COMMENT}\n${INJECTION}`,
      },
    ],
  });
}

function renderPane() {
  return render(
    <EvidencePane
      detail={hostileDetail()}
      state={{ kind: "ready", evidence: hostileEvidence() }}
      onRetry={() => {}}
      mapOpen={false}
      onToggleMap={() => {}}
      diffMode="side"
      onDiffMode={() => {}}
    />,
  );
}

describe("hostile evidence stays inert", () => {
  it("creates no script or image element and runs nothing", () => {
    const { container } = renderPane();
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("[onerror]")).toBeNull();
    expect((window as unknown as { __pwned?: boolean }).__pwned).toBeUndefined();
  });

  it("shows the markup and the instruction as visible text", () => {
    const { container } = renderPane();
    const text = container.textContent ?? "";
    expect(text).toContain("<script>window.__pwned = true</script>");
    expect(text).toContain("IGNORE PREVIOUS INSTRUCTIONS");
    expect(text).toContain(HOSTILE_TAG);
  });

  it("does not turn a URL in the evidence into a link", () => {
    const { container } = renderPane();
    const hrefs = Array.from(container.querySelectorAll("a")).map(
      (a) => a.getAttribute("href") ?? "",
    );
    expect(hrefs.some((href) => href.includes("evil.example"))).toBe(false);
    // The only link is the changeset's own page on osm.org, built from its numeric id.
    expect(hrefs).toEqual(["https://www.openstreetmap.org/changeset/900000000004"]);
  });

  it("opens the osm.org link safely", () => {
    renderPane();
    const link = screen.getByRole("link", { name: "Open on osm.org" });
    expect(link).toHaveAttribute("target", "_blank");
    expect(link.getAttribute("rel")).toContain("noopener");
  });

  it("renders discussion text, rule triggers and probe labels as text too", () => {
    const discussion = render(
      <DiscussionList
        entries={[
          { id: 7, author_display: "a", date: "2026-07-12T10:00:00Z", text: HOSTILE_COMMENT },
        ]}
        status="fetched"
      />,
    );
    expect(discussion.container.querySelector("script")).toBeNull();
    const rules = render(
      <RulesBlock rules={[makeRule({ triggered_by: { note: HOSTILE_TAG, link: INJECTION } })]} />,
    );
    expect(rules.container.querySelector("img")).toBeNull();
    expect(rules.container.textContent).toContain(HOSTILE_TAG);
    const panel = render(
      <FactPanelBlock
        panel={makePanel({
          probes: [
            {
              id: "x",
              label: HOSTILE_TAG,
              probability: 0.5,
              reading: "unknown",
              use: "composed",
              yes_means: "concern",
            },
          ],
        })}
      />,
    );
    expect(panel.container.querySelector("img")).toBeNull();
  });

  it("shows invisible and reordering characters as a visible placeholder", () => {
    const rlo = String.fromCharCode(0x202e);
    render(
      <DiscussionList
        entries={[
          { id: 9, author_display: "a", date: "2026-07-12T10:00:00Z", text: `safe${rlo}txet` },
        ]}
        status="fetched"
      />,
    );
    expect(screen.getByText("safe�txet")).toBeInTheDocument();
  });
});

/** Every non-test .ts/.tsx file under `dir`, recursively, as { name: path relative to components, text }. */
function componentSources(dir: string, base = dir): { name: string; text: string }[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) return componentSources(full, base);
    if (!/\.tsx?$/.test(entry.name) || /\.test\.tsx?$/.test(entry.name)) return [];
    return [{ name: relative(base, full).replaceAll("\\", "/"), text: readFileSync(full, "utf8") }];
  });
}

describe("no component writes HTML", () => {
  // All of src/components (queue, draft, history, config and shell as well as case): evidence text
  // reaches the queue rows and the history screens too.
  const sources = componentSources(join(__dirname, ".."));

  it("scans real files", () => {
    expect(sources.length).toBeGreaterThan(10);
  });

  it("uses no raw-HTML escape hatch anywhere", () => {
    const hits = sources
      .filter(({ text }) =>
        /dangerouslySetInnerHTML|\.innerHTML|insertAdjacentHTML|outerHTML|document\.write|\beval\(|new Function\(/.test(
          text,
        ),
      )
      .map(({ name }) => name);
    expect(hits).toEqual([]);
  });

  it("never fetches or follows a URL taken from evidence", () => {
    // pendingTab.ts is the one place that opens a tab; its only argument is the changeset page link
    // built from a numeric id (osmChangesetUrl), never text from evidence.
    const hits = sources
      .filter(({ name }) => name !== "draft/pendingTab.ts")
      .filter(({ text }) =>
        /\bfetch\(|new Image\(|window\.open\(|location\.(href|assign)/.test(text),
      )
      .map(({ name }) => name);
    expect(hits).toEqual([]);
  });
});

describe("coverage and gaps are never summarised away", () => {
  it("states skipped elements and each history gap reason", () => {
    const evidence = makeEvidence({
      coverage: makeCoverage({
        elements_in_changeset: 300,
        elements_detailed: 40,
        elements_skipped_budget: 260,
        score: 0.13,
        snapshot_truncated: true,
        history_gaps: [
          { osm_type: "way", osm_id: 7, reason: "redacted" },
          { osm_type: "way", osm_id: 23, reason: "redacted" },
        ],
      }),
    });
    render(
      <EvidencePane
        detail={makeDetail()}
        state={{ kind: "ready", evidence }}
        onRetry={() => {}}
        mapOpen={false}
        onToggleMap={() => {}}
        diffMode="side"
        onDiffMode={() => {}}
      />,
    );
    const gaps = screen.getByTestId("coverage-gaps");
    expect(gaps).toHaveTextContent("260 elements were skipped because the fetch budget ran out.");
    expect(gaps).toHaveTextContent("2 elements: history redacted");
    expect(screen.getByTestId("coverage-skipped")).toHaveTextContent("260");
    expect(screen.getByText(/cut short to fit its size limit/)).toBeInTheDocument();
    expect(screen.getByTestId("diff-unavailable")).toHaveTextContent("260 elements");
  });
});
