import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BandChip } from "./BandChip";
import { ConfidenceBlock } from "./ConfidenceBlock";
import { confidenceRows } from "./confidenceRows";

const NATURE = new Map([
  ["consistent_edit", { label: "Consistent edit", description: "Looks like ordinary mapping." }],
  ["likely_good_faith_mistake", { label: "Likely good-faith mistake" }],
  ["possible_deliberate_damage", { label: "Possible deliberate damage" }],
  ["needs_local_knowledge", { label: "Needs local knowledge" }],
]);
const ORDER = [...NATURE.keys()];
const PROBS = {
  consistent_edit: 0.484,
  likely_good_faith_mistake: 0.39,
  possible_deliberate_damage: 0.09,
  needs_local_knowledge: 0.036,
};

function renderBlock(props: Partial<React.ComponentProps<typeof ConfidenceBlock>> = {}) {
  return render(
    <ConfidenceBlock
      id="nature"
      title="Kind of edit"
      rows={confidenceRows(PROBS, NATURE, ORDER)}
      band="unsure"
      showBand
      orderSensitivity={0.07}
      {...props}
    />,
  );
}

describe("ConfidenceBlock", () => {
  it("shows every option with its own two-decimal number, in option order", () => {
    renderBlock();
    const values = screen.getAllByTestId("option-value").map((node) => node.textContent);
    expect(values).toEqual(["0.48", "0.39", "0.09", "0.04"]);
    const labels = screen.getAllByRole("meter").map((node) => node.getAttribute("aria-valuetext"));
    expect(labels).toEqual([
      "Consistent edit: 0.48",
      "Likely good-faith mistake: 0.39",
      "Possible deliberate damage: 0.09",
      "Needs local knowledge: 0.04",
    ]);
  });

  it("never shows a percentage or any harm-percentage wording", () => {
    const { container } = renderBlock();
    const text = container.textContent ?? "";
    expect(text).not.toContain("%");
    expect(text.toLowerCase()).not.toContain("vandal");
    expect(text.toLowerCase()).not.toMatch(/probability of (harm|damage)/);
  });

  it("gives each bar meter semantics with a name and a 0 to 1 range", () => {
    renderBlock();
    for (const meter of screen.getAllByRole("meter")) {
      expect(meter).toHaveAttribute("aria-valuemin", "0");
      expect(meter).toHaveAttribute("aria-valuemax", "1");
      expect(meter).toHaveAttribute("aria-labelledby");
      const label = document.getElementById(meter.getAttribute("aria-labelledby") ?? "");
      expect(label?.textContent).toBeTruthy();
    }
  });

  it("shows the backend band with its words, linked to the plain-language explanation", () => {
    renderBlock();
    const chip = screen.getByText("Model is unsure").closest("[data-band]");
    expect(chip).toHaveAttribute("data-band", "unsure");
    const explainer = document.getElementById(chip?.getAttribute("aria-describedby") ?? "");
    expect(explainer?.textContent).toContain("not how likely the edit is harmful");
  });

  it("states the order sensitivity as given", () => {
    renderBlock();
    expect(screen.getByText("Order sensitivity 0.07")).toBeInTheDocument();
  });

  it("marks an advisory answer and says it is not used for the lane", () => {
    renderBlock({
      advisory: true,
      showBand: false,
      markCode: "consistent_edit",
      markText: "advisory top choice",
    });
    expect(screen.getByTestId("nature-advisory")).toHaveTextContent(
      "not used to place the case in a lane",
    );
    expect(screen.getByText("(advisory top choice)")).toBeInTheDocument();
  });

  it("keeps an option the option set does not know, after the known ones", () => {
    const rows = confidenceRows({ ...PROBS, brand_new_option: 0.01 }, NATURE, ORDER);
    expect(rows.map((row) => row.code).at(-1)).toBe("brand_new_option");
    expect(rows.at(-1)?.label).toBe("Brand new option");
    renderBlock({ rows });
    expect(screen.getAllByRole("meter")).toHaveLength(5);
  });

  it("says so when no probabilities were recorded", () => {
    renderBlock({ rows: [] });
    expect(screen.getByText("No probabilities were recorded for this answer.")).toBeInTheDocument();
    expect(screen.queryAllByRole("meter")).toHaveLength(0);
  });

  it("uses the supplied explanation instead of the default note", () => {
    renderBlock({ explanation: "Custom note." });
    expect(screen.getByText("Custom note.")).toBeInTheDocument();
  });
});

describe("BandChip", () => {
  it("shows a glyph and words for each band, and a plain note when there is none", () => {
    const { rerender } = render(<BandChip band="confident" />);
    expect(screen.getByText("Model is confident")).toBeInTheDocument();
    rerender(<BandChip band="cannot_tell" />);
    expect(screen.getByText("Model cannot tell")).toBeInTheDocument();
    rerender(<BandChip band={null} />);
    expect(screen.getByText("No model reading")).toBeInTheDocument();
  });

  it("carries no number", () => {
    const { container } = render(<BandChip band="unsure" />);
    expect(within(container).queryByText(/\d/)).toBeNull();
  });
});
