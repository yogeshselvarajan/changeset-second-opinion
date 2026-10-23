import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  makeCoverage,
  makeDetail,
  makeDiff,
  makeElement,
  makePanel,
  makeRule,
} from "../../test/caseData";
import { ChangedObjectsList } from "./ChangedObjectsList";
import { groupTagDiffs } from "./caseModel";
import { CoverageBlock } from "./CoverageBlock";
import { DiscussionList } from "./DiscussionList";
import { FactPanelBlock } from "./FactPanelBlock";
import { FactsBlock } from "./FactsBlock";
import { RulesBlock } from "./RulesBlock";
import { TagDiffTable } from "./TagDiffTable";

const noop = () => {};

describe("TagDiffTable", () => {
  const diffs = [
    makeDiff({ key: "name", change: "changed", before: "Old Rd", after: "Old Road" }),
    makeDiff({ key: "note", change: "added", before: null, after: "hello" }),
    makeDiff({ key: "old_name", change: "removed", before: "Old Street", after: null }),
  ];

  function renderTable(
    mode: "side" | "unified",
    extra: Partial<Parameters<typeof TagDiffTable>[0]> = {},
  ) {
    return render(
      <TagDiffTable
        groups={groupTagDiffs(diffs)}
        mode={mode}
        onModeChange={noop}
        idLabels={new Map([["way/101", "E3"]])}
        detailed={40}
        total={88}
        {...extra}
      />,
    );
  }

  it("is a real table with a caption, column headers and a row header per key", () => {
    renderTable("side");
    const table = screen.getByRole("table", {
      name: "Tag changes per element, with the value before and after",
    });
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((h) => h.textContent),
    ).toEqual(["Change", "Key", "Before", "After"]);
    expect(
      within(table)
        .getAllByRole("rowheader")
        .map((h) => h.textContent),
    ).toEqual(expect.arrayContaining(["name", "note", "old_name"]));
  });

  it("names every change in words next to its glyph", () => {
    renderTable("side");
    const rows = screen.getAllByRole("row").filter((row) => row.hasAttribute("data-change"));
    expect(rows.map((row) => row.getAttribute("data-change"))).toEqual([
      "changed",
      "added",
      "removed",
    ]);
    expect(rows[0]).toHaveTextContent("Changed");
    expect(rows[1]).toHaveTextContent("Added");
    expect(rows[2]).toHaveTextContent("Removed");
    expect(rows[1]).toHaveTextContent("(none)"); // the missing before value is said, not left blank
  });

  it("labels the element group with its evidence id when the server's text has one", () => {
    renderTable("side");
    expect(screen.getByText("way/101")).toBeInTheDocument();
    expect(screen.getByText("E3")).toBeInTheDocument();
  });

  it("shows before and after lines in the unified layout", () => {
    renderTable("unified");
    const table = screen.getByRole("table");
    expect(table).toHaveAttribute("data-mode", "unified");
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((h) => h.textContent),
    ).toEqual(["Change", "Key", "Lines"]);
    expect(table).toHaveTextContent("Old Rd");
    expect(table).toHaveTextContent("Old Road");
  });

  it("switches layout with the buttons and reports the current one", () => {
    const onModeChange = vi.fn();
    renderTable("side", { onModeChange });
    expect(screen.getByRole("button", { name: "Side by side" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    fireEvent.click(screen.getByRole("button", { name: "Unified" }));
    expect(onModeChange).toHaveBeenCalledWith("unified");
  });

  it("says how many elements have no diff because of the budget or redaction", () => {
    renderTable("side");
    expect(screen.getByTestId("diff-unavailable")).toHaveTextContent(
      "Tag changes are unavailable for 48 elements",
    );
  });

  it("says so when there are no tag changes at all", () => {
    render(
      <TagDiffTable
        groups={[]}
        mode="side"
        onModeChange={noop}
        idLabels={new Map()}
        detailed={4}
        total={4}
      />,
    );
    expect(screen.getByTestId("diff-empty")).toHaveTextContent("No tag changes were reported.");
    expect(screen.queryByRole("table")).toBeNull();
  });
});

describe("FactPanelBlock", () => {
  it("lists every probe with its reading in words, its probability and how it counts", () => {
    render(<FactPanelBlock panel={makePanel()} />);
    const rows = screen.getAllByRole("row").filter((row) => row.hasAttribute("data-probe"));
    expect(rows).toHaveLength(3);
    const mature = rows.find((row) => row.getAttribute("data-probe") === "mature_feature_deleted")!;
    expect(mature).toHaveAttribute("data-reading", "yes");
    expect(mature).toHaveTextContent("Yes");
    expect(mature).toHaveTextContent("0.91");
    expect(mature).toHaveTextContent("Used in the recommendation");
    expect(mature).toHaveTextContent("yes raises concern");
    expect(mature).toHaveTextContent("Agrees");
    const evidence = rows.find((row) => row.getAttribute("data-probe") === "evidence_sufficient")!;
    expect(evidence).toHaveTextContent("Cross-check only");
    expect(evidence).toHaveTextContent("Disagrees"); // a disagreement is shown, not hidden
    const comment = rows.find(
      (row) => row.getAttribute("data-probe") === "comment_matches_changes",
    )!;
    expect(comment).toHaveTextContent("Unknown");
    expect(comment).toHaveTextContent("No cross-check");
    expect(comment).toHaveTextContent("yes reassures");
  });

  it("explains the thresholds and that unknown only withholds reassurance", () => {
    render(<FactPanelBlock panel={makePanel()} />);
    expect(screen.getByText(/reads no below 0.35, yes above 0.65/)).toBeInTheDocument();
    expect(screen.getByText(/Unknown never raises a lane/)).toBeInTheDocument();
  });

  it("shows the composition rows that fired and which probes read yes or unknown", () => {
    render(<FactPanelBlock panel={makePanel()} />);
    const composition = screen.getByTestId("composition");
    expect(within(composition).getByText("P1")).toBeInTheDocument();
    expect(composition).toHaveTextContent("Escalate to an experienced reviewer");
    expect(composition).toHaveTextContent("N2");
    expect(composition).toHaveTextContent(
      "Read yes: An old or heavily edited feature was deleted.",
    );
    expect(composition).toHaveTextContent(
      "Read unknown (withholds reassurance): The changeset comment matches the edits.",
    );
  });

  it("lists a cross-check for a probe the panel does not carry, instead of dropping it", () => {
    render(
      <FactPanelBlock
        panel={makePanel({
          cross_checks: { mature_feature_deleted: "agree", mystery_probe: "undecided" },
        })}
      />,
    );
    expect(screen.getByTestId("panel-stray-checks")).toHaveTextContent("mystery_probe: Undecided");
  });

  it("copes with a run that has no composition", () => {
    render(<FactPanelBlock panel={makePanel({ composition: null })} />);
    expect(screen.queryByTestId("composition")).toBeNull();
  });
});

describe("RulesBlock", () => {
  it("shows severity as a glyph and a word, the rule's meaning, and what triggered it", () => {
    render(
      <RulesBlock
        rules={[
          makeRule(),
          makeRule({
            code: "R4",
            label: "New account and deletions",
            severity: "warn",
            triggered_by: {},
          }),
        ]}
      />,
    );
    const r1 = screen.getByText("R1", { exact: false }).closest("li")!;
    expect(r1).toHaveAttribute("data-severity", "block");
    expect(r1).toHaveTextContent("Blocks reassurance");
    expect(r1).toHaveTextContent("Mature deletion");
    expect(r1).toHaveTextContent("older than a year");
    expect(r1).toHaveTextContent("age_days");
    expect(r1).toHaveTextContent("2190");
    const r4 = screen.getByText("R4", { exact: false }).closest("li")!;
    expect(r4).toHaveTextContent("Warning");
  });

  it("says so when no rule fired", () => {
    render(<RulesBlock rules={[]} />);
    expect(screen.getByTestId("no-rules")).toHaveTextContent("No rule fired.");
  });

  it("still lists a rule it has no explanation for", () => {
    render(
      <RulesBlock rules={[makeRule({ code: "R9", label: "Future rule", severity: "info" })]} />,
    );
    expect(screen.getByText("R9", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("Information")).toBeInTheDocument();
  });
});

describe("FactsBlock", () => {
  it("labels which changeset count is shown", () => {
    const edit = makeDetail();
    const { unmount } = render(
      <FactsBlock detail={edit} elements={[]} mapOpen={false} onToggleMap={noop} />,
    );
    expect(screen.getByTestId("user-changesets")).toHaveTextContent("5 at the time of this edit");
    unmount();
    const current = makeDetail({
      changeset: {
        ...edit.changeset!,
        user: { ...edit.changeset!.user!, changesets_count: 29, changesets_count_basis: "current" },
      },
    });
    render(<FactsBlock detail={current} elements={[]} mapOpen={false} onToggleMap={noop} />);
    expect(screen.getByTestId("user-changesets")).toHaveTextContent(
      "29 in total now (the count at the time of the edit was not published)",
    );
  });

  it("states a missing profile instead of showing blanks", () => {
    const detail = makeDetail();
    render(
      <FactsBlock
        detail={{ ...detail, changeset: { ...detail.changeset!, user: null } }}
        elements={[]}
        mapOpen={false}
        onToggleMap={noop}
      />,
    );
    expect(screen.getByTestId("user-missing")).toBeInTheDocument();
  });

  it("counts deleted features into age buckets, from the elements shown", () => {
    render(
      <FactsBlock
        detail={makeDetail()}
        elements={[
          makeElement({ action: "delete", age_days: 2190 }),
          makeElement({ action: "delete", age_days: 10, osm_id: 2 }),
          makeElement({ action: "modify", age_days: 9000, osm_id: 3 }),
        ]}
        mapOpen={false}
        onToggleMap={noop}
      />,
    );
    const ages = screen.getByTestId("deletion-ages");
    expect(ages).toHaveTextContent("Deleted features by age (2)");
    expect(within(ages).getByText(/over 365 days: 1/)).toBeInTheDocument();
    expect(within(ages).getByText(/up to 30 days: 1/)).toBeInTheDocument();
  });

  it("offers the map button only when there is a bounding box, and never pre-opens it", () => {
    const detail = makeDetail();
    const { unmount } = render(
      <FactsBlock detail={detail} elements={[]} mapOpen={false} onToggleMap={noop} />,
    );
    const button = screen.getByRole("button", { name: "Show map (m)" });
    expect(button).toHaveAttribute("aria-pressed", "false");
    unmount();
    render(
      <FactsBlock
        detail={{ ...detail, changeset: { ...detail.changeset!, bbox: null } }}
        elements={[]}
        mapOpen={false}
        onToggleMap={noop}
      />,
    );
    expect(screen.queryByRole("button", { name: /map/i })).toBeNull();
    expect(screen.getByText("not recorded")).toBeInTheDocument();
  });

  it("shows the flags and the counts as text", () => {
    render(<FactsBlock detail={makeDetail()} elements={[]} mapOpen={false} onToggleMap={noop} />);
    expect(screen.getByTestId("flags")).toHaveTextContent("New mapper");
    expect(screen.getByTestId("counts")).toHaveTextContent("0 created, 4 modified, 1 deleted");
  });
});

describe("CoverageBlock", () => {
  it("exposes the score as a labelled meter and states the fraction in words", () => {
    render(
      <CoverageBlock
        coverage={makeCoverage({ elements_in_changeset: 50, elements_detailed: 40, score: 0.8 })}
      />,
    );
    const meter = screen.getByRole("meter", { name: "Coverage score" });
    expect(meter).toHaveAttribute("aria-valuenow", "0.8");
    expect(meter).toHaveAttribute(
      "aria-valuetext",
      "Coverage score 0.80: 40 of 50 elements have details",
    );
    expect(screen.getByTestId("coverage-summary")).toHaveTextContent(
      "40 of 50 elements have details",
    );
  });

  it("says plainly when nothing was skipped and no history is missing", () => {
    render(<CoverageBlock coverage={makeCoverage()} />);
    expect(
      screen.getByText("No skipped elements and no history gaps were reported."),
    ).toBeInTheDocument();
  });

  it("flags a provisional snapshot and a failed profile fetch", () => {
    render(<CoverageBlock coverage={makeCoverage({ user_profile: "failed" })} provisional />);
    expect(screen.getByText(/provisional/)).toBeInTheDocument();
    expect(screen.getByText("could not be fetched")).toBeInTheDocument();
  });
});

describe("ChangedObjectsList and DiscussionList", () => {
  it("shows evidence ids, versions and deletion age with its bucket", () => {
    render(
      <ChangedObjectsList
        elements={[
          makeElement({
            osm_id: 101,
            action: "delete",
            age_days: 2190,
            version_before: 1,
            version_after: 2,
          }),
          makeElement({
            osm_id: 5,
            osm_type: "node",
            action: "create",
            version_before: null,
            version_after: 1,
            age_days: null,
          }),
        ]}
        idLabels={new Map([["way/101", "E1"]])}
        total={126}
      />,
    );
    const rows = screen.getAllByRole("row").filter((row) => row.hasAttribute("data-action"));
    expect(rows[0]).toHaveTextContent("E1");
    expect(rows[0]).toHaveTextContent("way/101");
    expect(rows[0]).toHaveTextContent("Deleted");
    expect(rows[0]).toHaveTextContent("v1 → v2");
    expect(rows[0]).toHaveTextContent("6 y");
    expect(rows[0]).toHaveTextContent("over 365 days");
    expect(rows[1]).toHaveTextContent("new, v1");
    expect(screen.getByRole("heading", { name: "Changed objects (2 of 126)" })).toBeInTheDocument();
  });

  it("has an empty state for each", () => {
    const objects = render(<ChangedObjectsList elements={[]} idLabels={new Map()} total={0} />);
    expect(objects.container).toHaveTextContent("No elements have details.");
    const discussion = render(<DiscussionList entries={[]} status="fetched" />);
    expect(discussion.container).toHaveTextContent("No discussion yet.");
  });

  it("says when the discussion could not be fetched", () => {
    render(<DiscussionList entries={[]} status="failed" />);
    expect(screen.getByText("The discussion could not be fetched.")).toBeInTheDocument();
  });
});
